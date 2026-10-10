from contextlib import contextmanager

import psycopg
from psycopg.rows import dict_row
from pgvector import Vector
from pgvector.psycopg import register_vector
from psycopg.types.json import Jsonb
from .signals import extract, VERSION, plan

from .chunking import stable_id
from .config import CHUNKER_VERSION
from .errors import Conflict, MemoryError
from .retrieval import bm25_rank, message_candidates, keyword_terms


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
                if not version or version["version"] != 3 or version["pipeline_signature"] != self.config.signature:
                    raise MemoryError("memory_migration_or_pipeline_mismatch")
                if self.config.contextual and conn.execute("SELECT to_regclass('memory.message_signals') AS name").fetchone()["name"] is None:
                    raise MemoryError("memory_context_migration_missing")
                register_vector(conn)
                yield conn
        except MemoryError:
            raise
        except psycopg.Error:
            raise MemoryError("memory_database_unavailable") from None

    def check(self):
        with self.connection() as conn:
            # Empty tables are ready. Verify all tables exist without scanning contents.
            for table in ("ingest_requests", "messages", "chunks", "chunk_sources", "message_signals"):
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
            # Serialize different Add requests in one user/session, after retry locking.
            session_key = int(stable_id("session-order", request.user_id, request.session_id)[:16], 16)
            session_key = session_key if session_key < 2**63 else session_key - 2**64
            conn.execute("SELECT pg_advisory_xact_lock(%s)", (session_key,))
            first = conn.execute("""SELECT coalesce(max(received_ordinal)+1,0) AS position
                FROM memory.messages WHERE user_id=%s AND session_id=%s""",
                (request.user_id, request.session_id)).fetchone()["position"]
            conn.execute("""INSERT INTO memory.ingest_requests
                (user_id, request_id, session_id, payload_hash, pipeline_version) VALUES (%s,%s,%s,%s,%s)""",
                (request.user_id, request.request_id, request.session_id, digest, self.config.pipeline_version))
            with conn.cursor() as cursor:
                cursor.executemany("""INSERT INTO memory.messages
                    (user_id,message_id,request_id,session_id,ordinal,role,content,source_timestamp_ms,received_ordinal,order_basis)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                    [(request.user_id, stable_id("message", request.user_id, request.request_id, i),
                      request.request_id, request.session_id, i, m.role, m.content, m.timestamp, first+i, "received")
                     for i, m in enumerate(request.messages)])
                cursor.executemany("""INSERT INTO memory.message_signals(user_id,message_id,parser_version,features)
                    VALUES(%s,%s,%s,%s)""",[(request.user_id,
                    stable_id("message",request.user_id,request.request_id,i),VERSION,Jsonb(extract(m.content,m.role,m.timestamp)))
                    for i,m in enumerate(request.messages)])
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
            vector_rows = [] if vector is None else conn.execute("""WITH scoped AS MATERIALIZED (
                SELECT * FROM memory.chunks WHERE user_id=%s)
                SELECT user_id,chunk_id,request_id,session_id,content, 1-(embedding <=> %s) AS score FROM scoped
                ORDER BY embedding <=> %s, session_id, request_id, content, chunk_id LIMIT %s""",
                (user_id, Vector(vector), Vector(vector), limit)).fetchall()
            lexical_rows = []
            if terms and self.config.retrieval in ("bm25", "hybrid_bm25"):
                # User-scoped exact lexical scan; O(user chunks), measured before deployment.
                corpus = conn.execute("""SELECT DISTINCT ON (c.chunk_id)
                    c.user_id,c.chunk_id,c.request_id,c.session_id,c.content,s.start_offset,m.ordinal
                    FROM memory.chunks c JOIN memory.chunk_sources s
                    ON s.user_id=c.user_id AND s.chunk_id=c.chunk_id
                    JOIN memory.messages m ON m.user_id=s.user_id AND m.message_id=s.message_id
                    WHERE c.user_id=%s ORDER BY c.chunk_id,m.ordinal,s.start_offset""", (user_id,)).fetchall()
                lexical_rows = bm25_rank(corpus, terms, limit)
            elif terms:
                lexical_rows = conn.execute("""WITH scoped AS MATERIALIZED (
                    SELECT * FROM memory.chunks WHERE user_id=%s), ranked AS (
                    SELECT user_id,chunk_id,request_id,session_id,content, (SELECT count(*) FROM unnest(%s::text[]) AS terms(term)
                        WHERE strpos(lower(scoped.content), term)>0) AS score FROM scoped)
                    SELECT * FROM ranked WHERE score>0 ORDER BY score DESC, session_id, request_id, content, chunk_id LIMIT %s""",
                    (user_id, terms, limit)).fetchall()
            self._attach_sources(conn, user_id, vector_rows + lexical_rows)
        return vector_rows, lexical_rows

    def contextual_candidates(self,user_id,query,seeds):
        with self.connection() as conn:
            records=conn.execute("""SELECT m.message_id,m.session_id,m.request_id,m.ordinal,m.role,
                m.source_timestamp_ms AS timestamp,m.stored_at,s.features FROM memory.messages m
                JOIN memory.message_signals s ON s.user_id=m.user_id AND s.message_id=m.message_id
                WHERE m.user_id=%s AND s.parser_version=%s AND s.features->>'version'=%s
                AND encode(sha256(convert_to(m.content,'UTF8')),'hex')=s.features->>'source_sha256'
                ORDER BY m.stored_at DESC,m.request_id,m.ordinal LIMIT %s""",
                (user_id,VERSION,VERSION,self.config.signal_scan_limit+1)).fetchall()
            truncated=len(records)>self.config.signal_scan_limit
            records=records[:self.config.signal_scan_limit]
            for r in records:
                r["stored_at"]=r["stored_at"].isoformat()
            ids,trace=plan(records,query,seeds,self.config.context_limit,self.config.link_hops)
            trace["signal_scan_truncated"]=truncated
            selected=[]
            for mid in ids:
                slices=conn.execute("""SELECT c.user_id,c.chunk_id,c.request_id,c.session_id,c.content,s.start_offset,m.ordinal
                    FROM memory.chunk_sources s JOIN memory.chunks c ON c.user_id=s.user_id AND c.chunk_id=s.chunk_id
                    JOIN memory.messages m ON m.user_id=s.user_id AND m.message_id=s.message_id
                    WHERE s.user_id=%s AND s.message_id=%s ORDER BY s.start_offset,c.chunk_id""",(user_id,mid)).fetchall()
                selected.extend(message_candidates(slices,keyword_terms(query))[:2])
            self._attach_sources(conn,user_id,selected)
        return [dict(r,score=1/(i+1)) for i,r in enumerate(selected)],trace

    @staticmethod
    def _attach_sources(conn, user_id, rows):
        ids = list({r["chunk_id"] for r in rows})
        sources = conn.execute("""SELECT s.*, m.request_id, m.session_id, m.ordinal, m.role,
            m.source_timestamp_ms AS timestamp, m.received_ordinal, m.stored_at, m.order_basis
            FROM memory.chunk_sources s
            JOIN memory.messages m ON m.user_id=s.user_id AND m.message_id=s.message_id
            WHERE s.user_id=%s AND s.chunk_id=ANY(%s) ORDER BY s.chunk_id, m.received_ordinal""",
            (user_id, ids)).fetchall()
        mapping = {}
        for source in sources:
            source["stored_at"] = source["stored_at"].isoformat()
            mapping.setdefault(source["chunk_id"], []).append(source)
        for row in rows:
            row["sources"] = mapping[row["chunk_id"]]

    def neighbors(self, user_id, seeds, window, terms=()):
        targets = set()
        for row in seeds:
            for source in row["sources"]:
                position = source.get("received_ordinal")
                if position is not None:
                    targets.update((source["session_id"], i) for i in
                                   range(max(0, position-window), position+window+1))
        if not targets:
            return []
        sessions, positions = zip(*sorted(targets))
        with self.connection() as conn:
            messages = conn.execute("""SELECT m.message_id,m.session_id,m.received_ordinal FROM memory.messages m
                JOIN unnest(%s::text[],%s::bigint[]) AS wanted(session_id,position)
                ON m.session_id=wanted.session_id AND m.received_ordinal=wanted.position
                WHERE m.user_id=%s ORDER BY m.session_id,m.received_ordinal""",
                (list(sessions), list(positions), user_id)).fetchall()
            chosen = {}
            # Scan ONE parent at a time, text only, no embeddings; max_chunks/payload
            # bound each Add. Linear target-message scan is measured, not constant-time.
            for message in messages:
                slices = conn.execute("""SELECT c.user_id,c.chunk_id,c.request_id,c.session_id,c.content,
                    s.start_offset,m.ordinal FROM memory.chunk_sources s JOIN memory.chunks c
                    ON c.user_id=s.user_id AND c.chunk_id=s.chunk_id
                    JOIN memory.messages m ON m.user_id=s.user_id AND m.message_id=s.message_id
                    WHERE s.user_id=%s AND s.message_id=%s ORDER BY s.start_offset,c.chunk_id""",
                    (user_id, message["message_id"])).fetchall()
                anchors = [s["start_offset"] for seed in seeds for s in seed["sources"]
                           if s["message_id"] == message["message_id"]]
                for row in message_candidates(slices, terms, anchors):
                    key = row["chunk_id"]
                    if key not in chosen or row["neighbor_priority"] < chosen[key]["neighbor_priority"]:
                        chosen[key] = row
            rows = list(chosen.values())
            self._attach_sources(conn, user_id, rows)
        return rows
