# Stage 01 — Document RAG baseline

## Objective
A reproducible offline document RAG pipeline from files to retrieval, optional DeepSeek generation, cited answers and evaluation. All datasets are deliberately synthetic.

## Implemented scope
1. Markdown/TXT UTF-8 parsing; optional PyMuPDF PDF and python-docx DOCX parsing.
2. Heading-path chunking with deterministic hashes and configurable token-window size/overlap.
3. SQLite registry including source URI, revision, SHA256, tenant and access groups.
4. FTS5 BM25 candidate search; hashed lexical vectors offline; true multilingual embeddings optional.
5. RRF fusion with lexical tie-break, top-k API controls.
6. Optional DeepSeek Chat Completions JSON answer and citation-ID validation.
7. Flask development API and CLI; built-in gold retrieval evaluation.

## Runbook
```bash
python -m pip install -e '.[api,llm,pdf,docx,dev]'
irf ingest datasets/stage01/pump_manual.md --source-uri fixture://pump_manual.md
irf ingest datasets/stage01/maintenance.md --source-uri fixture://maintenance.md
irf ingest datasets/stage01/cut_spec.md --source-uri fixture://cut_spec.md
irf evaluate datasets/stage01/gold.jsonl --mode hybrid --k 5
python scripts/stage01_ablate.py # writes outputs/stage01_ablation.json
irf query "P-102A 异常噪声" --mode hybrid
python -m pytest -q
python -m ruff check src tests
```

## Planned experiment matrix
A: Chunk window [100, 220, 400] x overlap [0, 40] tokens (estimated, not true tokenizer).
B: Retrieval [sparse, hashing-lexical dense, true semantic dense, RRF hybrid].
C: TopK [3, 5, 10].
D: Prompt variants [answer-v1, answer-v2 after review] and answer mode [extractive, deepseek].
Keep same fixed gold dataset and config/commit hashes; do not compare different source corpora as if controlled.

## Acceptance checklist
- [x] Source and revision can be recovered from every hit.
- [x] Offline ingest-query-evaluate code path implemented.
- [x] Tenant/group filtering occurs inside SQL retrieval queries.
- [x] Source revision supersession implemented.
- [x] DeepSeek API requires opt-in and external key.
- [x] Citation IDs are allowlisted; invented citation rejected.
- [ ] CI test status confirmed on latest commit.
- [ ] Real semantic encoder tested on multilingual corpus.
- [x] Deterministic basic chunk/search ablation grid (S01, synthetic fixtures).
- [ ] Full nDCG/precision and budget/latency evaluation (S07).
- [ ] Anchored page offsets, table footnotes, OCR (future).

## Prohibited claims
Not a production-grade OT control app, authenticated API, formal claim-verification engine, fully faithful multilingual retrieval or validated industrial maintenance system.

## Model note
`deepseek-flash` is the official DeepSeek V4.1 Flash identifier as of October 2026.
DeepSeek is used for generation, while embeddings are local and separately configured.
