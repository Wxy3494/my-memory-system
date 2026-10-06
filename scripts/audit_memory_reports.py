"""Audit saved synthetic API results without network calls or paid model requests."""
import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.memory.chunking import split_text
from evals.memory_eval import load_cases, score_case


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def audit(dataset, report):
    cases = load_cases([dataset])
    gold = {case['case_id']: case for case in cases}
    run = json.loads(Path(report).read_text(encoding='utf-8'))
    assert set(gold) == {row['case_id'] for row in run['cases']}
    assert len(run['cases']) == len(gold)
    assert digest(dataset) in run['dataset_hashes'].values(), 'dataset hash changed'
    # Runtime code must still match. This tool intentionally uses a corrected scorer.
    for path, old_hash in run['source_hashes'].items():
        if path != 'evals/memory_eval.py':
            assert digest(ROOT / path) == old_hash, 'runtime source changed: ' + path
    namespace = run['summary']['namespace']
    details = []
    config = run['config']
    for row in run['cases']:
        assert not row.get('error_type'), 'cannot audit incomplete HTTP run'
        case = gold[row['case_id']]
        data = row['evidence']
        candidates = sum(len(list(split_text(message['content'], int(config['MEMORY_CHUNK_TARGET_TOKENS']),
                                            int(config['MEMORY_CHUNK_OVERLAP_TOKENS']))))
                         for write in case['writes'] if write['user_id'] == case['search']['user_id']
                         for message in write['messages'])
        assert candidates < 100 and len(data) == candidates, 'baseline needs complete saved corpus'
        blind = sorted(data, key=lambda evidence: evidence['id'])
        strict = {str(k): score_case(case, data, namespace, k) for k in (5, 20, 100)}
        baseline = {str(k): score_case(case, blind, namespace, k) for k in (5, 20, 100)}
        details.append(dict(case_id=row['case_id'], category=row['category'], candidate_chunks=candidates,
                            strict_metrics=strict, blind_id_order_metrics=baseline))
    summary = dict(cases=len(details), evidence_cases=sum(bool(c['acceptable_evidence_groups']) for c in cases),
                   candidate_chunks_min=min(r['candidate_chunks'] for r in details),
                   candidate_chunks_max=max(r['candidate_chunks'] for r in details))
    for k in (5, 20, 100):
        for field, label in [('strict_metrics', 'vector'), ('blind_id_order_metrics', 'blind')]:
            scores = [r[field][str(k)]['recall'] for r in details if r[field][str(k)]['recall'] is not None]
            summary[f'{label}_recall@{k}'] = sum(scores) / len(scores) if scores else None
        summary[f'leakage_count@{k}'] = sum(r['strict_metrics'][str(k)]['leakage_count'] for r in details)
        summary[f'audit_errors@{k}'] = sum(r['strict_metrics'][str(k)]['audit_errors'] for r in details)
    return dict(dataset=str(dataset), dataset_sha256=digest(dataset), original_report=str(report),
                original_report_sha256=digest(report), original_scorer_sha256=run['source_hashes']['evals/memory_eval.py'],
                corrected_scorer_sha256=digest(ROOT / 'evals/memory_eval.py'), summary=summary, cases=details)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', default='docs/evidence/20261006-memory-local-closeout/strict-replay.json')
    args = parser.parse_args()
    base = ROOT / 'docs/evidence/20261006-memory-live'
    runs = [audit(ROOT / f'evals/memory_cases_{split}.jsonl', base / report)
            for split, report in [('dev', 'dev60-vector.json'), ('holdout', 'holdout40-vector.json')]]
    result = dict(network_calls=0, model_calls=0, method='Saved real API evidence, strict source auditing; blind baseline sorts the complete user corpus by chunk id without reading the query',
                  limitation='Template diagnostic set; all user corpora are below Top100. No official Answer/Full score.', runs=runs)
    path = ROOT / args.output
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps([run['summary'] for run in runs], ensure_ascii=False))
    return int(any(run['summary']['leakage_count@100'] or run['summary']['audit_errors@100'] for run in runs))


if __name__ == '__main__':
    raise SystemExit(main())
