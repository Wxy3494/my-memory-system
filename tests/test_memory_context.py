from dataclasses import replace
import unittest
from app.memory.chunking import stable_id
from app.memory.retrieval import bm25_rank, message_candidates, expand_neighbors, evidence
from app.memory.schemas import AddRequest
from app.memory.service import MemoryService
from tests.test_memory_improvements import OrderedFakeStore
from tests.test_memory_contract import CONFIG, FakeEmbeddings
from evals.memory_eval import score_case


class ContextRegression(unittest.TestCase):
    def test_long_adjacent_head_middle_tail_and_unmatched_interior_fact(self):
        for fraction in (0, .25, .5, .75, 1):
            with self.subTest(fraction=fraction):
                store = OrderedFakeStore()
                service = MemoryService(CONFIG, store, FakeEmbeddings())
                filler = "例行无关记录abcdefgh。" * 4000
                point = int(len(filler)*fraction)
                fact = "最终负责人为陶宁，工作地为厦门。"
                service.add(AddRequest(user_id="u",request_id="anchor",session_id="s",
                    messages=[dict(role="user",content="ULTRA-KEY 结论见下一条说明。")]))
                service.add(AddRequest(user_id="u",request_id="long",session_id="s",
                    messages=[dict(role="user",content=filler[:point]+fact+filler[point:])]))
                seed = store.rows[0]
                selected = message_candidates(store.rows[1:], ["ultra-key"])
                result = expand_neighbors([seed], [dict(r,sources=r["sources"]) for r in selected], 2,100,32768)
                self.assertTrue(any("陶宁" in r["content"] for r in result))
                self.assertTrue(any("厦门" in r["content"] for r in result))
                self.assertLessEqual(len(selected),8)
                self.assertLessEqual(len(result),9)

    def test_tied_bm25_ranking_independent_of_namespace_hashes(self):
        signatures=[]
        for namespace in ("zero:","namespace-A:","namespace-999:","汉字:","z:"*20):
            rows = [dict(user_id=namespace+"u",request_id=namespace+r,session_id=namespace+"s",
                chunk_id=stable_id(namespace,r),content="共同词项",ordinal=0,start_offset=0) for r in ("r3","r1","r2")]
            result=bm25_rank(rows,["共同"],3)
            signatures.append([r["request_id"][len(namespace):] for r in result])
        self.assertEqual(signatures,[['r1','r2','r3']]*5)

    def test_unknown_support_irrelevance_sensitive_and_source_audit_are_distinct(self):
        store=OrderedFakeStore()
        service=MemoryService(CONFIG,store,FakeEmbeddings())
        text="没有记录票号；合成联系标签PRIVATE-TEST。"
        request=dict(user_id="u",request_id="r",session_id="s",messages=[dict(role="user",content=text)])
        service.add(AddRequest(**request))
        data=[evidence(store.rows[0]).model_dump()]
        ref=dict(request_id="r",ordinal=0,quote="没有记录票号")
        case=dict(writes=[request],search=dict(user_id="u"),acceptable_evidence_groups=[],
            evidence_annotations=dict(unknown_support=[ref],irrelevant=[]),
            answer_contract=dict(forbidden_disclosures=["PRIVATE-TEST"]))
        result=score_case(case,data,"",100)
        self.assertEqual(result["unknown_support_count"],1)
        self.assertEqual(result["explicit_irrelevant_count"],0)
        self.assertEqual(result["declared_sensitive_content_count"],1)
        self.assertIsNone(result["recall"])
        data[0]["sources"][0]["request_id"]="invented"
        result=score_case(case,data,"",100)
        self.assertEqual(result["unknown_support_count"],0)
        self.assertEqual(result["audit_errors"],1)
        self.assertEqual(result["declared_sensitive_content_count"],0)


if __name__ == "__main__":
    unittest.main()
