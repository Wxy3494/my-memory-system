import hashlib
import json
import os
from dataclasses import dataclass, field
from urllib.parse import urlparse

from .errors import MemoryError

CHUNKER_VERSION = "utf8-budget-v1"


@dataclass(frozen=True)
class MemoryConfig:
    database_url: str = field(repr=False)
    api_key: str = field(repr=False)
    embedding_key: str = field(repr=False)
    base_url: str = ""
    model: str = "text-embedding-v4"
    dimension: int = 1024
    pipeline_version: str = "v0"
    target: int = 400
    overlap: int = 60
    retrieval: str = "vector"
    max_bytes: int = 8 * 1024 * 1024
    max_chunks: int = 20000
    timeout: float = 30
    probe_ttl: int = 900
    neighbor_window: int = 0
    seed_limit: int = 20
    evidence_bytes: int = 0
    min_similarity: float | None = None
    contextual: bool = False
    context_limit: int = 48
    link_hops: int = 2
    signal_scan_limit: int = 5000

    @classmethod
    def from_env(cls):
        try:
            value = cls(
                database_url=os.getenv("DATABASE_URL", ""),
                api_key=os.getenv("MEMORY_API_KEY", ""),
                embedding_key=os.getenv("MEMORY_EMBEDDING_API_KEY", ""),
                base_url=os.getenv("MEMORY_EMBEDDING_BASE_URL", "").rstrip("/"),
                model=os.getenv("MEMORY_EMBEDDING_MODEL", "text-embedding-v4"),
                dimension=int(os.getenv("MEMORY_EMBEDDING_DIM", "1024")),
                pipeline_version=os.getenv("MEMORY_PIPELINE_VERSION", "v0"),
                target=int(os.getenv("MEMORY_CHUNK_TARGET_BYTES", os.getenv("MEMORY_CHUNK_TARGET_TOKENS", "400"))),
                overlap=int(os.getenv("MEMORY_CHUNK_OVERLAP_BYTES", os.getenv("MEMORY_CHUNK_OVERLAP_TOKENS", "60"))),
                retrieval=os.getenv("MEMORY_RETRIEVAL_MODE", "vector"),
                max_bytes=int(os.getenv("MEMORY_MAX_PAYLOAD_BYTES", str(8 * 1024 * 1024))),
                max_chunks=int(os.getenv("MEMORY_MAX_CHUNKS_PER_ADD", "20000")),
                timeout=float(os.getenv("MEMORY_EMBEDDING_TIMEOUT_SECONDS", "30")),
                probe_ttl=int(os.getenv("MEMORY_PROBE_TTL_SECONDS", "900")),
                neighbor_window=int(os.getenv("MEMORY_NEIGHBOR_WINDOW", "0")),
                seed_limit=int(os.getenv("MEMORY_SEED_LIMIT", "20")),
                evidence_bytes=int(os.getenv("MEMORY_EVIDENCE_BYTES", "0")),
                min_similarity=(float(os.environ["MEMORY_MIN_SIMILARITY"])
                                if os.getenv("MEMORY_MIN_SIMILARITY") else None),
                contextual=os.getenv("MEMORY_CONTEXTUAL_RETRIEVAL","0")=="1",
                context_limit=int(os.getenv("MEMORY_CONTEXT_LIMIT","48")),
                link_hops=int(os.getenv("MEMORY_LINK_HOPS","2")),
                signal_scan_limit=int(os.getenv("MEMORY_SIGNAL_SCAN_LIMIT","5000")),
            )
            parsed = urlparse(value.base_url)
            if (not all((value.database_url, value.api_key, value.embedding_key, value.base_url))
                    or value.model != "text-embedding-v4" or value.dimension != 1024
                    or not value.pipeline_version or not 32 <= value.target <= 4096
                    or not 0 <= value.overlap < value.target // 2
                    or value.retrieval not in ("vector", "hybrid", "bm25", "hybrid_bm25")
                    or not 0 <= value.neighbor_window <= 5 or not 1 <= value.seed_limit <= 100
                    or value.evidence_bytes < 0
                    or os.getenv("MEMORY_CONTEXTUAL_RETRIEVAL","0") not in ("0","1")
                    or not 8 <= value.context_limit <= 100 or not 0 <= value.link_hops <= 3
                    or not 100 <= value.signal_scan_limit <= 20000
                    or (value.min_similarity is not None and not -1 <= value.min_similarity <= 1)
                    or value.max_bytes < 1024 or value.max_chunks < 1
                    or not 1 <= value.timeout <= 300 or not 30 <= value.probe_ttl <= 86400
                    or parsed.scheme != "https" or not parsed.netloc
                    or parsed.username or parsed.password or parsed.query or parsed.fragment):
                raise ValueError()
            return value
        except (ValueError, TypeError):
            raise MemoryError("memory_configuration_invalid") from None

    @property
    def signature(self):
        # Credential rotation is allowed; embedding space and chunk semantics are immutable.
        data = [self.base_url, self.model, self.dimension, self.pipeline_version, "source-prefix-v1",
                CHUNKER_VERSION, self.target, self.overlap]
        return hashlib.sha256(json.dumps(data, ensure_ascii=False).encode()).hexdigest()
