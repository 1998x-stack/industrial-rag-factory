"""Flask read-only research API. Authentication and production exposure are NOT in Stage 01."""
from __future__ import annotations
from pathlib import PurePosixPath

from .config import Settings
from .parsing import from_bytes
from .pipeline import Pipeline


def create_app(settings: Settings | None = None, pipeline: Pipeline | None = None):
    try:
        from flask import Flask, jsonify, request
    except ImportError as exc:
        raise RuntimeError("Install industrial-rag-factory[api]") from exc
    settings = settings or Settings.from_env()
    if settings.environment.lower() == "production":
        raise RuntimeError("Stage 01 Flask API is development-only; production requires authenticated gateway")
    app = Flask(__name__)
    app.config["MAX_CONTENT_LENGTH"] = 1_048_576
    service = pipeline or Pipeline(settings)

    @app.get("/healthz")
    def health():
        return jsonify({"status": "ok", "stage": "01", "mode": "development"})

    @app.post("/v1/documents")
    def documents():
        body = request.get_json(silent=True)
        if not isinstance(body,dict):
            return jsonify({"error":"JSON object required"}),400
        # Client cannot impersonate tenants or access groups in this development API.
        if any(k in body for k in ("tenant_id","access_groups","groups","principal")):
            return jsonify({"error":"tenant/group fields are server-controlled"}),400
        try:
            source = str(body["source_uri"])
            content = body["content"]
            if not isinstance(content,str):
                raise ValueError("content must be a UTF-8 string")
            suffix = PurePosixPath(source).suffix or ".md"
            if suffix not in (".md",".markdown",".txt"):
                raise ValueError("HTTP JSON ingest supports only text formats; use CLI for PDF/DOCX")
            doc = from_bytes(content.encode("utf-8"),source,suffix,
                             revision=str(body.get("revision","1")),
                             tenant_id=settings.tenant_id,access_groups=settings.groups)
            return jsonify(service.ingest(doc)),201
        except (KeyError,ValueError,UnicodeError) as exc:
            return jsonify({"error":str(exc)}),400

    @app.post("/v1/query")
    def query():
        body = request.get_json(silent=True)
        if not isinstance(body,dict):
            return jsonify({"error":"JSON object required"}),400
        if any(k in body for k in ("tenant_id","access_groups","groups","principal")):
            return jsonify({"error":"tenant/group fields are server-controlled"}),400
        try:
            question = body["question"]
            if not isinstance(question,str) or len(question)>2000:
                raise ValueError("question must be a string of at most 2000 chars")
            result = service.query(question,tenant=settings.tenant_id,groups=settings.groups,
                                   mode=body.get("mode","hybrid"),top_k=body.get("top_k",5))
            return jsonify(result.to_dict()),200
        except (ValueError,KeyError,TypeError) as exc:
            return jsonify({"error":str(exc)}),400

    @app.post("/v1/semantic/resolve")
    def semantic_resolve():
        body = request.get_json(silent=True)
        if not isinstance(body,dict) or any(
            key in body for key in ("tenant_id","access_groups","groups","principal")
        ):
            return jsonify({"error":"Invalid JSON or server-controlled context"}),400
        try:
            identifier = body["external_id"]
            if not isinstance(identifier,str) or len(identifier)>256:
                raise ValueError("Invalid external_id")
            from .semantic.service import SemanticService
            service = SemanticService.from_defaults()
            return jsonify(service.resolve(identifier,tenant_id=settings.tenant_id,
                          groups=settings.groups,system=body.get("system"),
                          at_time=body.get("at_time")))
        except (KeyError,ValueError) as exc:
            return jsonify({"error":str(exc)}),400

    @app.post("/v1/semantic/traverse")
    def semantic_traverse():
        body = request.get_json(silent=True)
        if not isinstance(body,dict) or any(
            key in body for key in ("tenant_id","access_groups","groups","principal")
        ):
            return jsonify({"error":"Invalid JSON or server-controlled context"}),400
        try:
            start, steps = body["subject"], body["steps"]
            if not isinstance(start,str) or not isinstance(steps,list):
                raise ValueError("Invalid graph query")
            from .semantic.service import SemanticService
            service = SemanticService.from_defaults()
            result = service.traverse(start,steps,tenant_id=settings.tenant_id,
                                      groups=settings.groups,at_time=body.get("at_time"))
            return jsonify(result)
        except (KeyError,ValueError,TypeError) as exc:
            return jsonify({"error":str(exc)}),400

    @app.post("/v1/multisource/assess")
    def multisource_assess():
        body = request.get_json(silent=True)
        if not isinstance(body,dict) or any(
            key in body for key in ("tenant_id","access_groups","groups","principal")
        ):
            return jsonify({"error":"Invalid JSON or server-controlled context"}),400
        try:
            batch_id = body["batch_id"]
            kind = body.get("kind","vibration_velocity")
            cadence = body.get("spacing_seconds",600)
            if not isinstance(batch_id,str) or not 1 <= len(batch_id) <= 128:
                raise ValueError("Invalid batch identifier")
            if kind not in ("vibration_velocity","temperature"):
                raise ValueError("Unsupported quantity kind")
            if type(cadence) is not int or not 1 <= cadence <= 86400:
                raise ValueError("Invalid sampling cadence")
            from .multisource.service import MultiSourceService
            multi = MultiSourceService.from_defaults()
            try:
                output = multi.assess_batch(batch_id,tenant_id=settings.tenant_id,
                    groups=settings.groups,kind=kind,spacing_seconds=cadence)
            finally:
                multi.close()
            return jsonify(output),200
        except (ValueError,KeyError,TypeError) as exc:
            return jsonify({"error":str(exc)}),400

    @app.post("/v1/agent/query")
    def agent_query():
        body = request.get_json(silent=True)
        # Entire request contract is one question. Planner, auth context and
        # execution tools are selected only from server-side configuration.
        if not isinstance(body,dict) or set(body) != {"question"}:
            return jsonify({"error":"Expected only question; runtime context is server-controlled"}),400
        question = body["question"]
        if not isinstance(question,str) or not question.strip() or len(question)>2000:
            return jsonify({"error":"Invalid question"}),400
        from .agent.service import AgentService
        agent = None
        try:
            agent = AgentService(settings,mode=settings.planner)
            result = agent.query(question)
            return jsonify(result),200
        except (ValueError,KeyError,TypeError):
            return jsonify({"error":"invalid_query_plan"}),400
        except RuntimeError:
            return jsonify({"error":"planner_or_tool_unavailable"}),503
        finally:
            if agent is not None:
                agent.close()

    @app.post("/v1/grounding/verify")
    def grounding_verify():
        body=request.get_json(silent=True)
        if not isinstance(body,dict) or not {"batch_id"} <= set(body) or (
            set(body)-{"batch_id","claims"}
        ):
            return jsonify({"error":"Only batch_id and optional claims are accepted"}),400
        from .grounding.contracts import Claim
        from .grounding.service import GroundingService
        grounding=None
        try:
            batch_id=body["batch_id"]
            raw=body.get("claims")
            if raw is not None and (not isinstance(raw,list) or not 1<=len(raw)<=50):
                raise ValueError("claims must contain 1..50 typed statements")
            claims=None if raw is None else [Claim.from_dict(item) for item in raw]
            grounding=GroundingService(settings)
            result=grounding.verify_batch(batch_id,claims)
            return jsonify(result),200
        except (ValueError,TypeError,KeyError):
            return jsonify({"error":"invalid_claim_or_batch"}),400
        except RuntimeError:
            return jsonify({"error":"verification_tool_unavailable"}),503
        finally:
            if grounding is not None:
                grounding.close()

    return app


def main() -> None:
    settings = Settings.from_env()
    if settings.host not in ("127.0.0.1","localhost","::1"):
        raise RuntimeError("Stage 01 development API must bind to loopback")
    app = create_app(settings)
    app.run(host=settings.host,port=settings.port,debug=False)
