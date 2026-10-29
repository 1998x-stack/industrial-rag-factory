# Stage 05 — EvidenceBundle, ClaimGraph and deterministic verification

## Outcome

Deliver the pipeline that transforms **trusted Stage 04 read-only tool results**
into machine-inspectable structured claims, evidence support/refutation edges,
conflict flags and conservative abstention. The target is an offline industrial
research baseline on synthetic data, not general entailment certification.

## Architecture

    Stage 01 document evidence / Stage 02 typed graph
                           + Stage 03 MES/historian/specs
                           |
                 trusted Stage 04 read-only QueryPlan
                           |
                    DAG execution and trace
                           |
              EvidenceBundle normalization
                           |
             provenance/identity/unit checks
                           |
              type-constrained ClaimGraph
                           |
       supported | refuted | conflicting | insufficient_evidence
                         + abstain

Stage 05 does not accept client-selected plans, authority records or evidence.
The Flask endpoint accepts only a canonical batch ID and optional bounded
candidate typed claims. All data comes from the server-authorized read-only
fixture adapters.

## Code categories

| Component | Contract | Guarantee |
| --- | --- | --- |
| grounding.contracts | Claim, EvidenceItem, EvidenceBundle, ClaimResult | Strict whitelist and bounded fields |
| grounding.service | Trusted DAG execution and claim selection | No user-supplied evidence or arbitrary tool |
| grounding.verifier | Evidence audit and typed claim decision | Provenance, count, units, conflict, citation checks |
| grounding.evaluation | Gold claim statuses | Deterministic fixture accuracy |
| grounding ClaimGraph | Claim/evidence nodes and edges | Separates support vs refutation |
| Flask/CLI | grounding-verify, grounding-evaluate | Local development only |

## Typed claim predicates

- batch_exceedance_count: nonnegative integer count of good synthetic samples
  above the approved fixture specification.
- batch_valid_sample_count: number of good samples accepted by Stage 03.
- batch_has_exceedance: observed exceedance on the accepted sampling grid.
- batch_within_observed_limits: all accepted samples meet the fixture upper bound.
- batch_equipment: canonical equipment ID for a single known batch execution.
- equipment_fault_cause: **always insufficient** until a dedicated causal
  knowledge source and validation framework exists.
- batch_product_conformity: **always insufficient** from vibration data alone.

No user may invent arbitrary predicates or infer safety-critical actions.

## Evidence qualification

1. Require an actual Stage 04 tool step named batch.assess, marked succeeded,
   with an output batch ID equal to the step's requested canonical ID.
2. Reject incomplete DAG execution for positive support.
3. Require sourced MES, approved identity mapping, RDF graph relation,
   specification and historian sample records.
4. Verify evidence ID integrity and refuse a reused ID with conflicting content.
5. Recompute each sample's reported exceedance against the unique parseable
   structured specification using approved quantity-kind unit conversion.
6. Reconcile valid sample count and exceedance count against the evidence list;
   verify the MES record matches the requested batch/equipment.
7. Check claim citation IDs are present and reference supporting structured
   evidence rather than document-only context.
8. Treat conflicting independent assessments as conflicting, rather than
   choosing a winner.
9. Refute explicit false numerical/equipment claims; abstain for unsupported
   causal claims, missing data, unknown sources and quality gaps.

## Example synthetic behavior

| Claim | Expected decision | Why |
| --- | --- | --- |
| B-104 has 2 exceeding observations | supported | 2/4 samples over synthetic limit |
| B-104 has 0 exceeding observations | refuted | disagrees with sample evidence |
| B-105 readings within observed limits | supported | 3/3 synthetic samples accepted |
| B-999 had a documented safe run | insufficient_evidence | missing authorized MES evidence |
| B-104 has bearing failure | insufficient_evidence | observed threshold does not imply cause |
| B-104 output is defective | insufficient_evidence | no product conformance evidence |

These outcomes reflect only fixture logic; they are NOT industrial operational
recommendations or real diagnostic determinations.

## Runbook

    pip install -e '.[api,llm,pdf,docx,ontology,dev]'
    irf grounding-verify B-104
    irf grounding-verify B-105
    irf grounding-verify B-999
    irf grounding-evaluate
    python scripts/stage05_evaluate.py
    pytest -q
    ruff check src tests

Flask: POST /v1/grounding/verify with JSON {"batch_id":"B-104"}.
Optional claims may be supplied as typed JSON; evidence, access groups, tenant,
planner or executable plans must never be accepted. Still development-only
and loopback-bound, without production identity authentication.

## Acceptance and evaluation

- [x] Bounded and typed EvidenceBundle, Claim, ClaimResult contracts.
- [x] Explicit ClaimGraph support and refutation edges.
- [x] Trusted Stage 04 execution-to-evidence integration.
- [x] Verified exact citation IDs and mandatory source-provenance categories.
- [x] Decimal-based synthetic sample/spec comparison independent of flags.
- [x] Correct supported/refuted/conflicting/insufficient decisions.
- [x] Conservative refusal for missing source, fault causes and product quality.
- [x] Injection-like document text cannot change structured numerical decision.
- [x] Negative tests for forged citations, inconsistent samples and ACL scope.
- [x] Golden claim benchmark with reproducible JSON output and dataset hash.
- [ ] General natural-language claim extraction and entailment quality.
- [ ] Source authenticity signatures and full bitemporal lineage.
- [ ] Applicability verified against independent enterprise authority registry.
- [ ] Production IAM and policy revocation / redaction: Stage 06.
- [ ] Statistical uncertainty intervals and full ablation panels: Stage 07.

## Limitations and audit posture

The evidence adapters use synthetic fixtures. Source URI/record ID fields are
provenance *claims* but are not cryptographically verified; SHA-256 of an
evaluation gold file is a reproducibility aid, not origin attestation.
Automatic claim candidates are derived from the same structured tool results
and therefore mostly test internal consistency rather than independent
ground truth. Independent true/false claims in gold evaluation expose that
distinction. Report benchmark accuracy only for this fixed simulated dataset.

A quotation or citation does not by itself establish physical truth. The
verifier checks a small typed claim language, not open-ended factual entailment.
The framework cannot infer maintenance necessity, component failure,
industrial safety, or batch quality from threshold exceedance alone.

## Stage 06 handoff

Introduce authenticated principals, source-level ACL, policy revocation,
source authenticity, audit correlation IDs and permission redaction across
tool results and evidence nodes. Preserve explicit abstention on incomplete
permissions. Stage 07 will benchmark ablations and statistical reliability.
