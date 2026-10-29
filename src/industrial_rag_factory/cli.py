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
    multi = sub.add_parser("multisource-assess")
    multi.add_argument("batch_id")
    multi.add_argument("--kind",default="vibration_velocity")
    multi.add_argument("--spacing-seconds",type=int,default=600)
    multi_eval = sub.add_parser("multisource-evaluate")
    multi_eval.add_argument("--gold",default="datasets/stage03/gold.jsonl")
    agent_query = sub.add_parser("agent-query")
    agent_query.add_argument("question")
    agent_query.add_argument("--planner",choices=("rules","deepseek"),default=None)
    agent_plan = sub.add_parser("agent-plan")
    agent_plan.add_argument("question")
    agent_plan.add_argument("--planner",choices=("rules","deepseek"),default=None)
    sub.add_parser("agent-evaluate")
    grounding_verify = sub.add_parser("grounding-verify")
    grounding_verify.add_argument("batch_id")
    grounding_verify.add_argument("--claims-json",default=None,
        help="JSON array of bounded candidate claims; no evidence may be supplied")
    grounding_evaluate = sub.add_parser("grounding-evaluate")
    grounding_evaluate.add_argument("--gold",default="datasets/stage05/gold.jsonl")
    ops= sub.add_parser("ops-stage",help="Stage offline immutable synthetic index")
    ops.add_argument("--manifest",default="config/stage08_manifest.json")
    ops.add_argument("--fail-at",choices=("after_ingest","before_catalog"),default=None)
    pub=sub.add_parser("ops-publish")
    pub.add_argument("version")
    pub.add_argument("--expected-active",default=None,
                     help="Expected active release, or omit for initial publication")
    roll=sub.add_parser("ops-rollback")
    roll.add_argument("version")
    roll.add_argument("--expected-active",required=True)
    oq=sub.add_parser("ops-query")
    oq.add_argument("question")
    exporter=sub.add_parser("ops-export")
    exporter.add_argument("version")
    exporter.add_argument("destination")
    importer=sub.add_parser("ops-import")
    importer.add_argument("archive")
    recover=sub.add_parser("ops-recover")
    recover.add_argument("version")
    recover.add_argument("--expected-active",default=None)
    prune=sub.add_parser("ops-prune")
    prune.add_argument("--keep",type=int,default=3)
    sub.add_parser("ops-status")
    sub.add_parser("ops-history")
    sub.add_parser("ops-readiness")
    args = parser.parse_args()
    settings = Settings.from_env()
    if args.command.startswith("ops-"):
        import os
        from .operations import ReleaseManager, readiness_report
        key=os.environ.get("IRF_OPS_HMAC_KEY","")
        manager=ReleaseManager(
            os.environ.get("IRF_OPS_ROOT","data/stage08"),
            Path.cwd(),key,settings=settings)
        if args.command=="ops-stage":
            manifest=json.loads(Path(args.manifest).read_text(encoding="utf-8"))
            payload=manager.stage(manifest,fail_at=args.fail_at)
        elif args.command=="ops-publish":
            payload=manager.publish(args.version,expected_active=args.expected_active)
        elif args.command=="ops-rollback":
            payload=manager.rollback(args.version,expected_active=args.expected_active)
        elif args.command=="ops-query":
            payload=manager.query(args.question)
        elif args.command=="ops-export":
            payload=manager.export_bundle(args.version,args.destination)
        elif args.command=="ops-import":
            payload=manager.import_bundle(args.archive)
        elif args.command=="ops-recover":
            payload=manager.recover(args.version,expected_active=args.expected_active)
        elif args.command=="ops-prune":
            payload=manager.prune(keep=args.keep)
        elif args.command=="ops-status":
            payload=manager.status()
        elif args.command=="ops-history":
            payload=manager.history()
        else:
            payload=readiness_report(manager.status())
        print(json.dumps(payload,ensure_ascii=False,indent=2))
        return
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
    if args.command.startswith("multisource-"):
        from .multisource.service import MultiSourceService
        from .multisource.evaluation import evaluate as multisource_evaluate
        service = MultiSourceService.from_defaults()
        try:
            if args.command == "multisource-assess":
                payload = service.assess_batch(args.batch_id,tenant_id=settings.tenant_id,
                                               groups=settings.groups,kind=args.kind,
                                               spacing_seconds=args.spacing_seconds)
            else:
                payload = multisource_evaluate(service,args.gold,
                    tenant_id=settings.tenant_id,groups=settings.groups)
        finally:
            service.close()
        print(json.dumps(payload,ensure_ascii=False,indent=2))
        return
    if args.command.startswith("agent-"):
        from .agent.service import AgentService
        from .agent.evaluation import evaluate_planner
        from .agent.planner import RulePlanner
        from .agent.runner import DAGRunner
        from .agent.tools import RunContext, build_tool_registry
        if args.command == "agent-evaluate":
            registry = build_tool_registry(settings)
            try:
                payload = evaluate_planner(RulePlanner(),DAGRunner(registry),
                    "datasets/stage04/gold.jsonl",RunContext(settings.tenant_id,settings.groups))
            finally:
                registry.close()
        else:
            agent = AgentService(settings,mode=args.planner or settings.planner)
            try:
                payload = agent.plan(args.question) if args.command == "agent-plan" else agent.query(args.question)
            finally:
                agent.close()
        print(json.dumps(payload,ensure_ascii=False,indent=2))
        return
    if args.command.startswith("grounding-"):
        from .grounding.contracts import Claim
        from .grounding.evaluation import evaluate_claims
        from .grounding.service import GroundingService
        grounding=GroundingService(settings)
        try:
            if args.command == "grounding-verify":
                claims = None if args.claims_json is None else [
                    Claim.from_dict(item) for item in json.loads(args.claims_json)
                ]
                payload=grounding.verify_batch(args.batch_id,claims)
            else:
                payload=evaluate_claims(grounding,args.gold)
        finally:
            grounding.close()
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
