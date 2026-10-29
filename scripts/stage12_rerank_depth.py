"""Explicit real pretrained candidate-depth comparison; never default CI."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from industrial_rag_factory.hfbench.depth import benchmark_depths
from industrial_rag_factory.hfbench.rerank import load_pretrained, prepare_models
from industrial_rag_factory.hfbench.techqa import fetch_techqa


def main():
    p=argparse.ArgumentParser()
    p.add_argument("--fetch",action="store_true")
    p.add_argument("--snapshot",default="data/hf/stage12_depth.json")
    p.add_argument("--revision",default="main")
    p.add_argument("--per-class",type=int,default=3)
    p.add_argument("--extra-corpus",type=int,default=8)
    p.add_argument("--encoder-revision",default="main")
    p.add_argument("--reranker-revision",default="main")
    p.add_argument("--depths",nargs="+",type=int,default=[4,8,12])
    p.add_argument("--output",default="outputs/stage12_rerank_depth.json")
    a=p.parse_args()
    if a.fetch:
        fetch_techqa(a.snapshot,revision=a.revision,
                     per_split_per_class=a.per_class,
                     extra_corpus=a.extra_corpus)
    path=Path(a.snapshot)
    if not path.is_file():
        p.error("Provide --fetch or local pinned public snapshot")
    snapshot=json.loads(path.read_text(encoding="utf-8"))
    sources=prepare_models(revision_encoder=a.encoder_revision,
                           revision_reranker=a.reranker_revision)
    encoder,reranker=load_pretrained(sources)
    report=benchmark_depths(snapshot,encoder,reranker,depths=tuple(a.depths))
    report["models"]={name:{key:value for key,value in entry.items()
                            if key!="local_path"}
                      for name,entry in sources.items()}
    output=Path(a.output)
    output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(json.dumps(report,ensure_ascii=False,sort_keys=True,
                                 indent=2,allow_nan=False),encoding="utf-8")
    summary={key:{"mrr":value["test"]["mrr_at_k"],
                   "p95_ms":value["test"]["p95_latency_ms"],
                   "false_answer_rate":value["test"]["false_answer_rate"]}
             for key,value in report["runs"].items()}
    print("Stage 12 reranking depth:",json.dumps(summary,sort_keys=True))
    print("Report:",output)


if __name__=="__main__":
    main()
