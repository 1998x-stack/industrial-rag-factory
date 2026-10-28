"""Offline-first Stage 01 CLI. Evaluation never calls a paid generator."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
from .config import Settings
from .evaluation import evaluate_jsonl
from .parsing import from_bytes
from .pipeline import Pipeline


def main() -> None:
    parser = argparse.ArgumentParser(description="Industrial RAG Factory / Stage 01")
    sub = parser.add_subparsers(dest="command",required=True)
    ingest = sub.add_parser("ingest")
    ingest.add_argument("path")
    ingest.add_argument("--source-uri",default=None)
    ingest.add_argument("--revision",default="1")
    ingest.add_argument("--max-tokens",type=int,default=220)
    ingest.add_argument("--overlap",type=int,default=40)
    query = sub.add_parser("query")
    query.add_argument("question")
    query.add_argument("--mode",choices=("sparse","dense","hybrid"),default="hybrid")
    query.add_argument("--top-k",type=int,default=5)
    evaluate = sub.add_parser("evaluate")
    evaluate.add_argument("dataset")
    evaluate.add_argument("--mode",choices=("sparse","dense","hybrid"),default="hybrid")
    evaluate.add_argument("--k",type=int,default=5)
    sub.add_parser("serve")
    args = parser.parse_args()
    settings = Settings.from_env()
    if args.command == "serve":
        from .api import main as serve
        serve()
        return
    pipeline = Pipeline(settings)
    try:
        if args.command == "ingest":
            path = Path(args.path).resolve(strict=True)
            doc = from_bytes(path.read_bytes(),args.source_uri or path.as_uri(),path.suffix,
                             revision=args.revision,tenant_id=settings.tenant_id,
                             access_groups=settings.groups)
            payload = pipeline.ingest(doc,args.max_tokens,args.overlap)
        elif args.command == "query":
            payload = pipeline.query(args.question,tenant=settings.tenant_id,
                                     groups=settings.groups,mode=args.mode,top_k=args.top_k).to_dict()
        else:
            payload = evaluate_jsonl(pipeline,args.dataset,tenant=settings.tenant_id,
                                     groups=settings.groups,mode=args.mode,k=args.k)
        print(json.dumps(payload,ensure_ascii=False,indent=2))
    finally:
        pipeline.close()


if __name__ == "__main__":
    main()
