"""Reproducible S01 offline ablation factory; no LLM calls or external API charges."""
from __future__ import annotations

import hashlib
import json
import tempfile
from dataclasses import replace
from pathlib import Path

from .config import Settings
from .evaluation import evaluate_jsonl
from .parsing import from_bytes
from .pipeline import Pipeline
from .prompts import PROMPT_VERSION


def run_stage01_ablation(
    sources: dict[str, Path],
    gold_path: str | Path,
    *,
    settings: Settings | None = None,
    chunk_sizes: tuple[int, ...] = (100, 220, 400),
    overlaps: tuple[int, ...] = (0, 40),
    modes: tuple[str, ...] = ("sparse", "dense", "hybrid"),
    k: int = 5,
) -> dict:
    """Run an isolated DB for every chunking configuration, compare retrieval modes."""
    if not sources:
        raise ValueError("At least one source is required")
    if any(size <= overlap or size < 10 or overlap < 0
           for size in chunk_sizes for overlap in overlaps):
        raise ValueError("Every chunk/overlap combination must be valid")
    settings = settings or Settings()
    settings = replace(settings, generator="extractive", deepseek_api_key="")
    # Hash the exact supplied fixture bytes, source identifiers and gold file.
    fingerprint = hashlib.sha256()
    for uri, path in sorted(sources.items()):
        fingerprint.update(uri.encode())
        fingerprint.update(Path(path).read_bytes())
    fingerprint.update(Path(gold_path).read_bytes())
    dataset_sha = fingerprint.hexdigest()
    runs = []
    for max_tokens in chunk_sizes:
        for overlap in overlaps:
            with tempfile.TemporaryDirectory(prefix="irf-s01-") as tmpdir:
                experiment = Pipeline(replace(settings, db_path=str(Path(tmpdir)/"index.sqlite3")))
                try:
                    for uri, path in sorted(sources.items()):
                        path = Path(path)
                        document = from_bytes(
                            path.read_bytes(), uri, path.suffix,
                            tenant_id=settings.tenant_id, access_groups=settings.groups,
                        )
                        experiment.ingest(document,max_tokens=max_tokens,overlap=overlap)
                    for mode in modes:
                        metrics = evaluate_jsonl(
                            experiment, gold_path, tenant=settings.tenant_id,
                            groups=settings.groups, mode=mode,k=k
                        )
                        config = {
                            "chunk_size": max_tokens, "overlap": overlap,
                            "mode": mode, "k": k, "backend": settings.dense_backend,
                            "encoder": experiment.retriever.embedder.name
                            if experiment.retriever.embedder else "none",
                        }
                        run_hash = hashlib.sha256(
                            json.dumps(config,sort_keys=True).encode() + dataset_sha.encode()
                        ).hexdigest()[:16]
                        runs.append({
                            "run_id":run_hash,
                            "config":config,
                            "metrics":{key:metrics[key] for key in (
                                "n","recall_at_k","mrr_at_k","hit_rate_at_k"
                            )},
                        })
                finally:
                    experiment.close()
    return {
        "stage":"S01",
        "dataset_sha256":dataset_sha,
        "prompt_version":PROMPT_VERSION,
        "embedding_caveat":"hashing backend is lexical, not true semantic",
        "runs":runs,
    }
