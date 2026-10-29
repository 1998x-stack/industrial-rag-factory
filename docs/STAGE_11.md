# Stage 11 — Real multilingual embeddings and cross-encoder reranking

## Research question

On a **fixed public technical-support QA corpus**, do pretrained dense
representations and an actual learned CrossEncoder change ranked retrieval,
observed inference latency, and the safety-relevant *accept vs abstain*
decision relative to lexical FTS5? This is NOT a plant OT correctness claim.

## Model and data contracts

- Public dataset: NVIDIA TechQA-RAG-Eval, Apache-2.0 declared; SHA and
  source-file hash inherited from Stage 10 snapshot.
- Embedding: `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2`
  (public, 384 dimensions, Apache-2.0 declared).
- Reranker: `cross-encoder/ms-marco-MiniLM-L6-v2` (public, English-focused,
  Apache-2.0 declared).
- All model revisions resolved to FULL 40-hex Git SHAs and pinned for local
  snapshot download; report excludes local filesystem cache paths.
- Use `trust_remote_code=False`. No arbitrary repo/model names.
- CPU only for controlled test baseline; external model weights do not
  enter the project repository.

### Candidate and scoring contract

```text
Same public TechQA source snapshot (revision / raw_sha256)
  -> Stage 01 from_bytes/chunks/SQLite FTS5 (isolated tenant)
  -> sparse query hits + pretrained dense query similarities
  -> RRF fusion with 60 offset (hybrid)
  -> CrossEncoder scores over hybrid top-12 candidates
  -> source URI deduplication + Hit@3/MRR@3
  -> per-lane DEV-only accept score cutoff
  -> frozen TEST false-answer rate/balanced accuracy/coverage
  -> TEST paired MRR difference to sparse, bootstrap by source group
  -> report with model/fixture SHA and observed P50/P95 query latency
```

Do not use `is_impossible` to construct ranking or score features. All
document body text is truncated to first 3500 characters for a bounded CPU
experiment; missing reference passages are possible. All queries share
identical corpus and query IDs.

The RRF score, cosine similarity, BM25 score and CrossEncoder logit
are fundamentally different. Thresholds are fitted *separately on DEV*
and **not** calibrated probabilities. TEST metrics are post-hoc analysis,
never a basis for retuning those thresholds.

### How to reproduce

```bash
# Deterministic lightweight offline path (fake model in unit tests)
pip install -e '.[api,llm,pdf,docx,ontology,dev]'
pytest -q tests/test_stage11.py

# Real CPU model download and experiment, explicitly opted in
pip install -e '.[pretrained-benchmark]'
python scripts/stage11_benchmark.py \
  --fetch --per-class 3 --extra-corpus 8 --pretrained --k 3

# Reuse immutable TechQA snapshot if already downloaded
python scripts/stage11_benchmark.py \
  --snapshot data/hf/stage11_techqa.json --pretrained --k 3
```

GitHub Actions runs the full model lane separately in
`.github/workflows/stage11-models.yml`, including CPU PyTorch,
model downloads and a retained `stage11-pretrained-techqa` JSON artifact.
It is purposely isolated from the regular offline CI matrix to make its
network, download and RAM cost visible.

### Report and limitations

The `outputs/stage11_benchmark.json` artifact records:
exact public dataset revision and SHA, model repository identities and full
model SHAs, 4 lane TEST metrics, per-question source URI ranks, failed
accept/reject counts, query P50/P95 latency and paired source-group 95%
bootstrap MRR delta. Raw prompt/evidence text is not archived.

The default Stage 10 sparse benchmark may use a different per-class sample
or full text length and therefore must not be used as a head-to-head score
without rerunning the S11 lanes with the SAME snapshot and truncation.

This evaluation uses query-associated references (weak relevance labels),
a small source corpus and few independent groups; confidence intervals
are illustrative and do not prove a generalized quality change.
Model loading, downloads, memory allocator peaks, energy, API billing
and end-to-end SLOs are not measured by query wall-clock timestamps.
The CrossEncoder is English-focused and not a multilingual reranker.

## Required further acceptance

- Run on larger independent relevance-labeled public or authorized industrial
  corpora with hard negatives and multilingual coverage.
- Measure memory peak, model init latency and throughput under realistic
  concurrency limits; obtain external tracing and performance baselines.
- Validate calibrated abstention thresholds with independent/OOD data.
- Production IAM and independent OT network boundaries remain blocked.
