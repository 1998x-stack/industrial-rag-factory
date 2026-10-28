# Stage 02 — Industrial Ontology, Entity Resolution & Knowledge Graph

## Stage objective

Build a deterministic, read-only **industrial semantic plane** alongside the
already delivered Stage 01 document RAG. This stage is not allowed to introduce
live OT control, autonomous asset merges, production IAM claims or uncontrolled
SPARQL/SQL execution.

## Upstream ontology dependency / version lock

`ontology/upstream.lock.json` records:
- **IOF Core Release 202603** (Released), release commit abbreviation `0c5af08`
- Version IRI `https://spec.industrialontologies.org/ontology/202603/core/Core/`
- Construct namespace `https://spec.industrialontologies.org/ontology/construct/`
- BFO 2020 (upstream IOF dependency)
- MIT upstream license metadata

Canonical normative artifact: `Core.rdf` in the upstream IOF release.
**Not vendored at Stage 02**: the complete IOF/BFO RDF files, local XML import
catalog, HermiT reasoner and OWL entailment materialization. The metadata is
a release pin, not a cryptographic source lock; a future release-sync task
must verify full SHA-256 per downloaded upstream artifact before enabling a
complete reasoner.

Stage 02 enterprise ontology is deliberately smaller. It declares application
classes for assets, production batches, work orders, execution, measurement points,
maintenance, specification and location, with explicit application predicates.
For the role model, instance facts use the exact IOF stable IRIs
`iof:EquipmentRole` and `iof:hasRole` (not substitutes).

## Module contracts

| Module | Input | Output | Guardrails |
|---|---|---|---|
| `semantic.identity` | alias/system, as-of time, tenant/group | resolved/ambiguous/unresolved | no guesses; approved mappings only; timezone mandatory |
| `semantic.graph` | synthetic entities/relations and TTL | authorized RDF graph, typed traversal | predicate allowlist; ≤5 hops; source-record lineage; time filtering |
| `semantic.validation` | authorized RDF graph + SHACL shapes | conforms / details | no full OWL reasoning; closed-world structural quality |
| `semantic.competency` | canonical paths + independent gold | per-CQ result and aggregate accuracy | deterministic, no LLM and no network |
| `semantic.service` | explicit context + method | read-only API/CLI payload | no write operations, no production authorization claim |

## Stage acceptance / tests

- [x] Maintain a version pin to released IOF 202603 and BFO dependency.
- [x] Enterprise ontology, RDF instance graph and SHACL shapes.
- [x] Approved ERP/MES/SCADA/CMMS entity mappings, ambiguity detection.
- [x] Effective time: old/new measurement-point swaps exclude invalid edges.
- [x] PROV `wasDerivedFrom` with immutable synthetic source record IDs.
- [x] 36 independent golden competency questions, including multi-hop queries.
- [x] Negative tests: missing role, missing tag, unknown predicate, dangling edge,
      tenant scope, ambiguous alias and bad timestamps.
- [x] Local Flask and CLI read-only endpoints.
- [ ] Import and mirror **complete** released IOF/BFO with cryptographic checksums.
- [ ] Full OWL 2 classification and consistency checks against imported IOF axioms.
- [ ] Authenticated user identity and source-of-truth mapping approval.
- [ ] Join real SQL/historian and indexed document evidence (Stage 03).

### Validation commands

```bash
python -m pip install -e '.[api,llm,pdf,docx,ontology,dev]'
python -m pytest -q
python -m ruff check src tests
irf semantic-validate --at-time 2026-10-20T10:00:00+08:00
irf semantic-evaluate --questions datasets/stage02/competency.jsonl
irf semantic-resolve SENSOR-LEGACY --system SCADA --at-time 2026-02-01T10:00:00+08:00
irf semantic-resolve SENSOR-LEGACY --system SCADA --at-time 2026-10-20T10:00:00+08:00
irf semantic-export outputs/authorized_graph.ttl
```

`SENSOR-LEGACY` maps to VIB03-A in February and VIB03-B in October.
Without `--at-time`, it remains ambiguous.

## Experiment and audit artifacts

- `datasets/stage02/plant.json`: synthetic entities and sourced assertions.
- `datasets/stage02/aliases.json`: controlled alias mapping table.
- `datasets/stage02/competency.jsonl`: 36 query specifications and expected IDs.
- `irf semantic-evaluate`: machine-readable test results.
- `irf semantic-export`: authorized time-valid Turtle graph.
- CI validates Stage 01 regression tests, Stage 02 tests, SHACL and competency cases.

## Limitations and hazards

1. OWL open-world assumption is not replaced by SHACL; `no_verified_path` means
   missing evidence, **not** verified absence.
2. Accepted relation mapping does not verify real-world cabling, source authenticity
   or equipment status. SHACL is necessary but not sufficient.
3. The local Flask API is loopback-only and has **no authenticated principals**.
4. The enterprise ontology is intentionally minimal, not an IOF Core replacement.
5. This graph is a reference fixture, not an operational asset master.
6. Schema/RDF export is read-only and does not connect to industrial controllers.

## Stage 03 handoff

Integrate time-aware canonical identity resolution into the query router; add
read-only structured and historian adapters, temporal join, unit/quantity
validation and a mixed document/graph evidence contract. Preserve provenance
and ACL scope across joins rather than merely joining labels or vector neighbors.

## References

- https://spec.industrialontologies.org/portal/release/202603/core.html
- https://github.com/iofoundry/ontology/releases/tag/Release_202603
- https://www.w3.org/TR/owl2-primer/
- https://www.w3.org/TR/shacl/
- https://www.w3.org/TR/prov-o/
