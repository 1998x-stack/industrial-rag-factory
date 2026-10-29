"""Deterministic, explicitly limited claim verification on structured synthetic evidence.

No LLM verdict and no document snippet can make a numeric claim authoritative.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable

from industrial_rag_factory.multisource.units import compare_upper

from .contracts import Claim, ClaimResult, EvidenceBundle, EvidenceItem

REQUIRED_KINDS = {"identity_mapping","mes_execution","graph_relation",
                  "specification","measurement"}
LIMIT = re.compile(r"^upper limit ([0-9]+(?:\\.[0-9]+)?) (mm/s|m/s); (vibration_velocity)$")
SAMPLE = re.compile(r"^([0-9]+(?:\\.[0-9]+)?) (mm/s|m/s); exceeded=(True|False)$")


@dataclass(frozen=True)
class Audit:
    acceptable: bool
    conflicts: tuple[str,...]
    problems: tuple[str,...]
    relevant_ids: tuple[str,...]


def audit_bundle(bundle: EvidenceBundle) -> Audit:
    problems=[]
    conflicts=[]
    seen: dict[str,EvidenceItem]={}
    for item in bundle.items:
        if item.id in seen and item!=seen[item.id]:
            conflicts.append("Evidence ID collision with incompatible payload")
        seen[item.id]=item
        if not item.source_uri or not item.source_record_id:
            problems.append("Evidence provenance missing")
        if item.kind=="document_chunk" and "Context only" not in item.note:
            problems.append("Document text cannot be promoted into specification authority")
    kinds={item.kind for item in bundle.items}
    numeric=[x for x in bundle.items if x.kind=="measurement"]
    # Independently recompute each sample exceedance against a single applicable
    # synthetic approved specification. The upstream S03 checks timing/quality.
    specs=[item for item in bundle.items if item.kind=="specification"]
    spec_match = LIMIT.fullmatch(specs[0].value) if len(specs)==1 else None
    if spec_match is None:
        problems.append("No unique parsable approved measurement limit")
    detected=[]
    for item in numeric:
        parsed=SAMPLE.fullmatch(item.value)
        if parsed is None:
            problems.append("Measurement quantity/flag invalid")
            continue
        observed=parsed.group(3)=="True"
        detected.append(observed)
        if spec_match:
            try:
                exceeds, _, _=compare_upper(
                    parsed.group(1),parsed.group(2),spec_match.group(3),
                    spec_match.group(1),spec_match.group(2))
                if exceeds!=observed:
                    conflicts.append("Measurement flag contradicts specification comparison")
            except ValueError:
                problems.append("Measurement has incompatible unit or quantity kind")
    mes=[item for item in bundle.items if item.kind=="mes_execution"]
    if not mes or not all(
        item.value.startswith(bundle.batch_id+" ") and
        any((" "+equipment+" ") in item.value for equipment in bundle.equipment)
        for item in mes
    ):
        problems.append("MES provenance does not match batch and equipment")
    if bundle.status=="insufficient_evidence":
        problems.append("Structured assessment reports insufficient evidence")
    if bundle.execution_state!="completed":
        problems.append("DAG execution incomplete")
    if not REQUIRED_KINDS <= kinds:
        problems.append("Missing identity/MES/graph/specification/measurement provenance")
    if len(numeric)!=bundle.valid_sample_count or sum(detected)!=bundle.exceedance_count:
        problems.append("Sample evidence inconsistent with reported counts")
    if (bundle.exceedance_count>bundle.valid_sample_count or
        bundle.status=="within_observed_limits" and bundle.exceedance_count>0 or
        bundle.status=="observed_exceedance" and bundle.exceedance_count==0):
        conflicts.append("Assessment counts contradict reported status")
    if not bundle.equipment:
        problems.append("No validated equipment identity")
    ids=tuple(sorted(x.id for x in bundle.items if x.kind in REQUIRED_KINDS))
    return Audit(not problems and not conflicts,tuple(sorted(set(conflicts))),
                 tuple(sorted(set(problems))),ids)


def _actual(bundle: EvidenceBundle, predicate: str):
    if predicate=="batch_exceedance_count":
        return bundle.exceedance_count
    if predicate=="batch_valid_sample_count":
        return bundle.valid_sample_count
    if predicate=="batch_has_exceedance":
        return bundle.exceedance_count>0
    if predicate=="batch_within_observed_limits":
        return bundle.status=="within_observed_limits"
    if predicate=="batch_equipment":
        return None if len(bundle.equipment)!=1 else bundle.equipment[0]
    return None


def verify_claims(
    claims: Iterable[Claim], bundles: Iterable[EvidenceBundle]
) -> dict:
    """Check typed claims against trusted-source adapter outputs, never free text."""
    claims=tuple(claims)
    bundles=tuple(bundles)
    if len(claims)>50 or len({c.claim_id for c in claims})!=len(claims):
        raise ValueError("Claim list too long or duplicate claim IDs")
    by_batch:dict[str,list[EvidenceBundle]]={}
    for bundle in bundles:
        by_batch.setdefault(bundle.batch_id,[]).append(bundle)
    answers=[]
    for claim in claims:
        matching=by_batch.get(claim.subject,[])
        if not matching:
            answers.append(ClaimResult(claim,"insufficient_evidence",(),(),
                          ("No evidence bundle for this batch.",)))
            continue
        # Different derived values from multiple read-only tools: never pick one.
        signatures={(b.status,b.exceedance_count,b.valid_sample_count,
                     b.equipment,b.rejected_sample_count) for b in matching}
        if len(signatures)>1:
            answers.append(ClaimResult(claim,"conflicting",(),(),
                          ("Independent structured assessments conflict.",)))
            continue
        bundle=matching[0]
        audits=[audit_bundle(x) for x in matching]
        if any(a.conflicts for a in audits):
            answers.append(ClaimResult(claim,"conflicting",(),(),
                          tuple(sorted({reason for a in audits for reason in a.conflicts}))))
            continue
        audit=audits[0]
        present={item.id for item in bundle.items}
        if any(cid not in present for cid in claim.citation_ids):
            answers.append(ClaimResult(claim,"insufficient_evidence",(),(),
                          ("Citation ID not in the authorized evidence bundle.",)))
            continue
        if claim.citation_ids and not set(claim.citation_ids).intersection(audit.relevant_ids):
            answers.append(ClaimResult(claim,"insufficient_evidence",(),(),
                          ("Citations do not refer to relevant structured sources.",)))
            continue
        if claim.predicate in ("equipment_fault_cause","batch_product_conformity"):
            answers.append(ClaimResult(claim,"insufficient_evidence",(),(),
                          ("Measurements do not establish fault causality or product conformity.",)))
            continue
        if not audit.acceptable:
            answers.append(ClaimResult(claim,"insufficient_evidence",(),(),
                          audit.problems))
            continue
        actual=_actual(bundle,claim.predicate)
        if actual is None:
            answers.append(ClaimResult(claim,"insufficient_evidence",(),(),
                          ("No deterministic rule available for this claim.",)))
            continue
        # At minimum, a numerical claim needs the measurement and approved spec.
        useful=tuple(sorted(x.id for x in bundle.items if x.kind in REQUIRED_KINDS))
        status="supported" if actual==claim.expected else "refuted"
        answers.append(ClaimResult(
            claim,status,useful if status=="supported" else (),
            useful if status=="refuted" else (),
            ("Verified only against synthetic, scoped, read-only structured fixtures.",)))
    statuses={x.status for x in answers}
    abstain=not answers or any(x.status!="supported" for x in answers)
    return {"status":"supported" if statuses=={"supported"} else
            "conflicting" if "conflicting" in statuses else
            "refuted" if "refuted" in statuses else "insufficient_evidence",
            "abstain":abstain,"claims":[x.to_dict() for x in answers],
            "limitations":[
                "Structural verification against synthetic adapter outputs only.",
                "No independent source authenticity, general textual entailment, or fault diagnosis.",
            ]}
