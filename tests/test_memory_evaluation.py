import json
from pathlib import Path
import tempfile
import unittest

from evals.memory_eval import load_cases, score_case
from app.memory.chunking import stable_id
from app.memory.retrieval import evidence


class EvidenceScoring(unittest.TestCase):
    def setUp(self):
        self.case = dict(case_id="a", writes=[dict(user_id="u", request_id="r", session_id="s",
            messages=[dict(role="user", content="前文。最后编号XYZ。")])], search=dict(user_id="u"),
            acceptable_evidence_groups=[[dict(request_id="r", ordinal=0, quote="XYZ")]])

    def data(self, user="u", start=3, end=11):
        text = self.case["writes"][0]["messages"][0]["content"]
        source = dict(message_id=stable_id("message", user, "r", 0), session_id="s", request_id="r",
                      ordinal=0, role="user", timestamp=None, start_offset=start, end_offset=end)
        return [evidence(dict(chunk_id="chunk", content=text[start:end], score=1, sources=[source])).model_dump()]

    def test_correct_message_but_wrong_chunk_does_not_count(self):
        result = score_case(self.case, self.data(start=0, end=3), "", 5)
        self.assertEqual(result["recall"], 0)
        result = score_case(self.case, self.data(), "", 5)
        self.assertEqual(result["recall"], 1)

    def test_leakage_and_fabricated_text_are_counted(self):
        self.assertEqual(score_case(self.case, self.data(user="other"), "", 5)["leakage_count"], 1)
        data = self.data()
        data[0]["content"] = "[source]\nInvented XYZ answer"
        result = score_case(self.case, data, "", 5)
        self.assertEqual(result["audit_errors"], 1)
        self.assertEqual(result["recall"], 0)

    def test_empty_gold_has_no_fake_perfect_recall(self):
        self.case["acceptable_evidence_groups"] = []
        result = score_case(self.case, self.data(), "", 100)
        self.assertIsNone(result["recall"])
        self.assertIsNone(result["unrelated_count"])
        self.assertEqual(result["fact_absent_return_count"], 1)
        self.assertEqual(result["unjudged_return_count"], 1)

    def test_fabricated_header_is_rejected(self):
        data = self.data()
        data[0]["content"] = "SYNTHETIC_OTHER_USER_SECRET_OR_FABRICATED_TEXT\n" + data[0]["content"].split("\n", 1)[1]
        result = score_case(self.case, data, "", 5)
        self.assertEqual(result["audit_errors"], 1)
        self.assertEqual(result["recall"], 0)

    def test_metadata_and_missing_sources_are_rejected(self):
        for field, value in (("role", "assistant"), ("timestamp", 123), ("session_id", "other"),
                             ("request_id", "other"), ("ordinal", 1), ("start_offset", True)):
            with self.subTest(field=field):
                data = self.data()
                data[0]["sources"][0][field] = value
                result = score_case(self.case, data, "", 5)
                self.assertEqual(result["audit_errors"], 1)
                self.assertEqual(result["recall"], 0)
        data = self.data()
        data[0]["sources"] = []
        self.assertEqual(score_case(self.case, data, "", 5)["audit_errors"], 1)

    def test_header_must_match_sources(self):
        data = self.data()
        header, raw = data[0]["content"].split("\n", 1)
        labels = json.loads(header[8:-1])
        labels[0]["role"] = "assistant"
        data[0]["content"] = "[source " + json.dumps(labels, ensure_ascii=False, separators=(",", ":")) + "]\n" + raw
        self.assertEqual(score_case(self.case, data, "", 5)["audit_errors"], 1)

    def test_dataset_100_and_no_shared_users(self):
        root = Path(__file__).resolve().parents[1] / "evals"
        cases = load_cases([root / "memory_cases_dev.jsonl", root / "memory_cases_holdout.jsonl"])
        self.assertEqual(len(cases), 100)
        self.assertEqual(sum(c["split"] == "dev" for c in cases), 60)


if __name__ == "__main__":
    unittest.main()
