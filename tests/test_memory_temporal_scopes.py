"""Synthetic counterexamples for source-scoped temporal hints; no model answers."""
import unittest
from app.memory.signals import extract, history_periods, plan, state_hints
from tests.test_memory_signals import record


class TemporalScopeTests(unittest.TestCase):
    def test_review_counterexample_state_order_and_global_periods(self):
        old=record("old","2026年1月星河采用甲方案。另有2028年12月旅行预约。")
        new=record("new","2026年10月星河采用乙方案。")
        hint=state_hints([old,new])[0]
        self.assertEqual([c["message_id"] for c in hint["candidates"]],["new"])
        self.assertEqual(hint["candidates"][0]["effective"],20261000)
        self.assertEqual(old["features"]["facts"][0]["time_binding"]["sort"],20260100)
        ids,trace=plan([old,new],"星河目前采用什么方案？",[dict(sources=[dict(message_id="old")])],2)
        self.assertEqual(ids,["new","old"])
        self.assertEqual(trace["temporal_selection"][1]["scoped_event_time"],20260100)
        periods={(b["topic"],b["period"]) for b in history_periods(old["features"])}
        self.assertIn(("other",202601),periods)
        self.assertIn(("travel",202812),periods)
        self.assertNotIn(("other",202812),periods)

    def test_comma_separated_events_keep_their_own_date(self):
        rows=[record("old","2026年1月远桥项目采用青案，另有2029年12月旅行预约。"),
              record("new","2026年10月远桥项目采用白案。")]
        self.assertEqual(state_hints(rows)[0]["candidates"][0]["message_id"],"new")
        periods={(b["topic"],b["period"]) for b in history_periods(rows[0]["features"])}
        self.assertIn(("work",202601),periods)
        self.assertIn(("travel",202912),periods)
        self.assertNotIn(("work",202912),periods)

    def test_unsplit_multiple_events_dates_or_date_ranges_stay_unknown(self):
        for text in ("2026年1月远桥采用青案并预约2029年12月旅行。",
                     "2026年1月远桥采用青案且另一个部门使用白案。",
                     "从2026年1月到2026年3月远桥采用青案。"):
            with self.subTest(text=text):
                f=extract(text)
                self.assertEqual(f["facts"][0]["time_binding"]["reason"],"ambiguous_multiple_events_or_times")
                self.assertIsNone(state_hints([record("x",text)])[0]["candidates"][0]["effective"])
                self.assertTrue(all(b["period"]==0 for b in history_periods(f)))

    def test_date_in_other_clause_does_not_date_undated_fact(self):
        rows=[record("undated","远桥采用青案。2029年12月旅行预约。"),
              record("dated","2026年10月远桥采用白案。")]
        hint=state_hints(rows)[0]
        self.assertEqual(hint["status"],"dated_candidates_with_unresolved_context")
        self.assertEqual({c["message_id"] for c in hint["candidates"]},{"undated","dated"})
        self.assertIsNone(next(c["effective"] for c in hint["candidates"] if c["message_id"]=="undated"))

    def test_future_plan_is_retained_without_becoming_current_fact(self):
        rows=[record("now","2026年10月远桥采用青案。"),
              record("plan","2029年12月远桥计划采用白案。")]
        hint=state_hints(rows)[0]
        self.assertEqual(hint["status"],"dated_candidates_with_unresolved_context")
        candidate=next(c for c in hint["candidates"] if c["message_id"]=="plan")
        self.assertIsNone(candidate["effective"])
        self.assertEqual(candidate["claim_kind"],"prospective")
        ids,_=plan(rows,"远桥当前采用什么方案？",[dict(sources=[dict(message_id="now")])],2)
        self.assertEqual(ids,["now","plan"])

    def test_backfill_message_time_is_only_fallback_and_control_is_unresolved(self):
        rows=[record("old","补录旧日志：2026年1月远桥使用青案。",time=1893456000000),
              record("new","2026年10月远桥使用白案。",time=1),
              record("withdraw","2026年11月远桥不再使用白案。"),
              record("restore","2026年12月恢复允许远桥使用青案。")]
        hint=state_hints(rows)[0]
        self.assertEqual(hint["status"],"dated_candidates_with_unresolved_context")
        self.assertEqual({c["message_id"] for c in hint["candidates"]},{"new","withdraw","restore"})
        self.assertEqual(set(hint["historical_sources"]),{"old","new","withdraw","restore"})
        ids,_=plan(rows,"远桥目前使用什么方案？",[dict(sources=[dict(message_id="old")])],4)
        self.assertEqual(ids[:2],["restore","withdraw"])
        self.assertLess(ids.index("new"),ids.index("old"))

    def test_equal_time_conflict_undated_relative_and_source_spans(self):
        rows=[record("a","2026年10月远桥采用青案。"),record("b","2026年10月远桥采用白案。")]
        self.assertEqual(state_hints(rows)[0]["status"],"unresolved_same_time_conflict")
        for text in ("远桥采用青案。", "明天远桥采用青案。", "远桥采用青案于2029年12月。"):
            f=extract(text)
            fact=f["facts"][0]
            self.assertEqual(text[fact["start"]:fact["end"]],fact["value"])
            self.assertIsNone(fact["time_binding"]["sort"])
            for event in f["events"]:
                for date in event["time_binding"]["expressions"]:
                    self.assertEqual(text[date["start"]:date["end"]],date["raw"])

    def test_multiple_fact_keys_in_seed_use_query_subject_time(self):
        rows=[record("old","2026年1月远桥采用青案。2029年12月银湾采用白案。"),
              record("new","2026年10月远桥采用白案。")]
        ids,trace=plan(rows,"远桥目前采用什么方案？",[dict(sources=[dict(message_id="old")])],2)
        self.assertEqual(ids,["new","old"])
        self.assertEqual(trace["temporal_selection"][1]["scoped_event_time"],20260100)

    def test_repeated_long_history_cannot_use_all_event_slots_before_tail_fact(self):
        text="2026年1月远桥采用青案。"+"例行项目记录。"*1600+"2026年10月远桥采用白案。"
        r=record("long",text)
        hint=state_hints([r])[0]
        self.assertEqual(hint["candidates"][0]["value"],"白案")
        self.assertEqual(hint["candidates"][0]["effective"],20261000)
        self.assertLessEqual(len(r["features"]["events"]),96)
        self.assertLessEqual(len(r["features"]["facts"]),32)
        for fact in r["features"]["facts"]:
            self.assertEqual(text[fact["start"]:fact["end"]],fact["value"])


if __name__=="__main__":
    unittest.main()
