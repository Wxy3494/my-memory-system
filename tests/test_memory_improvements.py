from dataclasses import replace
from datetime import datetime, timezone
import json
import random
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import os
import sys
import io
from contextlib import redirect_stdout
from evals.memory_load import main as load_main

from app.memory.config import MemoryConfig
from app.memory.retrieval import bm25_rank, evidence, expand_neighbors, select_evidence
from app.memory.schemas import AddRequest, SearchRequest
from app.memory.service import MemoryService
from evals.build_memory_challenge import build
from evals.build_memory_cases import build as build_regression
from evals.memory_answer_eval import evaluate, parse_answer, score_answer, validate_contract
from evals.memory_eval import load_cases, score_case
from evals.calibrate_memory_gate import calibrate
from tests.test_memory_contract import CONFIG, FakeEmbeddings, FakeStore


class OrderedFakeStore(FakeStore):
    """Contract fixture only. Real transaction/order correctness uses PostgreSQL tests."""
    def commit(self, request, digest, chunks, vectors):
        committed = super().commit(request,digest,chunks,vectors)
        if committed:
            session_rows = [r for r in self.rows if r["user_id"] == request.user_id
                            and r["sources"][0]["session_id"] == request.session_id]
            known = {r["message_id"]:r["sources"][0]["received_ordinal"] for r in session_rows
                     if r["sources"][0].get("received_ordinal") is not None}
            position = max(known.values(),default=-1)+1
            for row in session_rows:
                if row["message_id"] not in known:
                    known[row["message_id"]] = position
                    position += 1
                row["sources"][0].update(received_ordinal=known[row["message_id"]],
                    stored_at="2026-10-07T01:00:00+00:00",order_basis="received")
        return committed

    def neighbors(self,user_id,seeds,window,terms=()):
        return [r for r in self.rows if r["user_id"] == user_id]


class RetrievalImprovements(unittest.TestCase):
    def setUp(self):
        self.store = OrderedFakeStore()
        self.service = MemoryService(CONFIG,self.store,FakeEmbeddings())

    def add(self, request_id, content, user="u", timestamp=None):
        self.service.add(AddRequest(request_id=request_id,user_id=user,session_id="s",
                                   messages=[dict(role="user",content=content,timestamp=timestamp)]))

    def test_no_timestamp_cross_add_order_survives_shuffled_rank(self):
        self.add("r1","我现在住广州。")
        self.add("r2","我现在住杭州。")
        self.add("r2","我现在住杭州。")
        rows = [evidence(r).model_dump() for r in self.store.rows]
        random.Random(8).shuffle(rows)
        ordered = sorted(rows,key=lambda r:r["sources"][0]["received_ordinal"])
        self.assertEqual([r["sources"][0]["received_ordinal"] for r in ordered],[0,1])
        self.assertIn("广州",ordered[0]["content"])
        self.assertIn("杭州",ordered[1]["content"])
        self.assertIn('"order_basis":"received"',ordered[1]["content"])
        self.assertIn('"timestamp_ms":null',ordered[1]["content"])

    def test_time_is_not_replaced_by_receive_order(self):
        self.add("latest","较晚源消息",timestamp=2000)
        self.add("early","乱序导入较早源消息",timestamp=1000)
        self.assertEqual(self.store.rows[1]["sources"][0]["timestamp"],1000)
        self.assertEqual(self.store.rows[1]["sources"][0]["received_ordinal"],1)

    def test_extended_sources_are_audited(self):
        self.add("r1","编号ABCDE。")
        case=dict(writes=[dict(user_id="u",request_id="r1",session_id="s",
                              messages=[dict(role="user",content="编号ABCDE。")])],
                  search=dict(user_id="u"),acceptable_evidence_groups=[[dict(request_id="r1",ordinal=0,quote="ABCDE")]])
        data=[evidence(self.store.rows[0]).model_dump()]
        self.assertEqual(score_case(case,data,"",5)["recall"],1)
        data[0]["sources"][0]["received_ordinal"]=10
        self.assertEqual(score_case(case,data,"",5)["audit_errors"],1)

    def test_bm25_rare_exact_identifiers_beats_generic_term_hits(self):
        rows=[dict(chunk_id="a",content="会议会议会议会议会议 TRACE-100"),
              dict(chunk_id="b",content="会议 TRACE-101"),
              *[dict(chunk_id=f"c{i}",content="会议其他编号") for i in range(20)]]
        result=bm25_rank(rows,["会议","trace-101"],5)
        self.assertEqual(result[0]["chunk_id"],"b")
        self.assertEqual(bm25_rank(rows,["absent"],5),[])

    def test_neighbors_do_not_cross_user_or_session(self):
        self.add("a","问题—规则")
        self.add("b","例外—修改")
        self.add("other","PRIVATE_OTHER",user="other")
        seed=self.store.rows[0]
        result=expand_neighbors([seed],self.store.rows,1)
        self.assertEqual(len(result),2)
        bad=dict(self.store.rows[1],chunk_id="wrong-session",
                 sources=[dict(self.store.rows[1]["sources"][0],session_id="s2")])
        self.assertEqual(len(expand_neighbors([seed],[bad],1)),1)

    def test_budget_preserves_raw_slices_and_top_k(self):
        self.add("a","A"*30)
        self.add("b","B"*30)
        rows=self.store.rows
        size=len(evidence(rows[0]).content.encode())
        chosen=select_evidence(rows,100,size)
        self.assertEqual(len(chosen),1)
        self.assertTrue(chosen[0].content.endswith("A"*30))
        self.assertEqual(select_evidence(rows,5,1),[])
        self.assertEqual(len(select_evidence(rows,1)),1)

    def test_gate_uses_cosine_before_rrf_and_keeps_low_similarity_hops(self):
        self.add("a","目标")
        self.add("b","关联")
        self.store.rows[0]["score"]=.8
        self.store.rows[1]["score"]=.1
        service=MemoryService(replace(CONFIG,retrieval="hybrid",min_similarity=.5),self.store,FakeEmbeddings())
        self.assertEqual(len(service.search(SearchRequest(user_id="u",query="目标",top_k=5)).data),2)
        self.store.rows[0]["score"]=.4
        self.assertEqual(service.search(SearchRequest(user_id="u",query="未知",top_k=5)).data,[])


class AnswerContracts(unittest.TestCase):
    def case(self,kind,expected,status="answer",**kwargs):
        return dict(search=dict(query="合成测试问题",options=None),
                    answer_contract=dict(version="local-answer-v2",type=kind,expected=expected,status=status,**kwargs))

    def answer(self,value,status="answer"):
        return dict(status=status,answer=value,citations=["e"] if status=="answer" else [])

    def test_multiselect_complete_set_no_partial_credit_or_duplicates(self):
        case=self.case("multiple_choice",["A","C"])
        for answer,score in ((["C","A"],1),(["A"],0),(["A","B","C"],0),(["A","C","C"],0)):
            self.assertEqual(score_answer(case,self.answer(answer))["score"],score)

    def test_sequence_and_json_types_are_strict(self):
        case=self.case("ordered",["登记","复核","归档"])
        self.assertEqual(score_answer(case,self.answer(["登记","归档"]))["score"],0)
        self.assertEqual(score_answer(case,self.answer(["复核","登记","归档"]))["score"],0)
        self.assertEqual(score_answer(self.case("exact_json",1),self.answer(True))["score"],0)

    def test_rubric_requires_every_condition_and_boolean_judgment(self):
        case=self.case("rubric",None,rubric=[dict(id="x",requirement="中文"),dict(id="y",requirement="一句")])
        judgment=dict(criteria=[dict(id="x",satisfied=True,reason="满足"),dict(id="y",satisfied=False,reason="不满足")])
        self.assertEqual(score_answer(case,self.answer("你好。"),judgment)["score"],0)
        judgment["criteria"][1]["satisfied"]="true"
        with self.assertRaises(ValueError):
            score_answer(case,self.answer("你好。"),judgment)

    def test_wrong_refusal_and_irrelevant_sensitive_disclosure(self):
        self.assertEqual(score_answer(self.case("exact_json","周五"),self.answer(None,"unknown"))["score"],0)
        case=self.case("exact_json",None,"restricted",forbidden_disclosures=["SECRET"])
        self.assertEqual(score_answer(case,self.answer("SECRET"))["score"],0)
        self.assertEqual(score_answer(case,self.answer(None,"restricted"))["score"],1)

    def test_parser_rejects_fabricated_citations_and_extra_fields(self):
        with self.assertRaises(ValueError):
            parse_answer(self.answer("答"),{"other"})
        with self.assertRaises(ValueError):
            parse_answer(dict(self.answer("答"),extra="text"),{"e"})
        with self.assertRaises(ValueError):
            parse_answer(dict(status="unknown",answer="猜测",citations=[]),set())

    def test_failures_wrong_answers_and_normal_empty_are_separate(self):
        cases=[dict(self.case("exact_json","yes"),case_id="a"),dict(self.case("exact_json",None,"unknown"),case_id="b"),
               dict(self.case("exact_json","yes"),case_id="c")]
        retrieval={"a":dict(evidence=[dict(id="e",content="原文")]),"b":dict(evidence=[])}
        replay={"a":dict(answer=self.answer("no")),"b":dict(answer=self.answer(None,"unknown"))}
        report=evaluate(cases,retrieval,replay)
        self.assertEqual(report["summary"]["outcomes"],{"wrong":1,"correct":1,"retrieval_failed":1})
        self.assertEqual(report["summary"]["score_on_all_cases"],1/3)

    def test_gold_never_enters_answer_prompt(self):
        case=dict(self.case("exact_json","GOLD_ONLY"),case_id="a",search=dict(query="题目",options=None))
        observed=[]
        def call(stage,prompt,payload):
            observed.append(payload)
            return json.dumps(self.answer("yes")),{}
        evaluate([case],{"a":dict(evidence=[dict(id="e",content="原文")])},call=call)
        self.assertNotIn("GOLD_ONLY",json.dumps(observed))


class DatasetAndCalibration(unittest.TestCase):
    def test_byte_budget_names_and_legacy_signature_are_compatible(self):
        env=dict(DATABASE_URL="postgresql://unused/test",MEMORY_API_KEY="test",MEMORY_EMBEDDING_API_KEY="test",
                 MEMORY_EMBEDDING_BASE_URL="https://provider.invalid/v1",MEMORY_CHUNK_TARGET_TOKENS="400",
                 MEMORY_CHUNK_OVERLAP_TOKENS="60")
        with patch.dict(os.environ,env,clear=True):
            old=MemoryConfig.from_env()
        with patch.dict(os.environ,dict(env,MEMORY_CHUNK_TARGET_BYTES="400",MEMORY_CHUNK_OVERLAP_BYTES="60"),clear=True):
            current=MemoryConfig.from_env()
        self.assertEqual(old.signature,current.signature)
        with patch.dict(os.environ,dict(env,MEMORY_CHUNK_TARGET_BYTES="800"),clear=True):
            self.assertEqual(MemoryConfig.from_env().target,800)

    def test_new_suites_have_valid_gold_and_no_future_in_streaming_nodes(self):
        with tempfile.TemporaryDirectory() as tmp:
            build(tmp,200,200)
            build_regression(tmp)
            cases=load_cases([Path(tmp)/f"memory_challenge_v2_{s}.jsonl" for s in ("dev","holdout")])
            self.assertEqual({c["capability"] for c in cases},set("ABCDEGH"))
            self.assertEqual(len(cases),32)
            for case in cases:
                validate_contract(case)
                if "node" in case:
                    self.assertEqual(sum(w["user_id"]==case["search"]["user_id"] for w in case["writes"]),case["node"]+2)
            old=load_cases([Path(tmp)/f"memory_cases_v2_{s}.jsonl" for s in ("dev","holdout")])
            self.assertEqual(len(old),100)

    def test_calibration_cannot_tune_holdout_or_rrf(self):
        cases=[dict(case_id="p",split="dev",acceptable_evidence_groups=[[{}]]),
               dict(case_id="n",split="dev",acceptable_evidence_groups=[])]
        outputs={"p":dict(evidence=[dict(score=.8)]),"n":dict(evidence=[dict(score=.2)])}
        self.assertIsNotNone(calibrate(cases,outputs,"vector")["recommended_threshold"])
        with self.assertRaises(ValueError):
            calibrate(cases,outputs,"hybrid")
        cases[1]["split"]="holdout"
        with self.assertRaises(ValueError):
            calibrate(cases,outputs,"vector")

    def test_overlapping_scores_leave_gate_disabled(self):
        cases=[dict(case_id="p",split="dev",acceptable_evidence_groups=[[{}]]),
               dict(case_id="n",split="dev",acceptable_evidence_groups=[])]
        result=calibrate(cases,{"p":dict(evidence=[dict(score=.2)]),"n":dict(evidence=[dict(score=.8)])},"vector")
        self.assertIsNone(result["recommended_threshold"])


class CapacityWorkload(unittest.TestCase):
    def run_sample(self,foreign=False):
        class Client:
            messages=[]
            def __init__(self,**kwargs):
                pass
            def __enter__(self):
                return self
            def __exit__(self,*args):
                pass
            def post(self,path,json):
                class Response:
                    def raise_for_status(self):
                        pass
                    def json(self):
                        return body
                if path.endswith("/add"):
                    self.messages.extend(json["messages"])
                    body=dict(success=True)
                else:
                    session=json["user_id"].rsplit(":",1)[0]+":s-0"
                    body=dict(data=[dict(id="chunk",sources=[dict(session_id="FOREIGN" if foreign else session)])])
                return Response()
        with tempfile.TemporaryDirectory() as tmp:
            target=Path(tmp)/"load.json"
            args=["memory_load","--messages","3","--batch-size","2","--searches","1",
                  "--message-characters","2000","--output",str(target)]
            with patch.object(sys,"argv",args),patch.dict(os.environ,{"MEMORY_API_KEY":"test-key"}), \
                    patch("evals.memory_load.httpx.Client",Client),redirect_stdout(io.StringIO()):
                code=load_main()
            return code,json.loads(target.read_text(encoding="utf-8")),Client.messages

    def test_long_similar_workload_keeps_identifier_and_expected_size(self):
        code,report,messages=self.run_sample()
        self.assertEqual(code,0)
        self.assertEqual(report["add_batches_completed"],2)
        self.assertTrue(all(len(m["content"])==2000 for m in messages))
        self.assertIn("LOAD-0-2",messages[2]["content"])

    def test_foreign_evidence_is_capacity_failure(self):
        code,report,_=self.run_sample(foreign=True)
        self.assertEqual(code,1)
        self.assertEqual(report["search_completed"],0)
        self.assertEqual(report["errors"],["ValueError"])


if __name__ == "__main__":
    unittest.main()
