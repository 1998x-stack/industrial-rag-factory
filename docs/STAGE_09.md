# Stage 09 — Real Hugging Face Industrial Dataset Pipeline

## Dataset selection and licensing

**Primary (implemented):** Alibaba's [IndustryBench](https://huggingface.co/datasets/alibaba-multimodal-industrial-ai/IndustryBench).
The Hugging Face dataset card declares **MIT** and offers approximately
2,049 industrial questions/answers with Chinese questions, English/Russian/
Vietnamese translations, industry/capability labels and a `knowledge_text`
reference field. The dataset file is `huggingface_dataset.csv`.

**Secondary (reviewed, not benchmarked here):**
- IBM Research [AssetOpsBench](https://huggingface.co/datasets/ibm-research/AssetOpsBench),
  card declares Apache-2.0, scenario and FailureSensorIQ question families;
  must verify scenario and answer formats before adapter integration.
- NVIDIA [TechQA-RAG-Eval](https://huggingface.co/datasets/nvidia/TechQA-RAG-Eval),
  card declares Apache-2.0, technical-support QA with `is_impossible`
  and associated contexts; specifically useful for abstention follow-up.

Card license declarations do **not** establish that every embedded standards
extract/manual excerpt has independently confirmed downstream redistribution
permission. The repo does not copy the raw dataset or individual passages.

## Actual pipeline

```text
HfApi.dataset_info -> exact 40-char SHA -> hf_hub_download pinned CSV
  -> license + file-size + CSV field validation + raw file SHA-256
  -> missing/duplicate checks and evidence text content hashing
  -> cluster/group-stable query label train/dev/test partition
  -> isolated hf-public tenant and hf-benchmark group
  -> from_bytes -> heading-aware chunking -> Stage01 Store/FTS5/vectors
  -> sparse/hybrid retrieval and document ID/source URI deduplication
  -> source attribution and citation candidates
  -> retrieved_not_verified OR insufficient_evidence
  -> case-level Hit/Recall/MRR/nDCG + grouped bootstrap
  -> snapshot and report (local/CI artifact)
```

The benchmark's gold answers are **never appended to source documents**.
Questions and gold source associations are held out as labels while all
selected source texts are searchable, consistent with corpus retrieval.
Because `knowledge_text` belongs to the same original QA row, the target
source is almost always a known relevant context, which is a strong
**evaluation design bias**; no claim of blind external relevance annotations.

The public source is not connected to the MES/SCADA/CMMS/historian graph or
any live OT system. Stage05 `ClaimGraph` physical/numeric proof would be
incorrect to apply to this benchmark. Instead document evidence retains
source URI, revision and chunk, and all positive retrieval statuses are
explicitly `retrieved_not_verified`. An optional DeepSeek model would still
need independent entailment/citation evaluation.

## Reproduction

```bash
pip install -e '.[api,llm,pdf,docx,ontology,dev,huggingface]'
python scripts/stage09_hf_benchmark.py --fetch --limit-per-split 12 \
  --k 5 --modes sparse hybrid
```

This downloads the public CSV to a trusted Hugging Face client cache and
writes a normalized snapshot to ignored `data/hf/industrybench.json`.
Repeat with `--revision <reported-full-40-character-SHA>` for exact source
version replication. The script does not auto-download when `--fetch` is
omitted. Repository/model/file names are allowlisted, no remote code
execution or trust_remote_code is enabled.

GitHub Actions has two lanes: deterministic offline unit tests under the
existing Python 3.10/3.12 CI matrix, and one real-public-data online smoke
job on Python 3.12. The online job fails clearly if the remote data cannot
be fetched or its declared license/schema changes; it never silently
replaces public data with authored fake records. Report download artifacts
include metrics/IDs but should not include original source texts.

## Dataset-specific metrics

- Source-aware Recall@K, Hit@K, MRR@K, nDCG@K.
- Evidence citation integrity: every retrieved citation points to an actual
  indexed source URI and exact HF commit.
- Query latency in milliseconds, and local indexing time.
- Test-group percentile 95% bootstrap confidence intervals.
- Breakdown by published `industry_primary`.
- Answer literal containment in retrieved text is only a **diagnostic**;
  it is not a semantic entailment, factuality or hallucination metric.

**Non-claims:** no real-world plant failures predicted, no factory telemetry
validated, no authenticated independent standard source, no safety or
process-control authorization, no true dense semantic embedding, no actual
DeepSeek API usage/cost claims.

## Next recommended improvement

Add expert-reviewed QA with evidence identified independently of each query,
include negative/hard-distractor documents, run full-corpus retrieval and
learned multilingual embedding/reranking baselines with clearly accounted
inference latency/cost. Connect industrial data through real approved
source-specific connectors only after S06 production security readiness
and explicit facility authorization.

## Unjudged public distractors and source-ranked evaluation

The live job adds 64 public `knowledge_text` sources not paired with the 24
labeled questions. These are selected by content-hash order, independent
of test queries or answer strings. They are **unjudged** sources; do not
treat missing qrels as verified irrelevance.

The retriever overfetches physical chunks, then deduplicates by source URI
before calculating document-level MRR/Recall and emitting citation
candidates. This fixes the mismatch between chunk-level S01 results and
source-document benchmark labels. The live smoke is still a small
convenience sample and cannot support general accuracy claims.

## Optional end-to-end DeepSeek generation (explicitly paid)

The new `hfbench.answering.evaluate_generation` helper takes the same
normalized public snapshot, indexes source documents in an isolated local
tenant and runs Stage 01 `Pipeline.query` with a DeepSeek generator.
It is **off by default**, never invoked by CI, and bounded to 1–5 held-out
test questions. Its report contains status, evidence-source count and
latency only; it does not persist prompt content or generated answer bodies.

```bash
export DEEPSEEK_API_KEY="<your API key>"
export DEEPSEEK_BASE_URL="https://api.deepseek.com"
export DEEPSEEK_MODEL="deepseek-flash"
python scripts/stage09_hf_benchmark.py --snapshot data/hf/industrybench.json \
  --generate --generation-cases 3
```

Citation IDs must exist in the retrieved evidence; unsupported citation IDs
cause validation failure. **A citation-integrity pass is not proof of
entailment, a quality metric for a real factory, or safe equipment guidance.**
The offline regression uses a fake generator and performs no paid requests.
