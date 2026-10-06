import argparse
import os
import math
import re
from functools import lru_cache
from .observability import CURRENT, stage

class ModelUnavailable(Exception):
    pass

import psycopg
from pgvector.psycopg import register_vector
from psycopg.rows import dict_row

MODEL_NAME = "BAAI/bge-small-zh-v1.5"
QUERY_PREFIX = "为这个句子生成表示以用于检索相关文章："


def record_retrieval(rows):
    """Only public FAQ metadata can enter traces; never send retrieved text."""
    ctx = CURRENT.get()
    if ctx is None:
        return
    metadata = []
    for row in rows[:10]:
        rule, version, score = row.get('chunk_id', ''), row.get('version', ''), row.get('score')
        if (isinstance(rule, str) and re.fullmatch(r'RULE-[A-Z0-9-]{1,80}', rule)
                and isinstance(version, str) and re.fullmatch(r'[A-Za-z0-9._-]{1,64}', version)
                and row.get('source') == 'docs/faq.md'
                and isinstance(score, (int, float)) and math.isfinite(score)):
            metadata.append({'chunk_id': rule, 'version': version, 'score': round(score, 6)})
    ctx.retrieved_chunks = metadata


@lru_cache(maxsize=1)
def get_model():
    from sentence_transformers import SentenceTransformer

    cache_dir = os.environ.get("HF_HUB_CACHE")
    if not cache_dir:
        raise RuntimeError("请在配置了 D 盘模型缓存的终端运行")

    return SentenceTransformer(
        MODEL_NAME,
        cache_folder=cache_dir,
        device="cpu",
        local_files_only=True,
    )


def search_faq(question: str, top_k: int = 3) -> list[dict]:
    question = question.strip()
    if not question:
        raise ValueError("问题不能为空")
    if not 1 <= top_k <= 10:
        raise ValueError("top_k 必须在 1 到 10 之间")

    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        raise RuntimeError("请先设置 DATABASE_URL")

    with stage('embedding'):
        try:
            vector = get_model().encode(QUERY_PREFIX + question, normalize_embeddings=True)
        except Exception:
            raise ModelUnavailable() from None

    with stage('retrieval'), psycopg.connect(
        dsn, connect_timeout=10, options='-c statement_timeout=5000', row_factory=dict_row
    ) as conn:
        register_vector(conn)
        rows = conn.execute(
            """
            SELECT chunk_id, chunk_no, source, version,
                   start_line, end_line, content,
                   1 - (embedding <=> %s) AS score
            FROM faq_chunks
            WHERE model_name = %s AND source = %s
            ORDER BY embedding <=> %s
            LIMIT %s
            """,
            (vector, MODEL_NAME, "docs/faq.md", vector, top_k),
        ).fetchall()

    record_retrieval(rows)
    return rows


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="检索模拟店铺 FAQ")
    parser.add_argument("question", help="要检索的问题")
    args = parser.parse_args()

    print("正在加载本地模型并检索 FAQ……", flush=True)
    results = search_faq(args.question)

    if not results:
        print("没有检索到文档，请先运行 index_faq.py")

    for rank, item in enumerate(results, start=1):
        print(
            f"\n第 {rank} 条：{item['chunk_id']} "
            f"相似度={item['score']:.4f}"
        )
        print(
            f"来源：{item['source']} "
            f"行号：{item['start_line']}-{item['end_line']} "
            f"版本：{item['version']} "
            f"块编号：{item['chunk_no']}"
        )
        print(item["content"])
