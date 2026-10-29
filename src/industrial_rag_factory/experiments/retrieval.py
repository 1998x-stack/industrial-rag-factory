"""Actual indexing/retrieval experiments: fresh SQLite per chunk/overlap/seed.

Index contains all synthetic documents (the retrieval search corpus). Dev/test
LABELS never enter indexing or configuration selection. Test scores are
exploratory factorial comparisons; final config is selected only by dev.
"""
from __future__ import annotations

import random
import tempfile
from dataclasses import replace
from pathlib import Path

from industrial_rag_factory.config import Settings
from industrial_rag_factory.parsing import from_bytes
from industrial_rag_factory.pipeline import Pipeline

from .contracts import canonical_hash
from .stats import cluster_bootstrap_ci, paired_cluster_delta_ci


def _score(hits: list[str], correct: str, k: int) -> dict:
    ranked=list(dict.fromkeys(hits))[:k]
    rank=ranked.index(correct)+1 if correct in ranked else None
    return {"hit_at_k":int(rank is not None),
            "recall_at_k":int(rank is not None),
            "mrr_at_k":1/rank if rank is not None else 0.0,
            "ndcg_at_k":1/__import__("math").log2(rank+1) if rank is not None else 0.0}


def experiment(rows: list[dict], config: dict, *, settings: Settings | None = None,
               dataset_sha: str, resamples: int) -> dict:
    """Return per-case metrics, per-run metadata and DEV-chosen final TEST CI."""
    settings=replace(settings or Settings(),dense_backend="hashing",
                     generator="extractive",planner="rules",
                     security_mode="off",deepseek_api_key="")
    sources={}
    for row in rows:
        uri=row["source_uri"]
        if uri in sources and sources[uri]!=row["document_text"]:
            raise ValueError("Conflicting source content under same URI")
        sources[uri]=row["document_text"]
    runs=[]
    case_results={}
    for size in config["chunk_sizes"]:
        for overlap in config["overlaps"]:
            for seed in config["seeds"]:
                order=sorted(sources)
                random.Random(seed).shuffle(order)
                with tempfile.TemporaryDirectory(prefix="irf-stage07-") as tmp:
                    pipe=Pipeline(replace(settings,db_path=str(Path(tmp)/"index.sqlite3")))
                    try:
                        for uri in order:
                            doc=from_bytes(sources[uri].encode("utf-8"),uri,".md",
                                           tenant_id=settings.tenant_id,
                                           access_groups=settings.groups)
                            pipe.ingest(doc,max_tokens=size,overlap=overlap)
                        for mode in config["modes"]:
                            factor={"chunk_size":size,"overlap":overlap,
                                    "mode":mode,"seed":seed,
                                    "encoder":"hashing_lexical","k":config["k"]}
                            ident=canonical_hash({"factor":factor,"dataset":dataset_sha})[:16]
                            per_case=[]
                            for row in rows:
                                hits=pipe.retriever.search(row["question"],
                                    tenant=settings.tenant_id,groups=settings.groups,
                                    mode=mode,top_k=config["k"])
                                metrics=_score([x.source_uri for x in hits],
                                               row["source_uri"],config["k"])
                                per_case.append({"id":row["id"],"group_id":row["group_id"],
                                                 "split":row["split"],**metrics})
                            splits={}
                            for split in ("train","dev","test"):
                                selected=[x for x in per_case if x["split"]==split]
                                splits[split]={metric:sum(c[metric] for c in selected)/len(selected)
                                    for metric in ("hit_at_k","recall_at_k","mrr_at_k","ndcg_at_k")}
                                splits[split]["n"]=len(selected)
                            runs.append({"run_id":ident,"factor":factor,"metrics":splits})
                            case_results[ident]=per_case
                    finally:
                        pipe.close()
    # DEV selection is predetermined; never optimize hyperparameters on test.
    # The smallest seed determines a stable tie-break, not an extra dev vote.
    candidates=[x for x in runs if x["factor"]["seed"]==min(config["seeds"])]
    best=sorted(candidates,key=lambda x:(-x["metrics"]["dev"]["mrr_at_k"],
              -x["metrics"]["dev"]["recall_at_k"],x["factor"]["chunk_size"],
              x["factor"]["overlap"],x["factor"]["mode"]))[0]
    test=[x for x in case_results[best["run_id"]] if x["split"]=="test"]
    ci={metric:cluster_bootstrap_ci(test,metric,resamples=resamples,seed=202607)
        for metric in ("recall_at_k","mrr_at_k","ndcg_at_k")}
    # Pair the champion with a reference (same seed, chunking; sparse mode).
    baseline=next(x for x in runs if
                  x["factor"]=={**best["factor"],"mode":"sparse"})
    comparator=[x for x in case_results[baseline["run_id"]] if x["split"]=="test"]
    deltas={metric:paired_cluster_delta_ci(test,comparator,metric,
             resamples=resamples,seed=202608) for metric in ("recall_at_k","mrr_at_k")}
    # Detect order sensitivity, not pretend equal runs are independent sample sizes.
    siblings=[x for x in runs if all(x["factor"][key]==best["factor"][key]
              for key in ("chunk_size","overlap","mode"))]
    order_sensitive=any(
        x["metrics"]["test"]["mrr_at_k"]!=best["metrics"]["test"]["mrr_at_k"]
        for x in siblings)
    return {"runs":runs,"champion_dev_selected":best,
            "champion_test_ci":ci,"reference_sparse":baseline,
            "paired_delta_vs_sparse":deltas,
            "ingestion_order_sensitive":order_sensitive,
            "selection_rule":"max_dev_MRR_then_recall_then_smallest_factors",
            "caveat":"Tiny synthetic groups, lexical hashing, no tuned model. "
                     "CI is across source groups, NOT across model seeds."}
