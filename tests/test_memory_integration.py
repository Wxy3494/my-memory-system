"""Opt-in PostgreSQL + pgvector tests. Uses an EXPLICIT disposable *_memory_test DB.

Fake embeddings here test persistence, transactions and SQL, not retrieval quality.
"""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import os
import unittest
from urllib.parse import urlparse
import uuid

import psycopg

from app.memory.chunking import make_chunks, payload_hash
from app.memory.config import MemoryConfig
from app.memory.embeddings import Embeddings
from app.memory.errors import MemoryError
from app.memory.schemas import AddRequest, SearchRequest
from app.memory.service import MemoryService
from app.memory.store import PostgresStore
from scripts.memory_admin import migrate


class TestEmbeddings:
    def encode(self, texts):
        return [[1.0] + [0.0] * 1023 for _ in texts]

    def query(self, text):
        return self.encode([text])[0]


@unittest.skipUnless(os.getenv("MEMORY_TEST_DATABASE_URL"), "MEMORY_TEST_DATABASE_URL not configured; real DB unverified")
class PostgresIntegration(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        dsn = os.environ["MEMORY_TEST_DATABASE_URL"]
        if not urlparse(dsn).path.endswith("_memory_test"):
            raise RuntimeError("Use a separate disposable database ending in _memory_test")
        cls.config = MemoryConfig(dsn, "test-key", "unused", "https://test.invalid/v1")
        migrate(cls.config)
        migrate(cls.config)  # non-destructive rerun

    def setUp(self):
        self.user = "local-db:" + uuid.uuid4().hex
        self.other = self.user + ":other"
        self.store = PostgresStore(self.config)
        self.service = MemoryService(self.config, self.store, TestEmbeddings())

    def tearDown(self):
        with self.store.connection() as conn:
            conn.execute("DELETE FROM memory.ingest_requests WHERE user_id=ANY(%s)", ([self.user, self.other],))

    def request(self, **kwargs):
        body = dict(request_id="same-id", user_id=self.user, session_id="s1",
                    messages=[dict(role="user", content="这是完整的原文。😀", timestamp=1704067200000),
                              dict(role="assistant", content="我是助手，不能把建议当用户事实。")])
        body.update(kwargs)
        return AddRequest(**body)

    def counts(self):
        with self.store.connection() as conn:
            return [conn.execute(f"SELECT count(*) AS n FROM memory.{table} WHERE user_id=%s", (self.user,)).fetchone()["n"]
                    for table in ("ingest_requests", "messages", "chunks", "chunk_sources")]

    def test_durable_immediate_search_and_cross_user_isolation(self):
        self.service.add(self.request())
        response = self.service.search(SearchRequest(user_id=self.user, query="完整的原文", top_k=100))
        self.assertEqual(len(response.data), 2)
        other = self.service.search(SearchRequest(user_id=self.other, query="完整的原文", top_k=100))
        self.assertEqual(other.data, [])
        new_service = MemoryService(self.config, PostgresStore(self.config), TestEmbeddings())
        self.assertEqual(new_service.search(SearchRequest(user_id=self.user, query="原文", top_k=100)), response)
        with self.store.connection() as conn:
            rows = conn.execute("SELECT content,role,source_timestamp_ms FROM memory.messages WHERE user_id=%s ORDER BY ordinal", (self.user,)).fetchall()
        self.assertEqual(rows[0]["content"], "这是完整的原文。😀")
        self.assertEqual(rows[0]["source_timestamp_ms"], 1704067200000)

    def test_concurrent_duplicates_conflict_and_retry_after_response_loss(self):
        request = self.request()
        with ThreadPoolExecutor(max_workers=8) as pool:
            responses = list(pool.map(lambda _: self.service.add(request), range(16)))
        self.assertTrue(all(r.success for r in responses))
        self.assertEqual(self.counts(), [1, 2, 2, 2])
        self.service.add(request)  # response loss simulation: retry committed operation
        self.assertEqual(self.counts(), [1, 2, 2, 2])
        with self.assertRaises(MemoryError) as error:
            self.service.add(self.request(session_id="changed"))
        self.assertEqual(error.exception.status, 409)

    def test_rollback_after_receipt_and_message_insert(self):
        request = self.request()
        chunks = make_chunks(request, self.config)
        # Wrong dimensions force the DB to fail AFTER receipt/messages were inserted.
        with self.assertRaises(MemoryError):
            self.store.commit(request, payload_hash(request), chunks, [[1.0]] * len(chunks))
        self.assertEqual(self.counts(), [0, 0, 0, 0])
        self.service.add(request)
        self.assertEqual(self.counts(), [1, 2, 2, 2])

    def test_incremental_cross_session_hybrid_and_cascade_cleanup(self):
        self.service.add(self.request())
        self.service.add(self.request(request_id="second", session_id="s2", messages=[dict(role="user", content="我的追踪编号是TRACE-99。")]))
        config = replace(self.config, retrieval="hybrid")
        service = MemoryService(config, PostgresStore(config), TestEmbeddings())
        response = service.search(SearchRequest(user_id=self.user, query="TRACE-99", top_k=100))
        self.assertEqual(len(response.data), 3)
        self.assertIn("TRACE-99", response.data[0].content)
        with self.store.connection() as conn:
            conn.execute("DELETE FROM memory.ingest_requests WHERE user_id=%s", (self.user,))
        self.assertEqual(self.counts(), [0, 0, 0, 0])

    def test_pipeline_mismatch_refuses_to_mix_embeddings(self):
        store = PostgresStore(replace(self.config, base_url="https://different.invalid/v1"))
        with self.assertRaises(MemoryError):
            store.check()

    def test_top100_isolated_before_ranking_and_shared_request_id(self):
        self.service.add(self.request(messages=[dict(role="user", content=f"user A evidence {i}") for i in range(120)]))
        self.service.add(self.request(user_id=self.other, messages=[dict(role="user", content="OTHER_USER_SECRET")]))
        for k in (1, 5, 100):
            response = self.service.search(SearchRequest(user_id=self.user, query="evidence", top_k=k))
            self.assertEqual(len(response.data), k)
            self.assertFalse(any("OTHER_USER_SECRET" in row.content for row in response.data))
            self.assertEqual(len({row.id for row in response.data}), k)

    def test_foreign_keys_cannot_associate_another_users_sources(self):
        self.service.add(self.request())
        chunk = make_chunks(self.request(), self.config)[0]
        with self.assertRaises(MemoryError):
            with self.store.connection() as conn:
                conn.execute("INSERT INTO memory.chunk_sources(user_id,chunk_id,message_id,start_offset,end_offset) VALUES(%s,%s,%s,0,1)",
                             (self.other, chunk["chunk_id"], chunk["message_id"]))

    def test_concurrent_distinct_adds_preserve_continuous_session_order(self):
        requests = [self.request(request_id=f"ordered-{i}", messages=[dict(role="user",content=f"batch {i}")])
                    for i in range(12)]
        with ThreadPoolExecutor(max_workers=6) as pool:
            list(pool.map(self.service.add,requests))
        self.service.add(requests[0])
        with self.store.connection() as conn:
            rows = conn.execute("""SELECT received_ordinal,order_basis FROM memory.messages
                WHERE user_id=%s ORDER BY received_ordinal""",(self.user,)).fetchall()
        self.assertEqual([r["received_ordinal"] for r in rows],list(range(12)))
        self.assertTrue(all(r["order_basis"]=="received" for r in rows))

    def test_bm25_neighbors_are_isolated_and_source_time_is_preserved(self):
        self.service.add(self.request(messages=[dict(role="user",content="原规则：按RULE-917执行。",timestamp=2000)]))
        self.service.add(self.request(request_id="later",messages=[dict(role="user",content="刚才原规则的例外：加急跳过复核。",timestamp=1000)]))
        self.service.add(self.request(user_id=self.other,messages=[dict(role="user",content="PRIVATE RULE-917")]))
        config=replace(self.config,retrieval="bm25",neighbor_window=1,seed_limit=1)
        service=MemoryService(config,PostgresStore(config),TestEmbeddings())
        response=service.search(SearchRequest(user_id=self.user,query="RULE-917",top_k=100))
        self.assertEqual(len(response.data),2)
        self.assertFalse(any("PRIVATE" in r.content for r in response.data))
        self.assertEqual({r.sources[0].timestamp for r in response.data},{1000,2000})
        self.assertEqual({r.sources[0].received_ordinal for r in response.data},{0,1})

    def test_long_message_preserves_second_seed_and_bounds_database_expansion(self):
        self.service.add(self.request(request_id="long", session_id="first", messages=[dict(role="user",
            content="ALPHA-ONE ALPHA-TWO 主项目第一证据。" + "常规段落abcd。" * 4000)]))
        self.service.add(self.request(request_id="short", session_id="second", messages=[dict(role="user",
            content="BETA-ONE 第二证据，审批人在杭州。")]))
        config = replace(self.config, retrieval="bm25", neighbor_window=1)
        store = PostgresStore(config)
        class NoQuery(TestEmbeddings):
            def query(self, text):
                raise AssertionError("pure BM25 Search must not call a model")
        service = MemoryService(config, store, NoQuery())
        for limit in (2, 5, 100):
            data = service.search(SearchRequest(user_id=self.user,
                query="ALPHA-ONE ALPHA-TWO BETA-ONE", top_k=limit)).data
            self.assertEqual({s.request_id for r in data for s in r.sources}, {"long", "short"})
            self.assertLessEqual(len(data), limit)
        _, seeds = store.candidates(self.user, None, 20, ["alpha-one", "beta-one"])
        self.assertLessEqual(len(store.neighbors(self.user, seeds, 1)), 16)

    def test_long_adjacent_position_and_namespace_stability(self):
        config=replace(self.config,retrieval="bm25",neighbor_window=2,evidence_bytes=32768)
        store=PostgresStore(config)
        class NoQuery(TestEmbeddings):
            def query(self,text):
                raise AssertionError("no query model")
        service=MemoryService(config,store,NoQuery())
        signatures=[]
        for index,namespace in enumerate(("a:","z:","seed-23:","中文:","long-name:"*5)):
            user=self.user+namespace
            filler="例行无关记录abcdefgh。"*4000
            position=int(len(filler)*(0,.25,.5,.75,1)[index])
            fact="最终负责人为陶宁，工作地为厦门。"
            try:
                for name,text in (("anchor","ULTRA-KEY 结论见下一条说明。"),
                    ("detail",filler[:position]+fact+filler[position:])):
                    service.add(AddRequest(user_id=user,request_id=namespace+name,session_id=namespace+"s",
                        messages=[dict(role="user",content=text)]))
                data=service.search(SearchRequest(user_id=user,query="ULTRA-KEY 后续结论？",top_k=100)).data
                self.assertTrue(any("陶宁" in row.content for row in data))
                self.assertTrue(any("厦门" in row.content for row in data))
                self.assertLessEqual(sum(len(row.content.encode()) for row in data),32768)
                for name,text in (("r3","共同词项结论丙"),("r1","共同词项结论甲"),("r2","共同词项结论乙")):
                    service.add(AddRequest(user_id=user,request_id=namespace+name,session_id=namespace+"ties",
                        messages=[dict(role="user",content=text)]))
                _,ranked=store.candidates(user,None,3,["共同"])
                signatures.append([r["request_id"][len(namespace):] for r in ranked])
            finally:
                with store.connection() as conn:
                    conn.execute("DELETE FROM memory.ingest_requests WHERE user_id=%s",(user,))
        self.assertEqual(signatures,[['r1','r2','r3']]*5)

    def test_signal_index_backfill_retry_hash_and_rollback(self):
        import hashlib
        from app.memory.signals import VERSION
        request=self.request(messages=[dict(role="user",content="2026年4月蒲霜办公室设在宁德。")])
        self.service.add(request); self.service.add(request)
        with self.store.connection() as conn:
            before=conn.execute("SELECT message_id,content FROM memory.messages WHERE user_id=%s",(self.user,)).fetchall()
            signals=conn.execute("SELECT features FROM memory.message_signals WHERE user_id=%s",(self.user,)).fetchall()
            self.assertEqual(len(signals),1)
            self.assertEqual(signals[0]["features"]["source_sha256"],hashlib.sha256(before[0]["content"].encode()).hexdigest())
            conn.execute("DELETE FROM memory.message_signals WHERE user_id=%s",(self.user,))
        migrate(self.config)
        with self.store.connection() as conn:
            self.assertEqual(conn.execute("SELECT message_id,content FROM memory.messages WHERE user_id=%s",(self.user,)).fetchall(),before)
            self.assertEqual(conn.execute("SELECT parser_version FROM memory.message_signals WHERE user_id=%s",(self.user,)).fetchone()["parser_version"],VERSION)
            conn.execute("UPDATE memory.message_signals SET features=jsonb_set(features,'{source_sha256}','\"bad\"') WHERE user_id=%s",(self.user,))
        config=replace(self.config,contextual=True,retrieval="bm25")
        rows,trace=PostgresStore(config).contextual_candidates(self.user,"蒲霜办公室现在在哪里？",[])
        self.assertEqual(rows,[])
        self.assertEqual(trace["indexed_records"],0)

    def test_concurrent16_adds_have_matching_source_signals(self):
        requests=[self.request(request_id=f"index-{i}",messages=[dict(role="user",content=f"群组{i}目前采用蓝案。")]) for i in range(16)]
        with ThreadPoolExecutor(max_workers=16) as pool:
            list(pool.map(self.service.add,requests))
        with self.store.connection() as conn:
            row=conn.execute("""SELECT count(*) AS n FROM memory.messages m JOIN memory.message_signals s
                ON s.user_id=m.user_id AND s.message_id=m.message_id WHERE m.user_id=%s
                AND encode(sha256(convert_to(m.content,'UTF8')),'hex')=s.features->>'source_sha256'""",(self.user,)).fetchone()
        self.assertEqual(row["n"],16)

    def test_v1_signal_upgrade_is_idempotent_and_preserves_original_database_rows(self):
        from copy import deepcopy
        from psycopg.types.json import Jsonb
        from app.memory.signals import VERSION
        texts=["2026年1月星河采用甲方案。另有2028年12月旅行预约。","2026年10月星河采用乙方案。"]
        self.service.add(self.request(messages=[dict(role="user",content=t) for t in texts]))
        config=replace(self.config,contextual=True,retrieval="bm25")
        def snapshot():
            with self.store.connection() as conn:
                return {table:conn.execute(f"SELECT to_jsonb(t) AS row FROM memory.{table} t WHERE user_id=%s ORDER BY to_jsonb(t)::text",(self.user,)).fetchall()
                        for table in ("ingest_requests","messages","chunks","chunk_sources")}
        before=snapshot()
        with self.store.connection() as conn:
            signals=conn.execute("SELECT message_id,features FROM memory.message_signals WHERE user_id=%s",(self.user,)).fetchall()
            for row in signals:
                old=deepcopy(row["features"])
                old["version"]="source-lexical-signals-v1"; old.pop("events",None)
                for fact in old["facts"]:
                    for key in ("time_binding","claim_kind","event_span"):
                        fact.pop(key,None)
                conn.execute("UPDATE memory.message_signals SET parser_version=%s,features=%s WHERE user_id=%s AND message_id=%s",
                    (old["version"],Jsonb(old),self.user,row["message_id"]))
        self.assertEqual(PostgresStore(config).contextual_candidates(self.user,"星河当前采用什么方案？",[])[1]["indexed_records"],0)
        migrate(config)
        rows,trace=PostgresStore(config).contextual_candidates(self.user,"星河当前采用什么方案？",[])
        self.assertEqual(trace["parser_version"],VERSION)
        hint=trace["state_hints"][0]
        self.assertEqual(hint["candidates"][0]["value"],"乙方案")
        self.assertEqual(hint["candidates"][0]["effective"],20261000)
        self.assertEqual(trace["temporal_selection"][0]["scoped_event_time"],20261000)
        self.assertEqual(snapshot(),before)
        with self.store.connection() as conn:
            first=conn.execute("SELECT message_id,parser_version,features FROM memory.message_signals WHERE user_id=%s ORDER BY message_id",(self.user,)).fetchall()
        migrate(config)
        self.assertEqual(snapshot(),before)
        with self.store.connection() as conn:
            self.assertEqual(conn.execute("SELECT message_id,parser_version,features FROM memory.message_signals WHERE user_id=%s ORDER BY message_id",(self.user,)).fetchall(),first)
            conn.execute("UPDATE memory.message_signals SET features=jsonb_set(features,'{version}','\"old\"') WHERE user_id=%s",(self.user,))
        self.assertEqual(PostgresStore(config).contextual_candidates(self.user,"星河目前采用什么方案？",[])[1]["indexed_records"],0)
        migrate(config)
        self.assertEqual(snapshot(),before)
        self.assertEqual(PostgresStore(config).contextual_candidates(self.user,"星河目前采用什么方案？",[])[1]["indexed_records"],2)

    def test_temporal_counterexample_preserves_both_raw_sources_with_small_topk_and_budget(self):
        from evals.memory_eval import score_case
        writes=[self.request(request_id="old",session_id="old",messages=[dict(role="user",
            content="2026年1月星河采用甲方案。另有2028年12月旅行预约。")]),
                self.request(request_id="new",session_id="new",messages=[dict(role="user",
            content="2026年10月星河采用乙方案。")])]
        for request in writes:
            self.service.add(request)
        self.service.add(self.request(user_id=self.other,messages=[dict(role="user",content="PRIVATE 星河采用他人方案")]))
        for budget in (2048,32768):
            config=replace(self.config,retrieval="bm25",contextual=True,neighbor_window=2,context_limit=24,evidence_bytes=budget)
            service=MemoryService(config,PostgresStore(config),TestEmbeddings())
            for k in (2,5,100):
                data,trace=service.search_debug(SearchRequest(user_id=self.user,query="星河目前采用什么方案？",top_k=k))
                scored=score_case(dict(writes=[r.model_dump() for r in writes],search=dict(user_id=self.user),
                    acceptable_evidence_groups=[[dict(request_id="old",ordinal=0,quote="甲方案"),dict(request_id="new",ordinal=0,quote="乙方案")]]),
                    [r.model_dump() for r in data.data],"",k)
                self.assertTrue(scored["complete"])
                self.assertEqual((scored["audit_errors"],scored["leakage_count"]),(0,0))
                self.assertLessEqual(len(data.data),k)
                self.assertLessEqual(sum(len(row.content.encode()) for row in data.data),budget)
                self.assertEqual(trace["state_hints"][0]["candidates"][0]["value"],"乙方案")

    def test_authenticated_runtime_reports_actual_source_and_schema(self):
        from fastapi.testclient import TestClient
        from unittest.mock import patch
        from app.memory_main import app
        from app.memory.routes import get_service
        app.dependency_overrides[get_service]=lambda:self.service
        try:
            with patch.dict(os.environ,{"MEMORY_API_KEY":"test-key"}),TestClient(app) as client:
                self.assertEqual(client.get("/v1/memories/version").status_code,401)
                response=client.get("/v1/memories/version",headers={"Authorization":"Bearer test-key"})
                response.raise_for_status()
                data=response.json()
                self.assertEqual(data["required_schema_version"],3)
                self.assertEqual(data["signal_parser_version"],"source-lexical-signals-v2")
                self.assertIn("app/memory/signals.py",data["source_sha256"])
                self.assertNotIn("test-key",str(data))
        finally:
            app.dependency_overrides.clear()


@unittest.skipUnless(os.getenv("MEMORY_RUN_LIVE_EMBEDDING") == "1", "real paid embedding probe not explicitly enabled")
class LiveEmbedding(unittest.TestCase):
    def test_real_chinese_and_english_vectors(self):
        config = MemoryConfig.from_env()
        vectors = Embeddings(config).encode(["我在周五下午开会。", "My meeting is on Friday afternoon."])
        self.assertEqual(len(vectors), 2)
        self.assertTrue(all(len(v) == 1024 for v in vectors))


if __name__ == "__main__":
    unittest.main()
