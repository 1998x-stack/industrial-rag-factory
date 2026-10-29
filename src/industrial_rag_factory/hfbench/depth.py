"""S12 reranker candidate-depth ablation on a fixed public snapshot.

Each depth executes a fresh real Stage11 retrieval pass, so measured p95
includes its actual CrossEncoder workload, not predicted or simulated costs.
Depth comparisons are exploratory TEST contrasts, never TEST-driven tuning.
"""
from __future__ import annotations

import hashlib
import json

from industrial_rag_factory.experiments.stats import paired_cluster_delta_ci

from .stage11 import evaluate_stage11


def benchmark_depths(snapshot: dict, encoder, reranker, *,
                     depths: tuple[int,...] = (4,8,12), k: int = 3) -> dict:
    if (not depths or len(depths)>4 or len(set(depths))!=len(depths)
        or any(type(x) is not int or not k<=x<=24 for x in depths)
        or type(k) is not int or not 1<=k<=5):
        raise ValueError("Invalid bounded candidate-depth protocol")
    runs={}
    for depth in depths:
        report=evaluate_stage11(snapshot,encoder=encoder,reranker=reranker,
                                 k=k,candidates=depth,bootstrap_resamples=100)
        lane=report["lanes"]["hybrid_reranked"]
        runs[str(depth)]={
            "depth":depth,"test":lane["splits"]["test"],
            "dev_threshold":lane["threshold"]["threshold"],
            "test_cases":[{
                "id":row["id"],"group_id":row["group_id"],
                "mrr":float(row["mrr_at_k"] or 0.)
            } for row in lane["cases"] if row["split"]=="test"
                  and not row["impossible"]],
            "index_ms":report["stage01_index_ms"],
            "embedding_ms":report["pretrained_embed_ms"],
        }
    baseline=runs[str(min(depths))]["test_cases"]
    comparison={}
    for depth in depths:
        if depth==min(depths):
            continue
        comparison[str(depth)]=paired_cluster_delta_ci(
            runs[str(depth)]["test_cases"],baseline,"mrr",
            resamples=200,seed=1208)
    return {"stage":"S12","experiment":"real_rerank_depth_ablation",
            "dataset_revision":snapshot["revision"],
            "snapshot_sha256":hashlib.sha256(json.dumps(
                snapshot,sort_keys=True,ensure_ascii=False,
                separators=(",",":")).encode()).hexdigest(),
            "depths":list(depths),"k":k,"runs":runs,
            "paired_test_mrr_vs_min_depth":comparison,
            "limitations":[
                "Each depth independently reindexes/re-embeds same public corpus.",
                "Actual model inference timings on tiny CPU sample only.",
                "TEST values are exploratory; no test-driven model selection.",
                "No independently annotated hard relevance judgments.",
                "English CrossEncoder transfer to multilingual industrial text is not certified.",
                "Model download and startup not included in per-query p95.",
            ]}
