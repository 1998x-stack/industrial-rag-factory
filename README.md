# Industrial RAG Factory

> A reproducible, stage-driven laboratory for **industrial document RAG → ontology/graph retrieval → temporal reasoning → evidence verification → industrial evaluation**.

**Status:** Stage 01 implemented as a development baseline, not certified for production or OT use.
DeepSeek V4.1 Flash via official `deepseek-flash` API alias; Flask API is local-only.

## Design principles

- **Evidence first:** cited chunks preserve source URI, revision and section hierarchy; citation integrity is NOT factual entailment validation.
- **Factory mode:** data ingestion, parsing, chunking, indexing, retrieval, generation and evaluation have separate interfaces and stage gates.
- **Offline by default:** no model API call or billing unless `IRF_GENERATOR=deepseek` and `DEEPSEEK_API_KEY` are explicitly configured.
- **No fake semantics:** built-in `hashing` is a *lexical hashed-vector baseline*, not a semantic encoder; use `sentence-transformers` for actual dense semantics.
- **Fail closed for unavailable evidence:** no accessible hits means abstain; this does NOT prove the searched corpus is complete.
- **No OT command path:** this research project does not control equipment, PLCs or SCADA actuators.

## Stage map

| Stage | Scope | Gate |
|---|---|---|
| S00 | Project skeleton, CI, typed contracts, frozen configs | unit tests + reproducible environment |
| **S01** | Parsers (PDF/DOCX/MD/TXT), structure-aware chunks, FTS5, embeddings, hybrid RRF, DeepSeek JSON generation, Flask API, retrieval evaluation | end-to-end demo + offline tests |
| S02 | IOF/BFO mappings, RDF/OWL, SHACL, entity resolution and knowledge provenance | competency questions + shape tests |
| S03 | SQL, property/RDF graphs, time-series, units and bitemporal joins | multi-hop and temporal correctness |
| S04 | Typed query planner, DAG execution, tool contracts and fallback policies | planner and execution benchmarks |
| S05 | EvidenceBundle, ClaimGraph, rules and uncertainty policies | claim-level grounding / abstention |
| S06 | IAM, ACL revocation, prompt-injection defenses, audit and OT boundaries | adversarial and authorization gates |
| S07 | Factorial ablations, multi-seed runs, confidence intervals and dashboards | reproducible comparisons |
| S08 | Incremental indexing, rollback, observability, deployment and runbooks | release checklist and recovery drill |

See [ROADMAP](docs/ROADMAP.md), [architecture](docs/ARCHITECTURE.md), [S01 acceptance](docs/STAGE_01.md), [prompt registry](docs/PROMPTS.md) and [AGENTS.md](AGENTS.md).

## Install

Python 3.10+:

```bash
python -m pip install -e '.[api,llm,pdf,docx,dev]'
```

For semantic dense retrieval install `pip install -e '.[dense]'`; the first model load may download weights. For no extra dependencies: `pip install -e .`.

**Important:** The `flask` library is the HTTP backend; it is not part of the DeepSeek model name.

## Offline end-to-end quickstart

```bash
irf ingest datasets/stage01/pump_manual.md --source-uri fixture://pump_manual.md
irf ingest datasets/stage01/maintenance.md --source-uri fixture://maintenance.md
irf ingest datasets/stage01/cut_spec.md --source-uri fixture://cut_spec.md
irf query "P-102A 的轴承异响曾经如何处理？" --mode hybrid
irf evaluate datasets/stage01/gold.jsonl --mode hybrid
python scripts/stage01_ablate.py  # 18 reproducible offline configurations
python -m pytest -q
```

Index is stored at `./data/stage01.sqlite3`. Gold labels are simulated and intended to test plumbing, not production accuracy.

## DeepSeek V4.1 Flash configuration

Official API docs: https://api-docs.deepseek.com/quick_start/agent_integrations/

```bash
export DEEPSEEK_API_KEY="<YOUR_API_KEY>"
export DEEPSEEK_BASE_URL="https://api.deepseek.com"
export DEEPSEEK_MODEL="deepseek-flash"
export IRF_GENERATOR="deepseek"
irf query "P-102A 有什么历史维修记录？"
```

The model `deepseek-flash` is the documented alias serving V4.1 Flash; `deepseek-v4.1` is not the documented API model ID as of 2026-10-28. The SDK uses Chat Completions with `response_format=json_object`, and every response is schema-checked and citation-ID checked. This is **not** claim entailment checking.

## Flask local API

```bash
irf serve
curl -s http://127.0.0.1:5000/healthz
curl -s -X POST http://127.0.0.1:5000/v1/query \
  -H 'Content-Type: application/json' \
  -d '{"question":"P-102A 异常噪声","mode":"hybrid","top_k":3}'
```

- API accepts JSON UTF-8 MD/TXT ingestion, maximum 1 MiB; CLI handles PDF and DOCX.
- `tenant_id` and access groups come from server configuration and cannot be supplied by API requests.
- **No identity authentication is implemented in S01.** The Flask service is strictly for local development and intentionally refuses `IRF_ENV=production`.
- Do not publish the Flask development server or ingest confidential factory/OT data before Stage 06.

## Known limitations

PDF extraction is text-only (no OCR), DOCX tables have simplified serialization; chunk offsets are token-window identifiers rather than byte offsets; long conditional paragraphs may be split. FTS5 lexical tokenization uses simple ASCII/CJK unigram+bigrams; vector similarity is brute-force over a local SQLite sidecar, and offline reranking uses lexical overlap, not a learned reranker. Document revisions are active per source; historical retrieval and complete index release governance belong to later stages. Generation citation IDs are verified but source-truth and claim-level entailment are not.

## Research references

- IOF release portal: https://spec.industrialontologies.org/portal/
- W3C OWL 2: https://www.w3.org/TR/owl-primer/
- W3C SHACL: https://www.w3.org/TR/shacl/
- W3C PROV-O: https://www.w3.org/TR/prov-o/
- DeepSeek API: https://api-docs.deepseek.com/
- W3C/OGC SOSA/SSN: https://www.w3.org/TR/vocab-ssn/

## License

No license is granted until a LICENSE file is deliberately selected and committed.

## Stage 02 — Ontology + Knowledge Graph (implemented)

Stage 02 adds an **offline, read-only, IOF-aligned enterprise semantic graph**. It is a research
implementation, not a full upstream OWL import or industrial operational knowledge graph.

- Pin IOF Release 202603 and its stable construct namespace in `ontology/upstream.lock.json`
- Keep enterprise classes/predicates in `ontology/enterprise.ttl`; use the **actual**
  `iof:hasRole` and `iof:EquipmentRole` IRIs for equipment-role assertions
- Resolve ERP/MES/SCADA/CMMS aliases only from approved, tenant-scoped, time-valid mappings
- Construct RDF triples with relation source-record IDs, effective intervals and PROV citations
- Validate closed-world data requirements with SHACL; do not confuse validation with source truth
- Evaluate **36 manually specified competency questions** on a synthetic industrial graph

Install and run, from repository root:

```bash
pip install -e '.[api,llm,pdf,docx,ontology,dev]'
irf semantic-validate
irf semantic-evaluate
irf semantic-resolve EQ-00037 --system ERP --at-time 2026-10-20T10:00:00+08:00
irf semantic-export outputs/graph_20261020.ttl
irf serve
# POST /v1/semantic/resolve and /v1/semantic/traverse (localhost development only)
```

The original document `query`, `ingest`, and `evaluate` commands remain unchanged.
See [Stage 02 acceptance](docs/STAGE_02.md). **Stage 03** will connect this graph to
the read-only SQL/time-series retrieval plane; the S01 LLM currently receives document
evidence only, not authoritative graph-derived facts.

## Stage 03 — Multi-source industrial retrieval

A new offline, read-only path joins **MES SQLite → approved external asset alias →
temporal graph → time-series measurements → approved specification → unit-aware
threshold evidence**. It returns observations and limitations, not equipment
fault diagnoses or industrial actuation instructions.

Run from the repository root:

    pip install -e '.[api,llm,pdf,docx,ontology,dev]'
    irf multisource-assess B-104
    irf multisource-assess B-105
    irf multisource-evaluate
    python scripts/stage03_evaluate.py
    irf serve

Flask: POST /v1/multisource/assess with JSON {"batch_id":"B-104"} on localhost.
The Stage 01 document retriever can contribute context-only evidence; structured
measurements and specifications may not be overridden by unverified text.

See docs/STAGE_03.md for source contracts, failure modes, CI and limitations.
The MES, historian and thresholds are **synthetic fixtures only**. Production
connections, authenticated access, arbitrary user SQL/SPARQL, and OT actuation
are deliberately unsupported.

## Stage 04 - Typed Agent Query Planner

Stage 04 introduces strict JSON query plans, an offline deterministic rule
planner, an opt-in DeepSeek V4.1 Flash planner, six registered read-only tools,
DAG execution with dependency validation, bounded soft timeouts, retry policies,
and a structured redacted trace. Tool proposals never grant permissions.

Run from the repository root:

    irf agent-plan "B-104 的振动状态"
    irf agent-query "B-104 的振动状态"
    irf agent-query "ERP EQ-00037 有哪些测点"
    irf agent-evaluate
    python scripts/stage04_evaluate.py

For an optional paid DeepSeek JSON planner, set DEEPSEEK_API_KEY and
IRF_PLANNER=deepseek. Defaults to rules mode (offline, free).

Flask exposes POST /v1/agent/query with only a question field. Runtime
tenant/group and planner selection are server-owned. Flask is local development
only, without production identity authentication.

Soft thread timeouts return an error but cannot kill a running task; all
Stage 04 tools are read-only. Execution success is NOT claim entailment
or evidence authenticity. See docs/STAGE_04.md.

## Stage 05 — EvidenceBundle / ClaimGraph & deterministic verification

Stage 05 provides a **read-only claim-verification layer** over Stage 04
trusted typed execution and Stage 03 sourced industrial measurements:

    Batch ID -> trusted Stage 04 MES/batch-assess DAG -> EvidenceBundle
       -> structured provenance and numeric checks -> typed ClaimGraph
       -> supported / refuted / conflicting / insufficient_evidence + abstain

It does NOT use a model to decide truth. The verifier independently recomputes
each synthetic measurement's threshold flag against the unique approved
fixture specification (Decimal and physical unit checks). It also checks
MES batch/equipment identity, required source kinds, sample counts and
citation allowlists. Document passages alone cannot prove numeric limits.

Try the offline factory:

    irf grounding-verify B-104
    irf grounding-verify B-105
    irf grounding-verify B-999
    irf grounding-evaluate
    python scripts/stage05_evaluate.py
    pytest -q

Submit a bounded candidate claim to check rather than automatically inferring
one from the observation:

    irf grounding-verify B-104 --claims-json '[{"claim_id":"wrong","subject":"B-104","predicate":"batch_exceedance_count","expected":0}]'

Local Flask (development only): POST /v1/grounding/verify receives only
batch_id and optional typed claims. **Never accept client-supplied evidence or
authorization context.** A rejected claim is reported as refuted, not rewritten
as true; unsupported root-cause and product-conformity statements abstain.

See docs/STAGE_05.md for the data contracts and known limitations.
