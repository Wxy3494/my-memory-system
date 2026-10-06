-- Append-only V0 migration; never touches public.faq_chunks.
CREATE EXTENSION IF NOT EXISTS vector;
CREATE SCHEMA IF NOT EXISTS memory;
CREATE TABLE IF NOT EXISTS memory.schema_version (
    singleton boolean PRIMARY KEY DEFAULT true CHECK (singleton),
    version integer NOT NULL CHECK (version = 1),
    pipeline_signature text NOT NULL
);
CREATE TABLE IF NOT EXISTS memory.ingest_requests (
    user_id text NOT NULL,
    request_id text NOT NULL,
    session_id text NOT NULL,
    payload_hash text NOT NULL,
    pipeline_version text NOT NULL,
    completed_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY (user_id, request_id),
    UNIQUE (user_id, request_id, session_id)
);
CREATE TABLE IF NOT EXISTS memory.messages (
    user_id text NOT NULL,
    message_id text NOT NULL,
    request_id text NOT NULL,
    session_id text NOT NULL,
    ordinal integer NOT NULL CHECK (ordinal >= 0),
    role text NOT NULL CHECK (role IN ('user', 'assistant')),
    content text NOT NULL CHECK (length(content) > 0),
    source_timestamp_ms bigint CHECK (source_timestamp_ms >= 0),
    stored_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY (user_id, message_id),
    UNIQUE (user_id, request_id, ordinal),
    FOREIGN KEY (user_id, request_id, session_id)
        REFERENCES memory.ingest_requests(user_id, request_id, session_id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS memory_messages_session ON memory.messages(user_id, session_id);
CREATE TABLE IF NOT EXISTS memory.chunks (
    user_id text NOT NULL,
    chunk_id text NOT NULL,
    request_id text NOT NULL,
    session_id text NOT NULL,
    content text NOT NULL CHECK (length(content) > 0),
    embedding vector(1024) NOT NULL,
    embedding_model text NOT NULL CHECK (embedding_model = 'text-embedding-v4'),
    embedding_dim integer NOT NULL CHECK (embedding_dim = 1024),
    chunker_version text NOT NULL,
    PRIMARY KEY (user_id, chunk_id),
    FOREIGN KEY (user_id, request_id, session_id)
        REFERENCES memory.ingest_requests(user_id, request_id, session_id) ON DELETE CASCADE
);
-- Exact distance search in the indexed user's scope; no global ANN top-k filter.
CREATE INDEX IF NOT EXISTS memory_chunks_user ON memory.chunks(user_id);
CREATE TABLE IF NOT EXISTS memory.chunk_sources (
    user_id text NOT NULL,
    chunk_id text NOT NULL,
    message_id text NOT NULL,
    start_offset integer NOT NULL CHECK (start_offset >= 0),
    end_offset integer NOT NULL CHECK (end_offset > start_offset),
    PRIMARY KEY (user_id, chunk_id, message_id),
    FOREIGN KEY (user_id, chunk_id) REFERENCES memory.chunks(user_id, chunk_id) ON DELETE CASCADE,
    FOREIGN KEY (user_id, message_id) REFERENCES memory.messages(user_id, message_id) ON DELETE CASCADE
);
