"""从 raw.json 和按请求编号匹配的日志重算求职证据；不调用 LLM。"""
import argparse
import json
from pathlib import Path
import sys


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('folder',type=Path)
    args=parser.parse_args()
    folder=args.folder
    raw=json.loads((folder/'raw.json').read_text(encoding='utf-8-sig'))
    events={}
    for line in (folder/'server-log.jsonl').read_text(encoding='utf-8-sig').splitlines():
        try:
            event=json.loads(line)
        except ValueError:
            continue
        if event.get('event')=='request_finished':
            events[event['request_id']]=event
    results=raw['results']
    retrieval=[r['retrieval'] for r in results if 'retrieval' in r]
    def linked(actual):
        return events.get(actual.get('request_id'))
    metrics=dict(schema='career-metrics-v1',started=raw['started'],finished=raw.get('finished'),
                 dataset_sha256=raw['dataset_sha256'],total=len(results),
                 automatic_pass=sum(all(r['checks'].values()) for r in results),
                 retrieval_count=len(retrieval),
                 retrieval={k:sum(r[k] for r in retrieval)/len(retrieval)
                            for k in ['hit_at_1','hit_at_3','recall_at_3','rr']},
                 data_unchanged=raw.get('data_unchanged'),benchmark=[],condition_review_flags=[])
    all_samples=[r['actual'] for r in results]+raw.get('warmups',[])
    case_lines=['# 本轮逐题结果（自动检查与条件筛查）','',
                '自动检查不是语义准确率。条件筛查只检查明确词句，不能替代逐条对照 FAQ 的语义复核。','']
    for r in results:
        c=r['case']; actual=r['actual']; body=actual['body']; event=linked(actual)
        answer=body.get('answer','')
        flags=[]
        if 'RULE-REFUND-02' in c['relevant'] and body.get('route')=='faq_rag' and not any(w in answer for w in ['审核','审批']):
            flags.append('原路退回渠道回答可能省略审核通过前提；待语义复核')
        if ('RULE-RETURN-03' in c['relevant'] and body.get('route')=='faq_rag'
                and any(w in answer for w in ['质量','错发']) and '核实' not in answer):
            flags.append('涉及质量/错发运费承担，可能省略店铺核实条件；待语义复核')
        if flags:
            metrics['condition_review_flags'].append(dict(id=c['id'],flags=flags,answer=answer))
        case_lines += ['## '+c['id'],'', '- 输入：'+json.dumps(c['payload'],ensure_ascii=False),
            '- 预期：'+str(c.get('route',c.get('status')))+'；'+c['rubric'],
            '- 实际：'+(answer or json.dumps(body,ensure_ascii=False)),
            '- 引用：'+json.dumps(body.get('sources',[]),ensure_ascii=False),
            '- 自动检查：'+json.dumps(r['checks'],ensure_ascii=False),
            '- 条件筛查：'+('；'.join(flags) if flags else '未触发已定义的两类条件提示；不代表语义全部通过'),
            '- 请求编号：'+str(actual.get('request_id')),
            '- 日志原因：'+str(event.get('reason') if event else '日志缺失'), '']
    for b in raw['benchmarks']:
        samples=b['samples']
        all_samples += [s['actual'] for s in samples]
        logs=[linked(s['actual']) for s in samples]
        m={k:v for k,v in b.items() if k!='samples'}
        m.update(logs_matched=sum(e is not None for e in logs),
                 technical_failures=sum(bool(e and e['technical_failure']) for e in logs),
                 failed_samples=[s for s in samples if not s['business_success']])
        metrics['benchmark'].append(m)
    logs=[linked(s) for s in all_samples]
    metrics.update(http_requests=len(all_samples),logs_matched=sum(e is not None for e in logs),
                   technical_failures=sum(bool(e and e['technical_failure']) for e in logs),
                   generation_requests=sum(bool(e and 'generation' in e['stages_ms']) for e in logs),
                   cases_complete=len(results)==46,benchmarks_complete=len(raw['benchmarks'])==4)
    (folder/'metrics.json').write_text(json.dumps(metrics,ensure_ascii=False,indent=2),encoding='utf-8')
    (folder/'cases.md').write_text('\n'.join(case_lines),encoding='utf-8')
    print(json.dumps(metrics,ensure_ascii=False,indent=2))
    if not (metrics['cases_complete'] and metrics['benchmarks_complete'] and raw.get('finished')
            and metrics['http_requests']==metrics['logs_matched']):
        sys.exit('Incomplete run or missing log evidence; do not claim full acceptance.')


if __name__=='__main__':
    main()
