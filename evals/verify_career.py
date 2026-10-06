"""离线核验原始证据：重新计算检索、负载统计、检查与日志关系，无网络调用。"""
import argparse
import hashlib
import json
import math
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.faq_loader import load_faq
from cases import CASES
from career_workload import NEW_QUESTIONS


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('folder', type=Path)
    args = parser.parse_args()
    folder = args.folder
    raw = json.loads((folder / 'raw.json').read_text(encoding='utf-8-sig'))
    metrics = json.loads((folder / 'metrics.json').read_text(encoding='utf-8-sig'))
    baseline = json.loads((ROOT / 'docs/evaluation/stage5-baseline.json').read_text(encoding='utf-8-sig'))
    errors = []

    def require(condition, description):
        if not condition:
            errors.append(description)

    def close(actual, expected, description):
        require(isinstance(actual, (int, float)) and math.isfinite(actual)
                and math.isclose(actual, expected, rel_tol=1e-9, abs_tol=1e-7), description)

    cases = [r['case'] for r in raw['results']]
    require(cases == CASES, 'fixed cases differ from source')
    require(len(cases) == 46 and len({c['id'] for c in cases}) == 46, 'case count/identity')
    case_hash = hashlib.sha256(json.dumps(cases, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    require(case_hash == raw['dataset_sha256'] == baseline['dataset_sha256'], 'dataset hash mismatch')
    for name, expected in raw['code_sha256'].items():
        require(digest(ROOT / name) == expected, 'source version differs: ' + name)
    for row in json.loads((folder / 'tooling-hashes.json').read_text(encoding='utf-8-sig')) if (folder / 'tooling-hashes.json').exists() else []:
        require(digest(ROOT / 'evals' / row['file']) == row['Hash'].lower(), 'tool version differs: ' + row['file'])

    sources = {f"{c['chunk_id']} | {c['source']}:{c['start_line']}-{c['end_line']} | 版本={c['version']}" for c in load_faq()}
    automatic = 0
    retrieval = []
    for row in raw['results']:
        c, a = row['case'], row['actual']
        body = a['body']
        expected = {'http': a['status'] == c.get('status', 200)}
        if c.get('status', 200) == 200:
            cited = body.get('sources', [])
            expected.update(contract=(set(body) == {'answer','route','sources','needs_human'}
                and isinstance(body.get('answer'), str) and bool(body['answer'])
                and isinstance(cited, list) and all(isinstance(s, str) for s in cited)
                and type(body.get('needs_human')) is bool),
                route=body.get('route') == c['route'], human=body.get('needs_human') is c['needs_human'])
            if c['relevant']:
                expected['required_citations'] = set(c['relevant']) <= {s.split(' | ')[0] for s in cited}
            if c['route'] == 'handoff':
                expected['no_sources'] = cited == []
            if body.get('route') == 'faq_rag':
                expected['citation_metadata'] = all(s in sources for s in cited)
        require(expected == row['checks'], 'stored checks differ: ' + c['id'])
        automatic += all(expected.values())
        if c['relevant']:
            ids = [r['id'] for r in row['retrieved']][:3]
            require(len(row['retrieved']) <= 3, 'retrieval exceeds top3: ' + c['id'])
            relevant = set(c['relevant'])
            ranks = [i + 1 for i, item in enumerate(ids) if item in relevant]
            recalculated = dict(hit_at_1=bool(ids and ids[0] in relevant), hit_at_3=bool(ranks),
                recall_at_3=len(relevant.intersection(ids)) / len(relevant), rr=1/min(ranks) if ranks else 0)
            require(recalculated == row['retrieval'], 'retrieval score differs: ' + c['id'])
            retrieval.append(recalculated)
    require(automatic == metrics['automatic_pass'] and len(cases) == metrics['total'], 'automatic totals')
    require(len(retrieval) == metrics['retrieval_count'], 'retrieval denominator')
    for key in ['hit_at_1','hit_at_3','recall_at_3','rr']:
        close(metrics['retrieval'][key], sum(r[key] for r in retrieval)/len(retrieval), key)

    samples = [r['actual'] for r in raw['results']] + raw['warmups']
    new_questions = []
    require([(b['workload'], b['concurrency']) for b in raw['benchmarks']] ==
            [('repeated',1),('new',1),('repeated',2),('new',2)], 'benchmark group completeness/order')
    for index, b in enumerate(raw['benchmarks']):
        rows = b['samples']
        require(len(rows) == b['count'] == 20, 'benchmark sample count')
        valid = 0
        times = []
        for row in rows:
            a = row['actual']; body = a['body']; cited = body.get('sources', [])
            passed = (a['status'] == 200 and body.get('route') == 'faq_rag'
                and body.get('needs_human') is False and row['required_rule'] in {s.split(' | ')[0] for s in cited}
                and all(s in sources for s in cited))
            require(passed == row['business_success'], 'business result differs')
            valid += passed
            require(math.isfinite(a['ms']) and a['ms'] > 0, 'invalid request duration')
            times.append(a['ms']); samples.append(a)
            if b['workload'] == 'new':
                new_questions.append((row['question'], row['required_rule']))
            else:
                require(row['question'] == '付款后一般多久发货？', 'repeated input differs')
        require(valid == b['business_success'], 'business total differs')
        require(b['elapsed_s'] > 0, 'wall clock duration')
        expected_stats = dict(completed_rps=len(rows)/b['elapsed_s'], successful_rps=valid/b['elapsed_s'],
            p50_ms=sorted(times)[math.ceil(len(times)*.5)-1],
            p95_ms=sorted(times)[math.ceil(len(times)*.95)-1], max_ms=max(times))
        for key, value in expected_stats.items():
            close(b[key], value, 'raw ' + key)
            close(metrics['benchmark'][index][key], value, 'summary ' + key)
    require(new_questions == NEW_QUESTIONS and len({q for q, _ in new_questions}) == 40, 'new input identity/uniqueness')
    require(not {q for q, _ in new_questions}.intersection(c['payload'].get('question') for c in cases), 'new/fixed overlap')
    workload_hash = hashlib.sha256(json.dumps(new_questions,ensure_ascii=False).encode()).hexdigest()
    require(workload_hash == raw['workload_sha256'], 'workload hash')
    require(raw['before'] == raw['after'] == baseline['before'] and raw['data_unchanged'] is True
            and metrics['data_unchanged'] is True, 'FAQ snapshot changed')

    events = {}
    for line in (folder / 'server-log.jsonl').read_text(encoding='utf-8-sig').splitlines():
        try:
            e = json.loads(line)
        except ValueError:
            continue
        if e.get('event') == 'request_finished':
            require(e['request_id'] not in events, 'duplicate log request id')
            events[e['request_id']] = e
    require(len(samples) == metrics['http_requests'] == 128, 'total requests')
    require(len({s.get('request_id') for s in samples}) == 128, 'request id uniqueness')
    linked = [events.get(s.get('request_id')) for s in samples]
    matched = sum(e is not None for e in linked)
    require(matched == metrics['logs_matched'] == len(samples), 'missing request log')
    require(sum(bool(e and e['technical_failure']) for e in linked) == metrics['technical_failures'], 'technical failure total')
    require(sum(bool(e and 'generation' in e['stages_ms']) for e in linked) == metrics['generation_requests'], 'generation total')
    require(bool(raw.get('finished')), 'run not finished')
    for s, e in zip(samples, linked):
        if e and s['status'] == 200:
            require(e['route'] == s['body']['route'], 'response/log route mismatch')
    report = dict(schema='career-verification-v1', passed=not errors, errors=errors,
        raw_sha256=digest(folder/'raw.json'), metrics_sha256=digest(folder/'metrics.json'),
        verifier_sha256=digest(Path(__file__)), fixed_cases=len(cases), automatic_pass=automatic,
        retrieval_questions=len(retrieval), load_requests=len(samples)-len(cases)-len(raw['warmups']),
        request_logs_matched=matched,
        baseline_automatic_pass=sum(all(r['checks'].values()) for r in baseline['results']),
        scope='Offline arithmetic, identity, citations and log checks; no semantic accuracy claim.')
    (folder/'verification.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False,indent=2))
    if errors:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
