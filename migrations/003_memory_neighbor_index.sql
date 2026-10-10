-- Additive performance index; preserve every raw message/chunk/source and schema=2.
-- Neighbor lookup is by message; the existing PK begins with chunk_id instead.
CREATE INDEX IF NOT EXISTS memory_sources_message_offset
    ON memory.chunk_sources(user_id, message_id, start_offset, chunk_id);
