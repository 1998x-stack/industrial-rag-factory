"""Stage 12 public TechQA closed-loop SQLite read-only scaling and stress."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from industrial_rag_factory.hfbench.scale import run_scale
from industrial_rag_factory.hfbench.techqa import fetch_techqa


def main():
    p=argparse.ArgumentParser(description="Bounded public TechQA load and robustness")
    p.add_argument("--fetch",action="store_true")
    p.add_argument("--revision",default="main")
    p.add_argument("--snapshot",default="data/hf/stage12_techqa.json")
    p.add_argument("--per-class",type=int,default=10)
    p.add_argument("--extra-corpus",type=int,default=96)
    p.add_argument("--concurrency",type=int,nargs="+",default=[1,2,4])
    p.add_argument("--requests-per-worker",type=int,default=16)
    p.add_argument("--warmups",type=int,default=2)
    p.add_argument("--no-stress",action="store_true")
    p.add_argument("--output",default="outputs/stage12_scale.json")
    args=p.parse_args()
    if args.fetch:
        details=fetch_techqa(args.snapshot,revision=args.revision,
                             per_split_per_class=args.per_class,
                             extra_corpus=args.extra_corpus)
        print("Pinned TechQA source:",json.dumps(details,ensure_ascii=False,
                                                  sort_keys=True))
    path=Path(args.snapshot)
    if not path.is_file():
        p.error("No public dataset snapshot; pass --fetch explicitly")
    snapshot=json.loads(path.read_text(encoding="utf-8"))
    result=run_scale(snapshot,concurrencies=tuple(args.concurrency),
                     requests_per_worker=args.requests_per_worker,
                     warmups=args.warmups,stress=not args.no_stress)
    output=Path(args.output)
    output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(json.dumps(result,ensure_ascii=False,sort_keys=True,
                                 indent=2,allow_nan=False),encoding="utf-8")
    summary={name:[{
        "threads":x["concurrency"],"closed_loop_qps":x["completed_qps"],
        "p95_ms":x["p95_ms"],"p99_ms":x["p99_ms"],
        "errors":x["errors"]
    } for x in scenario["load"]] for name,scenario in result["scenarios"].items()}
    print("Stage 12:",json.dumps({
        "revision":result["revision"],"test_queries":result["test_questions"],
        "scenarios":summary,"report":str(output)},sort_keys=True))


if __name__=="__main__":
    main()
