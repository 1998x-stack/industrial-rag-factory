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
