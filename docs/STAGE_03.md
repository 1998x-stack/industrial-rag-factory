# Stage 03 — Multi-source Industrial Retrieval and Temporal Evidence

## Objective

Create a reproducible, read-only synthetic industrial evidence pipeline joining
MES, approved asset identity, IOF-aligned graph, historian measurements and
effective specifications. Stage 01 document evidence remains an optional,
separate, *context-only* channel. This stage does not claim an autonomous
Agent Query Planner, live device connectivity, or proof of equipment safety.

## Code categories and contracts

| Component | Contract | Verification |
| --- | --- | --- |
| multisource.contracts | Half-open, timezone-aware intervals; structured evidence | End exclusive, UTC-offset comparisons |
| multisource.sql | Prepared SQL by batch with row-budget and tenant/group scope | No free-form SQL |
| semantic.identity | External ERP ID to approved canonical asset | Matched at both process boundaries |
| semantic.graph | Allowlisted graph predicate and provenance | Scoped at process and sample time |
| multisource.historian | Bounded synthetic samples | Group, quality, cadence, timestamp |
| multisource.specs | Approved process specification | Equipment, mode, kind, full interval |
| multisource.units | Decimal unit conversion | Explicit quantity-kind/unit whitelist |
| multisource.service | Read-only evidence join | Cannot invent missing evidence |
| multisource.evaluation | Gold fixture benchmark | Reproducible and LLM-free |

## Online execution sequence

1. Accept a canonical batch ID; tenant and group are server-controlled.
2. Use parameterized SQL to load bounded, authorized MES execution rows.
3. Resolve original external ERP asset ID into canonical graph entity and
   compare with MES canonical ID at both ends of the interval.
4. Validate batch-to-execution, work order, equipment and specification RDF
   relations; record source relation IDs.
5. Identify the unique approved, time-applicable specification for equipment,
   operation mode and quantity kind.
6. Retrieve bounded historian samples, checking each timestamp against both
   directions of the effective sensor-to-asset graph mapping.
7. Validate quality and exact expected sample cadence; normalize physical
   units with a small Decimal conversion registry.
8. Return source-specific evidence and observation status. If any required
   sample or prerequisite is missing, return insufficient_evidence.
9. Append authorized Stage 01 document hits as context-only optional evidence
   when explicitly supplied through the Python service interface.

## Example synthetic scenarios

| Batch | Equipment | Mock samples | Expected outcome |
| --- | --- | --- | --- |
| B-104 | CUT-03 | 4 good readings, 2 above 4.5 mm/s | observed_exceedance |
| B-105 | CUT-04 | 3 good readings under 3.2 mm/s | within_observed_limits |
| B-999 | None | No authorized process | insufficient_evidence |

These are teaching fixtures; none of the measurements or specifications
represents real-world operating limits or licensed maintenance guidance.

## Operational runbook

    pip install -e '.[api,llm,pdf,docx,ontology,dev]'
    irf multisource-assess B-104 --kind vibration_velocity --spacing-seconds 600
    irf multisource-assess B-105
    irf multisource-evaluate --gold datasets/stage03/gold.jsonl
    python scripts/stage03_evaluate.py
    python -m pytest -q
    python -m ruff check src tests

The HTTP development service exposes POST /v1/multisource/assess with
{"batch_id":"B-104"}. It is loopback-only and unauthenticated;
DO NOT expose it publicly or connect confidential OT sources.

## Stage acceptance

- [x] Fixed, parameterized, tenant-scoped SQLite MES read model.
- [x] Original ERP ID requires approved temporal identity mapping.
- [x] Time-valid graph path for batch/work-order/equipment/specification.
- [x] Historian samples checked against sensor mapping at individual timestamps.
- [x] Quality, missing data, wrong sensor and incompatible units fail closed.
- [x] Decimal conversion for explicitly approved quantity-kind units.
- [x] No multiple competing approved specifications for the same query.
- [x] Provenance record IDs included in each evidence item.
- [x] CLI, local Flask, synthetic gold evaluation and regression tests.
- [ ] Fully audited bitemporal transaction-time history.
- [ ] Irregular sampling/time-weighted severity analytics.
- [ ] Real IAM, MES/OPC UA/historian connectors, industrial safety approval.
- [ ] Stage 04 planner DAG and Stage 05 claim-level semantic verification.

## Data and source safety

The structured values and links are simulated. No arbitrary SQL or SPARQL is
accepted. No autonomous OT control path exists. Observed threshold exceedance
does not imply a specific cause, failure diagnosis, downstream product quality
or recommended physical control action.

## Future stages

S04 adds typed read-only query plans and deterministic execution DAGs, bounded
tool budgets, explicit retries and timeout contracts. S05 adds supported,
refuted, conflicting and insufficient claim-state verification. S06 implements
production identity/policy and audit requirements. S07 measures model, retrieval
and query-plan ablations with data splits and confidence intervals.
