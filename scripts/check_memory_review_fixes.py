"""Reproduce only public synthetic v5 review counterexamples; never call a model."""
import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from app.memory.signals import VERSION, extract, history_periods, plan, state_hints
from scripts.memory_private_paths import require_private_git_clear


def record(mid,text):
    return dict(message_id=mid,session_id=mid,request_id=mid,ordinal=0,role="user",timestamp=None,
        stored_at="2026-10-08T01:00:00+00:00",features=extract(text))


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--output",required=True)
    args=parser.parse_args()
    target=(ROOT/args.output).resolve()
    if not target.is_relative_to(ROOT) or target.exists():
        parser.error("use a NEW report path inside project")
    scenarios=[
        ("original_review_counterexample","2026年1月星河采用甲方案。另有2028年12月旅行预约。","2026年10月星河采用乙方案。","星河",True),
        ("comma_and_different_entities","2026年1月远桥项目采用青案，另有2029年12月旅行预约。","2026年10月远桥项目采用白案。","远桥项目",True),
        ("two_fact_keys_one_seed","2026年1月远桥采用青案。2029年12月银湾采用白案。","2026年10月远桥采用白案。","远桥",True),
        ("ambiguous_one_clause","2026年1月远桥采用青案并预约2029年12月旅行。","2026年10月远桥采用白案。","远桥",False),
        ("date_in_different_clause","远桥采用青案。2029年12月旅行预约。","2026年10月远桥采用白案。","远桥",False),
        ("future_plan","2029年12月远桥计划采用青案。","2026年10月远桥采用白案。","远桥",False)]
    cases=[]
    for name,old,new,subject,dated in scenarios:
        records=[record("old",old),record("new",new)]
        ids,trace=plan(records,subject+"目前采用什么方案？",[dict(sources=[dict(message_id="old")])],2)
        hint=next(h for h in state_hints(records) if h["subject"]==subject)
        known=[c["message_id"] for c in hint["candidates"] if c["effective"] is not None]
        assert known==["new"] and ids==["new","old"],name
        if not dated:
            assert records[0]["features"]["facts"][0]["time_binding"]["sort"] is None or name=="future_plan",name
        cases.append(dict(case=name,synthetic=True,messages=[old,new],state_hints=hint,
                          selected_parents=ids,trace=trace,passed=True))
    text="2026年1月远桥采用青案。"+"例行项目记录。"*1600+"2026年10月远桥采用白案。"
    long=record("long",text)
    hint=state_hints([long])[0]
    assert hint["candidates"][0]["value"]=="白案" and hint["candidates"][0]["effective"]==20261000
    cases.append(dict(case="repeated_long_history_preserves_tail_fact",synthetic=True,
        message_sha256=long["features"]["source_sha256"],message_characters=len(text),state_hints=hint,
        indexed_events=len(long["features"]["events"]),indexed_facts=len(long["features"]["facts"]),passed=True))
    report=dict(executed_at=datetime.now(timezone(timedelta(hours=8))).isoformat(),timezone="Asia/Shanghai",
        parser_version=VERSION,cases=cases,private_git=require_private_git_clear(ROOT),paid_model_calls=0,
        source_hashes={name:hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in
            ("app/memory/signals.py","scripts/memory_private_paths.py",".gitignore","scripts/check_memory_review_fixes.py")},
        limitations="Synthetic hint/order/period and Git metadata checks only. No real Answer/Judge or official loss attribution.")
    target.parent.mkdir(parents=True,exist_ok=True)
    target.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps(dict(passed=len(cases),private_git_passed=True,report=str(target)),ensure_ascii=False))


if __name__=="__main__":
    main()
