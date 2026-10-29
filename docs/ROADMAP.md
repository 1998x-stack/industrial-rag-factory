# Industrial RAG Factory — Complete Stage Roadmap

Stages are **sequential acceptance gates**, not claims that future components already exist. Every stage produces source, tests, configs, documentation, ablations, and results.

| Stage | Deliverables | Required negative tests | Exit gate |
|---|---|---|---|
| S00 Foundation | Python packaging, config, contracts, CI, logging, seed fixtures | missing config, malformed input | offline setup/test succeeds |
| S01 Document baseline | PDF/DOCX/MD/TXT parser; structured chunks; FTS5; lexical-vector and multilingual embeddings; RRF; DeepSeek via Flask; golden retrieval eval | empty input; revision supersession; ACL groups; missing evidence; hallucinated citation | offline E2E + CI and documented limitations |
| S02 Ontology and entity | BFO/IOF version pin; enterprise ontology; same-as candidates; SHACL shapes; normalized source spans | unresolved IDs, invalid domain/range, inconsistent units | 30 competency questions and shape validation |
| S03 Multi-source retrieval | read-only SQL, RDF/property graph, historian adapter, temporal joins, unit converter | stale relation, schema drift, missing series, unit mismatch | graph, SQL and time-series gold cases |
| S04 Query planner | intent parsing, typed DAG, tool allowlist, budget, retries and deterministic routing | unknown tool, invalid parameters, cycles, timeout | planner accuracy and executable plan regression |
| S05 Grounded reasoning | EvidenceBundle; claim-level sources; applicable standards; deterministic numerical rules; abstention | contradictory versions, citation unsupported, incomplete coverage | support precision, calibrated abstention and traceability |
| S06 Security and OT | verified IAM, tenant and document ACL, redaction, external prompt isolation, audit, read-only segmentation | revocation, policy bypass, injection attempts | security tests and approval checklist |
| S07 Ablation factory | fixed splits, factors: parser/chunk/search/embedding/reranker/model/prompt; multi-seed; bootstrap CIs; dashboards | leakage, mislabeled gold, unrepeatable runs | full reproducible report with uncertainty |
| S08 Production | registry, blue-green indexes, rollback, SLOs, deployment, cost reports, recovery drills | failed rebuild, stale policy, service failure | operational readiness review |

## Stage prerequisites and tasks

### S00
- Agree competency questions, source-of-truth matrix, data disclosure policy.
- Freeze Python and dependency major versions; make CI deterministic.
- Document source, chunk, query and evidence contracts.

### S01 [delivered via PR #1; merged into main]
- S01-T01 document fixtures and parsers, including scanned-PDF detection/fail-closed.
- S01-T02 deterministic heading-aware chunking and overlap control.
- S01-T03 content hashes, revisions and active-index treatment.
- S01-T04 BM25 via SQLite FTS5 and query lexical normalization.
- S01-T05 pluggable semantic embeddings; offline lexical hashing baseline clearly separated.
- S01-T06 RRF hybrid, lexical rerank; exposed sparse/dense/hybrid controls.
- S01-T07 DeepSeek JSON adapter, versioned citation prompts, extractive fallback.
- S01-T08 Flask local API and CLI, no untrusted tenant/group fields.
- S01-T09 golden retrieval evaluation and negative tests.
- S01-T10 CI, README, AGENTS and reproducibility report.

### S02 [IOF-aligned offline semantic baseline delivered on Stage 02 branch; remaining full-import tasks documented in docs/STAGE_02.md]
- S02-T01 pin and mirror IOF/BFO release with license/provenance.
- S02-T02 define enterprise asset/process/measurement ontology.
- S02-T03 implement source-to-IRI mappings and time-bounded identity joins.
- S02-T04 SHACL shape validation and explicit open-world/closed-world policy.
- S02-T05 build, publish and verify RDF graph; CQ benchmark.

### S03 [implemented synthetic, read-only multi-source baseline; see docs/STAGE_03.md]
- S03-T01 design read-only SQL operator grammar and permission context.
- S03-T02 add graph traversal operator constrained by ontology.
- S03-T03 implement historian/time-series query, sampling quality and time alignment.
- S03-T04 quantity kind/unit checks (QUDT) and specification applicability.
- S03-T05 golden cross-system joins and conflict diagnostics.

### S04 [typed read-only planner baseline implemented; see docs/STAGE_04.md]
- S04-T01 query intent and entity resolution prompts with typed outputs.
- S04-T02 DAG schema: inputs, dependencies, timeout, budget, tool allowlist.
- S04-T03 deterministic execution engine and evidence dependency tracking.
- S04-T04 retries only for idempotent operations; circuit breaker and fail closed.
- S04-T05 planner regression and multi-tool traces.

### S05 [typed claim and provenance verifier implemented; see docs/STAGE_05.md]
- S05-T01 EvidenceBundle and stable citations with exact offsets.
- S05-T02 ClaimGraph and supported/refuted/conflicting/insufficient state machine.
- S05-T03 deterministic rules for numeric and process questions.
- S05-T04 contradiction handling, eligibility and abstention tests.
- S05-T05 report supported claims separately from hypothesis.

### S06 [local demo policy + security regression delivered; production gate remains OPEN; see docs/STAGE_06.md]
- S06-T01 authentication and authorization within the trusted gateway.
- S06-T02 field/document-level ACL and policy refresh/revocation.
- S06-T03 prompt-injection sandbox and tool-parameter validators.
- S06-T04 OT separation, no direct actuator control, security audit.
- S06-T05 incident, recovery and threat-model review.

### S07
- S07-T01 dataset contracts and train/dev/test source isolation.
- S07-T02 factorial experiment registry and immutable config hashes.
- S07-T03 Recall@n/nDCG/MRR plus document, graph, numeric and faithfulness metrics.
- S07-T04 multiple random seeds, bootstrap CIs and failure taxonomy.
- S07-T05 reproducible HTML/report artifacts and benchmark dashboard.

### S08
- S08-T01 incremental data connectors and reconciliation.
- S08-T02 atomic index publication, signed lineage and rollback.
- S08-T03 OpenTelemetry tracing and operational SLOs.
- S08-T04 cost and latency controls, redaction and retention.
- S08-T05 disaster recovery drill, QA acceptance and release report.
