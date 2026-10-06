"""聚合原始结果和脱敏服务日志；不调用模型，也不自动评分语义正确性。"""
import argparse,json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app.faq_loader import load_faq

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('result')
    parser.add_argument('log')
    parser.add_argument('output')
    args=parser.parse_args()
    data=json.loads(Path(args.result).read_text(encoding='utf-8-sig'))
    events={}
    for line in Path(args.log).read_text(encoding='utf-8-sig').splitlines():
        try: event=json.loads(line)
        except ValueError: continue
        if event.get('event')=='request_finished': events[event['request_id']]=event
    results=data['results']
    retrieval=[r['retrieval'] for r in results if 'retrieval' in r]
    known={f"{c['chunk_id']} | {c['source']}:{c['start_line']}-{c['end_line']} | 版本={c['version']}" for c in load_faq()}
    citations=[s for r in results if r['actual']['body'].get('route')=='faq_rag' for s in r['actual']['body']['sources']]
    samples=[r['actual'] for r in results]
    for benchmark in data['benchmarks']: samples.extend([benchmark['warmup'],*benchmark['samples']])
    linked=[events[s['request_id']] for s in samples if s.get('request_id') in events]
    summary=dict(total=len(results),automatic_pass=sum(all(r['checks'].values()) for r in results),
        failures=[dict(id=r['case']['id'],checks=r['checks']) for r in results if not all(r['checks'].values())],
        retrieval_count=len(retrieval),retrieval={k:sum(r[k] for r in retrieval)/len(retrieval) for k in ['hit_at_1','hit_at_3','recall_at_3','rr']},
        citations_count=len(citations),citations_metadata_valid=sum(s in known for s in citations),
        http_samples=len(samples),logs_matched=len(linked),technical_failures=sum(e['technical_failure'] for e in linked),
        generation_requests=sum('generation' in e['stages_ms'] for e in linked),
        data_unchanged=data.get('data_unchanged'),
        per_case=[dict(id=r['case']['id'],reason=events.get(r['actual'].get('request_id'),{}).get('reason'),technical_failure=events.get(r['actual'].get('request_id'),{}).get('technical_failure')) for r in results],
        benchmarks=[{k:v for k,v in b.items() if k not in ('samples','warmup')} for b in data['benchmarks']])
    Path(args.output).write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in summary.items() if k not in ('per_case','benchmarks')},ensure_ascii=False,indent=2))
if __name__=='__main__': main()
