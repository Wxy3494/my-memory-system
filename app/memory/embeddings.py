import math
import threading
import time

import httpx
from prometheus_client import Counter

from .chunking import split_text
from .errors import MemoryError

TOKENS = Counter("memory_embedding_tokens_total", "Provider-reported embedding tokens")
CALLS = Counter("memory_embedding_calls_total", "Embedding requests", ["result"])
_probes = {}
_lock = threading.Lock()


def record_probe(config, ok):
    with _lock:
        _probes[config.signature] = (time.monotonic(), ok)


def upstream_status(config):
    with _lock:
        value = _probes.get(config.signature)
    if value is None or time.monotonic() - value[0] > config.probe_ttl:
        return "not_probed_or_expired"
    return "ok" if value[1] else "unavailable"


def validate_vectors(vectors, count, dimension):
    if not isinstance(vectors, list) or len(vectors) != count:
        raise MemoryError("embedding_invalid_response")
    normalized = []
    for vector in vectors:
        if (not isinstance(vector, list) or len(vector) != dimension
                or any(isinstance(v, bool) or not isinstance(v, (int, float))
                       or not math.isfinite(v) for v in vector)):
            raise MemoryError("embedding_invalid_response")
        # hypot avoids overflow in normalization of large but finite values.
        norm = math.hypot(*vector)
        if not math.isfinite(norm) or norm == 0:
            raise MemoryError("embedding_invalid_response")
        normalized.append([v / norm for v in vector])
    return normalized


class Embeddings:
    def __init__(self, config):
        self.config = config

    def encode(self, texts):
        output = []
        try:
            with httpx.Client(timeout=self.config.timeout, follow_redirects=False) as client:
                for start in range(0, len(texts), 10):
                    batch = texts[start:start + 10]
                    response = None
                    for attempt in range(3):
                        try:
                            response = client.post(self.config.base_url + "/embeddings",
                                headers={"Authorization": "Bearer " + self.config.embedding_key},
                                json={"model": self.config.model, "input": batch,
                                      "dimensions": self.config.dimension, "encoding_format": "float"})
                            if response.status_code != 429 and response.status_code < 500:
                                break
                        except (httpx.TimeoutException, httpx.NetworkError):
                            if attempt == 2:
                                raise MemoryError("embedding_unavailable") from None
                        if attempt < 2:
                            time.sleep(0.5 * 2 ** attempt)
                    if response is None or response.status_code != 200:
                        raise MemoryError("embedding_unavailable")
                    body = response.json()
                    data = body["data"]
                    indices = [item["index"] for item in data]
                    if (any(type(i) is not int for i in indices)
                            or sorted(indices) != list(range(len(batch)))):
                        raise MemoryError("embedding_invalid_response")
                    ordered = [item["embedding"] for item in sorted(data, key=lambda row: row["index"])]
                    output.extend(validate_vectors(ordered, len(batch), self.config.dimension))
                    tokens = body.get("usage", {}).get("total_tokens", 0)
                    if type(tokens) is int and tokens >= 0:
                        TOKENS.inc(tokens)
                    CALLS.labels("ok").inc()
            record_probe(self.config, True)
            return output
        except Exception as exc:
            record_probe(self.config, False)
            CALLS.labels("failed").inc()
            if isinstance(exc, MemoryError):
                raise
            raise MemoryError("embedding_invalid_response") from None

    def query(self, text):
        # Long questions are represented in full; never truncate to the first 2000 chars.
        pieces = list(split_text(text, 4096, 0))
        vectors = self.encode([piece.content for piece in pieces])
        weights = [len(piece.content.encode()) for piece in pieces]
        total = sum(weights)
        mean = [sum(v[i] * w / total for v, w in zip(vectors, weights))
                for i in range(self.config.dimension)]
        return validate_vectors([mean], 1, self.config.dimension)[0]
