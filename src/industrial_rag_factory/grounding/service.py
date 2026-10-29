"""Stage 05 integration: execute trusted Stage 04 plan, then verify claims.

No caller-supplied source evidence or arbitrary plan is accepted by this façade.
"""
from __future__ import annotations

from pathlib import Path

from industrial_rag_factory.agent.contracts import QueryPlan
from industrial_rag_factory.agent.runner import DAGRunner
from industrial_rag_factory.agent.tools import RunContext, build_tool_registry
from industrial_rag_factory.config import Settings

from .contracts import BATCH_RE, Claim, EvidenceBundle, extract_assessments
from .verifier import verify_claims


def trusted_batch_plan(batch_id: str) -> QueryPlan:
    if not isinstance(batch_id, str) or not BATCH_RE.fullmatch(batch_id):
        raise ValueError("Invalid canonical batch ID")
    return QueryPlan.from_dict({
        "intent":"batch_evidence_verification","version":"stage04-v1",
        "required_evidence":["mes.by_batch","batch.assess"],
        "steps":[
            {"id":"mes","tool":"mes.by_batch","args":{"batch_id":batch_id}},
            {"id":"assessment","tool":"batch.assess","args":{"batch_id":batch_id},
             "depends_on":["mes"]},
        ],
    })


def proposed_observation_claims(bundle: EvidenceBundle) -> list[Claim]:
    """Stage 05 fixture candidates are derived, not an independent LLM assertion."""
    claims=[
        Claim("count",bundle.batch_id,"batch_exceedance_count",bundle.exceedance_count),
        Claim("valid",bundle.batch_id,"batch_valid_sample_count",bundle.valid_sample_count),
        Claim("exceedance",bundle.batch_id,"batch_has_exceedance",
              bundle.exceedance_count>0),
    ]
    if len(bundle.equipment)==1:
        claims.append(Claim("asset",bundle.batch_id,"batch_equipment",bundle.equipment[0]))
    return claims


class GroundingService:
    def __init__(self, settings: Settings | None = None, *,
                 root: str | Path = ".", registry=None):
        self.settings=settings or Settings.from_env()
        self.registry=registry or build_tool_registry(self.settings,root)
        self._owns_registry=registry is None
        self.runner=DAGRunner(self.registry)

    def capture_batch(self, batch_id: str) -> tuple[dict,list[EvidenceBundle]]:
        plan=trusted_batch_plan(batch_id)
        execution=self.runner.run(
            plan,RunContext(self.settings.tenant_id,self.settings.groups))
        execution["plan"]=plan.to_dict()
        bundles=extract_assessments(execution)
        return execution,bundles

    def verify_batch(self, batch_id: str, claims: list[Claim] | None = None) -> dict:
        execution,bundles=self.capture_batch(batch_id)
        if claims is None:
            claims=proposed_observation_claims(bundles[0]) if bundles else [
                Claim("missing",batch_id,"batch_has_exceedance",True)
            ]
        if not claims or any(claim.subject != batch_id for claim in claims):
            raise ValueError("Claim subjects must match the selected batch")
        verdict=verify_claims(claims,bundles)
        return {"stage":"S05","batch_id":batch_id,
                "verification":verdict,
                "evidence_bundle":[bundle.to_dict() for bundle in bundles],
                "execution":{"status":execution["status"],
                             "trace":execution["trace"]},
                "summary":"Only the synthetic structured observations have been checked; "
                          "this is not an equipment diagnosis or product conformity decision."}

    def close(self) -> None:
        if self._owns_registry:
            self.registry.close()
