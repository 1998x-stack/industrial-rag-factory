"""Execute genuine public TechQA corpus retrieval and abstention evaluation.

No question label or 'is_impossible' field enters the index or the inference
policy. DEV selects cutoff, which is frozen before looking at TEST labels.
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

from .abstention import decide, metrics, tune


def evaluate_techqa(snapshot: dict, *, k: int = 3,
                    chunk_size: int = 380, overlap: int = 40) -> dict:
    if snapshot.get("dataset_id")!="nvidia/TechQA-RAG-Eval":
        raise ValueError("Unknown public TechQA data")
    docs=snapshot.get("docs")
    questions=snapshot.get("queries")
    if (not isinstance(docs,list) or not isinstance(questions,list)
        or not 6<=len(questions)<=250 or not 1<=len(docs)<=550
        or type(k) is not int or not 1<=k<=10
        or not 20<=overlap<chunk_size<=1000):
        raise ValueError("Invalid benchmark parameters")
    index_uris={d["source_uri"] for d in docs}
    if len(index_uris)!=len(docs):
        raise ValueError("Duplicate corpus source")
    for q in questions:
        if not set(q["context_uris"])<=index_uris:
            raise ValueError("Missing referenced index source")
    records=[]
    index_chunks=0
    elapsed_ingest=0.
    with tempfile.TemporaryDirectory(prefix="irf-techqa-") as folder:
        settings=replace(Settings(),db_path=str(Path(folder)/"index.sqlite3"),
                         tenant_id="techqa-public",groups=("techqa-test",),
                         dense_backend="hashing",generator="extractive",planner="rules")
        pipe=Pipeline(settings)
        try:
            for document in docs:
                started=time.perf_counter()
                original=from_bytes(document["text"].encode("utf-8"),
                    document["source_uri"],".md",revision=snapshot["revision"],
                    tenant_id="techqa-public",access_groups=("techqa-test",),
                    title=document["title"])
                result=pipe.ingest(original,max_tokens=chunk_size,overlap=overlap)
                index_chunks+=result["chunks"]
                elapsed_ingest+=time.perf_counter()-started
            for query in questions:
                started=time.perf_counter()
                hits=pipe.retriever.search(query["question"],
                    tenant="techqa-public",groups=("techqa-test",),
                    mode="sparse",top_k=min(50,max(k*10,20)))
                top_score=hits[0].score if hits else None
                seen=set()
                ranked=[]
                for hit in hits:
                    if hit.source_uri not in seen:
                        ranked.append(hit.source_uri)
                        seen.add(hit.source_uri)
                    if len(ranked)>=k:
                        break
                gold=set(query["context_uris"])
                positions=[i+1 for i,uri in enumerate(ranked) if uri in gold]
                records.append({
                    "id":query["id"],"group_id":query["group_id"],
                    "split":query["split"],"impossible":query["impossible"],
                    "top_score":top_score,"retrieved_sources":ranked,
                    "gold_source_count":len(gold),
                    "hit_at_k":float(bool(positions)) if gold else None,
                    "mrr_at_k":1/min(positions) if positions else
                               (0.0 if gold else None),
                    "latency_ms":round((time.perf_counter()-started)*1000,3),
                })
        finally:
            pipe.close()
    dev=[r for r in records if r["split"]=="dev"]
    test=[r for r in records if r["split"]=="test"]
    train=[r for r in records if r["split"]=="train"]
    calibration=tune(dev)
    threshold=calibration["threshold"]
    results={}
    for name,rows in (("train",train),("dev",dev),("test",test)):
        total=metrics(rows,threshold)
        positives=[r for r in rows if not r["impossible"]]
        total["answerable_retrieval_hit_at_k"]=(
            sum(r["hit_at_k"] for r in positives)/len(positives))
        total["answerable_mrr_at_k"]=(
            sum(r["mrr_at_k"] for r in positives)/len(positives))
        results[name]=total
    # Never give the evaluator's true impossible flag to the inference
    # function; it uses only finite score and DEV-frozen threshold.
    for row in records:
        row["predicted_answerable"]=decide(row["top_score"],threshold)
    return {"stage":"S10","dataset_id":snapshot["dataset_id"],
            "revision":snapshot["revision"],
            "raw_sha256":snapshot["raw_sha256"],
            "snapshot_sha256":hashlib.sha256(
                json.dumps(snapshot,sort_keys=True,ensure_ascii=False,
                           separators=(",",":")).encode("utf-8")).hexdigest(),
            "corpus_docs":len(docs),"index_chunks":index_chunks,
            "queries":len(questions),"unjudged_extra_docs":
                snapshot.get("unjudged_extra_docs",0),
            "ingest_duration_ms":round(elapsed_ingest*1000,3),
            "threshold":calibration,
            "evaluation":results,
            "cases":records,
            "limitations":[
                "TechQA is genuine IT support text, not MES/OT equipment data.",
                "Threshold is tuned on DEV only, not deployable confidence calibration.",
                "Gold is_impossible labels are used only after retrieval for scoring.",
                "A predicted answerable query is never a verified factual answer.",
                "Scores, cutoffs and quality are corpus/FTS implementation dependent.",
                "Negative labels may be imperfect, and context qrels incomplete.",
                "Question-associated contexts and extra unjudged documents limit external validity.",
                "No model-generated text, operational actions, paid DeepSeek or real OT controls.",
            ]}
