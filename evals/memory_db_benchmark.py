"""Frozen candidate through real routes/SQL at every node; synthetic Add vectors only."""
import argparse
from dataclasses import replace
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sys
import time
from unittest.mock import patch
from urllib.parse import urlparse
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from fastapi.testclient import TestClient
from app.memory_main import app
from app.memory.config import MemoryConfig
from app.memory.routes import get_service
from app.memory.service import MemoryService
from app.memory.store import PostgresStore
from app.memory.schemas import SearchRequest
from evals.memory_eval import load_cases, score_case
from evals.memory_live_ablation import summarize
from scripts.measure_memory_local import FakeVectors
from scripts.memory_admin import migrate


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    parser.add_argument("--data", nargs="+")
    parser.add_argument("--candidate", default="evals/memory_candidate_v6.json")
    parser.add_argument("--ablation",action="store_true")
    parser.add_argument("--namespace")
    parser.add_argument("--case-ids", nargs="+")
    args = parser.parse_args()
    dsn = os.getenv("MEMORY_TEST_DATABASE_URL", "")
    if not urlparse(dsn).path.endswith("_memory_test"):
        parser.error("explicit isolated test database required")
    files = [Path(p).resolve() for p in args.data] if args.data else [ROOT/"evals"/f"{suite}_{split}.jsonl"
             for suite in ("memory_context_v4","memory_governance_v5") for split in ("dev", "holdout")]
    cases = load_cases(files)
    if args.case_ids:
        wanted=set(args.case_ids)
        if wanted-{c["case_id"] for c in cases}:
            parser.error("unknown selected case")
        cases=[c for c in cases if c["case_id"] in wanted]
    frozen = json.loads((ROOT/args.candidate).read_text())
    config = MemoryConfig(dsn, "local-test", "unused", "https://test.invalid/v1",
        retrieval=frozen["MEMORY_RETRIEVAL_MODE"], neighbor_window=frozen["MEMORY_NEIGHBOR_WINDOW"],
        seed_limit=frozen["MEMORY_SEED_LIMIT"], evidence_bytes=frozen["MEMORY_EVIDENCE_BYTES"],
        contextual=frozen.get("MEMORY_CONTEXTUAL_RETRIEVAL",False),context_limit=frozen.get("MEMORY_CONTEXT_LIMIT",48),
        link_hops=frozen.get("MEMORY_LINK_HOPS",2),signal_scan_limit=frozen.get("MEMORY_SIGNAL_SCAN_LIMIT",5000))
    migrate(config)
    store = PostgresStore(config)
    service = MemoryService(config, store, FakeVectors())
    baseline_config=replace(config,contextual=False)
    baseline=MemoryService(baseline_config,PostgresStore(baseline_config),FakeVectors())
    baseline_results=[]
    namespace = args.namespace or "round3-suite:" + uuid.uuid4().hex + ":"
    inserted_users, results = set(), []
    app.dependency_overrides[get_service] = lambda: service
    def save():
        grouped = {}
        for field in ("split", "capability"):
            for value in sorted({r[field] for r in results}):
                grouped[field+":"+value] = summarize([r for r in results if r[field] == value], namespace)
        report = dict(execution="real_ASGI_PostgreSQL_fake_Add_vectors_no_query_model", paid_model_calls=0,
            executed_at=datetime.now(timezone.utc).isoformat(), config=frozen,
            summary=summarize(results, namespace), groups=grouped, cases=results,
            dataset_hashes={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in files},
            source_hashes={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest()
                           for p in list((ROOT/"app/memory").glob("*.py")) + [Path(__file__),ROOT/"evals/memory_eval.py",ROOT/args.candidate]},
            limitation="Tests selected lexical route with real provenance/SQL. No real embedding/Answer/Judge, cloud network or official scoring.")
        if args.ablation:
            report["baseline_context_off"]=dict(summary=summarize(baseline_results,namespace),cases=baseline_results,
                control="Same current source/schema/stored embeddings; only contextual flag off; not frozen v4 image")
        Path(args.output).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        return report
    try:
        with patch.dict(os.environ, {"MEMORY_API_KEY":"local-test"}), TestClient(app) as client:
            headers = {"Authorization":"Bearer local-test"}
            for case in cases:
                row = dict(case_id=case["case_id"], split=case["split"], capability=case["capability"])
                try:
                    for write in case["writes"]:
                        body = dict(write, **{key:namespace+write[key] for key in ("user_id", "request_id", "session_id")})
                        inserted_users.add(body["user_id"])
                        client.post("/v1/memories/add", headers=headers, json=body).raise_for_status()
                    started = time.perf_counter()
                    response = client.post("/v1/memories/search", headers=headers,
                        json=dict(case["search"], user_id=namespace+case["search"]["user_id"]))
                    response.raise_for_status()
                    data = response.json()["data"]
                    search_elapsed=(time.perf_counter()-started)*1000
                    if args.ablation:
                        started_base=time.perf_counter()
                        base_data=[e.model_dump() for e in baseline.search(SearchRequest(**dict(case["search"],user_id=namespace+case["search"]["user_id"]))).data]
                        baseline_results.append(dict(case_id=case["case_id"],split=case["split"],capability=case["capability"],
                            elapsed_ms=(time.perf_counter()-started_base)*1000,evidence=base_data,
                            metrics={str(k):score_case(case,base_data,namespace,k) for k in (5,20,100)}))
                    row.update(elapsed_ms=search_elapsed, evidence=data,
                        metrics={str(k):score_case(case, data, namespace, k) for k in (5,20,100)},
                        result_count=len(data), content_bytes=sum(len(r["content"].encode()) for r in data))
                except Exception as exc:
                    row.update(error_type=type(exc).__name__)
                results.append(row)
                save()
    finally:
        app.dependency_overrides.clear()
        with store.connection() as conn:
            conn.execute("DELETE FROM memory.ingest_requests WHERE user_id=ANY(%s)", (sorted(inserted_users),))
    report = save()
    print(json.dumps(report["summary"]))
    return int(bool(report["summary"]["failed"] or report["summary"]["audit_errors@100"] or report["summary"]["leaks@100"]))


if __name__ == "__main__":
    raise SystemExit(main())
