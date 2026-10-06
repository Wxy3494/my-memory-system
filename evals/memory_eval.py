"""Evidence evaluation against a REAL running API, using local synthetic data only."""
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import time
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.memory.chunking import stable_id


def load_cases(paths):
    cases = []
    owners, ids = {}, set()
    for path in paths:
        for line in Path(path).read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            case = json.loads(line)
            if case["case_id"] in ids:
                raise ValueError("duplicate case_id")
            ids.add(case["case_id"])
            for write in case["writes"]:
                owner = owners.setdefault(write["user_id"], str(path))
                if owner != str(path):
                    raise ValueError("user shared across dataset splits")
            messages = {(w["request_id"], i): m for w in case["writes"]
                        if w["user_id"] == case["search"]["user_id"] for i, m in enumerate(w["messages"])}
            for group in case["acceptable_evidence_groups"]:
                for ref in group:
                    message = messages[(ref["request_id"], ref["ordinal"])]
                    if ref.get("quote") and ref["quote"] not in message["content"]:
                        raise ValueError("expected quote absent from source")
            cases.append(case)
    return cases


def percentile(values, fraction):
    if not values:
        return None
    values = sorted(values)
    return round(values[max(0, math.ceil(len(values) * fraction) - 1)], 3)


def score_case(case, data, namespace, k):
    corpus = {}
    for w in case["writes"]:
        if w["user_id"] == case["search"]["user_id"]:
            for i, message in enumerate(w["messages"]):
                key = stable_id("message", namespace + w["user_id"], namespace + w["request_id"], i)
                corpus[key] = (w, i, message)
    found, leaks, audit_errors = [], 0, 0
    for row in data[:k]:
        sources = row.get("sources")
        content = row.get("content")
        if not isinstance(sources, list) or not sources or not isinstance(content, str):
            audit_errors += 1
            continue
        header, separator, raw = content.partition("\n")
        valid = bool(separator and header.startswith("[source ") and header.endswith("]"))
        try:
            labels = json.loads(header[8:-1]) if valid else None
        except (ValueError, TypeError):
            labels = None
        candidates, expected_labels = [], []
        for source in sources:
            if not isinstance(source, dict):
                valid = False
                continue
            original = corpus.get(source.get("message_id"))
            if original is None:
                leaks += 1
                valid = False
                continue
            write, ordinal, message = original
            start, end = source.get("start_offset"), source.get("end_offset")
            expected = dict(message_id=source["message_id"], session_id=namespace + write["session_id"],
                            request_id=namespace + write["request_id"], ordinal=ordinal,
                            role=message["role"], timestamp=message.get("timestamp"),
                            start_offset=start, end_offset=end)
            if (set(source) != set(expected) or source != expected
                    or type(source.get("ordinal")) is not int
                    or (source.get("timestamp") is not None and type(source["timestamp"]) is not int)
                    or type(start) is not int or type(end) is not int
                    or not 0 <= start < end <= len(message["content"])
                    or raw != message["content"][start:end]):
                valid = False
                continue
            expected_labels.append(dict(role=message["role"], timestamp_ms=message.get("timestamp"),
                                        session_id=namespace + write["session_id"], ordinal=ordinal,
                                        start_offset=start, end_offset=end))
            candidates.append((write["request_id"], ordinal, raw))
        # Compare the complete canonical header too: no discarded or unassociated text.
        expected_header = "[source " + json.dumps(expected_labels, ensure_ascii=False, separators=(",", ":")) + "]"
        if not valid or labels != expected_labels or header != expected_header:
            audit_errors += 1
            continue
        found.extend(candidates)
    groups = case["acceptable_evidence_groups"]
    if not groups:
        return dict(recall=None, complete=None, leakage_count=leaks, audit_errors=audit_errors,
                    unrelated_count=len(data[:k]))
    recalls = []
    for group in groups:
        covered = sum(any(r == ref["request_id"] and o == ref["ordinal"] and
                          (not ref.get("quote") or ref["quote"] in text) for r, o, text in found) for ref in group)
        recalls.append(covered / len(group))
    best = max(recalls)
    return dict(recall=best, complete=best == 1, leakage_count=leaks,
                audit_errors=audit_errors, unrelated_count=None)


def http_run(args, cases):
    import httpx
    key = os.getenv("MEMORY_API_KEY", "")
    if not key:
        raise ValueError("MEMORY_API_KEY is required")
    namespace = args.namespace or "local-eval:" + uuid.uuid4().hex + ":"
    results, latencies = [], []
    with httpx.Client(base_url=args.base_url.rstrip("/"), timeout=300,
                      headers={"Authorization": "Bearer " + key}) as client:
        for case in cases:
            try:
                for original in case["writes"]:
                    write = dict(original, user_id=namespace + original["user_id"],
                                 request_id=namespace + original["request_id"], session_id=namespace + original["session_id"])
                    response = client.post("/v1/memories/add", json=write)
                    response.raise_for_status()
                    if response.json() != {"success": True, **{k: write[k] for k in ("request_id", "user_id", "session_id")}}:
                        raise ValueError("add_protocol_failure")
                request = dict(case["search"], user_id=namespace + case["search"]["user_id"], top_k=100)
                start = time.perf_counter()
                response = client.post("/v1/memories/search", json=request)
                elapsed = (time.perf_counter() - start) * 1000
                response.raise_for_status()
                data = response.json()["data"]
                if (not isinstance(data, list) or len(data) > 100 or len({r["id"] for r in data}) != len(data)
                        or any(not isinstance(r["content"], str) or not r["content"] or not r.get("sources") for r in data)
                        or any(data[i]["score"] < data[i+1]["score"] for i in range(len(data)-1))):
                    raise ValueError("search_protocol_failure")
                latencies.append(elapsed)
                results.append(dict(case_id=case["case_id"], category=case["category"],
                                    elapsed_ms=round(elapsed, 3), result_count=len(data),
                                    metrics={str(k): score_case(case, data, namespace, k) for k in (5, 20, 100)},
                                    evidence=data))
            except Exception as exc:
                # HTTP errors may include response content. Never write their messages.
                results.append(dict(case_id=case["case_id"], error_type=type(exc).__name__))
    summary = dict(dataset_cases=len(cases), completed=sum("metrics" in r for r in results),
                   failed=sum("error_type" in r for r in results), namespace=namespace,
                   search_ms_p50=percentile(latencies, .5), search_ms_p95=percentile(latencies, .95),
                   duplicate_database_writes="not_measured_by_HTTP_evaluator")
    summary["completion_rate"] = summary["completed"] / len(cases) if cases else None
    summary["metric_population"] = "completed cases; no-answer cases excluded from recall"
    for k in (5, 20, 100):
        measurements = [r["metrics"][str(k)] for r in results if "metrics" in r]
        values = [m["recall"] for m in measurements if m["recall"] is not None]
        summary[f"recall@{k}"] = sum(values) / len(values) if values else None
        summary[f"recall_denominator@{k}"] = len(values)
        summary[f"complete_coverage@{k}"] = sum(v == 1 for v in values) / len(values) if values else None
        summary[f"leakage_count@{k}"] = sum(m["leakage_count"] for m in measurements)
        summary[f"audit_errors@{k}"] = sum(m["audit_errors"] for m in measurements)
        summary[f"no_answer_unrelated_count@{k}"] = sum(m["unrelated_count"] or 0 for m in measurements)
    return summary, results


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", nargs="+", default=["evals/memory_cases_dev.jsonl"])
    parser.add_argument("--validate-only", action="store_true")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--namespace")
    parser.add_argument("--output", default="evals/results/memory-run.json")
    parser.add_argument("--label", default="v0-vector")
    args = parser.parse_args()
    try:
        cases = load_cases(args.data)
        if args.validate_only:
            print(json.dumps(dict(status="valid", cases=len(cases), data=args.data), ensure_ascii=False))
            return 0
        summary, results = http_run(args, cases)
        hashes = {str(p): hashlib.sha256(Path(p).read_bytes()).hexdigest() for p in args.data}
        root = Path(__file__).resolve().parents[1]
        sources = list((root / "app/memory").glob("*.py")) + list((root / "migrations").glob("*.sql"))
        sources += [root / "app/memory_main.py", root / "app/observability.py", Path(__file__).resolve()]
        source_hashes = {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sources}
        config = {k: os.getenv(k) for k in ("MEMORY_EMBEDDING_MODEL", "MEMORY_EMBEDDING_DIM", "MEMORY_PIPELINE_VERSION",
                   "MEMORY_CHUNK_TARGET_TOKENS", "MEMORY_CHUNK_OVERLAP_TOKENS", "MEMORY_RETRIEVAL_MODE")}
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(dict(label=args.label, source_hashes=source_hashes, config=config,
                                         dataset_hashes=hashes, summary=summary, cases=results), ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(summary, ensure_ascii=False))
        return 1 if summary["failed"] or summary["leakage_count@100"] or summary["audit_errors@100"] else 0
    except Exception as exc:
        print(json.dumps({"status": "failed", "error_type": type(exc).__name__}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
