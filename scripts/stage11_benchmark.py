"""TechQA public head-to-head retrieval; pretrained models only with --pretrained."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from industrial_rag_factory.hfbench.stage11 import evaluate_stage11
from industrial_rag_factory.hfbench.techqa import fetch_techqa


def main():
    p=argparse.ArgumentParser(description="S11 source-ranked paired retrieval benchmark")
    p.add_argument("--snapshot",default="data/hf/stage11_techqa.json")
    p.add_argument("--fetch",action="store_true")
    p.add_argument("--revision",default="main")
    p.add_argument("--per-class",type=int,default=3)
    p.add_argument("--extra-corpus",type=int,default=8)
    p.add_argument("--pretrained",action="store_true",
                   help="explicitly download and execute two pretrained models")
    p.add_argument("--encoder-revision",default="main")
    p.add_argument("--reranker-revision",default="main")
    p.add_argument("--output",default="outputs/stage11_benchmark.json")
    p.add_argument("--k",type=int,default=3)
    a=p.parse_args()
    if a.fetch:
        print("Pinned dataset:",json.dumps(fetch_techqa(
            a.snapshot,revision=a.revision,
            per_split_per_class=a.per_class,extra_corpus=a.extra_corpus)))
    file=Path(a.snapshot)
    if not file.is_file():
        p.error("No local snapshot. Use --fetch explicitly")
    snapshot=json.loads(file.read_text(encoding="utf-8"))
    models=None
    encoder=reranker=None
    if a.pretrained:
        from industrial_rag_factory.hfbench.rerank import (
            load_pretrained, prepare_models,
        )
        models=prepare_models(revision_encoder=a.encoder_revision,
                              revision_reranker=a.reranker_revision)
        encoder,reranker=load_pretrained(models)
    report=evaluate_stage11(snapshot,encoder=encoder,reranker=reranker,k=a.k)
    if models:
        report["model_provenance"]={name:{
            key:value for key,value in meta.items() if key!="local_path"}
            for name,meta in models.items()}
    out=Path(a.output)
    out.parent.mkdir(parents=True,exist_ok=True)
    out.write_text(json.dumps(report,ensure_ascii=False,sort_keys=True,
                              indent=2,allow_nan=False),encoding="utf-8")
    summary={name:{
        "test_mrr":round(lane["splits"]["test"]["mrr_at_k"],3),
        "test_balanced_accuracy":round(
            lane["splits"]["test"]["balanced_accuracy"],3),
        "test_false_answer_rate":round(
            lane["splits"]["test"]["false_answer_rate"],3),
        "p95_ms":lane["splits"]["test"]["p95_latency_ms"]
    } for name,lane in report["lanes"].items()}
    print("Stage 11:",json.dumps({"model_execution":report["models_executed"],
           "documents":report["documents"],"questions":report["questions"],
           "summary":summary,"artifact":str(out)},sort_keys=True))


if __name__=="__main__":
    main()
