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


@unittest.skipUnless(os.getenv("MEMORY_RUN_LIVE_EMBEDDING") == "1", "real paid embedding probe not explicitly enabled")
class LiveEmbedding(unittest.TestCase):
    def test_real_chinese_and_english_vectors(self):
        config = MemoryConfig.from_env()
        vectors = Embeddings(config).encode(["我在周五下午开会。", "My meeting is on Friday afternoon."])
        self.assertEqual(len(vectors), 2)
        self.assertTrue(all(len(v) == 1024 for v in vectors))


if __name__ == "__main__":
    unittest.main()
