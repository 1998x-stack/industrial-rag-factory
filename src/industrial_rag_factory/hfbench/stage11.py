"""Paired real public retrieval lanes: sparse, dense, RRF, reranked-RRF.

The same Stage01 FTS indexing and TechQA frozen query/label manifest feed
every lane. Gold labels are accessed only AFTER candidate scoring. Reranker
is an English MS MARCO model; multilingual transfer is NOT established.
"""
from __future__ import annotations

import hashlib
import json
import math
import tempfile
import time
from collections import defaultdict
from dataclasses import replace
from pathlib import Path

from industrial_rag_factory.config import Settings
from industrial_rag_factory.experiments.stats import paired_cluster_delta_ci
from industrial_rag_factory.parsing import from_bytes
from industrial_rag_factory.pipeline import Pipeline

from .abstention import metrics, tune

LANES=("sparse","dense","hybrid","hybrid_reranked")


def percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered=sorted(values)
    pos=(len(ordered)-1)*fraction
    lo=int(pos)
    return round(ordered[lo]*(1-(pos-lo))+
                 ordered[min(lo+1,len(ordered)-1)]*(pos-lo),3)


def _dense_scores(query: str, chunks: list[tuple[str,str,str]],
                  vectors, encoder) -> list[tuple[str,float]]:
    q=encoder.encode([query],normalize_embeddings=True)
    # Work with Python list or NumPy array, without adding dependency to
    # the lightweight offline test lane.
    query_vector=list(q[0])
    values=[]
    for (chunk_id,source_uri,_),vector in zip(chunks,vectors):
        score=sum(float(x)*float(y) for x,y in zip(query_vector,vector))
        values.append((chunk_id,source_uri,score))
    values.sort(key=lambda x:(-x[2],x[0]))
    return [(id,score) for id,_,score in values]


def _fusion(sparse: list[str],dense: list[str]) -> list[tuple[str,float]]:
    scores=defaultdict(float)
    for ranked in (sparse,dense):
        for rank,cid in enumerate(ranked,1):
            scores[cid]+=1/(60+rank)
    return sorted(scores.items(),key=lambda x:(-x[1],x[0]))


def evaluate_stage11(snapshot: dict, *, encoder=None, reranker=None,
                     k: int = 3, candidates: int = 12,
                     max_doc_chars: int = 3500,
                     chunk_size: int = 360, overlap: int = 40,
                     bootstrap_resamples: int = 200) -> dict:
    if snapshot.get("dataset_id")!="nvidia/TechQA-RAG-Eval":
        raise ValueError("Unexpected public dataset")
    documents=snapshot.get("docs")
    questions=snapshot.get("queries")
    if (not isinstance(documents,list) or not isinstance(questions,list)
        or not 6<=len(questions)<=250 or not 1<=len(documents)<=550
        or type(k) is not int or not 1<=k<=10 or
        type(candidates) is not int or not k<=candidates<=30
        or type(max_doc_chars) is not int or not 500<=max_doc_chars<=5000
        or not 20<=overlap<chunk_size<=900
        or not 100<=bootstrap_resamples<=500):
        raise ValueError("Stage11 benchmark budget exceeded")
    known={x["source_uri"] for x in documents}
    if len(known)!=len(documents):
        raise ValueError("Duplicated source URI")
    if any(not set(q["context_uris"])<=known for q in questions):
        raise ValueError("Missing relevant source in indexed snapshot")
    if (encoder is None)!=(reranker is None):
        raise ValueError("Encoder and reranker must be provided together")
    lanes=LANES if encoder is not None else ("sparse",)
    index_ms=0.
    query_records={name:[] for name in lanes}
    with tempfile.TemporaryDirectory(prefix="irf-s11-") as folder:
        settings=replace(Settings(),db_path=str(Path(folder)/"index.sqlite3"),
                         dense_backend="none",generator="extractive",planner="rules",
                         tenant_id="techqa-public",groups=("techqa-benchmark",))
        pipe=Pipeline(settings)
        try:
            for doc in documents:
                t=time.perf_counter()
                parsed=from_bytes(doc["text"][:max_doc_chars].encode("utf-8"),
                                  doc["source_uri"],".md",
                                  revision=snapshot["revision"],
                                  tenant_id="techqa-public",
                                  access_groups=("techqa-benchmark",),
                                  title=doc["title"])
                pipe.ingest(parsed,max_tokens=chunk_size,overlap=overlap)
                index_ms+=(time.perf_counter()-t)*1000
            db=pipe.store.con
            chunks=[(r["chunk_id"],r["source_uri"],r["text"])
                    for r in db.execute("""
                SELECT c.chunk_id,d.source_uri,c.text FROM chunks c
                JOIN documents d ON d.document_id=c.document_id
                WHERE d.tenant_id='techqa-public' AND d.active=1
                ORDER BY c.chunk_id
                """)]
            if not chunks or len(chunks)>600:
                raise ValueError("Too many or empty chunks for bounded CPU experiment")
            chunk_by_id={c[0]:c for c in chunks}
            vectors=None
            embed_ms=0.
            if encoder:
                t=time.perf_counter()
                vectors=encoder.encode([c[2] for c in chunks],
                                       batch_size=16,normalize_embeddings=True)
                embed_ms=(time.perf_counter()-t)*1000
                if len(vectors)!=len(chunks):
                    raise ValueError("Encoder emitted wrong vector count")
            for q in questions:
                question=q["question"]
                t=time.perf_counter()
                sparse_hits=pipe.retriever.search(
                    question,tenant="techqa-public",groups=("techqa-benchmark",),
                    mode="sparse",top_k=min(50,max(candidates*3,20)))
                sparse=[(h.chunk.chunk_id,float(h.score)) for h in sparse_hits]
                sparse_ms=(time.perf_counter()-t)*1000
                dense=[]
                dense_ms=0.
                if encoder:
                    t=time.perf_counter()
                    dense=_dense_scores(question,chunks,vectors,encoder)[:50]
                    dense_ms=(time.perf_counter()-t)*1000
                sequences={
                    "sparse":(sparse,sparse_ms),
                }
                if encoder:
                    fused=_fusion([cid for cid,_ in sparse],
                                  [cid for cid,_ in dense])
                    sequences.update({
                        "dense":(dense,dense_ms),
                        "hybrid":(fused,sparse_ms+dense_ms),
                    })
                    selected=fused[:candidates]
                    t=time.perf_counter()
                    predictions=reranker.predict(
                        [(question,chunk_by_id[cid][2]) for cid,_ in selected],
                        batch_size=8,show_progress_bar=False)
                    if len(predictions)!=len(selected):
                        raise ValueError("Reranker returned incomplete scores")
                    rescored=[]
                    for (cid,_),value in zip(selected,predictions):
                        score=float(value)
                        if not math.isfinite(score):
                            raise ValueError("Non-finite reranker prediction")
                        rescored.append((cid,score))
                    rescored.sort(key=lambda x:(-x[1],x[0]))
                    sequences["hybrid_reranked"]=(rescored,
                        sparse_ms+dense_ms+(time.perf_counter()-t)*1000)
                for name,(items,latency) in sequences.items():
                    ranked=[]
                    seen=set()
                    for cid,score in items:
                        source=chunk_by_id[cid][1]
                        if source not in seen:
                            seen.add(source)
                            ranked.append((source,float(score)))
                        if len(ranked)>=k:
                            break
                    refs=set(q["context_uris"])
                    positions=[i+1 for i,(uri,_) in enumerate(ranked) if uri in refs]
                    query_records[name].append({
                        "id":q["id"],"group_id":q["group_id"],
                        "split":q["split"],"impossible":q["impossible"],
                        "top_score":float(items[0][1]) if items else None,
                        "hit_at_k":float(bool(positions)) if refs else None,
                        "mrr_at_k":1/min(positions) if positions else
                                    (0. if refs else None),
                        "latency_ms":round(latency,3),
                        "retrieved_source_uris":[x[0] for x in ranked],
                    })
        finally:
            pipe.close()
    evaluations={}
    for name,rows in query_records.items():
        dev=[r for r in rows if r["split"]=="dev"]
        cutoff=tune(dev)
        splits={}
        for split in ("train","dev","test"):
            sub=[r for r in rows if r["split"]==split]
            values=metrics(sub,cutoff["threshold"])
            positives=[r for r in sub if not r["impossible"]]
            if not positives:
                raise ValueError("Split missing answerable records")
            values["mrr_at_k"]=sum(x["mrr_at_k"] for x in positives)/len(positives)
            values["hit_at_k"]=sum(x["hit_at_k"] for x in positives)/len(positives)
            values["p50_latency_ms"]=percentile([x["latency_ms"] for x in sub],.5)
            values["p95_latency_ms"]=percentile([x["latency_ms"] for x in sub],.95)
            splits[split]=values
        evaluations[name]={"threshold":cutoff,"splits":splits,"cases":rows}
    paired={}
    baseline=[{"id":r["id"],"group_id":r["group_id"],
               "metric":float(r["mrr_at_k"] or 0.)}
              for r in query_records["sparse"] if r["split"]=="test"]
    for name in evaluations:
        if name=="sparse":
            continue
        candidate=[{"id":r["id"],"group_id":r["group_id"],
                    "metric":float(r["mrr_at_k"] or 0.)}
                   for r in query_records[name] if r["split"]=="test"]
        paired[name]=paired_cluster_delta_ci(
            candidate,baseline,"metric",resamples=bootstrap_resamples,seed=1905)
    return {"stage":"S11","dataset_id":snapshot["dataset_id"],
            "dataset_revision":snapshot["revision"],
            "dataset_raw_sha256":snapshot["raw_sha256"],
            "snapshot_sha256":hashlib.sha256(json.dumps(
                snapshot,sort_keys=True,ensure_ascii=False,
                separators=(",",":")).encode()).hexdigest(),
            "models_executed":bool(encoder),
            "documents":len(documents),"questions":len(questions),
            "chunks_indexed":len(chunks),
            "chunking_truncation_chars":max_doc_chars,
            "stage01_index_ms":round(index_ms,3),
            "pretrained_embed_ms":round(embed_ms,3),
            "lanes":evaluations,"paired_test_mrr_delta_vs_sparse":paired,
            "limitations":[
                "Gold is_impossible labels used only for metrics, not ranking or inference.",
                "Reference contexts are author-provided and query-associated, not independent qrels.",
                "Only first capped characters of each document indexed; incomplete relevance is possible.",
                "DEV alone selects lane-specific cutoffs; TEST never used to choose a model.",
                "CrossEncoder MS MARCO reranker trained in English; multilingual transfer is unverified.",
                "Model initialization/download excluded from per-query latency. CPU timings are not steady-state SLO.",
                "Dense search scans all bounded chunks in memory: not a production vector index.",
                "Reranker scores and rank-fusion scores are not calibrated probability values.",
                "TechQA IT support examples are not real plant OT/telemetry/safety data.",
            ]}
