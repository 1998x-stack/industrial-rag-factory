"""Real Hugging Face public IndustryBench -> S01 index -> evidence report.

No implicit download in default tests. This script requires an explicit
--fetch or an existing validated local normalized snapshot.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from industrial_rag_factory.hfbench.adapter import prepare_industrybench
from industrial_rag_factory.hfbench.runner import evaluate_benchmark

ROOT=Path(__file__).resolve().parents[1]


def main() -> None:
    parser=argparse.ArgumentParser(description="Public industrial QA retrieval benchmark")
    parser.add_argument("--fetch",action="store_true",help="explicitly access Hugging Face Hub")
    parser.add_argument("--revision",default="main",
                        help="full pinned revision SHA or main (resolved and recorded)")
    parser.add_argument("--limit-per-split",type=int,default=12)
    parser.add_argument("--snapshot",default="data/hf/industrybench.json")
    parser.add_argument("--output",default="outputs/stage09_hf_report.json")
    parser.add_argument("--k",type=int,default=5)
    parser.add_argument("--modes",nargs="+",choices=("sparse","hybrid","dense"),
                        default=["sparse","hybrid"])
    args=parser.parse_args()
    snapshot=Path(args.snapshot)
    if args.fetch:
        details=prepare_industrybench(snapshot,revision=args.revision,
                                      limit_per_split=args.limit_per_split)
        print("Pinned real dataset:",json.dumps(details,ensure_ascii=False))
    if not snapshot.is_file():
        parser.error("No local benchmark snapshot. Supply --fetch explicitly.")
    record=json.loads(snapshot.read_text(encoding="utf-8"))
    report=evaluate_benchmark(record,modes=tuple(args.modes),k=args.k)
    dest=Path(args.output)
    dest.parent.mkdir(parents=True,exist_ok=True)
    dest.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
    scores={mode:result["scores"]["test"]["mrr"]
            for mode,result in report["modes"].items()}
    print(f"Stage 09: source={report['dataset_id']}@{report['source_revision']}, "
          f"documents={report['corpus_docs']}, questions={report['queries']}, "
          f"TEST MRR@{args.k}={scores}")
    print(f"Report: {dest}")


if __name__=="__main__":
    main()
