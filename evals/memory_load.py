"""Opt-in, paid capacity workload. Defaults to a small 100-message sample."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
from datetime import datetime, timedelta, timezone
import time
import uuid

import httpx


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--messages", type=int, default=100)
    parser.add_argument("--users", type=int, default=1)
    parser.add_argument("--concurrency", type=int, default=1)
    parser.add_argument("--searches", type=int, default=20)
    parser.add_argument("--message-characters", type=int, default=0, help="0 retains short baseline; otherwise pad long similar messages")
    parser.add_argument("--batch-size", type=int, default=100)
    parser.add_argument("--timeout", type=float, default=300)
    parser.add_argument("--output")
    args = parser.parse_args()
    if (not 1 <= args.messages <= 100000 or not 1 <= args.users <= 1000 or not 1 <= args.concurrency <= 32 or args.searches < 1
            or not 0 <= args.message_characters <= 20000 or not 1 <= args.batch_size <= 1000 or not 1 <= args.timeout <= 600
            or args.batch_size*max(100,args.message_characters)*4 > 7*1024*1024):
        parser.error("invalid workload bounds")
    key = os.getenv("MEMORY_API_KEY")
    if not key:
        parser.error("MEMORY_API_KEY is required")
    prefix = "local-load:" + uuid.uuid4().hex + ":"
    users = [prefix + str(i) for i in range(args.users)]
    add_times, search_times, errors = [], [], []
    with httpx.Client(base_url=args.base_url, timeout=args.timeout, headers={"Authorization": "Bearer " + key}) as client:
        def add(batch):
            i, user, messages = batch
            started = time.perf_counter()
            try:
                result = client.post("/v1/memories/add", json=dict(request_id=prefix + f"r-{user}-{i}",
                    user_id=users[user], session_id=prefix + f"s-{user}", messages=messages))
                result.raise_for_status()
                if result.json().get("success") is not True:
                    raise ValueError()
                return (time.perf_counter() - started) * 1000, None
            except Exception as exc:
                return None, type(exc).__name__
        def message(user,number):
            text=f"自建容量测试记录{number}，项目编号LOAD-{user}-{number}，每周五下午开会。"
            if args.message_characters:
                # Keep exact near identifiers and the original fact; extend without truncation.
                missing=max(0,args.message_characters-len(text))
                filler="同主题相似记录与编号容易混淆，需要核对原始人物和时间。"
                text+=(filler*((missing+len(filler)-1)//len(filler)))[:missing]
            return dict(role="user",content=text)
        batches = [(i, u, [message(u,j) for j in range(i,min(i+args.batch_size,args.messages))])
                   for u in range(args.users) for i in range(0,args.messages,args.batch_size)]
        started = time.perf_counter()
        with ThreadPoolExecutor(max_workers=args.concurrency) as pool:
            for elapsed, error in pool.map(add, batches):
                (errors if error else add_times).append(error if error else elapsed)
        ingest_seconds = time.perf_counter() - started
        def search(i):
            started = time.perf_counter()
            try:
                response = client.post("/v1/memories/search", json=dict(user_id=users[i % len(users)],
                    query="我的项目周会什么时候举行？", top_k=100))
                response.raise_for_status()
                if not isinstance(response.json()["data"], list):
                    raise ValueError()
                data=response.json()["data"]
                if len(data)>100 or len({r["id"] for r in data})!=len(data):
                    raise ValueError("search_protocol_failure")
                if any(s["session_id"] != prefix+f"s-{i % len(users)}" for r in data for s in r.get("sources",[])):
                    raise ValueError("cross_user_evidence")
                return (time.perf_counter() - started) * 1000, None
            except Exception as exc:
                return None, type(exc).__name__
        with ThreadPoolExecutor(max_workers=args.concurrency) as pool:
            for elapsed, error in pool.map(search, range(args.searches)):
                (errors if error else search_times).append(error if error else elapsed)
    def percentile(values, p):
        import math
        return sorted(values)[max(0, math.ceil(len(values) * p) - 1)] if values else None
    report = dict(synthetic=True, executed_at=datetime.now(timezone(timedelta(hours=8))).isoformat(), timezone="Asia/Shanghai",
                  message_characters=args.message_characters,batch_size=args.batch_size,timeout_seconds=args.timeout,
                  users=users, requested_messages_per_user=args.messages, concurrency=args.concurrency,
                  ingest_seconds=ingest_seconds, add_batches_completed=len(add_times), search_completed=len(search_times),
                  add_ms_p50=percentile(add_times, .5), add_ms_p95=percentile(add_times, .95),
                  search_ms_p50=percentile(search_times, .5), search_ms_p95=percentile(search_times, .95),
                  errors=errors, storage_and_peak_memory="measure_on_server_separately")
    output = Path(args.output or f"evals/results/memory-load-{datetime.now(timezone(timedelta(hours=8))):%Y%m%d-%H%M%S}.json")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))
    return int(bool(errors))


if __name__ == "__main__":
    raise SystemExit(main())
