"""Actual Stage 01→ retrieval → cited evidence → safe abstention on public data.

The Stage 05 numeric batch verifier is NOT re-used for public textual facts:
its trusted MES/spec/measurement conditions are not available on HF data.
"""
from __future__ import annotations

import hashlib
import json
import tempfile
import time
from dataclasses import replace
from pathlib import Path

from industrial_rag_factory.config import Settings
from industrial_rag_factory.parsing import from_bytes
from industrial_rag_factory.pipeline import Pipeline

from .metrics import score, summarize


def _normal(text: str) -> str:
    return " ".join(text.lower().split())


def evaluate_benchmark(snapshot: dict, *, modes: tuple[str,...] = ("sparse","hybrid"),
                       k: int = 5, chunk_size: int = 500,
                       overlap: int = 60, resamples: int = 300) -> dict:
    if snapshot.get("dataset_id")!="alibaba-multimodal-industrial-ai/IndustryBench":
        raise ValueError("Untrusted benchmark source")
    docs=snapshot.get("documents")
    queries=snapshot.get("queries")
    if (not isinstance(docs,list) or not isinstance(queries,list) or
        not 12<=len(queries)<=600 or not 1<=len(docs)<=600 or
        not set(modes)<={"sparse","hybrid","dense"} or
        not modes or not 1<=k<=10 or not 20<=overlap<chunk_size<=1500):
        raise ValueError("Invalid benchmark bounds")
    if len({d["source_uri"] for d in docs})!=len(docs):
        raise ValueError("Duplicate evidence document URI")
    known={d["source_uri"] for d in docs}
    for q in queries:
        if q["gold_source_uri"] not in known:
            raise ValueError("Gold qrel has no indexed source")
    records={}
    ingest=[]
    with tempfile.TemporaryDirectory(prefix="irf-public-hfbench-") as temp:
        settings=replace(Settings(),db_path=str(Path(temp)/"benchmark.sqlite3"),
                         dense_backend="hashing",generator="extractive",planner="rules",
                         tenant_id="hf-public",groups=("hf-benchmark",))
        pipeline=Pipeline(settings)
        try:
            for d in docs:
                start=time.perf_counter()
                document=from_bytes(d["text"].encode("utf-8"),d["source_uri"],
                       ".md",revision=snapshot["revision"],tenant_id="hf-public",
                       access_groups=("hf-benchmark",),title=d["title"])
                info=pipeline.ingest(document,max_tokens=chunk_size,overlap=overlap)
                ingest.append({"sha256":document.sha256,"chunks":info["chunks"],
                               "duration_ms":round((time.perf_counter()-start)*1000,3)})
            for mode in modes:
                per_case=[]
                for query in queries:
                    started=time.perf_counter()
                    hits=pipeline.retriever.search(
                        query["question"],tenant="hf-public",groups=("hf-benchmark",),
                        mode=mode,top_k=k)
                    delay=(time.perf_counter()-started)*1000
                    unique=list(dict.fromkeys(x.source_uri for x in hits))
                    metrics=score(unique,{query["gold_source_uri"]},k)
                    citation_candidates=[{"evidence_id":f"E{i}","source_uri":h.source_uri,
                        "revision":h.revision,"chunk_id":h.chunk.chunk_id}
                        for i,h in enumerate(hits[:k],1)]
                    # Answer isn't generated. Benchmark textual answer and
                    # citation candidates are assessed only for surface coverage.
                    # Never claim semantic entailment from substring overlap.
                    gold=_normal(query["answer"])
                    excerpt_coverage=bool(gold and any(gold in _normal(h.chunk.text)
                                                         for h in hits))
                    per_case.append({
                        "id":query["id"],"group_id":query["group_id"],
                        "split":query["split"],"industry":query["industry"],
                        "capability":query["capability"],**metrics,
                        "query_latency_ms":round(delay,3),
                        "retrieved_source_uris":unique,
                        "citation_candidates":citation_candidates,
                        "answer_literal_in_retrieved_chunks":excerpt_coverage,
                        "grounding_status":"retrieved_not_verified" if hits
                                            else "insufficient_evidence",
                    })
                records[mode]={"scores":summarize(per_case,resamples=resamples),
                               "cases":per_case}
        finally:
            pipeline.close()
    return {
        "stage":"S09",
        "dataset_id":snapshot["dataset_id"],
        "source_revision":snapshot["revision"],
        "source_file_sha256":snapshot["raw_sha256"],
        "license_tag":snapshot["license_tag"],
        "snapshot_sha256":hashlib.sha256(
            json.dumps(snapshot,sort_keys=True,ensure_ascii=False,
                       separators=(",",":")).encode("utf-8")).hexdigest(),
        "corpus_docs":len(docs),"queries":len(queries),
        "chunk_size":chunk_size,"overlap":overlap,"k":k,
        "index_chunks":sum(x["chunks"] for x in ingest),
        "index_duration_ms_sum":round(sum(x["duration_ms"] for x in ingest),3),
        "modes":records,
        "limitations":[
            "Real public benchmark rows, not real-world operational measurements or source authenticity.",
            "Benchmark knowledge_text may overlap its corresponding gold answer; positive retrieval is not independently annotated.",
            "Citation IDs verify reference identity only, not truth or entailment.",
            "Literal answer coverage checks string matching, not semantic correctness.",
            "No independent verifier/ClaimGraph physical-fact verdict on benchmark text.",
            "Hashing dense baseline is lexical, not a pretrained semantic embedding.",
            "No DeepSeek generation call or token billing in this offline test.",
            "Source documents are indexed across all splits; only questions/labels are held out.",
        ],
    }
