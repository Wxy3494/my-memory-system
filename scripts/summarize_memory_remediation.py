"""Synthetic retrieval attribution only, never infer private model failure causes."""
import argparse
from collections import Counter
import json
from pathlib import Path


def main():
    p=argparse.ArgumentParser();p.add_argument("--report",required=True);p.add_argument("--output",required=True)
    args=p.parse_args();data=json.loads(Path(args.report).read_text(encoding="utf-8"))
    base={r["case_id"]:r for r in data["baseline_context_off"]["cases"]}
    rows=[]
    for r in data["cases"]:
        old=base.get(r["case_id"],{}); m=r.get("metrics",{}).get("100"); b=old.get("metrics",{}).get("100")
        layer=("retrieval_execution_failure" if m is None else "source_integrity_or_isolation" if m["audit_errors"] or m["leakage_count"]
               else "evidence_complete_answer_not_run" if m["complete"] is True else "no_fact_gold_support_separate" if m["complete"] is None else "coverage_missing")
        gain=b is not None and b["complete"] is False and m is not None and m["complete"] is True
        rows.append(dict(case_id=r["case_id"],capability=r["capability"],layer=layer,
            supplementation_closed_local_gap=gain,top5_complete=r.get("metrics",{}).get("5",{}).get("complete"),
            top100_complete=m["complete"] if m else None,answer_run=False))
    report=dict(provenance="synthetic_only",total=len(rows),layers=dict(Counter(r["layer"] for r in rows)),
        local_closed_gaps=[r["case_id"] for r in rows if r["supplementation_closed_local_gap"]],
        official_smoke_causal_attribution="pending_private_trace_and_version_mapping",cases=rows)
    Path(args.output).write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps({k:v for k,v in report.items() if k!="cases"},ensure_ascii=False))


if __name__=="__main__":
    main()
