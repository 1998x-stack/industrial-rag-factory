"""Stage 12 bounded closed-loop load and lexical distractor stress on public QA.

Crucial concurrency boundary: a separate immutable read-only SQLite handle
is opened INSIDE each worker; never share Store.con across worker threads.
All timings are local wall-clock observations, not production SLOs.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import sqlite3
import statistics
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
from urllib.parse import quote

from industrial_rag_factory.config import Settings
from industrial_rag_factory.experiments.stats import paired_cluster_delta_ci
from industrial_rag_factory.parsing import from_bytes
from industrial_rag_factory.pipeline import Pipeline
from industrial_rag_factory.retrieval import Retriever
from industrial_rag_factory.storage import Store


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def percentile(values: list[float], fraction: float) -> float:
    if not values or not 0<=fraction<=1:
        raise ValueError("Percentile requires samples and 0..1 fraction")
    ordered=sorted(values)
    location=(len(ordered)-1)*fraction
    left=int(location)
    return round(ordered[left]*(1-location+left)+
                 ordered[min(left+1,len(ordered)-1)]*(location-left),3)


def _snapshot_documents(snapshot: dict, *, stress: bool) -> tuple[list[dict],int]:
    documents=[dict(d) for d in snapshot["docs"]]
    if not stress:
        return documents,0
    # A query-conditioned stress fixture, constructed from TRAIN questions
    # only. No held-out DEV/TEST query or answer text enters the decoys.
    # These synthetic passages are NOT independently annotated negatives.
    training=sorted((q for q in snapshot["queries"] if q["split"]=="train"),
                    key=lambda r:r["id"])
    n=0
    for query in training[:24]:
        question=query["question"][:1000]
        uid=_sha(query["id"]+question)
        documents.append({
            "source_uri":"fixture://s12/lexical-distractor/"+uid[:24],
            "text":("# Synthetic unverified distractor\n\n"+
                    ("Indexing stress token matching: "+question+"\n")*3+
                    "This synthetic record supplies no verified answer or "
                    "technical repair instruction."),
            "title":"S12 synthetic lexical distractor "+uid[:10]})
        n+=1
    return documents,n


def _build_index(snapshot: dict, path: Path, *, stress: bool,
                 chunk_size: int = 300, overlap: int = 40) -> dict:
    documents,decoys=_snapshot_documents(snapshot,stress=stress)
    if len(documents)>600 or not 20<=overlap<chunk_size<=900:
        raise ValueError("Index construction budget exceeded")
    opts=replace(Settings(),db_path=str(path),dense_backend="none",
                 generator="extractive",planner="rules",
                 tenant_id="techqa-public",groups=("techqa-benchmark",))
    pipeline=Pipeline(opts)
    start=time.perf_counter()
    chunk_count=0
    try:
        for doc in documents:
            body=doc["text"]
            if not isinstance(body,str) or not body.strip():
                raise ValueError("Invalid document")
            parsed=from_bytes(body[:5000].encode("utf-8"),doc["source_uri"],
                              ".md",revision=snapshot["revision"],
                              tenant_id="techqa-public",
                              access_groups=("techqa-benchmark",),
                              title=doc["title"])
            chunk_count+=pipeline.ingest(parsed,max_tokens=chunk_size,
                                         overlap=overlap)["chunks"]
    finally:
        pipeline.close()
    if path.stat().st_size>64*1024*1024:
        raise ValueError("SQLite benchmark storage budget exceeded")
    return {"documents":len(documents),"synthetic_decoys":decoys,
            "chunks":chunk_count,"index_size_bytes":path.stat().st_size,
            "index_ms":round((time.perf_counter()-start)*1000,3)}


def _open_readonly(path: Path) -> Store:
    uri="file:"+quote(str(path.resolve()),safe="/")+"?mode=ro"
    store=object.__new__(Store)
    store.path=str(path)
    store.con=sqlite3.connect(uri,uri=True,timeout=5)
    store.con.row_factory=sqlite3.Row
    store.con.execute("PRAGMA query_only=ON")
    return store


def _run_workload(path: Path, queries: list[dict], *,
                  concurrency: int, requests_per_worker: int,
                  warmups: int, k: int) -> tuple[dict,list[dict]]:
    if (type(concurrency) is not int or not 1<=concurrency<=8
        or type(requests_per_worker) is not int
        or not 2<=requests_per_worker<=150
        or type(warmups) is not int or not 0<=warmups<=10
        or not queries or type(k) is not int or not 1<=k<=10):
        raise ValueError("Invalid bounded workload")
    barrier=threading.Barrier(concurrency+1,timeout=20)
    allowed_tenant="techqa-public"
    groups=("techqa-benchmark",)
    ordered=sorted(queries,key=lambda q:q["id"])
    def worker(worker_id):
        store=_open_readonly(path)
        retriever=Retriever(store,backend="none")
        try:
            def call(q):
                return retriever.search(q["question"],tenant=allowed_tenant,
                                        groups=groups,mode="sparse",
                                        top_k=min(50,max(20,k*8)))
            for index in range(warmups):
                call(ordered[(worker_id+index)%len(ordered)])
            # Prove a direct tenant/group cross-scope query has zero hits.
            unauthorized=retriever.search(
                ordered[0]["question"],tenant="other-tenant",
                groups=groups,mode="sparse",top_k=k)
            if unauthorized:
                raise RuntimeError("Tenant boundary violation in benchmark")
            bad_group=retriever.search(
                ordered[0]["question"],tenant=allowed_tenant,
                groups=("not-allowed",),mode="sparse",top_k=k)
            if bad_group:
                raise RuntimeError("Group isolation violation in benchmark")
            barrier.wait()
            results=[]
            for index in range(requests_per_worker):
                q=ordered[(worker_id*requests_per_worker+index)%len(ordered)]
                start=time.perf_counter()
                hits=call(q)
                elapsed=(time.perf_counter()-start)*1000
                # Source-level dedup, since Stage01 retrieval ranks CHUNKS.
                seen=set()
                sources=[]
                for h in hits:
                    if h.source_uri not in seen:
                        sources.append(h.source_uri)
                        seen.add(h.source_uri)
                    if len(sources)>=k:
                        break
                gold=set(q["context_uris"])
                positions=[i+1 for i,source in enumerate(sources)
                           if source in gold]
                results.append({"id":q["id"],"group_id":q["group_id"],
                    "impossible":q["impossible"],
                    "elapsed_ms":elapsed,
                    "mrr":(1/min(positions) if positions else 0.)
                            if gold else None,
                    "hit":float(bool(positions)) if gold else None,
                    "found":bool(sources)})
            return results
        finally:
            store.close()
    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        futures=[pool.submit(worker,index) for index in range(concurrency)]
        start=time.perf_counter()
        barrier.wait()
        start=time.perf_counter()
        records=[record for future in futures for record in future.result()]
        elapsed=max(time.perf_counter()-start,1e-9)
    samples=[x["elapsed_ms"] for x in records]
    answerable=[x for x in records if not x["impossible"]]
    return {"concurrency":concurrency,
            "requests":len(records),"closed_loop_wall_seconds":round(elapsed,5),
            "completed_qps":round(len(records)/elapsed,3),
            "p50_ms":percentile(samples,.5),
            "p95_ms":percentile(samples,.95),
            "p99_ms":percentile(samples,.99),
            "mean_ms":round(statistics.fmean(samples),3),
            "errors":0,"access_boundary_checks_per_worker":2,
            "answerable_mrr":round(statistics.fmean(
                x["mrr"] for x in answerable),6) if answerable else None,
            "answerable_hit":round(statistics.fmean(
                x["hit"] for x in answerable),6) if answerable else None,
            "test_ids":len({x["id"] for x in records})},records


def run_scale(snapshot: dict, *,
              concurrencies: tuple[int,...] = (1,2,4),
              requests_per_worker: int = 12,
              warmups: int = 2,
              k: int = 3,
              stress: bool = True) -> dict:
    if snapshot.get("dataset_id")!="nvidia/TechQA-RAG-Eval":
        raise ValueError("Expected pinned public TechQA snapshot")
    docs=snapshot.get("docs")
    queries=snapshot.get("queries")
    if (not isinstance(docs,list) or not isinstance(queries,list)
        or not 6<=len(queries)<=250 or not 1<=len(docs)<=550
        or not concurrencies or len(concurrencies)>4
        or any(type(c) is not int or not 1<=c<=8 for c in concurrencies)
        or len(set(concurrencies))!=len(concurrencies)
        or not all(set(q["context_uris"])<={
                   d["source_uri"] for d in docs} for q in queries)):
        raise ValueError("Invalid source/split/concurrency protocol")
    selected=[q for q in queries if q["split"]=="test"]
    if len(selected)<6:
        raise ValueError("Missing independent held-out TEST questions")
    datasets={}
    # No concurrent use of a writable Pipeline SQLite connection.
    # Each scenario starts from its own ephemeral, closed index.
    with tempfile.TemporaryDirectory(prefix="irf-stage12-") as folder:
        for variant in (("base","stress") if stress else ("base",)):
            path=Path(folder)/(variant+".sqlite3")
            index=_build_index(snapshot,path,stress=variant=="stress")
            runs=[]
            percase=[]
            for concurrency in concurrencies:
                summary,records=_run_workload(
                    path,selected,concurrency=concurrency,
                    requests_per_worker=requests_per_worker,
                    warmups=warmups,k=k)
                runs.append(summary)
                if concurrency==1:
                    percase=records
            datasets[variant]={"index":index,"load":runs,
                "case_metrics":[{"id":r["id"],"group_id":r["group_id"],
                                 "mrr":r["mrr"] if r["mrr"] is not None else 0.}
                                for r in percase]}
    paired=None
    if stress:
        # Same canonical case IDs can recur under repeated benchmark loops:
        # aggregate at case ID, then bootstrap by independent source groups.
        def bycase(rows):
            grouped={}
            for r in rows:
                entry=grouped.setdefault(r["id"],{
                    "id":r["id"],"group_id":r["group_id"],"scores":[]})
                entry["scores"].append(r["mrr"])
            return [{"id":r["id"],"group_id":r["group_id"],
                     "mrr":statistics.fmean(r["scores"])}
                    for r in grouped.values()]
        first=bycase(datasets["stress"]["case_metrics"])
        second=bycase(datasets["base"]["case_metrics"])
        if len(first)>=2:
            paired=paired_cluster_delta_ci(first,second,"mrr",
                                            resamples=200,seed=1207)
    fingerprint=hashlib.sha256(json.dumps(
        snapshot,ensure_ascii=False,sort_keys=True,
        separators=(",",":")).encode("utf-8")).hexdigest()
    return {"stage":"S12","workload":"closed_loop_local_SQLite_FTS5",
        "dataset_id":snapshot["dataset_id"],"revision":snapshot["revision"],
        "raw_sha256":snapshot["raw_sha256"],"snapshot_sha256":fingerprint,
        "query_subset":"TEST_only",
        "test_questions":len(selected),"concurrencies":list(concurrencies),
        "requests_per_worker":requests_per_worker,"warmups_per_worker":warmups,
        "top_k":k,"scenarios":datasets,
        "paired_test_mrr_stress_minus_base":paired,
        "memory_method":"process_peak_rss_not_per_trial",
        "peak_rss_kib":_peak_memory(),
        "limitations":[
            "Public IT support contexts, not authenticated industrial OT source data.",
            "Closed-loop local client throughput, not externally offered-load capacity.",
            "SQLite uses separate read-only connections per thread; Python thread GIL affects CPU.",
            "P99 computed on tiny sample; do not interpret as steady-state service SLO.",
            "No independent concurrency load generators, autoscaling or multi-host network.",
            "TRAIN-question-conditioned decoys are synthetic stress texts, not expert-labeled negatives.",
            "The test corpus is constructed from weakly annotated question-associated contexts.",
            "No pretrained model, CrossEncoder, GPU, real-token billing or other source formats are timed.",
            "Peak process RSS contains imports/indexing and cannot be attributed to a single scenario.",
        ]}


def _peak_memory() -> int | None:
    try:
        import resource
        peak=int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
        if os.uname().sysname=="Darwin":
            return peak//1024
        return peak
    except (ImportError,AttributeError,OSError):
        return None
