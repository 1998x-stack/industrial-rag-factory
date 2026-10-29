# Stage 07 — Ablation Factory, Fixed Splits & Statistical Validation

## Objective

Create an executable, fully offline **experimental protocol** rather than an
unreproducible benchmark score. Stage 07 combines genuine retrieval
factorial tests with deterministic stage-level negative controls and
source-group uncertainty estimates. It does not pretend to measure future
DeepSeek quality, general semantic entailment or industrial fault detection.

## Fixed data contract and leakage policy

`datasets/stage07/retrieval_cases.jsonl` contains 54 synthetic questions from
27 source/asset groups. Each group contains two questions for a single
synthetic source document. The split is **train=18 (9 groups),
dev=18 (9 groups), test=18 (9 groups)**.

- A source/asset group cannot appear in more than one split.
- A source URI cannot be reused across split boundaries.
- Exact normalized document contents and exact normalized query text cannot
  appear in multiple splits; IDs must be globally unique.
- The retrieval corpus contains all 27 documents (as normal for searching);
  their documents are NOT held out from the index. The **label/query
  partitions** and their groups are held out for evaluation.
- All template patterns are synthetically constructed and similar. Group
  separation is not real-world distribution shift protection. There is no
  external evaluation set, no independent annotator and no real industrial
  labels.

## Experimental factorial grid

The committed protocol, `config/stage07_experiments.json`, runs:

- Chunk sizes: 100, 220
- Overlaps: 0, 40
- Retriever modes: sparse, dense hashing-lexical and RRF hybrid
- Ingestion order seeds: 11, 29, 47
- K=3; 400 group bootstrap resamples

Total: **2×2×3×3 = 36 actually executed retrieval trials**. Each trial
indexes the synthetic documents through the real parsing, chunking, indexing
and retriever path in a clean isolated SQLite database. Outcomes are
hit@K, Recall@K, MRR@K and nDCG@K per question and mean by split.

Parameters are selected by DEV MRR@K (then recall, then stable factor
tie-break). TEST scores are used for post-selection reporting only.
Every factorial TEST variant is published for *exploratory* comparison.
Do not tune again based on this TEST output.

## Cluster uncertainty and paired differences

Use percentile bootstrap with asset/source groups as independent units,
sampling entire groups (including their questions), not individual
correlated queries. Each estimate states confidence level, group count and
resample count. For comparisons, align case IDs before taking the
per-case difference and use identical cluster resamples. This reports
paired delta = selected MRR minus sparse-reference MRR.

Ingestion-order seeds perturb the index build sequence only. They
are not random training seeds, independently trained language models,
independent replicates for statistical inference or evidence of deployment
reliability. With nine test groups, the reported CIs are illustrative;
a production publication needs many more independently sourced groups.

## Cross-stage negative controls

| Lane | Actual code path | Safe control | What is measured |
| --- | --- | --- | --- |
| S02 graph | KnowledgeGraph.traverse, 36 CQs | Return no verified graph path | Exact expected path match |
| S03 MES | MultiSourceService + 3 gold batches | No unsafe bypass | Exact known batch status |
| S04 planner | RulePlanner selects typed tool sequence, 8 queries | Document-search-only fallback | Tool sequence exact match |
| S05 verifier | verify_claims over 14 labeled claims | Always abstain, insufficient | Four-way status exact match |
| S06 security | Separate authenticated/revocation/denial CI | **Never disable** access controls | Security checks reported separately |

These negative controls are purpose-built conservative fallbacks, NOT
independently trained alternate models. Differences are informative
integration contrasts, not causal proof of the true component contribution
in a deployed industrial system.

## Explicitly unmeasured

`config/stage07_factors.json` documents all factor statuses:

- Parser alternatives: unavailable; current formats share one parser path.
- Alternate reranker: no learned reranker installed or verified.
- Embedding: lexical hashing held constant; this is not genuine dense semantic
  model evaluation. GPU/Qwen/Whisper are not prerequisites for this CI.
- Prompts and DeepSeek models: no paid calls, no real API key and no
  repeat-model evaluation in CI. **Do not report LLM quality or cost gains**.
- Security: never switch off policies to inflate retrieval metrics.

## Code and outputs

- `experiments/contracts.py`: strict config and group leakage checks.
- `experiments/retrieval.py`: run real pipelines and per-case retrieval.
- `experiments/cross_stage.py`: read-only graph, MES, planner, claim contrasts.
- `experiments/stats.py`: cluster bootstrap and paired deltas.
- `experiments/runner.py`: immutable input hashes and integrated report.
- `experiments/report.py`: escaped local HTML tables and uncertainty summary.
- `scripts/stage07_ablate.py`: one-command artifact generation.
- `tests/test_stage07.py`: leakage, reproducibility, stats and report safety.

Reproduce:

```bash
pip install -e '.[api,llm,pdf,docx,ontology,dev]'
python scripts/stage07_ablate.py
pytest -q
ruff check src tests
```

CI archives `outputs/stage07_ablation.json` and
`outputs/stage07_report.html`. The JSON includes file SHA-256 hashes,
protocol, code revision when running under GitHub Actions, trial IDs,
all factors and caveats. A hash proves byte reproducibility, **not** source
authenticity, privacy approval or scientific validity.

## Acceptance

- [x] 54 cases grouped by 27 distinct synthetic source/asset families.
- [x] Precommitted train/dev/test membership and cross-split leak checks.
- [x] 36 actual offline retrieval configurations and 3 order seeds.
- [x] DEV-only winner selection; TEST exploratory data clearly separated.
- [x] Recall@K, Hit@K, MRR@K, nDCG@K and fingerprinted run IDs.
- [x] 95% cluster bootstrap intervals and paired sparse deltas.
- [x] S02, S04, S05 conservative fail-closed ablations and S03 gold summary.
- [x] S06 denial, revocation and audit regressions remain enforced in CI.
- [x] Self-contained JSON and escaped static HTML artifacts.
- [ ] Multiple independent real factory/plant datasets and independent labels.
- [ ] DeepSeek model/prompt quality, variance, latency and token-cost trials.
- [ ] Alternative parser, learned reranker and embedding-model comparisons.
- [ ] Hierarchical multi-plant bootstrap / calibration with larger samples.
- [ ] Fully authenticated, security-approved industrial environment.

## Next stage: S08 production engineering

Promote only after independent OT/IT and security gate approval. Stage 08
should add atomic index version publication, rollback, retention, telemetry,
failure drills, cost caps, source freshness SLOs and deployment readiness
review. Stage 07 simulation success does **not** authorize S08 production.
