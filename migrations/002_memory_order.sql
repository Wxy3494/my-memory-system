-- Additive upgrade. Existing text, IDs, embeddings and pipeline signature stay intact.
ALTER TABLE memory.messages ADD COLUMN IF NOT EXISTS received_ordinal bigint;
ALTER TABLE memory.messages ADD COLUMN IF NOT EXISTS order_basis text;
-- Historic acceptance order cannot be proven for equal ingestion timestamps.
-- Explicitly label this deterministic backfill as reconstructed, not source order.
WITH ranked AS (
    SELECT user_id, message_id,
           row_number() OVER (PARTITION BY user_id, session_id
             ORDER BY stored_at, request_id, ordinal, message_id) - 1 AS position
    FROM memory.messages
)
UPDATE memory.messages m SET received_ordinal=r.position,
    order_basis='legacy_ingest_reconstructed'
FROM ranked r WHERE m.user_id=r.user_id AND m.message_id=r.message_id
    AND m.received_ordinal IS NULL;
ALTER TABLE memory.messages ALTER COLUMN received_ordinal SET NOT NULL;
ALTER TABLE memory.messages ALTER COLUMN order_basis SET NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS memory_messages_received_order
    ON memory.messages(user_id, session_id, received_ordinal);
ALTER TABLE memory.schema_version DROP CONSTRAINT IF EXISTS schema_version_version_check;
UPDATE memory.schema_version SET version=2 WHERE singleton;
