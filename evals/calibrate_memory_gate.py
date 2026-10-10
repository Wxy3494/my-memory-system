"""DEV-only cosine gate calibration. Never treats RRF/BM25 scores as similarity."""
import argparse
import hashlib
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from evals.memory_eval import load_cases


def calibrate(cases, results, mode, max_false_rejection=0.0):
    if mode != "vector" or any(c["split"] != "dev" for c in cases):
        raise ValueError("calibration requires DEV and genuine vector output")
    positives, negatives = [], []
    for case in cases:
        result = results.get(case["case_id"])
        if result is None or "error_type" in result or not result.get("evidence"):
            raise ValueError("incomplete ungated calibration run")
        score = max(row["score"] for row in result["evidence"])
        if not -1 <= score <= 1:
            raise ValueError("invalid cosine score")
        needs_evidence = case["acceptable_evidence_groups"] or case.get("evidence_annotations", {}).get("unknown_support")
        (positives if needs_evidence else negatives).append(score)
    if not positives or not negatives:
        raise ValueError("calibration needs relevant and unknown DEV questions")
    measurements = []
    for threshold in sorted(set(positives+negatives+[min(positives+negatives)-1e-6, max(positives+negatives)+1e-6])):
        if not -1 <= threshold <= 1:
            continue
        measurements.append(dict(threshold=threshold,
            false_rejection_rate=sum(s<threshold for s in positives)/len(positives),
            unknown_return_rate=sum(s>=threshold for s in negatives)/len(negatives)))
    candidates = [r for r in measurements if r["false_rejection_rate"] <= max_false_rejection]
    best = min(candidates, key=lambda r:(r["unknown_return_rate"],r["false_rejection_rate"],r["threshold"])) if candidates else None
    # No reduction of unknown returns means no reason to enable a gate.
    return dict(recommended_threshold=best["threshold"] if best and best["unknown_return_rate"] < 1 else None,
        selected=best, measurements=measurements, positive_questions=len(positives), unknown_questions=len(negatives),
        limitations="Calibrates question-level max cosine only; does not prove privacy, refusal or full-hop retention. Freeze before holdout.")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dev", required=True)
    parser.add_argument("--vector-report", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    stored = json.loads(Path(args.vector_report).read_text(encoding="utf-8"))
    mode = stored.get("config",{}).get("MEMORY_RETRIEVAL_MODE")
    report = calibrate(load_cases([args.dev]), {r["case_id"]:r for r in stored["cases"]}, mode)
    report.update(dataset_sha256=hashlib.sha256(Path(args.dev).read_bytes()).hexdigest(),
                  vector_report_sha256=hashlib.sha256(Path(args.vector_report).read_bytes()).hexdigest())
    target = Path(args.output)
    target.parent.mkdir(parents=True,exist_ok=True)
    target.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps({"recommended_threshold":report["recommended_threshold"]}))


if __name__ == "__main__":
    main()
