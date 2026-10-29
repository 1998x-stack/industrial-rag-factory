"""Bounded, explicit claim and evidence schemas (no arbitrary executable statements)."""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from typing import Any

CLAIM_TYPES = {
    "batch_exceedance_count", "batch_valid_sample_count",
    "batch_has_exceedance", "batch_within_observed_limits",
    "batch_equipment", "equipment_fault_cause", "batch_product_conformity",
}
CLAIM_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_-]{0,63}$")
BATCH_RE = re.compile(r"^B-[0-9]{2,8}$")


@dataclass(frozen=True)
class Claim:
    claim_id: str
    subject: str
    predicate: str
    expected: int | bool | str
    citation_ids: tuple[str, ...] = ()

    @classmethod
    def from_dict(cls, value: dict) -> "Claim":
        if not isinstance(value, dict) or set(value) - {
            "claim_id", "subject", "predicate", "expected", "citation_ids"
        } or not {"claim_id", "subject", "predicate", "expected"} <= set(value):
            raise ValueError("Invalid claim schema")
        ident, subject, predicate = (
            value["claim_id"], value["subject"], value["predicate"]
        )
        if not isinstance(ident, str) or not CLAIM_RE.fullmatch(ident):
            raise ValueError("Invalid claim_id")
        if not isinstance(subject, str) or not BATCH_RE.fullmatch(subject):
            raise ValueError("Only canonical batch IDs are supported in Stage 05")
        if predicate not in CLAIM_TYPES:
            raise ValueError("Predicate outside supported factual claims")
        expected = value["expected"]
        if predicate in ("batch_exceedance_count", "batch_valid_sample_count"):
            if type(expected) is not int or not 0 <= expected <= 1000:
                raise ValueError("Expected a nonnegative integer sample count")
        elif predicate in ("batch_has_exceedance", "batch_within_observed_limits",
                           "batch_product_conformity"):
            if type(expected) is not bool:
                raise ValueError("Expected a boolean factual claim")
        else:
            if not isinstance(expected, str) or not 1 <= len(expected) <= 128:
                raise ValueError("Expected a short string")
        citations=value.get("citation_ids",[])
        if (not isinstance(citations,list) or len(citations)>50 or
            not all(isinstance(x,str) and 1 <= len(x)<=128 for x in citations) or
            len(set(citations))!=len(citations)):
            raise ValueError("Invalid citation IDs")
        return cls(ident,subject,predicate,expected,tuple(citations))

    def to_dict(self) -> dict:
        return {**asdict(self),"citation_ids":list(self.citation_ids)}


@dataclass(frozen=True)
class EvidenceItem:
    id: str
    kind: str
    source_uri: str
    source_record_id: str
    entity_id: str
    time: str | None
    value: str
    note: str

    @classmethod
    def from_dict(cls, value: dict) -> "EvidenceItem":
        required={"id","kind","source_uri","source_record_id","entity_id","time","value"}
        if not isinstance(value,dict) or not required <= set(value):
            raise ValueError("Malformed evidence record")
        for key in required-{"time"}:
            if not isinstance(value[key],str) or not value[key] or len(value[key])>4096:
                raise ValueError("Malformed evidence field")
        if value["time"] is not None:
            from industrial_rag_factory.semantic.identity import instant
            if not isinstance(value["time"],str):
                raise ValueError("Malformed evidence timestamp")
            instant(value["time"])
        return cls(*(value[k] for k in (
            "id","kind","source_uri","source_record_id","entity_id","time","value"
        )),note=str(value.get("note",""))[:2000])

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class EvidenceBundle:
    batch_id: str
    status: str
    equipment: tuple[str, ...]
    exceedance_count: int
    valid_sample_count: int
    rejected_sample_count: int
    items: tuple[EvidenceItem, ...]
    limitations: tuple[str, ...]
    execution_state: str = "completed"
    source_tool: str = "batch.assess"

    @classmethod
    def from_assessment(cls, data: dict, *, execution_state: str = "completed"
                        ) -> "EvidenceBundle":
        if not isinstance(data,dict) or not BATCH_RE.fullmatch(str(data.get("batch_id",""))):
            raise ValueError("Assessment requires a canonical batch ID")
        if data.get("status") not in (
            "observed_exceedance","within_observed_limits","insufficient_evidence"
        ):
            raise ValueError("Unknown assessment state")
        counts=[data.get(key) for key in (
            "exceedance_count","valid_sample_count","rejected_sample_count"
        )]
        if any(type(n) is not int or not 0 <= n <= 1000 for n in counts):
            raise ValueError("Invalid sample counts")
        if not isinstance(data.get("equipment"),list) or not all(
            isinstance(x,str) and len(x)<=128 for x in data["equipment"]
        ):
            raise ValueError("Invalid equipment list")
        raw=data.get("evidence")
        if not isinstance(raw,list) or len(raw)>1000:
            raise ValueError("Invalid evidence collection")
        items=tuple(EvidenceItem.from_dict(item) for item in raw)
        limitations=data.get("limitations",[])
        if not isinstance(limitations,list) or not all(
            isinstance(x,str) for x in limitations
        ):
            raise ValueError("Invalid limitations")
        return cls(data["batch_id"],data["status"],tuple(data["equipment"]),
                   *counts,items,tuple(limitations),execution_state)

    def to_dict(self) -> dict:
        return {"batch_id":self.batch_id,"status":self.status,
                "equipment":list(self.equipment),
                "exceedance_count":self.exceedance_count,
                "valid_sample_count":self.valid_sample_count,
                "rejected_sample_count":self.rejected_sample_count,
                "evidence":[item.to_dict() for item in self.items],
                "limitations":list(self.limitations),
                "execution_state":self.execution_state,"source_tool":self.source_tool}


@dataclass(frozen=True)
class ClaimResult:
    claim: Claim
    status: str
    supporting: tuple[str, ...]
    refuting: tuple[str, ...]
    reasons: tuple[str, ...]

    def to_dict(self) -> dict:
        return {"claim":self.claim.to_dict(),"status":self.status,
                "supporting_evidence_ids":list(self.supporting),
                "refuting_evidence_ids":list(self.refuting),
                "reasons":list(self.reasons)}


def extract_assessments(execution: dict) -> list[EvidenceBundle]:
    """Only accept outputs of successfully executed, registered batch.assess steps.

    This function normalizes a previously obtained executor result; callers
    must not accept externally supplied executor JSON as authoritative.
    """
    if not isinstance(execution,dict):
        raise ValueError("Executor output must be an object")
    plan=execution.get("plan")
    results=execution.get("results")
    states=execution.get("step_status")
    if not isinstance(plan,dict) or not isinstance(results,dict) or not isinstance(states,dict):
        raise ValueError("Executor output must contain plan, results and step status")
    from industrial_rag_factory.agent.contracts import QueryPlan
    checked=QueryPlan.from_dict(plan)
    bundles=[]
    for step in checked.steps:
        if step.tool != "batch.assess":
            continue
        if states.get(step.id)!="succeeded" or step.id not in results:
            continue
        data=results[step.id]
        bundle=EvidenceBundle.from_assessment(
            data,execution_state=str(execution.get("status","failed")))
        # Bind the result to its actual plan argument, not any batch ID it invents.
        if isinstance(step.args.get("batch_id"),str) and step.args["batch_id"]!=bundle.batch_id:
            raise ValueError("Assessment output batch does not match executed plan")
        bundles.append(bundle)
    return bundles
