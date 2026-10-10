from dataclasses import replace
from datetime import datetime,timezone
import unittest
from unittest.mock import patch
import os
from app.memory.config import MemoryConfig
from app.memory.signals import extract,plan,state_hints,utc_anchor
from app.memory.runtime import runtime_report
from evals.memory_answer_eval import score_answer
from scripts.diagnose_memory_trace import classify
from tests.test_memory_contract import CONFIG


def record(mid,text,role="user",time=None):
    return dict(message_id=mid,session_id=mid,request_id=mid,ordinal=0,role=role,timestamp=time,
        stored_at="2026-10-08T01:00:00+00:00",features=extract(text,role,time))


class SignalsTests(unittest.TestCase):
    def test_time_spans_precision_unknown_anchor_and_assistant_authority(self):
        text="2027年11月课程举行；明天交付；2028年2月30日不合法。"
        f=extract(text,"assistant")
        self.assertEqual(f["authority"],"assistant_statement_not_user_fact")
        for t in f["times"]:
            self.assertEqual(text[t["start"]:t["end"]],t["raw"])
        self.assertEqual([t["precision"] for t in f["times"]],["month","relative"])
        self.assertIsNone(f["times"][1]["anchor_utc"])
        self.assertFalse(f["times"][1]["resolved"])
        self.assertEqual(utc_anchor(0),"1970-01-01T00:00:00+00:00")

    def test_state_hints_use_event_dates_and_preserve_history_and_conflict(self):
        rows=[record("a","2026年4月蒲霜办公室设在宁德。"),record("b","补录旧日志：2026年1月蒲霜办公室设在福州。"),
              record("assistant","2026年8月蒲霜办公室设在外城。","assistant")]
        h=state_hints(rows)
        self.assertEqual(len(h),1)
        self.assertEqual(h[0]["candidates"][0]["message_id"],"a")
        self.assertEqual(set(h[0]["historical_sources"]),{"a","b"})
        rows.append(record("c","2026年4月蒲霜办公室设在泉州。"))
        self.assertEqual(state_hints(rows)[0]["status"],"unresolved_same_time_conflict")

    def test_link_closure_direction_and_denial_stay_raw(self):
        rows=[record("a","蒲霜工程由孟舟执行。"),record("b","孟舟所在部门负责人是黎川。"),
              record("c","黎川的部门在宁德，不在福州。")]
        seeds=[dict(sources=[dict(message_id="a")])]
        ids,trace=plan(rows,"蒲霜工程的执行部门在哪？",seeds,48,2)
        self.assertTrue(set("abc")<=set(ids))
        self.assertLessEqual(len(trace["link_rounds"]),2)
        self.assertTrue(rows[2]["features"]["terms"])

    def test_runtime_report_has_source_identity_without_credentials(self):
        report=runtime_report(replace(CONFIG,contextual=True))
        self.assertEqual(report["required_schema_version"],3)
        self.assertNotIn(CONFIG.api_key,str(report))
        self.assertNotIn(CONFIG.embedding_key,str(report))
        self.assertIn("app/memory/signals.py",report["source_sha256"])

    def test_partial_and_all_rubric_contracts_are_distinct(self):
        c=dict(answer_contract=dict(type="rubric",status="answer",aggregation="partial_mean",rubric=[dict(id="a"),dict(id="b")]))
        a=dict(status="answer",answer="测试答案")
        j=dict(criteria=[dict(id="a",score=1,reason="满足"),dict(id="b",score=.5,reason="部分满足")])
        self.assertEqual(score_answer(c,a,j)["score"],.75)
        j["criteria"][1]["score"]=True
        with self.assertRaises(ValueError):
            score_answer(c,a,j)

    def test_trace_diagnosis_does_not_invent_unknown_production_contract(self):
        self.assertEqual(classify(dict(failure_stage="parse"))["layer"],"format_or_parser_failure")
        self.assertEqual(classify(dict(answer="wrong"))["layer"],"unmapped_private_contract")


if __name__=="__main__":
    unittest.main()
