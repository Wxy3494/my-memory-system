import json
from pathlib import Path
import tempfile
import unittest

from evals.build_memory_stress import build
from evals.memory_eval import load_cases


class StressData(unittest.TestCase):
    def test_independent_balanced_valid_cases_and_immutable_output(self):
        with tempfile.TemporaryDirectory() as directory:
            report = build(directory, 4, 5)
            cases = load_cases([Path(directory)/f"memory_stress_v3_{s}.jsonl" for s in ("dev", "holdout")])
            self.assertEqual(len(cases), 42)
            self.assertEqual(len({c["scenario_id"] for c in cases}), 42)
            for row in report["datasets"].values():
                self.assertEqual(row["capabilities"], {k:3 for k in "ABCDEGH"})
            with self.assertRaises(ValueError):
                build(directory, 4, 5)


if __name__ == "__main__":
    unittest.main()
