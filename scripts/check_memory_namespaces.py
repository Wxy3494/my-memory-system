"""Five actual DB runs of the reviewed conflict plus implicit positional cases."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--output-dir",required=True)
    args=parser.parse_args()
    target=Path(args.output_dir)
    target.mkdir()
    ids=["v3-dev-conflict_no_order", *[f"v4-dev-{p}" for p in ("head","middle","tail","quarter","three_quarters","english_tail")]]
    reports=[]
    for i,prefix in enumerate(("round3-stability:a:","round3-stability:z:","round3-stability:seed23:",
                               "round3-stability:中文:","round3-stability:long-name-1234567890:")):
        path=target/f"namespace-{i}.json"
        result=subprocess.run([sys.executable,"evals/memory_db_benchmark.py","--namespace",prefix,
            "--case-ids",*ids,"--output",str(path)],cwd=ROOT,env=os.environ,capture_output=True,timeout=90)
        (target/f"namespace-{i}-console.txt").write_bytes(result.stdout+result.stderr)
        if result.returncode:
            raise RuntimeError("namespace_run_failed")
        reports.append(json.loads(path.read_text(encoding="utf-8")))
    signatures=[{c["case_id"]:[r["content"].partition("\n")[2] for r in c["evidence"][:20]] for c in r["cases"]} for r in reports]
    equal=all(s==signatures[0] for s in signatures)
    complete=all(r["summary"]["complete@5"]==1 and not r["summary"]["audit_errors@100"]
                 and not r["summary"]["leaks@100"] for r in reports)
    summary=dict(runs=5,cases_per_run=len(ids),raw_top20_order_identical=equal,
                 complete_at5_all_runs=complete,paid_model_calls=0,
                 scope="Same frozen gold/config; original conflict and six implicit positional cases, not universal stability proof")
    (target/"summary.json").write_text(json.dumps(summary,indent=2),encoding="utf-8")
    print(json.dumps(summary))
    return 0 if equal and complete else 1


if __name__=="__main__":
    raise SystemExit(main())
