"""Live synthetic HTTP checks (paid embedding calls). Does not run platform Smoke."""
import argparse
import json
import os
from pathlib import Path
import sys
import uuid

import httpx

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--output", default="evals/results/memory-smoke.json")
    parser.add_argument("--check-existing", help="Read saved smoke report and verify persisted evidence after restart")
    args = parser.parse_args()
    key = os.getenv("MEMORY_API_KEY")
    if not key:
        parser.error("MEMORY_API_KEY is required")
    prefix = "local-smoke:" + uuid.uuid4().hex + ":"
    user, other = prefix + "a", prefix + "b"
    if args.check_existing:
        old = json.loads(Path(args.check_existing).read_text(encoding="utf-8"))
        user, other = old["users"]
    checks = []
    try:
        with httpx.Client(base_url=args.base_url.rstrip("/"), timeout=300,
                          headers={"Authorization": "Bearer " + key}) as client:
            def search(who):
                response = client.post("/v1/memories/search", json=dict(user_id=who,
                    query="我的项目会、订单退款和人工客服记录", top_k=100, options=["A. 周五", "B. 周一"]))
                response.raise_for_status()
                return response.json()["data"]
            if not args.check_existing:
                write = dict(request_id=prefix + "write", user_id=user, session_id=prefix + "s1",
                    messages=[dict(role="user", content="我通常在周五下午开项目会。", timestamp=1704067200000)])
                response = client.post("/v1/memories/add", json=write)
                response.raise_for_status()
                assert response.json() == dict(success=True, request_id=write["request_id"], user_id=user, session_id=write["session_id"])
                checks.append("exact_echo")
                before = search(user)
                assert before and "周五下午" in before[0]["content"]
                assert before[0]["sources"][0]["timestamp"] == 1704067200000
                checks.append("immediate_search_and_timestamp")
                retry = client.post("/v1/memories/add", json=write)
                assert retry.status_code == 200 and retry.json() == response.json()
                assert search(user) == before
                checks.append("retry_same_evidence")
                conflict = client.post("/v1/memories/add", json=dict(write, session_id=prefix + "changed"))
                assert conflict.status_code == 409
                checks.append("conflict_409")
                wrong_key = client.post("/v1/memories/add", json=write, headers={"Authorization": "Bearer deliberately-invalid"})
                assert wrong_key.status_code == 401
                checks.append("wrong_token_401")
                incremental = dict(write, request_id=prefix + "write2", session_id=prefix + "s2",
                    messages=[dict(role="assistant", content="我建议先找人工客服处理退款。"),
                              dict(role="user", content="我的订单退款记录编号是SMOKE-ABC。")])
                response = client.post("/v1/memories/add", json=incremental)
                response.raise_for_status()
                checks.append("incremental_write")
            data = search(user)
            assert any("周五下午" in r["content"] for r in data)
            assert any("SMOKE-ABC" in r["content"] for r in data)
            assert any(s["role"] == "assistant" for r in data for s in r["sources"])
            assert len({r["id"] for r in data}) == len(data) and len(data) <= 100
            checks.append("cross_session_evidence_role_and_top100")
            assert search(other) == []
            checks.append("empty_other_user")
            readiness = client.get("/ready/memory")
            assert readiness.status_code == 200
            checks.append("api_process_recent_embedding_readiness")
        report = dict(status="passed", check_existing=bool(args.check_existing), users=[user, other],
                      checks=checks, result_count=len(data), local_synthetic=True,
                      platform_smoke="not_performed", database_duplicate_count="not_measured_by_http")
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(report, ensure_ascii=False))
        return 0
    except Exception as exc:
        print(json.dumps(dict(status="failed", completed_checks=checks, error_type=type(exc).__name__)))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
