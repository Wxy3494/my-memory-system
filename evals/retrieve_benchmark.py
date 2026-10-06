"""Fixed 50/50 business/FAQ HTTP workload; standard library, no generation calls."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
WORKLOAD = [
    ({'question': '我的订单状态', 'order_id': 'ORD-1001'}, 'order_lookup', None),
    ({'question': '付款后一般多久发货？'}, 'faq_retrieval', 'RULE-SHIPPING-01'),
    ({'question': '我的退款状态', 'refund_id': 'REF-2001'}, 'refund_lookup', None),
    ({'question': '七天无理由退货有什么条件？'}, 'faq_retrieval', 'RULE-RETURN-01'),
]


def percentile(values, quantile):
    return sorted(values)[math.ceil(len(values) * quantile) - 1] if values else None


def summarize(rows, elapsed):
    times = [r['ms'] for r in rows]
    passed = sum(r['passed'] for r in rows)
    return dict(requests=len(rows), passed=passed, errors=len(rows)-passed,
                error_rate=(len(rows)-passed)/len(rows) if rows else None,
                elapsed_s=elapsed, completed_qps=len(rows)/elapsed,
                successful_qps=passed/elapsed, p50_ms=percentile(times, .5),
                p95_ms=percentile(times, .95), p99_ms=percentile(times, .99))


def request_one(base_url, index, timeout):
    payload, expected_route, required = WORKLOAD[index % len(WORKLOAD)]
    started = time.perf_counter()
    status, body, request_id, error = None, {}, None, None
    try:
        request = Request(base_url + '/v1/retrieve',
                          data=json.dumps(payload).encode(),
                          headers={'Content-Type': 'application/json'}, method='POST')
        try:
            response = urlopen(request, timeout=timeout)
        except HTTPError as exc:
            response = exc
        with response:
            status = response.status
            request_id = response.headers.get('X-Request-ID')
            body = json.load(response)
        if not isinstance(body, dict):
            raise ValueError('Unexpected response shape')
    except (OSError, URLError, ValueError) as exc:
        body = {}
        error = type(exc).__name__  # Never store URLs, credentials or raw errors.
    chunks = body.get('chunks') or []
    ids = [c.get('chunk_id') for c in chunks if isinstance(c, dict)]
    business = body.get('business_result') or {}
    passed = (error is None and status == 200 and body.get('route') == expected_route
              and body.get('needs_human') is False and bool(request_id))
    if required:
        passed = passed and body.get('reason') == 'candidates_found' and required in ids
    else:
        passed = (passed and body.get('reason') == 'record_found' and not chunks
                  and isinstance(business, dict) and business.get('route') == expected_route
                  and business.get('needs_human') is False)
    return dict(index=index, workload_index=index % len(WORKLOAD), expected_route=expected_route,
                status=status, route=body.get('route'), reason=body.get('reason'),
                request_id=request_id, chunk_ids=ids, passed=bool(passed), error=error,
                ms=(time.perf_counter()-started)*1000)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base-url', default='http://127.0.0.1:8000')
    parser.add_argument('--requests', type=int, default=1000)
    parser.add_argument('--concurrency', type=int, default=4)
    parser.add_argument('--timeout', type=float, default=15)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.requests < 4 or args.requests > 100000 or args.requests % 4:
        parser.error('--requests must be a multiple of 4 between 4 and 100000')
    if not 1 <= args.concurrency <= 64 or not 0 < args.timeout <= 120:
        parser.error('concurrency must be 1..64; timeout must be (0,120] seconds')
    url = urlsplit(args.base_url)
    if (url.scheme not in ('http', 'https') or not url.hostname or url.username or url.password
            or url.query or url.fragment or url.path not in ('', '/')):
        parser.error('--base-url must be an HTTP origin without credentials, query or path')
    if args.output.exists():
        parser.error('output exists; choose a new file to preserve prior evidence')
    args.output.parent.mkdir(parents=True, exist_ok=True)
    # Reserve the evidence file before any workload, so an existing run is never overwritten.
    with args.output.open('x', encoding='utf-8') as output:
        started_at = datetime.now(timezone.utc).isoformat()
        base_url = args.base_url.rstrip('/')
        warmups = [request_one(base_url, i, args.timeout) for i in range(4)]
        rows = []
        began = time.perf_counter()
        if all(r['passed'] for r in warmups):
            with ThreadPoolExecutor(max_workers=args.concurrency) as pool:
                rows = list(pool.map(lambda i: request_one(base_url, i, args.timeout), range(args.requests)))
        elapsed = time.perf_counter()-began
        summary = summarize(rows, elapsed)
        report = dict(schema='retrieval-benchmark-v1', started_at=started_at,
                      finished_at=datetime.now(timezone.utc).isoformat(), base_url=base_url,
                      workload=WORKLOAD, concurrency=args.concurrency, requested_count=args.requests,
                      cache_mode='no_query_or_answer_cache; model_warmed_by_probes',
                      client=dict(platform=platform.platform(), python=platform.python_version(),
                                  logical_cpus=os.cpu_count()),
                      local_source_sha256={str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
                          for p in sorted((ROOT/'app').glob('*.py'))},
                      faq_sha256=hashlib.sha256((ROOT/'docs/faq.md').read_bytes()).hexdigest(),
                      warmups=warmups, summary=summary,
                      by_route={route: summarize([r for r in rows if r['expected_route'] == route], elapsed)
                                for route in sorted({r['expected_route'] for r in rows})}, samples=rows,
                      limitation='Closed-loop finite workload; local hashes do not prove server image identity. '
                                 'Record server image, CPU/RAM, FAQ count and monitoring state separately. '
                                 'P99 is nearest-rank over all attempts, including failures; no generation or cache-hit claim.')
        json.dump(report, output, ensure_ascii=False, indent=2)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if not rows or summary['errors']:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
