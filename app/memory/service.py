import json

from .chunking import make_chunks, payload_hash
from .embeddings import validate_vectors
from .errors import PayloadTooLarge
from .retrieval import evidence, keyword_terms, rank
from .schemas import AddResponse, SearchResponse


class MemoryService:
    def __init__(self, config, store, embeddings):
        self.config, self.store, self.embeddings = config, store, embeddings

    def check_size(self, request):
        if len(json.dumps(request.model_dump(), ensure_ascii=False).encode()) > self.config.max_bytes:
            raise PayloadTooLarge("memory_payload_too_large")

    def add(self, request):
        self.check_size(request)
        digest = payload_hash(request)
        if not self.store.existing(request, digest):
            chunks = make_chunks(request, self.config)
            texts = []
            for chunk in chunks:
                message = request.messages[chunk["ordinal"]]
                prefix = f"role={message.role}; source_timestamp_ms={message.timestamp}\n"
                texts.append(prefix + chunk["content"])
            vectors = validate_vectors(self.embeddings.encode(texts),
                                       len(chunks), self.config.dimension)
            self.store.commit(request, digest, chunks, vectors)
        return AddResponse(request_id=request.request_id, user_id=request.user_id, session_id=request.session_id)

    def search(self, request):
        self.check_size(request)
        vector = validate_vectors([self.embeddings.query(request.query)], 1, self.config.dimension)[0]
        hybrid = self.config.retrieval == "hybrid"
        limit = max(200, request.top_k * 2) if hybrid else request.top_k
        rows, lexical = self.store.candidates(request.user_id, vector, limit,
                                              keyword_terms(request.query) if hybrid else None)
        # options are accepted, never copied into stored evidence or used as an answer.
        return SearchResponse(data=[evidence(row) for row in rank(rows, lexical, request.top_k, hybrid)])
