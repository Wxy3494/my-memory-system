"""逐题评估 + 重复/新问题闭环负载；不修改业务代码和数据。"""
import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import sys
import time
import urllib.request

sys.path.insert(0, '/app')
from cases import CASES, VERSION
from career_workload import NEW_QUESTIONS
from run import call, percentile, retrieval_score, score


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', required=True)
    parser.add_argument('--base', default='http://127.0.0.1:8000')
    args = parser.parse_args()
    target = Path(args.output)
    if target.exists():
        raise SystemExit('Output exists; choose a new run name.')
    assert len(NEW_QUESTIONS) == len({q for q, _ in NEW_QUESTIONS}) == 40
    assert not ({q for q, _ in NEW_QUESTIONS} & {c['payload'].get('question') for c in CASES})
    from app.faq_search import search_faq, MODEL_NAME
    from app.faq_loader import load_faq
    import psycopg

    def snapshot():
        with psycopg.connect(os.environ['DATABASE_URL'], connect_timeout=5) as conn:
            return conn.execute('SELECT chunk_id,version,md5(content),md5(embedding::text) FROM faq_chunks ORDER BY chunk_id').fetchall()

    known = {f"{c['chunk_id']} | {c['source']}:{c['start_line']}-{c['end_line']} | 版本={c['version']}" for c in load_faq()}
    with urllib.request.urlopen(args.base+'/ready', timeout=30) as response:
        ready = json.load(response)
    data = dict(schema='career-evidence-v1', started=datetime.now(timezone.utc).isoformat(),
                dataset_version=VERSION, ready=ready, results=[], benchmarks=[],
                dataset_sha256=hashlib.sha256(json.dumps(CASES,ensure_ascii=False,sort_keys=True).encode()).hexdigest(),
                workload_sha256=hashlib.sha256(json.dumps(NEW_QUESTIONS,ensure_ascii=False).encode()).hexdigest(),
                embedding_model=MODEL_NAME, generation_model=os.environ.get('DEEPSEEK_MODEL','deepseek-flash'),
                runtime=dict(python=platform.python_version(), platform=platform.platform(), client='API container loopback'),
                before=snapshot(), code_sha256={name:hashlib.sha256(Path('/app/'+name).read_bytes()).hexdigest()
                                              for name in ['app/main.py','app/faq_search.py','app/faq_answer.py','docs/faq.md']})

    def save():
        target.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')

    def success(actual, rule):
        body = actual['body']
        sources = body.get('sources', []) if isinstance(body,dict) else []
        return (actual['status']==200 and body.get('route')=='faq_rag' and body.get('needs_human') is False
                and any(s.split(' | ')[0]==rule for s in sources) and all(s in known for s in sources))

    for case in CASES:
        row = dict(case=case)
        if case['relevant']:
            rows=search_faq(case['payload']['question'])
            row['retrieved']=[dict(id=r['chunk_id'],score=r['score']) for r in rows]
            row['retrieval']=retrieval_score(case['relevant'],[r['chunk_id'] for r in rows])
        row['actual']=call(args.base,case['payload'])
        row['checks']=score(case,row['actual'])
        if row['actual']['body'].get('route')=='faq_rag':
            row['checks']['citation_metadata']=all(s in known for s in row['actual']['body'].get('sources',[]))
        data['results'].append(row)
        save()
        print(json.dumps(dict(case=case['id'],automatic_pass=all(row['checks'].values()),ms=round(row['actual']['ms']))),flush=True)

    # 两次预热单独存储；新问题测量集在本次运行此前未请求过。
    data['warmups']=[call(args.base,{'question':'付款后一般多久发货？'}),
                     call(args.base,{'question':'签收后多久可以申请退货？'})]
    for workload, concurrency in [('repeated',1),('new',1),('repeated',2),('new',2)]:
        index = 0 if concurrency==1 else 20
        questions = ([('付款后一般多久发货？','RULE-SHIPPING-01')]*20
                     if workload=='repeated' else NEW_QUESTIONS[index:index+20])

        def invoke(item):
            question, rule = item
            return dict(question=question,required_rule=rule,actual=call(args.base,{'question':question}))

        started=time.perf_counter()
        with ThreadPoolExecutor(max_workers=concurrency) as pool:
            samples=list(pool.map(invoke,questions))
        elapsed=time.perf_counter()-started
        times=[s['actual']['ms'] for s in samples]
        for s in samples:
            s['business_success']=success(s['actual'],s['required_rule'])
        count=sum(s['business_success'] for s in samples)
        data['benchmarks'].append(dict(workload=workload,concurrency=concurrency,count=20,
            elapsed_s=elapsed,business_success=count,completed_rps=20/elapsed,successful_rps=count/elapsed,
            p50_ms=percentile(times,.5),p95_ms=percentile(times,.95),max_ms=max(times),samples=samples))
        save()
        print(json.dumps({k:v for k,v in data['benchmarks'][-1].items() if k!='samples'}),flush=True)
    data['after']=snapshot()
    data['data_unchanged']=data['before']==data['after']
    data['finished']=datetime.now(timezone.utc).isoformat()
    save()


if __name__=='__main__':
    main()
