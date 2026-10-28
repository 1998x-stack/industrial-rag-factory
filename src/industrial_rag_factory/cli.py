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
    semantic_resolve = sub.add_parser("semantic-resolve")
    semantic_resolve.add_argument("external_id")
    semantic_resolve.add_argument("--system", default=None)
    semantic_resolve.add_argument("--at-time", default=None)
    semantic_validate = sub.add_parser("semantic-validate")
    semantic_validate.add_argument("--at-time", default="2026-10-20T10:00:00+08:00")
    semantic_eval = sub.add_parser("semantic-evaluate")
    semantic_eval.add_argument("--questions",default="datasets/stage02/competency.jsonl")
    semantic_export = sub.add_parser("semantic-export")
    semantic_export.add_argument("output")
    semantic_export.add_argument("--at-time",default="2026-10-20T10:00:00+08:00")
    args = parser.parse_args()
    settings = Settings.from_env()
    if args.command == "serve":
        from .api import main as serve
        serve()
        return
    if args.command.startswith("semantic-"):
        from .semantic.service import SemanticService
        service = SemanticService.from_defaults()
        if args.command == "semantic-resolve":
            payload = service.resolve(args.external_id,tenant_id=settings.tenant_id,
                                      groups=settings.groups,system=args.system,
                                      at_time=args.at_time)
        elif args.command == "semantic-validate":
            payload = service.validate(tenant_id=settings.tenant_id,
                                       groups=settings.groups,at_time=args.at_time)
        elif args.command == "semantic-evaluate":
            payload = service.evaluate(args.questions,tenant_id=settings.tenant_id,
                                       groups=settings.groups)
        else:
            payload = service.export(args.output,tenant_id=settings.tenant_id,
                                     groups=settings.groups,at_time=args.at_time)
        print(json.dumps(payload,ensure_ascii=False,indent=2))
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
