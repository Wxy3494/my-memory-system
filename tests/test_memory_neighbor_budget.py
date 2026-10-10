"""Regression of the independent review's long-message starvation counterexample."""
from dataclasses import replace
import unittest
from unittest.mock import Mock

from app.memory.retrieval import evidence, expand_neighbors
from app.memory.schemas import AddRequest, SearchRequest
from app.memory.service import MemoryService
from tests.test_memory_contract import CONFIG, FakeEmbeddings
from tests.test_memory_improvements import OrderedFakeStore


class NeighborBudget(unittest.TestCase):
    def setUp(self):
        self.store = OrderedFakeStore()
        self.service = MemoryService(CONFIG, self.store, FakeEmbeddings())
        for request, session, text in (
            ("long", "first", "ALPHA-ONE ALPHA-TWO 主项目第一证据。" + "常规段落abcd。" * 4000),
            ("support", "second", "BETA-ONE 主项目第二证据，审批人在杭州。"),
            ("third", "third", "GAMMA-ONE 第三证据，杭州办公室在西楼。"),
        ):
            self.service.add(AddRequest(request_id=request, user_id="u", session_id=session,
                                        messages=[dict(role="user", content=text)]))
        self.seeds = [next(row for row in self.store.rows if row["sources"][0]["request_id"] == key)
                      for key in ("long", "support", "third")]

    def test_long_message_cannot_starve_multisession_three_hop_seeds(self):
        self.assertGreater(len(self.store.rows), 200)
        for limit in (3, 5, 100):
            result = expand_neighbors(self.seeds, self.store.rows, 1, limit)
            self.assertTrue({r["chunk_id"] for r in self.seeds} <= {r["chunk_id"] for r in result})
            self.assertLessEqual(len(result), limit)
            self.assertEqual(len(result), len({r["chunk_id"] for r in result}))
            self.assertEqual([r["score"] for r in result], sorted([r["score"] for r in result], reverse=True))

    def test_exact_seed_byte_budget_protects_all_seeds(self):
        budget = sum(len(evidence(row).content.encode()) for row in self.seeds)
        result = expand_neighbors(self.seeds, self.store.rows, 1, 100, budget)
        self.assertEqual({r["chunk_id"] for r in result}, {r["chunk_id"] for r in self.seeds})
        self.assertEqual(sum(len(evidence(r).content.encode()) for r in result), budget)

    def test_insufficient_budget_and_duplicate_seed_are_explicitly_bounded(self):
        result = expand_neighbors(self.seeds * 2, self.store.rows, 1, 2)
        self.assertEqual([r["chunk_id"] for r in result], [r["chunk_id"] for r in self.seeds[:2]])
        self.assertEqual(expand_neighbors(self.seeds, self.store.rows, 1, 100, 1), [])

    def test_pure_bm25_does_not_call_query_model_but_cosine_gate_does(self):
        store, model = Mock(), Mock()
        store.candidates.return_value = ([], [])
        service = MemoryService(replace(CONFIG, retrieval="bm25"), store, model)
        service.search(SearchRequest(user_id="u", query="目标", top_k=5))
        model.query.assert_not_called()
        self.assertIsNone(store.candidates.call_args.args[1])
        model.query.return_value = [1.] + [0.] * 1023
        service = MemoryService(replace(CONFIG, retrieval="bm25", min_similarity=.5), store, model)
        service.search(SearchRequest(user_id="u", query="目标", top_k=5))
        model.query.assert_called_once()


if __name__ == "__main__":
    unittest.main()
