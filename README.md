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
