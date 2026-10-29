# Architecture — Industrial RAG Factory

## Goals and non-goals
- Goal: reproducible retrieval and answer-quality experiments on synthetic industrial documents.
- Goal: clear modular interfaces for future ontology, graph, SQL and time-series additions.
- Non-goal S01: live plant access, certified industrial safety advice, online inference performance SLA, multimodal OCR, operational actuation.

## Offline knowledge build
`source bytes -> format parser -> normalized text -> heading-aware chunks -> document/revision registry -> FTS5 lexical tokens + embedding vectors`.

Data contract: Document (tenant, groups, canonical source URI, revision, content hash); Chunk (stable ID, section path, ordinal); Hit (source URI, revision, retrieval channels).
Current citation location: document URI + heading path; exact page offsets and anchored spans are S02+.

## Online query
`question -> lexical and/or dense retrieval -> RRF fusion -> lexical tie-break -> evidence-labelled prompt -> DeepSeek JSON -> citation ID allowlist -> Answer`.

S01 generation checks only structural constraints and citation IDs. It cannot prove the citation supports the specific sentence. Source applicability, version relevance and knowledge provenance are addressed in later stages.

## Security boundaries
The local research API has no authentication. Server-side configured tenant/group scope is applied in SQLite WHERE/EXISTS before ranking. Access is not verified against an identity provider. Public/production deployment is forbidden until an authenticated gateway, IAM and audit arrive.

## Stage-expansion interfaces
S02: EntityResolver + RDF/OWL ontology registry + SHACL validator.
S03: GraphRetriever + SQLQueryService + TimeSeriesQueryService + UnitService + TemporalMapper.
S04: Typed QueryPlan, graph-safe execution, budgets and retries.
S05: EvidenceBundle, claim verification, contradiction and abstention.
S06: policy engine, authenticated principals, signed/verified revocation, audit.
S07: factorial experiments, token and latency instrumentation, confidence intervals.
S08: release registry, incremental rebuild, rollback, reliability reporting.

## Architecture decisions
- ADR-001: local SQLite FTS5 index to enable offline tests without a search cluster.
- ADR-002: vector sidecar with explicit encoder names to avoid comparing incompatible embeddings.
- ADR-003: DeepSeek is generation-only; it is not treated as an embedding service.
- ADR-004: only scoped source passages enter generation; none is an instruction.
- ADR-005: Flask local-only until external security capabilities exist.

## Technical debt
- Heading tracking for nested sections; table and conditional-clause preservation.
- Exact document anchors and provenance spans.
- Retire historical indexes and atomic multi-document publication.
- Batched true embedding indexing, scalable ANN, cached reranking.
- DeepSeek quota, cost and latency metrics; dedicated LLM gateway.

## Stage 02 semantic plane

`datasets/stage02/aliases.json` → approved, temporal, tenant-scoped identity aliases
→ canonical IDs. `ontology/enterprise.ttl` maps application concepts to IOF
construct IRIs. `datasets/stage02/plant.json` → typed entities and sourced relations →
`KnowledgeGraph.scoped` builds a filtered RDF graph. `ontology/shapes.ttl` + pySHACL
check structural constraints. `competency.jsonl` gives independent 36-case expected results.

- No arbitrary SPARQL accepted from users: read-only allowlisted relations, max five hops.
- The actual IOF `hasRole` and `EquipmentRole` terms are used, but the full OWL
  closure is **not imported**, therefore this stage makes no claim to complete
  IOF classification, logical consistency checking, or cross-ontology interoperability.
- The inferred meaning of absence is explicitly *no verified graph path*, not proof of absence.
- Data is synthetic and tenants/groups are configured by the developer, not authenticated.
- Graph-to-LLM tool routing and numerical calculations remain for S03–S05.

## Stage 03: bounded multi-source lane

The Stage 03 evidence path uses the same authorized scope (tenant_id and
access_groups) across every source. MES SQL returns approved fixture process
records. EntityResolver checks ERP external IDs at the interval boundaries.
The Stage 02 graph verifies the execution's batch, equipment, work order,
specification and sensor mapping, retaining relation source IDs. Historian
samples are checked against the map at their *own* timestamps. Specification
applicability includes equipment, mode, quantity kind and full validity interval.

Quantity conversion uses Decimal to normalize mm/s and m/s (plus simple
temperature units), with a small explicit QUDT-linked registry. It is not
general dimensional reasoning. Strict expected-grid coverage is required to
claim within-observed-limits. No time-weighted duration or probabilistic
anomaly diagnosis is attempted.

Outputs are structured status, evidence and limitations. Optional Stage 01
retriever adds document snippets as context-only evidence. DeepSeek generation
is NOT used to execute SQL or to validate the scientific content of claims.

## Stage 04 trusted query execution boundary

User question -> RulePlanner or DeepSeek JSON proposal -> strict versioned
QueryPlan contract -> validated dependency graph -> read-only ToolRegistry
-> bounded worker invocation -> structured tool results and redacted trace.

Registered tools are document.search, entity.resolve, graph.traverse,
mes.by_batch, historian.read and batch.assess. Arguments use JSON objects
with exact accepted key sets and typed validation. References are expressed
as $ref objects that can only point to declared completed prerequisite
steps; output values are revalidated before any tool execution.

Each SQL-backed operation opens its connection inside its own worker thread.
Time budgets and circuit/retry policy bound orchestration. Thread timeouts
are SOFT; they cannot terminate a running function. The roadmap requires
killable worker process isolation, IAM and full auditing for production.

A completed execution provides structured facts and provenance, NOT an
authoritative natural-language diagnostic claim.

## Stage 05: evidence qualification and typed claim graph

A trusted server-owned Batch ID enters a deterministic Stage 04 QueryPlan
with mes.by_batch and batch.assess. The result is normalized to a bounded
EvidenceBundle with canonical batch ID, equipment, evidence source/record IDs,
measurement values, timestamps and explicit quality limitations.

The verifier checks necessary provenance categories (MES, identity mapping,
RDF relation, approved specification, historian measurement), numeric
consistency using Decimal and unit-kind compatibility, measurement-count
consistency and exact citation IDs. Ambiguous/conflicting evidence returns
conflicting; evidence gaps and unsupported causal or product-quality claims
return insufficient_evidence. Only a fully supported typed claim avoids
abstention.

ClaimGraph output contains typed claim nodes, sourced evidence nodes, and
supporting/refuting edges. This is **not** a complete natural-language
entailment model; it deliberately supports only a small set of typed synthetic
batch predicates. It does not verify cryptographic source authenticity or
independently acquire source permissions; Stage 06 addresses production IAM.

## Stage 06: developer-only security façade

S01–S05 code remains the same in default offline mode. When
IRF_SECURITY_MODE=demo, Flask blocks every legacy /v1/* route to prevent
unauthenticated bypass. The two /v1/secure/* endpoints require short-lived
HMAC-signed developer capability tokens.

The trusted gateway validates token audience, signature and expiration,
then reloads current subject policy and scopes tenant/groups and tool rights
from that policy, NEVER from token or query parameters. GuardedRegistry
enforces permissions both before and after each read-only operation and
requires all nested source_uri fields to match explicit allowed prefixes.
Current policy is checked again before response serialization; selected
fields are redacted after source validation.

An HMAC-chained JSONL local audit records only a pseudonym, event type,
decision, timestamp, request ID and previous MAC. File integrity checks
can detect some modifications but do NOT establish immutable or independently
signed audit logging. There are no Stage 06 production services or OT
network connectors. The forbidden-protocol guard is defense in depth only;
real industrial protection requires external firewall/conduit rules.

Flow: signed local capability -> PolicyStore (reload) -> guarded S04 tools
-> S05 claim verification -> source-policy recheck -> redaction -> audit
-> response. Legacy /v1 routes disabled only when secure demo mode enabled.

## Stage 07: offline factorial experiment and statistical qualification

`config/stage07_experiments.json` fixes chunking, overlap, retrieval modes,
index-order seeds and bootstrap resamples. An explicit factor registry in
`config/stage07_factors.json` discloses held-constant/unavailable dimensions.
`datasets/stage07/retrieval_cases.jsonl` contains 54 synthetic labeled
questions in 27 independent asset groups with train/dev/test assignments.
`experiments/contracts.py` detects exact group/source/query/content leakage.

Actual `Pipeline` instances run in temporary isolated SQLite indexes.
DEV labels choose the champion, and TEST metrics are measured without
further parameter fitting. Case-level retrieval hit, recall, MRR and nDCG
feed a **source-group** percentile bootstrap. Paired contrasts align the
same case IDs and use shared bootstrap group draws. Seeds change ingest
order, not LLM/model weights.

The S02 graph, S04 planner and S05 claim verifier are each tested against
safe negative controls (disabled components abstain rather than fabricate
facts). S03 evaluates the existing MES golden records. S06 policy, audit,
source ACL and OT denial stay enforced and are tested in separate security CI.

Outputs are `stage07_ablation.json` and an escaped, dependency-free HTML
receipt. This is **synthetic offline integration evidence**, not production
LLM or RAG quality, and the very small group count makes intervals illustrative.

## Stage 08: offline immutable release catalog

Stage 08 introduces `operations.ReleaseManager`, a separate, developer-only
blue/green publication path for the synthetic document index. Changed-source
hashing, full source-manifest reconciliation and staged SQLite copying make
the new index independent of the active one. Metadata are locally HMAC signed
and snapshot bytes SHA-256 checked; only a verified staged snapshot can be
made active by a compare-and-swap SQLite catalog update. Rollback similarly
requires a verified target and an expected-current version.

A published snapshot is opened by pinned, query-only SQLite URI and never
through the mutating Store constructor. A POSIX advisory lock guards the
version pointer during query; concurrent writers cannot swap an index until
a pinned reader completes. Source deletes physically purge staged content.

An optional OpenTelemetry API span measures operation categories without
secrets/content; local query samples provide a small p95 smoke metric.
There is no configured exporter, production authorization or live OT
integration. The independent readiness gate remains production_blocked.

## Stage 09 public Hugging Face benchmark path

Explicit HF Hub download with pinned full dataset commit and checked license
-> local raw CSV SHA -> required-field/schema/duplicate checks -> near-document
cluster grouping -> train/dev/test question label manifest -> isolated
`hf-public`/`hf-benchmark` tenant -> existing Stage 01 from_bytes parser,
chunking, SQLite FTS5 + lexical hashing index -> document-level source-aware
retrieval and citation IDs -> candidate evidence and abstention status ->
case-level recall, MRR, nDCG and source-group bootstrap intervals ->
`outputs/stage09_hf_report.json`.

Gold `answer` is used only for a separate literal-substring diagnostic,
never to construct indexed context or claim certainty. The public
`knowledge_text` field is question-associated, so context retrieval may be
biased toward easy matches; this benchmark is not a blind external corpus
retrieval leaderboard. Stage 03 MES/OT and Stage 05 numerical claim verification
do not become valid through HF text. Stage 06 network security remains separate.

## Stage 10 second public corpus / calibration lane

NVIDIA TechQA `train.json` downloaded with a pinned HF revision and card
license guard -> source context dedup and connected-component grouping ->
balanced answerable/impossible QA split -> isolated `techqa-public`
SQLite/FTS5 index -> document-level rankings and raw top sparse score ->
DEV-only threshold selection -> frozen TEST confusion, selective coverage,
false-answer rate and source MRR. No model is shown gold `is_impossible`
labels; the score is not an independently calibrated confidence probability.
The data concern public IT technical support, not live industrial data.

The optional S10 multilingual variant resolves a fixed public model to a full
upstream commit, downloads that snapshot only with explicit CLI opt-in, and
configures the existing S01 Pipeline `sentence-transformers` encoder.
It reports actual backend and full model provenance; the default live
benchmark still uses lexical FTS and does not fetch model weights.

## S11: source-aware pretrained retrieval comparison

The already pinned public TechQA normalization is reused unchanged. Stage 01
indexing parses/chunks an identical, bounded sample of documents to a
temporary tenant. Sparse uses existing FTS5; Dense encodes the same chunks
through a pinned public multilingual model; Hybrid combines ranks with
RRF(60). A fixed English CrossEncoder predicts candidate text pair
scores for only the RRF top 12. Document-level dedup happens BEFORE
Hit/MRR calculation. The labels and gold source URIs are used only after
ranking, and DEV alone chooses separate decision thresholds for each lane.

The output includes source/provenance hashes, per-query ranks, case-aligned
source-group bootstrap deltas, and a clear wall-clock timing scope for
indexing, embedding and query. It is not an LLM QA entailment test, not an
OT evaluation, and not evidence that threshold scores generalize beyond
this tiny public corpus.

## Stage 12: closed-loop robustness and actual model-depth contrast

An exact pinned TechQA dataset snapshot is indexed through Stage 01 in a
temporary independent SQLite store. Closed-loop concurrent workers each
open their OWN read-only connection and run FTS5, probing cross-tenant and
cross-group denial. Baseline is compared with question-conditioned synthetic
lexical decoys derived **only from TRAIN**; TEST evaluation uses only
answerable reference cases for paired source-group MRR bootstrap.

Local measurements include completed QPS, P50/P95/P99 wall-clock query
duration, index size/time and process peak RSS. These metrics exclude network
serving, arrival-rate control and production SLO qualification.

In a distinct real-pretrained job, the S11 comparison is reexecuted for
reranker candidate depth 4, 8 and 12 under the same public snapshot/model
commit identity. Actual CPU runtime—not a simulated ranking proxy—determines
observed p95 for each depth. Tiny public results remain exploratory.
