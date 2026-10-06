import hashlib
import os

import psycopg
from pgvector.psycopg import register_vector

from app.faq_loader import load_faq

MODEL_NAME = "BAAI/bge-small-zh-v1.5"


def main() -> None:
    dsn = os.environ.get("DATABASE_URL")
    cache_dir = os.environ.get("HF_HUB_CACHE")
    if not dsn or not cache_dir:
        raise RuntimeError("请先设置 DATABASE_URL 和 HF_HUB_CACHE")

    chunks = load_faq()
    source = chunks[0]["source"]

    with psycopg.connect(dsn) as conn:
        # 新数据库先启用向量类型，再让 Python 注册类型适配器。
        # 已有扩展时跳过创建；与后续表和数据同步处于同一事务。
        conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
        register_vector(conn)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS faq_chunks (
                source TEXT NOT NULL,
                chunk_id TEXT NOT NULL,
                chunk_no INTEGER NOT NULL,
                version TEXT NOT NULL,
                start_line INTEGER NOT NULL,
                end_line INTEGER NOT NULL,
                content TEXT NOT NULL,
                content_hash TEXT NOT NULL,
                model_name TEXT NOT NULL,
                embedding vector(512) NOT NULL,
                PRIMARY KEY (source, chunk_id)
            )
        """)

        existing = {
            row[0]: (row[1], row[2])
            for row in conn.execute(
                "SELECT chunk_id, content_hash, model_name "
                "FROM faq_chunks WHERE source = %s",
                (source,),
            ).fetchall()
        }

        to_embed = []
        for chunk in chunks:
            digest = hashlib.sha256(chunk["text"].encode("utf-8")).hexdigest()
            if existing.get(chunk["chunk_id"]) == (digest, MODEL_NAME):
                conn.execute(
                    """UPDATE faq_chunks
                       SET chunk_no = %s, version = %s,
                           start_line = %s, end_line = %s
                       WHERE source = %s AND chunk_id = %s""",
                    (
                        chunk["chunk_no"], chunk["version"],
                        chunk["start_line"], chunk["end_line"],
                        source, chunk["chunk_id"],
                    ),
                )
            else:
                to_embed.append((chunk, digest))

        if to_embed:
            from sentence_transformers import SentenceTransformer

            model = SentenceTransformer(
                MODEL_NAME, cache_folder=cache_dir, device="cpu"
            )
            vectors = model.encode(
                [chunk["text"] for chunk, _ in to_embed],
                normalize_embeddings=True,
            )
            if vectors.shape[1] != 512:
                raise ValueError("模型向量维度不是 512")

            for (chunk, digest), vector in zip(to_embed, vectors):
                conn.execute(
                    """INSERT INTO faq_chunks
                       (source, chunk_id, chunk_no, version, start_line,
                        end_line, content, content_hash, model_name, embedding)
                       VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                       ON CONFLICT (source, chunk_id) DO UPDATE SET
                         chunk_no = EXCLUDED.chunk_no,
                         version = EXCLUDED.version,
                         start_line = EXCLUDED.start_line,
                         end_line = EXCLUDED.end_line,
                         content = EXCLUDED.content,
                         content_hash = EXCLUDED.content_hash,
                         model_name = EXCLUDED.model_name,
                         embedding = EXCLUDED.embedding""",
                    (
                        source, chunk["chunk_id"], chunk["chunk_no"],
                        chunk["version"], chunk["start_line"],
                        chunk["end_line"], chunk["text"], digest,
                        MODEL_NAME, vector,
                    ),
                )

        removed_ids = set(existing) - {chunk["chunk_id"] for chunk in chunks}
        for chunk_id in removed_ids:
            conn.execute(
                "DELETE FROM faq_chunks WHERE source = %s AND chunk_id = %s",
                (source, chunk_id),
            )

        total = conn.execute(
            "SELECT count(*) FROM faq_chunks WHERE source = %s", (source,)
        ).fetchone()[0]

    print(
        f"总数={total} 新增或重算={len(to_embed)} "
        f"复用向量={len(chunks) - len(to_embed)} 删除={len(removed_ids)}"
    )


if __name__ == "__main__":
    main()
