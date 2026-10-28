"""Sparse/dense/hybrid retrieval and RRF. Only ranks accessible chunks."""
from __future__ import annotations
from dataclasses import replace
from .contracts import Hit
from .embedding import create_embedder
from .storage import Store, search_tokens


class Retriever:
    def __init__(self, store: Store, backend: str = "hashing", model: str = ""):
        self.store = store
        self.embedder = create_embedder(backend, model)

    def dense(self, question: str, tenant: str, groups: tuple[str, ...], k: int) -> list[Hit]:
        if self.embedder is None:
            return []
        query = self.embedder.encode([question])[0]
        results = []
        for hit, vector in self.store.vectors(tenant,groups,self.embedder.name):
            if len(vector) == len(query):
                results.append(replace(hit,score=sum(a*b for a,b in zip(query,vector))))
        return sorted(results,key=lambda x:x.score,reverse=True)[:k]

    def search(self, question: str, *, tenant: str, groups: tuple[str, ...],
               mode: str = "hybrid", top_k: int = 5) -> list[Hit]:
        if mode not in ("sparse","dense","hybrid"):
            raise ValueError("mode must be sparse, dense or hybrid")
        if not 1 <= top_k <= 50:
            raise ValueError("top_k out of range")
        if not question.strip():
            raise ValueError("query cannot be empty")
        if not tenant or not groups:
            raise ValueError("tenant and groups required")
        count = min(100,max(top_k*5,15))
        sparse = self.store.sparse(question,tenant,groups,count) if mode != "dense" else []
        dense = self.dense(question,tenant,groups,count) if mode != "sparse" else []
        if mode == "sparse":
            return sparse[:top_k]
        if mode == "dense":
            return dense[:top_k]
        combined: dict[str, tuple[Hit,float,set[str]]] = {}
        for channel,ranked in (("sparse",sparse),("dense",dense)):
            for position,hit in enumerate(ranked,1):
                key = hit.chunk.chunk_id
                previous = combined.get(key)
                score = (previous[1] if previous else 0) + 1/(60+position)
                channels = set(previous[2]) if previous else set()
                channels.add(channel)
                combined[key] = (hit,score,channels)
        # Stage 01 rerank: cheap lexical evidence tie-break; not a learned cross-encoder.
        query_terms = set(search_tokens(question))
        hits = []
        for hit,score,channels in combined.values():
            overlap = len(query_terms & set(search_tokens(hit.chunk.text)))
            hits.append(replace(hit,score=score+0.00001*overlap,
                                channels=tuple(sorted(channels))))
        return sorted(hits,key=lambda x:(-x.score,x.chunk.chunk_id))[:top_k]
