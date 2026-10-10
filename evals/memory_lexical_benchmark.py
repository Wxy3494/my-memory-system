"""Real OFFLINE lexical ablation on raw slices; no fake dense scores or model answers."""
import argparse
from collections import defaultdict
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import sys
import time

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app.memory.chunking import make_chunks
from app.memory.config import MemoryConfig
from app.memory.retrieval import bm25_rank, keyword_terms, expand_neighbors, select_evidence, message_candidates,combine_context
from app.memory.signals import extract,plan
from app.memory.schemas import AddRequest
from evals.memory_eval import load_cases, score_case, percentile


def corpus(case,config):
    rows,seen,positions=[],set(),{}
    for write in case["writes"]:
        if write["user_id"] != case["search"]["user_id"]:
            continue
        key=(write["user_id"],write["request_id"])
        if key in seen:
            continue
        seen.add(key)
        start=positions.get(write["session_id"],0)
        positions[write["session_id"]]=start+len(write["messages"])
        for c in make_chunks(AddRequest(**write),config):
            m=write["messages"][c["ordinal"]]
            rows.append(dict(c,user_id=write["user_id"],session_id=write["session_id"],request_id=write["request_id"],
                sources=[dict(message_id=c["message_id"],session_id=write["session_id"],request_id=write["request_id"],
                    ordinal=c["ordinal"],role=m["role"],timestamp=m.get("timestamp"),start_offset=c["start_offset"],
                    end_offset=c["end_offset"],received_ordinal=start+c["ordinal"],
                    stored_at="2026-10-07T00:00:00+00:00",order_basis="received")]))
    return rows


def benchmark(cases):
    config=MemoryConfig("offline-unused","unused","unused","https://offline.invalid/v1")
    routes={route:[] for route in ("id_baseline","term_count","bm25","bm25_seed20","bm25_window1","bm25_window2_budget32k","bm25_contextual_v5")}
    for case in cases:
        rows=corpus(case,config)
        terms=keyword_terms(case["search"]["query"])
        for mode,results in routes.items():
            started=time.perf_counter()
            if mode=="id_baseline":
                ranked=[dict(r,score=1/(i+1)) for i,r in enumerate(sorted(rows,key=lambda r:r["chunk_id"]))]
            elif mode=="term_count":
                ranked=[dict(r,score=sum(t in r["content"].lower() for t in terms)) for r in rows]
                ranked=sorted([r for r in ranked if r["score"]>0],key=lambda r:(-r["score"],r["chunk_id"]))
            else:
                ranked=bm25_rank(rows,terms,100)
                if mode=="bm25_seed20":
                    ranked=ranked[:20]
                if mode=="bm25_window1":
                    ranked=expand_neighbors(ranked[:20],local_neighbors(rows,ranked[:20],1,terms),1)
                if mode=="bm25_window2_budget32k":
                    ranked=expand_neighbors(ranked[:20],local_neighbors(rows,ranked[:20],2,terms),2,100,32768)
                if mode=="bm25_contextual_v5":
                    direct=ranked
                    prefix=expand_neighbors(direct[:20],local_neighbors(rows,direct[:20],2,terms),2,100,32768)[:5]
                    records,by_message=local_records(case,rows)
                    ids,_=plan(records,case["search"]["query"],direct[:20],24,2)
                    context=[dict(row,score=1/(i+1)) for i,mid in enumerate(ids)
                        for row in message_candidates(by_message[mid],terms)[:2]]
                    selected=combine_context(direct,context)
                    selected=unique_order(prefix+selected)
                    expanded=expand_neighbors(selected[:24],local_neighbors(rows,selected[:24],2,terms),2,100,32768)
                    ranked=unique_order(prefix+expanded)[:100]
            data=[e.model_dump() for e in select_evidence(ranked,100)]
            results.append(dict(case_id=case["case_id"],capability=case["capability"],split=case["split"],
                candidates=len(rows),elapsed_ms=(time.perf_counter()-started)*1000,
                result_count=len(data),content_bytes=sum(len(e["content"].encode()) for e in data),
                metrics={str(k):score_case(case,data,"",k) for k in (5,20,100)},evidence=data))
    reports={}
    for mode,results in routes.items():
        grouped=defaultdict(list)
        for result in results:
            grouped[result["split"]].append(result)
            grouped[result["split"]+":"+result["capability"]].append(result)
        summaries={}
        for name,items in grouped.items():
            summary=dict(total=len(items),completed=len(items),failed=0,completion_rate=1,
                elapsed_ms_p95=percentile([r["elapsed_ms"] for r in items],.95),
                mean_return_count=sum(r["result_count"] for r in items)/len(items),
                mean_content_bytes=sum(r["content_bytes"] for r in items)/len(items))
            for k in (5,20,100):
                measurements=[r["metrics"][str(k)] for r in items]
                scored=[m for m in measurements if m["recall"] is not None]
                summary.update({f"recall@{k}":sum(m["recall"] for m in scored)/len(scored) if scored else None,
                    f"complete@{k}":sum(m["complete"] for m in scored)/len(scored) if scored else None,
                    f"mrr@{k}":sum(m["reciprocal_rank"] for m in scored)/len(scored) if scored else None,
                    f"audit_errors@{k}":sum(m["audit_errors"] for m in measurements),
                    f"leaks@{k}":sum(m["leakage_count"] for m in measurements),
                    **{f"{metric}@{k}":sum(m[metric] for m in measurements) for metric in (
                        "fact_absent_return_count", "unknown_support_count", "explicit_irrelevant_count",
                        "unjudged_return_count", "declared_sensitive_content_count")}})
            summaries[name]=summary
        reports[mode]=dict(summary={"namespace":"","execution":"offline_lexical_no_embedding_calls"},groups=summaries,cases=results)
    return reports


def local_neighbors(rows,seeds,window,terms):
    targets = {(s["session_id"],p) for seed in seeds for s in seed["sources"]
               for p in range(max(0,s["received_ordinal"]-window),s["received_ordinal"]+window+1)}
    groups = defaultdict(list)
    for row in rows:
        s=row["sources"][0]
        if (s["session_id"],s["received_ordinal"]) in targets:
            groups[s["message_id"]].append(row)
    return [row for message_id,group in groups.items() for row in message_candidates(group,terms,
        [s["start_offset"] for seed in seeds for s in seed["sources"] if s["message_id"]==message_id])]


def unique_order(rows):
    chosen={}
    for row in rows:
        if row["chunk_id"] not in chosen:
            chosen[row["chunk_id"]]=dict(row,score=1/(len(chosen)+1))
    return list(chosen.values())


def local_records(case,rows):
    groups=defaultdict(list); records=[]
    for row in rows:
        groups[row["sources"][0]["message_id"]].append(row)
    for mid,group in groups.items():
        s=group[0]["sources"][0]
        write=next(w for w in case["writes"] if w["user_id"]==case["search"]["user_id"] and w["request_id"]==s["request_id"])
        msg=write["messages"][s["ordinal"]]
        records.append(dict(message_id=mid,session_id=s["session_id"],request_id=s["request_id"],ordinal=s["ordinal"],role=s["role"],
            timestamp=s["timestamp"],stored_at=s["stored_at"],features=extract(msg["content"],s["role"],s["timestamp"])))
    return records,groups


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--data",nargs="+",required=True)
    parser.add_argument("--output-dir",required=True)
    args=parser.parse_args()
    reports=benchmark(load_cases(args.data))
    target=Path(args.output_dir)
    if target.exists():
        parser.error("use a NEW output directory; preserve previous evidence")
    target.mkdir(parents=True)
    summary={}
    for mode,report in reports.items():
        report.update(executed_at=datetime.now(timezone(timedelta(hours=8))).isoformat(),
            dataset_hashes={str(p):hashlib.sha256(Path(p).read_bytes()).hexdigest() for p in args.data},
            limitation="Offline CPU lexical latency, simulated receipt labels; not API/DB/cloud latency or Answer/Judge scores.")
        report["source_hashes"]={str(p.relative_to(Path(__file__).resolve().parents[1])):hashlib.sha256(p.read_bytes()).hexdigest()
            for p in [Path(__file__).resolve(),Path(__file__).resolve().parents[1]/"app/memory/retrieval.py",
                      Path(__file__).resolve().parents[1]/"app/memory/chunking.py",Path(__file__).resolve().with_name("memory_eval.py")]}
        (target/f"{mode}.json").write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
        summary[mode]=report["groups"]
    (target/"ablation-summary.json").write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps({mode:{split:report["groups"][split] for split in ("dev","holdout") if split in report["groups"]}
                      for mode,report in reports.items()},ensure_ascii=False))


if __name__ == "__main__":
    main()
