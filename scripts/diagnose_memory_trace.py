"""Private normalized-trace triage. No original question/gold is exported publicly."""
import argparse
from collections import Counter
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from evals.memory_eval import score_case


def classify(item):
    stage=item.get("failure_stage")
    if stage in ("add","search","parse","judge_call"):
        return dict(layer={"add":"write_failure","search":"retrieval_failure","parse":"format_or_parser_failure","judge_call":"judge_execution_failure"}[stage])
    if not all(k in item for k in ("writes","search","acceptable_evidence_groups","evidence")):
        return dict(layer="unmapped_private_contract",reason="normalized source/gold fields unavailable")
    try:
        metrics=score_case(item,item["evidence"],item.get("namespace",""),100)
    except Exception as exc:
        return dict(layer="unmapped_private_contract",error_type=type(exc).__name__)
    if metrics["audit_errors"] or metrics["leakage_count"]:
        return dict(layer="source_integrity_or_isolation",metrics=metrics)
    if metrics["complete"] is False:
        return dict(layer="evidence_missing_or_budget",metrics=metrics)
    if item.get("judge_correct") is False:
        return dict(layer="generation_or_judging_unresolved",metrics=metrics,
            reason="Gold support covered; need private answer/rubric/parser to distinguish reasoning, state/time interpretation and judge")
    return dict(layer="no_confirmed_failure_or_missing_verdict",metrics=metrics)


def main():
    parser=argparse.ArgumentParser(); parser.add_argument("--input",required=True); parser.add_argument("--output-dir",required=True)
    args=parser.parse_args(); target=Path(args.output_dir).resolve()
    if not target.is_relative_to(ROOT/".private-eval") or target.exists():
        parser.error("private results must use a NEW directory inside .private-eval")
    source=Path(args.input).resolve()
    if source.is_relative_to(ROOT) and not source.is_relative_to(ROOT/".private-eval"):
        parser.error("project-local private input must be inside .private-eval")
    data=json.loads(source.read_text(encoding="utf-8"))
    results=[dict(case_id=item.get("case_id"),**classify(item)) for item in data["cases"]]
    target.mkdir(parents=True)
    (target/"diagnosis.json").write_text(json.dumps(dict(_release_visibility="private",cases=results),ensure_ascii=False,indent=2),encoding="utf-8")
    summary=dict(total=len(results),layers=dict(Counter(r["layer"] for r in results)),
                 scope="Normalized private trace diagnosis, not official score reconstruction")
    print(json.dumps(summary,ensure_ascii=False))
    (target/"summary.json").write_text(json.dumps(summary,indent=2),encoding="utf-8")


if __name__=="__main__":
    main()
