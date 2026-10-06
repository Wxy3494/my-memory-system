from contextlib import contextmanager

import psycopg
from psycopg.rows import dict_row
from pgvector import Vector
from pgvector.psycopg import register_vector

from .chunking import stable_id
from .config import CHUNKER_VERSION
from .errors import Conflict, MemoryError


class PostgresStore:
    def __init__(self, config):
        self.config = config

    @contextmanager
    def connection(self):
        try:
            with psycopg.connect(self.config.database_url, connect_timeout=5,
                                 options="-c statement_timeout=30000 -c lock_timeout=10000",
                                 row_factory=dict_row) as conn:
                version = conn.execute("SELECT version, pipeline_signature FROM memory.schema_version WHERE singleton").fetchone()
                if not version or version["version"] != 1 or version["pipeline_signature"] != self.config.signature:
                    raise MemoryError("memory_migration_or_pipeline_mismatch")
                register_vector(conn)
                yield conn
        except MemoryError:
            raise
        except psycopg.Error:
            raise MemoryError("memory_database_unavailable") from None

    def check(self):
        with self.connection() as conn:
            # Empty tables are ready. Verify all tables exist without scanning contents.
            for table in ("ingest_requests", "messages", "chunks", "chunk_sources"):
                if conn.execute("SELECT to_regclass(%s) AS name", ("memory." + table,)).fetchone()["name"] is None:
                    raise MemoryError("memory_migration_missing")

    @staticmethod
    def _existing(conn, request, digest):
        row = conn.execute("SELECT payload_hash FROM memory.ingest_requests WHERE user_id=%s AND request_id=%s",
                           (request.user_id, request.request_id)).fetchone()
        if row and row["payload_hash"] != digest:
            raise Conflict("request_payload_conflict")
        return row is not None

    def existing(self, request, digest):
        with self.connection() as conn:
            return self._existing(conn, request, digest)

    def commit(self, request, digest, chunks, vectors):
        with self.connection() as conn:
            # Transaction-scoped lock: second simultaneous retry sees the first commit.
            key = int(stable_id(request.user_id, request.request_id)[:16], 16)
            key = key if key < 2**63 else key - 2**64
            conn.execute("SELECT pg_advisory_xact_lock(%s)", (key,))
            if self._existing(conn, request, digest):
                return False
            conn.execute("""INSERT INTO memory.ingest_requests
                (user_id, request_id, session_id, payload_hash, pipeline_version) VALUES (%s,%s,%s,%s,%s)""",
                (request.user_id, request.request_id, request.session_id, digest, self.config.pipeline_version))
            with conn.cursor() as cursor:
                cursor.executemany("""INSERT INTO memory.messages
                    (user_id,message_id,request_id,session_id,ordinal,role,content,source_timestamp_ms)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s)""",
                    [(request.user_id, stable_id("message", request.user_id, request.request_id, i),
                      request.request_id, request.session_id, i, m.role, m.content, m.timestamp)
                     for i, m in enumerate(request.messages)])
                cursor.executemany("""INSERT INTO memory.chunks
                    (user_id,chunk_id,request_id,session_id,content,embedding,embedding_model,embedding_dim,chunker_version)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                    [(request.user_id, c["chunk_id"], request.request_id, request.session_id,
                      c["content"], Vector(v), self.config.model, self.config.dimension, CHUNKER_VERSION)
                     for c, v in zip(chunks, vectors, strict=True)])
                cursor.executemany("""INSERT INTO memory.chunk_sources
                    (user_id,chunk_id,message_id,start_offset,end_offset) VALUES (%s,%s,%s,%s,%s)""",
                    [(request.user_id, c["chunk_id"], c["message_id"], c["start_offset"], c["end_offset"]) for c in chunks])
        return True  # psycopg context exited: committed before Add responds.

    def candidates(self, user_id, vector, limit, terms=None):
        with self.connection() as conn:
            # Materialized scope explicitly isolates BEFORE vector distance ordering.
            vector_rows = conn.execute("""WITH scoped AS MATERIALIZED (
                SELECT * FROM memory.chunks WHERE user_id=%s)
                SELECT user_id,chunk_id,request_id,session_id,content, 1-(embedding <=> %s) AS score FROM scoped
                ORDER BY embedding <=> %s, chunk_id LIMIT %s""",
                (user_id, Vector(vector), Vector(vector), limit)).fetchall()
            lexical_rows = []
            if terms:
                lexical_rows = conn.execute("""WITH scoped AS MATERIALIZED (
                    SELECT * FROM memory.chunks WHERE user_id=%s), ranked AS (
                    SELECT user_id,chunk_id,request_id,session_id,content, (SELECT count(*) FROM unnest(%s::text[]) AS terms(term)
                        WHERE strpos(lower(scoped.content), term)>0) AS score FROM scoped)
                    SELECT * FROM ranked WHERE score>0 ORDER BY score DESC, chunk_id LIMIT %s""",
                    (user_id, terms, limit)).fetchall()
            ids = list({r["chunk_id"] for r in vector_rows + lexical_rows})
            sources = conn.execute("""SELECT s.*, m.request_id, m.session_id, m.ordinal, m.role,
                m.source_timestamp_ms AS timestamp FROM memory.chunk_sources s
                JOIN memory.messages m ON m.user_id=s.user_id AND m.message_id=s.message_id
                WHERE s.user_id=%s AND s.chunk_id=ANY(%s) ORDER BY s.chunk_id, m.ordinal""",
                (user_id, ids)).fetchall()
        mapping = {}
        for source in sources:
            mapping.setdefault(source["chunk_id"], []).append(source)
        for row in vector_rows + lexical_rows:
            row["sources"] = mapping[row["chunk_id"]]
        return vector_rows, lexical_rows
