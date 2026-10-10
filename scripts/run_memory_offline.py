"""One-command OFFLINE remediation checks. No environment file, network, DB or paid call."""
import argparse
from datetime import datetime, timedelta, timezone
import json
import logging
import os
from pathlib import Path
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--output-dir")
    args=parser.parse_args()
    now=datetime.now(timezone(timedelta(hours=8)))
    output=(ROOT/(args.output_dir or f"docs/evidence/{now:%Y%m%d-%H%M%S}-offline")).resolve()
    if not output.is_relative_to(ROOT) or output.exists():
        parser.error("use a NEW evidence directory inside project; historical outputs are never overwritten")
    output.mkdir(parents=True)
    data=[ROOT/"evals"/f"{suite}_{split}.jsonl" for suite in ("memory_context_v4","memory_governance_v5") for split in ("dev","holdout")]
    annotated=[ROOT/"evals"/f"memory_cases_v2_{split}.jsonl" for split in ("dev","holdout")]
    from evals.memory_eval import load_cases
    from evals.memory_answer_eval import validate_contract
    all_cases=load_cases(annotated+data)
    for case in all_cases:
        validate_contract(case)
    # Disable every opt-in live test even if an unrelated terminal configured it.
    env=dict(os.environ)
    for name in ("MEMORY_TEST_DATABASE_URL","MEMORY_RUN_LIVE_EMBEDDING"):
        env.pop(name,None)
    test_command=[sys.executable,"-c",
        "import sys; "
        "from scripts.verify_memory import main; sys.exit(main())",
        "--output",str(output/"verification.json")]
    tests=subprocess.run(test_command,cwd=ROOT,env=env,capture_output=True,text=True,encoding="utf-8")
    (output/"verification-console.txt").write_text(tests.stdout+tests.stderr,encoding="utf-8")
    if tests.returncode:
        print(json.dumps({"status":"failed","stage":"offline_regression","evidence":str(output)}))
        return 1
    from evals.memory_lexical_benchmark import main as lexical_main
    previous=sys.argv
    try:
        sys.argv=["memory_lexical_benchmark","--data",*(str(p) for p in data),"--output-dir",str(output/"lexical")]
        lexical_main()
    finally:
        sys.argv=previous
    report=dict(status="offline_checks_completed",executed_at=now.isoformat(),timezone="Asia/Shanghai",
        valid_annotated_questions=len(all_cases),paid_model_calls=0,external_database_calls=0,
        scope="Contract/native-grader regression, SQL syntax, data validation and real lexical algorithm ablation",
        database_scope="This CPU-only command does not execute PostgreSQL; separate isolated DB reports exist",
        pending=["real vector comparison","generated Answer/Judge scores",
                 "semantic governance/privacy acceptance","cloud authenticated roundtrip","credential rotation",
                 "HTTPS","cloud capacity","official Smoke/Full"])
    (output/"offline-summary.json").write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps(report,ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
