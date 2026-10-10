"""Opt-in real DB/provider ablation: ingest once, compare modes at EACH streaming node."""
import argparse
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import sys
import time
from urllib.parse import urlparse
import uuid

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app.memory.config import MemoryConfig
from app.memory.embeddings import Embeddings
from app.memory.schemas import AddRequest, SearchRequest
from app.memory.service import MemoryService
from app.memory.store import PostgresStore
from evals.memory_eval import load_cases, score_case, percentile
from scripts.memory_admin import migrate


class QueryCache:
    def __init__(self,provider):
        self.provider,self.vectors=provider,{}

    def encode(self,texts):
        return self.provider.encode(texts)

    def query(self,text):
        if text not in self.vectors:
            self.vectors[text]=self.provider.query(text)
        return self.vectors[text]


def summarize(results,namespace):
    completed=[r for r in results if "metrics" in r]
    summary=dict(namespace=namespace,total=len(results),completed=len(completed),failed=len(results)-len(completed),
        completion_rate=len(completed)/len(results) if results else None,
        search_ms_p95=percentile([r["elapsed_ms"] for r in completed],.95))
    for k in (5,20,100):
        scores=[r["metrics"][str(k)] for r in completed]
        positives=[m for m in scores if m["recall"] is not None]
        summary.update({f"recall@{k}":sum(m["recall"] for m in positives)/len(positives) if positives else None,
            f"complete@{k}":sum(m["complete"] for m in positives)/len(positives) if positives else None,
            f"mrr@{k}":sum(m["reciprocal_rank"] for m in positives)/len(positives) if positives else None,
            f"audit_errors@{k}":sum(m["audit_errors"] for m in scores),
            f"leaks@{k}":sum(m["leakage_count"] for m in scores),
            **{f"{metric}@{k}":sum(m.get(metric, 0) for m in scores) for metric in (
                "fact_absent_return_count", "unknown_support_count", "explicit_irrelevant_count",
                "unjudged_return_count", "declared_sensitive_content_count")}})
    return summary


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--data",nargs="+",required=True)
    parser.add_argument("--env-file",help="Explicit credential file; never echoed or copied into evidence")
    parser.add_argument("--live",action="store_true",help="Required permission flag for PAID embedding calls")
    parser.add_argument("--case-ids",nargs="+")
    parser.add_argument("--output-dir",required=True)
    args=parser.parse_args()
    if not args.live:
        parser.error("--live is required for real model calls")
    if args.env_file:
        from dotenv import load_dotenv
        if not Path(args.env_file).is_file():
            parser.error("explicit environment file missing")
        load_dotenv(args.env_file,override=False)
    dsn=os.getenv("MEMORY_TEST_DATABASE_URL","")
    if not urlparse(dsn).path.endswith("_memory_test"):
        parser.error("explicit isolated MEMORY_TEST_DATABASE_URL ending in _memory_test required")
    # A production DATABASE_URL is never used for this runner.
    os.environ["DATABASE_URL"]=dsn
    config=MemoryConfig.from_env()
    cases=load_cases(args.data)
    dataset_population=len(cases)
    if args.case_ids:
        wanted=set(args.case_ids)
        if wanted-set(c["case_id"] for c in cases):
            parser.error("unknown requested case id")
        cases=[c for c in cases if c["case_id"] in wanted]
    modes={"vector":replace(config,retrieval="vector",neighbor_window=0,min_similarity=None,evidence_bytes=0),
           "hybrid":replace(config,retrieval="hybrid",neighbor_window=0,min_similarity=None,evidence_bytes=0),
           "bm25":replace(config,retrieval="bm25",neighbor_window=0,min_similarity=None,evidence_bytes=0),
           "bm25_window2_budget32k":replace(config,retrieval="bm25",neighbor_window=2,seed_limit=20,
                                            min_similarity=None,evidence_bytes=32768),
           "hybrid_bm25":replace(config,retrieval="hybrid_bm25",neighbor_window=0,min_similarity=None,evidence_bytes=0),
           "hybrid_bm25_window1":replace(config,retrieval="hybrid_bm25",neighbor_window=1,seed_limit=20,
                                         min_similarity=None,evidence_bytes=0)}
    migrate(config)
    namespace="local-ablation:"+uuid.uuid4().hex+":"
    cache=QueryCache(Embeddings(config))
    services={mode:MemoryService(c,PostgresStore(c),cache) for mode,c in modes.items()}
    results={mode:[] for mode in modes}
    target=Path(args.output_dir)
    if target.exists():
        parser.error("use a NEW output directory; preserve earlier experiments")
    target.mkdir(parents=True)
    source_paths=list((Path(__file__).resolve().parents[1]/"app/memory").glob("*.py"))
    source_paths += list((Path(__file__).resolve().parents[1]/"migrations").glob("*.sql"))+[Path(__file__).resolve()]
    def save():
        for mode,items in results.items():
            c=modes[mode]
            report=dict(execution="real_db_real_embedding_inprocess_not_HTTP",executed_at=datetime.now(timezone(timedelta(hours=8))).isoformat(),
                summary=summarize(items,namespace),cases=items,
                selected_cases=[c["case_id"] for c in cases],dataset_population=dataset_population,
                dataset_hashes={str(p):hashlib.sha256(Path(p).read_bytes()).hexdigest() for p in args.data},
                source_hashes={str(p.relative_to(Path(__file__).resolve().parents[1])):hashlib.sha256(p.read_bytes()).hexdigest() for p in source_paths},
                config={"MEMORY_RETRIEVAL_MODE":c.retrieval,"MEMORY_NEIGHBOR_WINDOW":c.neighbor_window,
                        "MEMORY_SEED_LIMIT":c.seed_limit,"MEMORY_EMBEDDING_MODEL":c.model,"MEMORY_EMBEDDING_DIM":c.dimension,
                        "MEMORY_CHUNK_TARGET_TOKENS":c.target,"MEMORY_CHUNK_OVERLAP_TOKENS":c.overlap},
                controls="Same stored embeddings/chunks. Compare modes before the NEXT node. Query embedding cached, not search results.",
                limitation="Sequential in-process timing, warmed query cache. Not external API latency, independent-network acceptance or cloud capacity.")
            (target/f"{mode}.json").write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
    for case in cases:
        try:
            for original in case["writes"]:
                request=AddRequest(**dict(original,user_id=namespace+original["user_id"],
                    session_id=namespace+original["session_id"],request_id=namespace+original["request_id"]))
                services["vector"].add(request)
        except Exception as exc:
            for mode in modes:
                results[mode].append(dict(case_id=case["case_id"],error_type=type(exc).__name__,stage="add"))
            save()
            continue
        # Seed vector once, then every mode receives the exact same query vector.
        request=SearchRequest(**dict(case["search"],user_id=namespace+case["search"]["user_id"]))
        try:
            cache.query(request.query)
        except Exception as exc:
            for mode in modes:
                results[mode].append(dict(case_id=case["case_id"],error_type=type(exc).__name__,stage="query_embedding"))
            save()
            continue
        for mode,service in services.items():
            try:
                started=time.perf_counter()
                data=[item.model_dump() for item in service.search(request).data]
                results[mode].append(dict(case_id=case["case_id"],category=case["category"],capability=case.get("capability"),
                    elapsed_ms=(time.perf_counter()-started)*1000,result_count=len(data),
                    content_bytes=sum(len(r["content"].encode()) for r in data),evidence=data,
                    metrics={str(k):score_case(case,data,namespace,k) for k in (5,20,100)}))
            except Exception as exc:
                results[mode].append(dict(case_id=case["case_id"],error_type=type(exc).__name__,stage="search"))
        save()  # Each node's raw record survives a later interruption.
        print(json.dumps({"case_id":case["case_id"],"completed_modes":sum("metrics" in results[m][-1] for m in modes)}))
    summaries={m:summarize(r,namespace) for m,r in results.items()}
    print(json.dumps(summaries,ensure_ascii=False))
    return int(any(s["failed"] or s["audit_errors@100"] or s["leaks@100"] for s in summaries.values()))


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(json.dumps({"status":"failed","error_type":type(exc).__name__}))
        raise SystemExit(1)
