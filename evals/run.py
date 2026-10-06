import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import hashlib,json,math,os,sys,time
from pathlib import Path
import urllib.request,urllib.error
sys.path.insert(0,'/app')
from cases import CASES,VERSION

def call(base,payload):
    start=time.perf_counter()
    request=urllib.request.Request(base+'/ask',data=json.dumps(payload).encode(),headers={'Content-Type':'application/json'})
    try:
        try: response=urllib.request.urlopen(request,timeout=45)
        except urllib.error.HTTPError as exc: response=exc
        with response:
            return dict(status=response.status,body=json.load(response),request_id=response.headers.get('x-request-id'),ms=(time.perf_counter()-start)*1000)
    except Exception as exc:
        return dict(status=0,body={},error=type(exc).__name__,ms=(time.perf_counter()-start)*1000)

def percentile(values,fraction):
    return sorted(values)[max(0,math.ceil(len(values)*fraction)-1)] if values else None

def score(case,actual):
    body=actual['body']
    checks={'http':actual['status']==case.get('status',200)}
    if case.get('status',200)==200:
        checks['contract']=(isinstance(body,dict) and set(body)=={'answer','route','sources','needs_human'} and isinstance(body.get('answer'),str) and bool(body.get('answer')) and isinstance(body.get('sources'),list) and all(isinstance(s,str) for s in body['sources']) and type(body.get('needs_human')) is bool)
        checks['route']=body.get('route')==case['route']
        checks['human']=body.get('needs_human') is case['needs_human']
        if case['relevant']:
            cited={s.split(' | ')[0] for s in body.get('sources',[]) if isinstance(s,str)}
            checks['required_citations']=set(case['relevant'])<=cited
        if case['route']=='handoff': checks['no_sources']=body.get('sources')==[]
    return checks

def retrieval_score(relevant,ids):
    ranks=[i+1 for i,id in enumerate(ids) if id in relevant]
    return dict(hit_at_1=bool(ranks and ranks[0]==1),hit_at_3=bool(ranks),recall_at_3=len(set(relevant)&set(ids))/len(set(relevant)),rr=1/min(ranks) if ranks else 0)

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--output',required=True)
    parser.add_argument('--base',default='http://127.0.0.1:8000')
    args=parser.parse_args()
    from app.faq_search import search_faq,MODEL_NAME
    import psycopg
    def snapshot():
        with psycopg.connect(os.environ['DATABASE_URL'],connect_timeout=5) as conn:
            return conn.execute('SELECT chunk_id,version,md5(content),md5(embedding::text) FROM faq_chunks ORDER BY chunk_id').fetchall()
    with urllib.request.urlopen(args.base+'/ready',timeout=30) as response: ready=json.load(response)
    data=dict(version=VERSION,started=datetime.now(timezone.utc).isoformat(),ready=ready,dataset_sha256=hashlib.sha256(json.dumps(CASES,ensure_ascii=False,sort_keys=True).encode()).hexdigest(),embedding_model=MODEL_NAME,generation_model=os.environ.get('DEEPSEEK_MODEL','deepseek-flash'),python=sys.version.split()[0],before=snapshot(),results=[],benchmarks=[])
    def save(): Path(args.output).write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
    for case in CASES:
        result=dict(case=case)
        if case['relevant']:
            rows=search_faq(case['payload']['question'])
            result['retrieved']=[dict(id=r['chunk_id'],score=r['score']) for r in rows]
            result['retrieval']=retrieval_score(case['relevant'],[r['chunk_id'] for r in rows])
        result['actual']=call(args.base,case['payload'])
        result['checks']=score(case,result['actual'])
        data['results'].append(result)
        save()
        print(json.dumps(dict(case=case['id'],passed=all(result['checks'].values()),route=result['actual']['body'].get('route'),ms=round(result['actual']['ms']))),flush=True)
    for kind,payload,count in [('order',{'question':'我的订单状态','order_id':'ORD-1001'},60),('rag',{'question':'付款后一般多久发货？'},6)]:
        for concurrency in [1,2]:
            warmup=call(args.base,payload)
            start=time.perf_counter()
            with ThreadPoolExecutor(max_workers=concurrency) as pool:
                samples=list(pool.map(lambda _:call(args.base,payload),range(count)))
            elapsed=time.perf_counter()-start
            expected='order_lookup' if kind=='order' else 'faq_rag'
            valid=[s['status']==200 and s['body'].get('route')==expected and s['body'].get('needs_human') is False for s in samples]
            times=[s['ms'] for s in samples]
            benchmark=dict(kind=kind,concurrency=concurrency,count=count,elapsed_s=elapsed,completed_rps=count/elapsed,successful_rps=sum(valid)/elapsed,business_success=sum(valid),p50_ms=percentile(times,.5),p95_ms=percentile(times,.95),max_ms=max(times),warmup=warmup,samples=samples)
            data['benchmarks'].append(benchmark)
            save()
            print(json.dumps({k:v for k,v in benchmark.items() if k not in ('samples','warmup')}),flush=True)
    data['after']=snapshot()
    data['data_unchanged']=data['before']==data['after']
    data['finished']=datetime.now(timezone.utc).isoformat()
    save()
if __name__=='__main__': main()
