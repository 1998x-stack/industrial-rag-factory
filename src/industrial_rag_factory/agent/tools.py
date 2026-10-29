"""Allowlisted read-only tools with worker-local DB connections.

The services accessing SQLite are created/closed inside the worker thread; a
SQLite connection must never cross thread boundaries. Each invocation uses a
bounded, independent local research fixture, with server-selected access scope.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable

from industrial_rag_factory.config import Settings
from industrial_rag_factory.multisource.contracts import Interval
from industrial_rag_factory.multisource.service import MultiSourceService
from industrial_rag_factory.pipeline import Pipeline
from industrial_rag_factory.semantic.service import SemanticService

from .contracts import TOOLS, PlanValidationError, validate_args


class TransientToolError(RuntimeError):
    """Only explicitly transient failures are eligible for one idempotent retry."""


@dataclass(frozen=True)
class RunContext:
    tenant_id: str
    groups: tuple[str, ...]

    def __post_init__(self):
        if not self.tenant_id or not self.groups:
            raise ValueError("Trusted execution context must be nonempty")


@dataclass(frozen=True)
class ReadOnlyTool:
    name: str
    invoke: Callable[[dict, RunContext], dict]
    idempotent: bool = True


class ToolRegistry:
    def __init__(self, tools: list[ReadOnlyTool], on_close: Callable[[], None] | None = None):
        self._tools = {t.name: t for t in tools}
        if len(self._tools) != len(tools) or set(self._tools) - set(TOOLS):
            raise ValueError("Duplicate or unknown tool in registry")
        if not all(t.idempotent for t in tools):
            raise ValueError("Stage 04 supports only idempotent read-only tools")
        self._on_close = on_close

    def execute(self, tool: str, args: dict, context: RunContext) -> dict:
        if tool not in self._tools:
            raise PlanValidationError("Unregistered tool")
        validate_args(tool, args, allow_refs=False)
        result = self._tools[tool].invoke(args, context)
        if not isinstance(result, dict):
            raise TypeError("Tool output must be a structured JSON object")
        return result

    def names(self) -> tuple[str, ...]:
        return tuple(sorted(self._tools))

    def close(self) -> None:
        if self._on_close is not None:
            self._on_close()


def build_tool_registry(settings: Settings | None = None, root: str | Path = ".") -> ToolRegistry:
    settings = settings or Settings.from_env()
    root = Path(root)
    # Graph reads do not use a shared database cursor.
    semantic = SemanticService.from_defaults(root)

    def document_search(args: dict, context: RunContext) -> dict:
        pipeline = Pipeline(settings)
        try:
            hits = pipeline.retriever.search(args["question"],tenant=context.tenant_id,
                groups=context.groups,mode=args.get("mode","hybrid"),top_k=args.get("top_k",5))
            return {"status":"retrieved" if hits else "no_accessible_evidence",
                    "hits":[h.to_dict() for h in hits]}
        finally:
            pipeline.close()

    def entity_resolve(args: dict, context: RunContext) -> dict:
        return semantic.resolve(args["external_id"],tenant_id=context.tenant_id,
            groups=context.groups,system=args.get("system"),at_time=args.get("at_time"))

    def graph_traverse(args: dict, context: RunContext) -> dict:
        return semantic.traverse(args["subject"],args["steps"],tenant_id=context.tenant_id,
            groups=context.groups,at_time=args.get("at_time"))

    def mes_by_batch(args: dict, context: RunContext) -> dict:
        multi = MultiSourceService.from_defaults(root)
        try:
            records = multi.mes.by_batch(args["batch_id"],tenant_id=context.tenant_id,
                                        groups=context.groups,max_rows=20)
            return {"status":"found" if records else "no_accessible_execution",
                    "records":[asdict(row) for row in records]}
        finally:
            multi.close()

    def historian_read(args: dict, context: RunContext) -> dict:
        multi = MultiSourceService.from_defaults(root)
        try:
            interval=Interval(args["start"],args["end"])
            samples=multi.historian.read(set(args["point_ids"]),interval,
                            tenant_id=context.tenant_id,groups=context.groups,max_samples=100)
            return {"status":"found" if samples else "no_accessible_samples","samples":[
                {"sample_id":s.sample_id,"point_id":s.point_id,"timestamp":s.timestamp,
                 "value":s.value,"kind":s.kind,"unit":s.unit,"quality":s.quality,
                 "source_uri":s.source_uri} for s in samples]}
        finally:
            multi.close()

    def batch_assess(args: dict, context: RunContext) -> dict:
        multi = MultiSourceService.from_defaults(root)
        try:
            return multi.assess_batch(args["batch_id"],tenant_id=context.tenant_id,
                groups=context.groups,kind=args.get("kind","vibration_velocity"),
                spacing_seconds=args.get("spacing_seconds",600))
        finally:
            multi.close()

    tools = [
        ReadOnlyTool("document.search",document_search),
        ReadOnlyTool("entity.resolve",entity_resolve),
        ReadOnlyTool("graph.traverse",graph_traverse),
        ReadOnlyTool("mes.by_batch",mes_by_batch),
        ReadOnlyTool("historian.read",historian_read),
        ReadOnlyTool("batch.assess",batch_assess),
    ]
    return ToolRegistry(tools)
