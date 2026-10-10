"""Actual ASGI routes + PostgreSQL; fake vectors; no cloud or semantic claims."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sys
import time
from urllib.parse import urlparse
import uuid
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from fastapi.testclient import TestClient
from app.memory_main import app
from app.memory.config import MemoryConfig
from app.memory.routes import get_service
from app.memory.service import MemoryService
from app.memory.store import PostgresStore
from scripts.memory_admin import migrate
from evals.memory_eval import percentile, score_case


class FakeVectors:
    def encode(self, texts):
        return [[1.] + [0.] * 1023 for _ in texts]

    def query(self, text):
        raise AssertionError("BM25 must not call query embedding")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    dsn = os.environ.get("MEMORY_TEST_DATABASE_URL", "")
    if not urlparse(dsn).path.endswith("_memory_test"):
        parser.error("explicit temporary test database required")
    config = MemoryConfig(dsn, "local-test", "unused", "https://test.invalid/v1", retrieval="bm25",
                          neighbor_window=2, evidence_bytes=32768,contextual=True,context_limit=24)
    migrate(config)
    store = PostgresStore(config)
    service = MemoryService(config, store, FakeVectors())
    namespace = "round2:" + uuid.uuid4().hex
    writes = []
    for key, text in (("first", "ALPHA-ONE ALPHA-TWO 第一证据。" + "常规段落abcd。" * 4000),
                      ("second", "BETA-ONE 第二证据，审批人在杭州。"),
                      ("third", "GAMMA-ONE 第三证据，办公室在西楼。")):
        writes.append(dict(user_id=namespace, request_id=key, session_id=key,
                           messages=[dict(role="user", content=text)]))
    case = dict(writes=writes, search=dict(user_id=namespace), acceptable_evidence_groups=[[
        dict(request_id=key, ordinal=0, quote=quote) for key, quote in
        (("first", "ALPHA-ONE"), ("second", "BETA-ONE"), ("third", "GAMMA-ONE"))]])
    report = dict(execution="inprocess_ASGI_real_PostgreSQL_fake_vectors", paid_model_calls=0,
                  started_at=datetime.now(timezone.utc).isoformat(), counterexample={}, workloads={})
    app.dependency_overrides[get_service] = lambda: service
    try:
        with patch.dict(os.environ, {"MEMORY_API_KEY": "local-test"}), TestClient(app) as client:
            headers = {"Authorization": "Bearer local-test"}
            report["unauthorized_status"] = client.post("/v1/memories/search", json=dict(user_id=namespace, query="ALPHA-ONE")).status_code
            for write in writes:
                client.post("/v1/memories/add", json=write, headers=headers).raise_for_status()
            for budget in (0, 32768, 1):
                service.config = replace(config, evidence_bytes=budget)
                for k in (2, 5, 100):
                    response = client.post("/v1/memories/search", headers=headers,
                        json=dict(user_id=namespace, query="ALPHA-ONE ALPHA-TWO BETA-ONE GAMMA-ONE", top_k=k))
                    response.raise_for_status()
                    data = response.json()["data"]
                    report["counterexample"][f"bytes{budget}_top{k}"] = dict(
                        metrics=score_case(case, data, "", k), count=len(data), evidence=data)
                    if budget != 1 and k >= 5:
                        assert report["counterexample"][f"bytes{budget}_top{k}"]["metrics"]["complete"]
            service.config = config
            for population in (100, 1000):
                noise = dict(user_id=namespace, request_id=f"noise-{population}", session_id="noise",
                    messages=[dict(role="user", content=f"批次{population}参考档案{i} ALPHA-OTHER BETA-OTHER，与主项目无关。")
                              for i in range(population)])
                client.post("/v1/memories/add", json=noise, headers=headers).raise_for_status()
                for concurrency in (1, 4, 16):
                    def search(index):
                        start = time.perf_counter()
                        target_user = namespace if index % 4 else namespace + ":foreign"
                        response = client.post("/v1/memories/search", headers=headers,
                            json=dict(user_id=target_user, query="ALPHA-ONE ALPHA-TWO BETA-ONE GAMMA-ONE", top_k=100))
                        response.raise_for_status()
                        data = response.json()["data"]
                        assert target_user == namespace or data == []
                        if target_user == namespace:
                            assert score_case(case, data, "", 100)["complete"]
                        return dict(ms=(time.perf_counter()-start)*1000, count=len(data), foreign=target_user != namespace)
                    with ThreadPoolExecutor(max_workers=concurrency) as pool:
                        samples = list(pool.map(search, range(24)))
                    with store.connection() as conn:
                        count = conn.execute("SELECT count(*) AS n FROM memory.chunks WHERE user_id=%s", (namespace,)).fetchone()["n"]
                    report["workloads"][f"noise{population}_concurrency{concurrency}"] = dict(
                        actual_chunks=count, samples=samples, completed=len(samples), failures=0,
                        p95_ms=percentile([s["ms"] for s in samples], .95))
    finally:
        app.dependency_overrides.clear()
        with store.connection() as conn:
            conn.execute("DELETE FROM memory.ingest_requests WHERE user_id=%s", (namespace,))
    report.update(config=dict(retrieval="bm25", neighbor_window=2, seed_limit=20, evidence_bytes=32768,contextual=True,context_limit=24,
                              min_similarity=None, query_model_calls=0),
                  limitation="Local ASGI client includes routing, auth and DB. Fake Add vectors; no TCP/cloud/model latency, no semantic accuracy.",
                  source_hashes={str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
                                 for p in list((ROOT / "app/memory").glob("*.py")) + [Path(__file__)]})
    Path(args.output).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: {n:v for n,v in value.items() if n != "samples"} for k,value in report["workloads"].items()}))


if __name__ == "__main__":
    main()
