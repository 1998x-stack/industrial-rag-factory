"""Strict schema for LLM-proposed, deterministic read-only query plans."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from industrial_rag_factory.semantic.graph import ALLOWED_PREDICATES
from industrial_rag_factory.semantic.identity import instant

STEP_RE = re.compile(r"^[a-z][a-z0-9_]{0,39}$")
REF_RE = re.compile(r"^([a-z][a-z0-9_]{0,39})\.([a-zA-Z_][a-zA-Z0-9_]*(?:\.[a-zA-Z_0-9]+)*)$")
TOOLS = {
    "document.search": ({"question"}, {"question", "mode", "top_k"}),
    "entity.resolve": ({"external_id"}, {"external_id", "system", "at_time"}),
    "graph.traverse": ({"subject", "steps"}, {"subject", "steps", "at_time"}),
    "mes.by_batch": ({"batch_id"}, {"batch_id"}),
    "historian.read": ({"point_ids", "start", "end"}, {"point_ids", "start", "end"}),
    "batch.assess": ({"batch_id"}, {"batch_id", "kind", "spacing_seconds"}),
}


class PlanValidationError(ValueError):
    """Invalid plans are never dispatched to tools."""


def ref_info(value: Any) -> tuple[str, str] | None:
    if not isinstance(value, dict) or set(value) != {"$ref"}:
        return None
    match = REF_RE.fullmatch(str(value["$ref"]))
    if not match:
        raise PlanValidationError("Invalid reference path")
    return match.group(1), match.group(2)


def collect_refs(value: Any) -> set[str]:
    result: set[str] = set()
    if isinstance(value, dict):
        ref = ref_info(value)
        if ref:
            result.add(ref[0])
        else:
            if "$ref" in value:
                raise PlanValidationError("References must have only a $ref key")
            for nested in value.values():
                result.update(collect_refs(nested))
    elif isinstance(value, list):
        for nested in value:
            result.update(collect_refs(nested))
    return result


def validate_args(tool: str, args: dict, *, allow_refs: bool = True) -> None:
    if tool not in TOOLS or not isinstance(args, dict):
        raise PlanValidationError("Unknown or invalid tool arguments")
    required, allowed = TOOLS[tool]
    if not required <= set(args) or set(args) - allowed:
        raise PlanValidationError(f"{tool}: missing or forbidden parameter")
    if any(key in args for key in ("tenant_id", "groups", "access_groups", "principal")):
        raise PlanValidationError("Authorization context cannot be passed in plan arguments")
    for key, value in args.items():
        if allow_refs and ref_info(value):
            continue
        if key in {"question", "external_id", "subject", "batch_id", "system", "kind",
                   "start", "end", "at_time"}:
            if not isinstance(value, str) or not value.strip() or len(value) > 2048:
                raise PlanValidationError(f"Invalid {key}")
            if key in ("at_time", "start", "end"):
                instant(value)
            if key == "kind" and value not in ("vibration_velocity", "temperature"):
                raise PlanValidationError("Unsupported quantity kind")
            if key == "system" and value not in ("ERP", "MES", "SCADA", "CMMS"):
                raise PlanValidationError("Unsupported identity source system")
        elif key in ("top_k", "spacing_seconds"):
            maximum = 10 if key == "top_k" else 86400
            if type(value) is not int or not 1 <= value <= maximum:
                raise PlanValidationError(f"Invalid {key}")
        elif key == "mode":
            if value not in ("sparse", "dense", "hybrid"):
                raise PlanValidationError("Invalid retrieval mode")
        elif key == "steps":
            if not isinstance(value, list) or not 1 <= len(value) <= 5:
                raise PlanValidationError("Graph steps must be a nonempty list of <=5 hops")
            for hop in value:
                if not isinstance(hop, dict) or set(hop) != {"predicate", "direction"}:
                    raise PlanValidationError("Invalid graph hop schema")
                if hop["predicate"] not in ALLOWED_PREDICATES or hop["direction"] not in ("in", "out"):
                    raise PlanValidationError("Graph predicate/direction not allowlisted")
        elif key == "point_ids":
            if not isinstance(value, list) or not 1 <= len(value) <= 30 or not all(
                isinstance(x, str) and re.fullmatch(r"[A-Za-z0-9_-]{1,80}", x)
                for x in value
            ):
                raise PlanValidationError("Invalid measurement point identifiers")
        else:
            raise PlanValidationError(f"Unsupported {key}")
    if not allow_refs and "start" in args and "end" in args:
        if instant(args["start"]) >= instant(args["end"]):
            raise PlanValidationError("Invalid historian time interval")


@dataclass(frozen=True)
class PlanStep:
    id: str
    tool: str
    args: dict[str, Any]
    depends_on: tuple[str, ...] = ()
    timeout_ms: int = 2000
    max_retries: int = 0

    @classmethod
    def from_dict(cls, raw: dict) -> "PlanStep":
        if not isinstance(raw, dict) or set(raw) - {
            "id", "tool", "args", "depends_on", "timeout_ms", "max_retries"
        } or not {"id", "tool", "args"} <= set(raw):
            raise PlanValidationError("Unexpected or missing step keys")
        ident, tool, args = raw["id"], raw["tool"], raw["args"]
        if not isinstance(ident, str) or not STEP_RE.fullmatch(ident):
            raise PlanValidationError("Invalid step id")
        if tool not in TOOLS:
            raise PlanValidationError("Tool not on read-only allowlist")
        deps = raw.get("depends_on", [])
        if not isinstance(deps, list) or not all(isinstance(x, str) for x in deps):
            raise PlanValidationError("Dependencies must be a list of IDs")
        timeout = raw.get("timeout_ms", 2000)
        retries = raw.get("max_retries", 0)
        if type(timeout) is not int or not 50 <= timeout <= 5000:
            raise PlanValidationError("Step timeout outside [50,5000] ms")
        if type(retries) is not int or not 0 <= retries <= 1:
            raise PlanValidationError("At most one safe retry allowed")
        validate_args(tool, args)
        return cls(ident, tool, args, tuple(deps), timeout, retries)

    def to_dict(self) -> dict:
        return {"id": self.id, "tool": self.tool, "args": self.args,
                "depends_on": list(self.depends_on), "timeout_ms": self.timeout_ms,
                "max_retries": self.max_retries}


@dataclass(frozen=True)
class QueryPlan:
    intent: str
    steps: tuple[PlanStep, ...]
    required_evidence: tuple[str, ...] = ()
    unknowns: tuple[str, ...] = ()
    version: str = "stage04-v1"

    @classmethod
    def from_dict(cls, raw: dict) -> "QueryPlan":
        if not isinstance(raw, dict) or set(raw) - {
            "intent", "steps", "required_evidence", "unknowns", "version"
        } or not {"intent", "steps"} <= set(raw):
            raise PlanValidationError("Unexpected or missing plan keys")
        if not isinstance(raw["intent"], str) or not raw["intent"].strip():
            raise PlanValidationError("Invalid plan intent")
        steps = raw["steps"]
        if not isinstance(steps, list) or not 1 <= len(steps) <= 8:
            raise PlanValidationError("Plan must have between 1 and 8 steps")
        parsed = tuple(PlanStep.from_dict(x) for x in steps)
        ids = {x.id for x in parsed}
        if len(ids) != len(parsed):
            raise PlanValidationError("Duplicate step IDs")
        for item in parsed:
            deps = set(item.depends_on)
            if len(deps) != len(item.depends_on) or item.id in deps or not deps <= ids:
                raise PlanValidationError("Missing, self or duplicate dependencies")
            if not collect_refs(item.args) <= deps:
                raise PlanValidationError("Reference must declare its step dependency")
        # A full topological sort validates dependency cycles, without trusting step order.
        remaining = {s.id: set(s.depends_on) for s in parsed}
        scheduled: list[str] = []
        while remaining:
            ready = [s.id for s in parsed if s.id in remaining and not remaining[s.id]]
            if not ready:
                raise PlanValidationError("Dependency cycle")
            scheduled.extend(ready)
            for name in ready:
                remaining.pop(name)
            for needs in remaining.values():
                needs.difference_update(ready)
        fields = (raw.get("required_evidence", []), raw.get("unknowns", []))
        for field_value in fields:
            if not isinstance(field_value, list) or len(field_value) > 20 or not all(
                isinstance(x, str) and len(x) <= 256 for x in field_value
            ):
                raise PlanValidationError("Invalid evidence/unknown list")
        if raw.get("version", "stage04-v1") != "stage04-v1":
            raise PlanValidationError("Unsupported plan contract version")
        return cls(raw["intent"], parsed, tuple(fields[0]), tuple(fields[1]))

    def ordered_steps(self) -> tuple[PlanStep, ...]:
        remaining = {s.id: s for s in self.steps}
        done: set[str] = set()
        order = []
        while remaining:
            for step in self.steps:
                if step.id in remaining and set(step.depends_on) <= done:
                    order.append(step)
                    done.add(step.id)
                    del remaining[step.id]
                    break
        return tuple(order)

    def to_dict(self) -> dict:
        return {"intent": self.intent, "steps": [x.to_dict() for x in self.steps],
                "required_evidence": list(self.required_evidence),
                "unknowns": list(self.unknowns), "version": self.version}
