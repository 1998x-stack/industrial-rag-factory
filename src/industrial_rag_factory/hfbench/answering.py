"""Optional Stage 09 RAG generation smoke; no claims of independent entailment.

Only trusted opt-in applications may pass a paid model client. No secrets or
model output bodies are written to benchmark reports.
"""
from __future__ import annotations

import time
import tempfile
from collections import Counter
from dataclasses import replace
from pathlib import Path

from industrial_rag_factory.config import Settings
from industrial_rag_factory.parsing import from_bytes
from industrial_rag_factory.pipeline import Pipeline


def evaluate_generation(snapshot: dict, *, generator=None,
                        max_test_cases: int = 3, mode: str = "sparse",
                        k: int = 3) -> dict:
    """Perform actual Stage01 query/generate/citation validation on public rows.

    A caller-provided generator is supported for offline tests. Without a
    generator a real DeepSeek key and explicit opt-in are mandatory.
    """
    if (type(max_test_cases) is not int or not 1<=max_test_cases<=5 or
        mode not in ("sparse","hybrid") or not 1<=k<=5 or
        snapshot.get("dataset_id")!="alibaba-multimodal-industrial-ai/IndustryBench"):
        raise ValueError("Invalid generation trial configuration")
    test=[q for q in snapshot["queries"] if q["split"]=="test"][:max_test_cases]
    if not test:
        raise ValueError("No held-out test cases")
    if generator is None:
        from industrial_rag_factory.llm import DeepSeekGenerator
        settings=Settings.from_env()
        if not settings.deepseek_api_key:
            raise RuntimeError("DEEPSEEK_API_KEY required for explicit generation")
        generator=DeepSeekGenerator(settings.deepseek_api_key,settings.deepseek_base_url,
                                    settings.deepseek_model)
    counts=Counter()
    cases=[]
    with tempfile.TemporaryDirectory(prefix="irf-stage09-generation-") as folder:
        settings=replace(Settings(),db_path=str(Path(folder)/"index.sqlite3"),
                         tenant_id="hf-public",groups=("hf-benchmark",),
                         dense_backend="hashing",generator="extractive")
        pipeline=Pipeline(settings,generator=generator)
        try:
            for row in snapshot["documents"]:
                doc=from_bytes(row["text"].encode("utf-8"),row["source_uri"],".md",
                               revision=snapshot["revision"],tenant_id="hf-public",
                               access_groups=("hf-benchmark",))
                pipeline.ingest(doc,max_tokens=500,overlap=60)
            for row in test:
                started=time.perf_counter()
                answer=pipeline.query(row["question"],tenant="hf-public",
                                      groups=("hf-benchmark",),mode=mode,top_k=k)
                counts[answer.status]+=1
                cases.append({"id":row["id"],"status":answer.status,
                    "latency_ms":round((time.perf_counter()-started)*1000,3),
                    "citations_checked":answer.status=="generated_citations_checked",
                    "evidence_sources":len(answer.evidence)})
        finally:
            pipeline.close()
    return {"mode":mode,"generator":"injected_mock" if hasattr(generator,"_hf_mock")
            else "opt_in_external_provider","cases":cases,"status_counts":dict(counts),
            "max_test_cases":max_test_cases,
            "limitations":["Generated responses are not included in reports.",
                           "Citation ID checks do not guarantee factual entailment.",
                           "This is not a paid model accuracy or operational safety assessment.",
                           "Token usage and provider billing are not measured by this helper."]}
