"""Offline correctness and HTTP contract tests; NOT provider/PostgreSQL acceptance."""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import io
import json
import logging
import os
import threading
import unittest
from unittest.mock import MagicMock, patch

import httpx
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.memory_main import app
from app.memory.chunking import make_chunks, payload_hash, split_text
from app.memory.config import MemoryConfig
from app.memory.embeddings import Embeddings, validate_vectors
from app.memory.errors import Conflict, MemoryError
from app.memory.retrieval import keyword_terms, rank
from app.memory.routes import get_service
from app.memory.schemas import AddRequest, SearchRequest
from app.memory.service import MemoryService

CONFIG = MemoryConfig("unused", "test-token", "test-embedding-token", "https://provider.invalid/v1")


class FakeEmbeddings:
    def encode(self, texts):
        return [[1.0] + [0.0] * 1023 for _ in texts]

    def query(self, text):
        return self.encode([text])[0]


class FakeStore:
    def __init__(self):
        self.lock = threading.Lock()
        self.requests, self.rows = {}, []

    def existing(self, request, digest):
        with self.lock:
            old = self.requests.get((request.user_id, request.request_id))
            if old and old != digest:
                raise Conflict("request_payload_conflict")
            return bool(old)

    def commit(self, request, digest, chunks, vectors):
        with self.lock:
            key = (request.user_id, request.request_id)
            if key in self.requests:
                if self.requests[key] != digest:
                    raise Conflict("request_payload_conflict")
                return False
            rows = []
            for c in chunks:
                message = request.messages[c["ordinal"]]
                rows.append(dict(c, user_id=request.user_id, score=1.0,
                    sources=[dict(message_id=c["message_id"], session_id=request.session_id,
                                  request_id=request.request_id, ordinal=c["ordinal"], role=message.role,
                                  timestamp=message.timestamp, start_offset=c["start_offset"], end_offset=c["end_offset"])]))
            self.requests[key] = digest
            self.rows.extend(rows)
            return True

    def candidates(self, user_id, vector, limit, terms=None):
        return [row for row in self.rows if row["user_id"] == user_id][:limit], []


class ContractTests(unittest.TestCase):
    def setUp(self):
        self.store = FakeStore()
        self.embedding = FakeEmbeddings()
        self.service = MemoryService(CONFIG, self.store, self.embedding)
        app.dependency_overrides[get_service] = lambda: self.service
        self.env = patch.dict(os.environ, {"MEMORY_API_KEY": "test-token"})
        self.env.start()
        self.client = TestClient(app)
        self.headers = {"Authorization": "Bearer test-token"}

    def tearDown(self):
        app.dependency_overrides.clear()
        self.env.stop()

    def payload(self, **kwargs):
        body = dict(request_id=" request:A ", user_id=" User:甲 ", session_id=" Session:A ",
                    messages=[dict(role="user", content="我在周五下午开项目会。", timestamp=1704067200000)])
        body.update(kwargs)
        return body

    def add(self, body=None):
        return self.client.post("/v1/memories/add", headers=self.headers, json=body or self.payload())

    def search(self, user=" User:甲 ", query="我的订单退款人工客服记录", top_k=100):
        return self.client.post("/v1/memories/search", headers=self.headers,
            json=dict(user_id=user, query=query, top_k=top_k, options=["A. unrelated", "B. another"]))

    def test_exact_echo_immediate_search_sources(self):
        response = self.add()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), dict(success=True, request_id=" request:A ",
                                              user_id=" User:甲 ", session_id=" Session:A "))
        data = self.search().json()["data"]
        self.assertIn("我在周五下午开项目会。", data[0]["content"])
        self.assertIn('"role":"user"', data[0]["content"])
        self.assertIn("1704067200000", data[0]["content"])
        self.assertEqual(data[0]["sources"][0]["start_offset"], 0)
        self.assertNotIn("unrelated", data[0]["content"])
        self.assertIn("x-request-id", response.headers)

    def test_isolation_and_cross_session(self):
        self.add()
        self.add(self.payload(request_id="b", session_id="second", messages=[dict(role="assistant", content="我建议改在周一。")]))
        self.assertEqual(len(self.search().json()["data"]), 2)
        self.assertEqual(self.search(user="User:甲").json(), {"data": []})
        self.assertEqual(self.search(user="another").json(), {"data": []})

    def test_idempotence_conflict_and_cross_user_request_id(self):
        self.add()
        original = self.search().json()
        self.add()
        self.assertEqual(self.search().json(), original)
        conflict = self.add(self.payload(session_id="changed"))
        self.assertEqual(conflict.status_code, 409)
        self.assertEqual(len(self.store.rows), 1)
        self.assertEqual(self.add(self.payload(user_id="other")).status_code, 200)

    def test_concurrent_duplicate_add(self):
        request = AddRequest(**self.payload())
        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(lambda _: self.service.add(request), range(24)))
        self.assertTrue(all(r.success for r in results))
        self.assertEqual(len(self.store.rows), 1)

    def test_error_token_never_writes(self):
        for headers in ({}, {"Authorization": "Bearer incorrect"}, {"Authorization": "Token test-token"}):
            self.assertEqual(self.client.post("/v1/memories/add", json=self.payload(), headers=headers).status_code, 401)
        self.assertEqual(self.store.rows, [])

    def test_invalid_contract(self):
        cases = [self.payload(messages=[]), self.payload(extra=True),
                 self.payload(messages=[dict(role="system", content="text")]),
                 self.payload(messages=[dict(role="user", content=" ")]),
                 self.payload(messages=[dict(role="user", content="a\x00b")]),
                 self.payload(messages=[dict(role="user", content="x", timestamp=True)]),
                 self.payload(messages=[dict(role="user", content="x", timestamp=-1)]),
                 self.payload(user_id="")]
        for body in cases:
            self.assertEqual(self.add(body).status_code, 422)
        for k in (0, 1001, True, "100", 1.5):
            self.assertEqual(self.search(top_k=k).status_code, 422)
        self.assertEqual(self.store.rows, [])

    def test_top_k_and_long_question(self):
        self.add(self.payload(messages=[dict(role="user", content="fact " + str(i)) for i in range(120)]))
        for k in (1, 5, 100):
            self.assertEqual(len(self.search(top_k=k).json()["data"]), k)
        self.assertEqual(self.search(query="长问题" * 1000).status_code, 200)

    def test_provider_and_db_failure_are_not_empty_success(self):
        with patch.object(self.embedding, "encode", side_effect=MemoryError("embedding_unavailable")):
            self.assertEqual(self.add().status_code, 503)
        self.assertEqual(self.store.rows, [])
        with patch.object(self.store, "candidates", side_effect=MemoryError("memory_database_unavailable")):
            self.assertEqual(self.search().status_code, 503)

    def test_invalid_vectors_never_reach_commit(self):
        for vectors in ([], [[0.0] * 1024], [[float("nan")] * 1024], [[1.0] * 512]):
            with patch.object(self.embedding, "encode", return_value=vectors):
                self.assertEqual(self.add().status_code, 503)
        self.assertEqual(self.store.rows, [])

    def test_size_limit_no_partial_write(self):
        with patch.dict(os.environ, {"MEMORY_MAX_PAYLOAD_BYTES": "1024"}):
            self.assertEqual(self.add(self.payload(messages=[dict(role="user", content="大" * 2000)])).status_code, 413)
        self.assertEqual(self.store.rows, [])

    def test_logs_and_metrics_never_include_private_text_or_keys(self):
        buffer = io.StringIO()
        logger = logging.getLogger("rag.telemetry")
        # Discover existing logger's name via module rather than relying on a guessed name.
        from app.observability import logger
        handler = logging.StreamHandler(buffer)
        logger.addHandler(handler)
        try:
            self.add(self.payload(messages=[dict(role="user", content="PRIVATE_MEMORY_987")]))
            self.search()
        finally:
            logger.removeHandler(handler)
        metrics = self.client.get("/metrics").text
        for private in ("PRIVATE_MEMORY_987", "test-token", "User:甲", "request:A"):
            self.assertNotIn(private, buffer.getvalue())
            self.assertNotIn(private, metrics)
        self.assertIn('path="/v1/memories/add"', metrics)

    def test_health_independent_and_readiness_missing_configuration(self):
        self.assertEqual(self.client.get("/health").status_code, 200)
        with patch.dict(os.environ, {"MEMORY_EMBEDDING_API_KEY": ""}):
            self.assertEqual(self.client.get("/ready/memory").status_code, 503)


class ChunkAndProviderTests(unittest.TestCase):
    def test_full_unicode_coverage_exact_offsets_and_budget(self):
        text = "开始😀。\n" + "English 混合段落！" * 1000 + "最终事实XYZ"
        pieces = list(split_text(text, 400, 60))
        covered = set()
        for piece in pieces:
            self.assertEqual(text[piece.start:piece.end], piece.content)
            self.assertLessEqual(len(piece.content.encode()), 400)
            covered.update(range(piece.start, piece.end))
        self.assertEqual(len(covered), len(text))
        self.assertTrue(pieces[-1].content.endswith("最终事实XYZ"))

    def test_hash_preserves_order_role_time_and_identifier(self):
        body = dict(request_id="r", user_id="u", session_id="s", messages=[dict(role="user", content="one"), dict(role="assistant", content="two")])
        original = AddRequest(**body)
        other = original.model_copy(update={"messages": list(reversed(original.messages))})
        self.assertNotEqual(payload_hash(original), payload_hash(other))
        self.assertEqual(make_chunks(original, CONFIG), make_chunks(original, CONFIG))
        # IDs encode source position, while changed payloads are rejected by the receipt hash.
        self.assertEqual(make_chunks(original, CONFIG)[0]["chunk_id"], make_chunks(other, CONFIG)[0]["chunk_id"])

    def test_real_adapter_batching_and_index_reorder(self):
        calls = []
        def endpoint(request):
            body = json.loads(request.content)
            self.assertEqual(body["dimensions"], 1024)
            calls.append(len(body["input"]))
            return httpx.Response(200, json={"data": [dict(index=i, embedding=[float(i + 1), 1.0] + [0.0] * 1022)
                    for i in reversed(range(len(body["input"])))], "usage": {"total_tokens": 3}})
        factory = httpx.Client
        with patch("app.memory.embeddings.httpx.Client", side_effect=lambda **kwargs: factory(transport=httpx.MockTransport(endpoint), **kwargs)):
            output = Embeddings(CONFIG).encode(["x"] * 23)
        self.assertEqual(calls, [10, 10, 3])
        self.assertEqual(len(output), 23)
        self.assertAlmostEqual(output[0][0], 2 ** -.5)
        self.assertGreater(output[9][0], output[0][0])

    def test_adapter_rejects_missing_duplicate_and_malformed_vectors(self):
        bad = [[], [dict(index=1, embedding=[1.0] * 1024)],
               [dict(index=0, embedding=[True] * 1024)], [dict(index=0, embedding=[float("inf")] * 1024)]]
        for data in bad:
            client = MagicMock()
            client.__enter__.return_value = client
            client.post.return_value = httpx.Response(200, json={"data": data}) if not any(
                any(isinstance(x, float) and x == float("inf") for x in r["embedding"]) for r in data) else MagicMock(
                    status_code=200, json=lambda: {"data": data})
            with patch("app.memory.embeddings.httpx.Client", return_value=client):
                with self.assertRaises(MemoryError):
                    Embeddings(CONFIG).encode(["x"])

    def test_bounded_retry_and_no_retry_on_bad_key(self):
        for status, count in ((401, 1), (429, 3), (500, 3)):
            client = MagicMock()
            client.__enter__.return_value = client
            client.post.return_value.status_code = status
            with patch("app.memory.embeddings.httpx.Client", return_value=client), patch("app.memory.embeddings.time.sleep"):
                with self.assertRaises(MemoryError):
                    Embeddings(CONFIG).encode(["x"])
            self.assertEqual(client.post.call_count, count)

    def test_query_consumes_all_long_text(self):
        encoder = Embeddings(CONFIG)
        with patch.object(encoder, "encode", side_effect=FakeEmbeddings().encode) as encode:
            result = encoder.query("中文" * 4000 + "ENDING")
        submitted = encode.call_args.args[0]
        self.assertTrue(submitted[-1].endswith("ENDING"))
        self.assertEqual("".join(submitted), "中文" * 4000 + "ENDING")
        self.assertEqual(len(result), 1024)

    def test_hybrid_rrf_and_chinese_terms(self):
        self.assertIn("周五", keyword_terms("我的周五会议 ORD-991"))
        self.assertIn("ord-991", keyword_terms("我的周五会议 ORD-991"))
        v = [dict(chunk_id="a", score=.8), dict(chunk_id="b", score=.7)]
        k = [dict(chunk_id="b", score=1)]
        result = rank(v, k, 100, True)
        self.assertEqual([r["chunk_id"] for r in result], ["b", "a"])
        self.assertEqual(len({r["chunk_id"] for r in result}), 2)


if __name__ == "__main__":
    unittest.main()
