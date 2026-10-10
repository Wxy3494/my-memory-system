import json

from .chunking import make_chunks, payload_hash
from .embeddings import validate_vectors
from .errors import PayloadTooLarge
from .retrieval import expand_neighbors, keyword_terms, rank, select_evidence,combine_context
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
        return self.search_debug(request)[0]

    def search_debug(self, request):
        """Internal diagnostics for synthetic evaluators; HTTP only returns raw evidence."""
        self.check_size(request)
        trace={"contextual_enabled":self.config.contextual}
        # Pure lexical Search needs no model call. Add still embeds stored chunks.
        needs_vector = self.config.retrieval != "bm25" or self.config.min_similarity is not None
        vector = (validate_vectors([self.embeddings.query(request.query)], 1, self.config.dimension)[0]
                  if needs_vector else None)
        hybrid = self.config.retrieval in ("hybrid", "hybrid_bm25")
        limit = max(200, request.top_k * 2) if hybrid else request.top_k
        rows, lexical = self.store.candidates(request.user_id, vector, limit,
                                              keyword_terms(request.query) if self.config.retrieval != "vector" else None)
        # Optional DEV-calibrated gate on genuine cosine scores, never on RRF/BM25.
        # Gate the question, not each hop: supporting evidence may have low similarity.
        threshold = self.config.min_similarity
        if threshold is not None and (not rows or max(row["score"] for row in rows) < threshold):
            return SearchResponse(data=[]),dict(trace,gate="rejected")
        selected = lexical[:request.top_k] if self.config.retrieval == "bm25" else rank(rows, lexical, request.top_k, hybrid)
        prefix=[]
        if self.config.contextual:
            base=selected
            if self.config.neighbor_window:
                direct=selected[:self.config.seed_limit]
                base=expand_neighbors(direct,self.store.neighbors(request.user_id,direct,self.config.neighbor_window,
                    keyword_terms(request.query)),self.config.neighbor_window,request.top_k,self.config.evidence_bytes)
            prefix=base[:min(5,request.top_k)]
            context,trace=self.store.contextual_candidates(request.user_id,request.query,selected[:self.config.seed_limit])
            # Context parents each get one slot before additional slices. Keep eight
            # initial direct seeds; preserve all raw sources and only rerank locally.
            selected=combine_context(selected,context)
            ordered,seen=[],set()
            for row in prefix+selected:
                if row["chunk_id"] not in seen:
                    ordered.append(dict(row,score=1/(len(ordered)+1))); seen.add(row["chunk_id"])
            selected=ordered
        if self.config.neighbor_window:
            seeds = selected[:max(self.config.seed_limit,self.config.context_limit) if self.config.contextual else self.config.seed_limit]
            selected = expand_neighbors(seeds, self.store.neighbors(request.user_id, seeds,
                                        self.config.neighbor_window, keyword_terms(request.query)), self.config.neighbor_window,
                                        request.top_k, self.config.evidence_bytes)
        if prefix:
            # Prefix rows were reserved as seeds above, so reordering cannot add bytes.
            ordered,seen=[],set()
            for row in prefix+selected:
                if row["chunk_id"] not in seen:
                    ordered.append(dict(row,score=1/(len(ordered)+1))); seen.add(row["chunk_id"])
            selected=ordered[:request.top_k]
        # options are accepted, never copied into stored evidence or used as an answer.
        return SearchResponse(data=select_evidence(selected, request.top_k, self.config.evidence_bytes)),trace
