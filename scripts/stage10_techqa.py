"""Explicit opt-in real TechQA download, FTS evaluation, DEV/TST abstention."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from industrial_rag_factory.hfbench.techqa import fetch_techqa
from industrial_rag_factory.hfbench.techqa_runner import evaluate_techqa


def main():
    p=argparse.ArgumentParser(description="Public TechQA answerability benchmark")
    p.add_argument("--fetch",action="store_true")
    p.add_argument("--revision",default="main")
    p.add_argument("--per-class",type=int,default=8)
    p.add_argument("--extra-corpus",type=int,default=60)
    p.add_argument("--snapshot",default="data/hf/techqa.json")
    p.add_argument("--output",default="outputs/stage10_techqa.json")
    p.add_argument("--k",type=int,default=3)
    a=p.parse_args()
    if a.fetch:
        pinned=fetch_techqa(a.snapshot,revision=a.revision,
                            per_split_per_class=a.per_class,
                            extra_corpus=a.extra_corpus)
        print("Pinned TechQA dataset:",json.dumps(pinned,sort_keys=True))
    path=Path(a.snapshot)
    if not path.exists():
        p.error("No snapshot available; download only with explicit --fetch")
    data=json.loads(path.read_text(encoding="utf-8"))
    report=evaluate_techqa(data,k=a.k)
    out=Path(a.output)
    out.parent.mkdir(parents=True,exist_ok=True)
    out.write_text(json.dumps(report,ensure_ascii=False,indent=2),
                   encoding="utf-8")
    print("Stage 10:",json.dumps({
        "revision":report["revision"],
        "corpus_docs":report["corpus_docs"],
        "questions":report["queries"],
        "test":report["evaluation"]["test"],
        "dev_cutoff":report["threshold"]["threshold"],
        "path":str(out),
    },sort_keys=True))


if __name__=="__main__":
    main()
