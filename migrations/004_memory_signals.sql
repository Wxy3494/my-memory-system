-- Derived retrieval hints, source-linked and deletable; raw messages remain authoritative.
CREATE TABLE IF NOT EXISTS memory.message_signals (
    user_id text NOT NULL,
    message_id text NOT NULL,
    parser_version text NOT NULL,
    features jsonb NOT NULL,
    PRIMARY KEY(user_id,message_id),
    FOREIGN KEY(user_id,message_id) REFERENCES memory.messages(user_id,message_id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS memory_signals_user ON memory.message_signals(user_id);
UPDATE memory.schema_version SET version=3 WHERE singleton;
