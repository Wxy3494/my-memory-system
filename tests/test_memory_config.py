import os
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from app.memory_main import app
from app.memory.config import MemoryConfig
from app.memory.embeddings import record_probe
from app.memory.errors import MemoryError
from app.memory.schemas import AddRequest

ENV = dict(DATABASE_URL="postgresql://fake:fake@localhost/test", MEMORY_API_KEY="test-key",
           MEMORY_EMBEDDING_BASE_URL="https://provider.invalid/v1", MEMORY_EMBEDDING_API_KEY="fake-provider-key")


class ConfigurationTests(unittest.TestCase):
    def test_invalid_configuration_is_explicit_and_no_secrets(self):
        for fields in ({"MEMORY_EMBEDDING_DIM": "512"}, {"MEMORY_EMBEDDING_MODEL": "BGE"},
                       {"MEMORY_CHUNK_OVERLAP_TOKENS": "399"}, {"MEMORY_CHUNK_TARGET_TOKENS": "invalid"},
                       {"MEMORY_EMBEDDING_BASE_URL": "http://insecure.invalid"},
                       {"MEMORY_EMBEDDING_BASE_URL": "https://user:private@provider.invalid"}):
            with patch.dict(os.environ, dict(ENV, **fields)):
                with self.assertRaises(MemoryError) as result:
                    MemoryConfig.from_env()
                self.assertEqual(str(result.exception), "memory_configuration_invalid")

    def test_empty_db_ready_only_with_fresh_probe_and_no_paid_health_call(self):
        with patch.dict(os.environ, ENV), patch("app.memory.routes.PostgresStore.check") as check, \
                patch("app.memory.routes.Embeddings.encode") as paid:
            config = MemoryConfig.from_env()
            record_probe(config, True)
            client = TestClient(app)
            self.assertEqual(client.get("/ready/memory").status_code, 200)
            with patch("app.memory.embeddings.time.monotonic", return_value=10**15):
                self.assertEqual(client.get("/ready/memory").status_code, 503)
            paid.assert_not_called()
            check.assert_called()

    def test_long_unicode_ids_rejected_before_database_index_overflow(self):
        with self.assertRaises(ValueError):
            AddRequest(request_id="r", user_id="字" * 200, session_id="s", messages=[dict(role="user", content="text")])
