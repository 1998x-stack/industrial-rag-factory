"""S01 end-to-end ingestion, retrieval, citation-labelled generation."""
from __future__ import annotations
import re
from .chunking import chunk_document
from .config import Settings
from .contracts import Answer, Document
from .embedding import create_embedder
from .llm import DeepSeekGenerator
from .retrieval import Retriever
from .storage import Store


class Pipeline:
    def __init__(self, settings: Settings, generator=None):
        self.settings = settings
        self.store = Store(settings.db_path)
        self.retriever = Retriever(self.store,settings.dense_backend,settings.dense_model)
        self.generator = generator
        if generator is None and settings.generator == "deepseek":
            self.generator = DeepSeekGenerator(settings.deepseek_api_key,
                                               settings.deepseek_base_url,
                                               settings.deepseek_model)

    def ingest(self, document: Document, max_tokens: int = 220, overlap: int = 40) -> dict:
        chunks = chunk_document(document,max_tokens,overlap)
        encoder = self.retriever.embedder
        vectors = encoder.encode([c.text for c in chunks]) if encoder and chunks else None
        self.store.ingest(document,chunks,vectors,encoder.name if encoder else None)
        return dict(document_id=document.document_id,chunks=len(chunks),sha256=document.sha256,
                    revision=document.revision,embedding=encoder.name if encoder else "disabled")

    def query(self, question: str, *, tenant: str, groups: tuple[str, ...],
              mode: str = "hybrid", top_k: int = 5) -> Answer:
        hits = self.retriever.search(question,tenant=tenant,groups=groups,mode=mode,top_k=top_k)
        if not hits:
            return Answer(question,"No accessible supporting evidence; unable to answer.",
                          "insufficient_evidence",())
        evidence = [(f"E{i}", f"{hit.title} | {hit.source_uri} | Rev {hit.revision} "
                                  f"| Section {hit.chunk.section_path}\n{hit.chunk.text}")
                    for i,hit in enumerate(hits,1)]
        if self.generator is None:
            # Offline smoke mode, not a generative answer and not truth verification.
            snippet = hits[0].chunk.text[:500]
            return Answer(question,f"Retrieved passage [E1]: {snippet}",
                          "retrieved_not_verified",tuple(hits),
                          ("Offline extractive baseline; no claim validation.",))
        try:
            generated = self.generator.generate(question,evidence)
            ids = generated["citation_ids"]
            allowed = {label for label,_ in evidence}
            if (not isinstance(ids,list) or not all(isinstance(i,str) for i in ids)
                    or any(i not in allowed for i in ids)):
                raise ValueError("Invalid or invented evidence citation")
            if generated["abstain"]:
                return Answer(question,generated["answer"],"insufficient_evidence",
                              tuple(hits),model=self.settings.deepseek_model)
            if not ids or not generated["answer"].strip():
                raise ValueError("Non-abstaining answer requires valid cited evidence")
            answer = generated["answer"] + "\nSources: " + ", ".join(f"[{i}]" for i in ids)
            return Answer(question,answer,"generated_citations_checked",tuple(hits),
                          ("Citation ID integrity checked; factual entailment not yet verified.",),
                          self.settings.deepseek_model)
        except (ValueError,KeyError,TypeError) as exc:
            return Answer(question,"Generator output failed citation or schema validation.",
                          "validation_failed",tuple(hits),(type(exc).__name__,),
                          self.settings.deepseek_model)

    def close(self):
        self.store.close()
