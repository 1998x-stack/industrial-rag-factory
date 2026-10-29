# Stage 12 — Robustness, Scalability and Rerank Candidate Budget

## Goal and scope

Stage 12 extends the real Stage 09–11 public corpus workflow with bounded
CPU concurrency, demonstrable read-only database isolation, synthetic
lexical distractors, larger source sets and **actual** reranker depth
execution. It does not deploy infrastructure or query live OT devices.

### Source and benchmark design

- Public dataset: NVIDIA TechQA-RAG-Eval, pinned dataset revision
  `0b5bbc84b7f07d6d09d063130e90b716d8d4a32a`.
- Default live load sample: 10 answerable + 10 unanswerable questions
  per split (60 total), and up to 96 additional unjudged corpus documents.
- Documents/corpus are the same for all load configurations; only DEV
  labels are available for future model threshold fitting. The load suite
  assesses TEST retrieval only, rather than tuning on TEST.
- A second stress index adds at most 24 synthetic text documents, each
  derived from a TRAIN question only. This is deliberately adversarial
  lexical matching stress, **not** an expert-reviewed hard-negative qrel.
- No question/answer labels are appended to public source documents.
- The corpus includes unmatched sources whose relevance is unjudged.

## Concurrent read-only FTS workloads

Run:

```bash
pip install -e '.[huggingface,dev]'
python scripts/stage12_scale.py --fetch \
  --revision 0b5bbc84b7f07d6d09d063130e90b716d8d4a32a \
  --per-class 10 --extra-corpus 96 \
  --concurrency 1 2 4 --requests-per-worker 16
```

Each of 1/2/4 client threads opens an independent SQLite `mode=ro` file
descriptor with `PRAGMA query_only=ON`. Two explicit negative probes
confirm another tenant/group cannot retrieve indexed documents. We use a
barrier to start measured closed-loop requests together and one independent
cursor/connection per worker. No write access is exercised after indexing.

Reported metrics:
- Completed QPS: number of completed client-side queries divided by observed
  wall time, measured in a synchronous/closed-loop thread pool.
- p50/p95/p99: query durations in milliseconds, *including* SQL execution,
  Python processing and source-level dedup; no network or model generation.
- Per-TEST answerable source Hit@K/MRR@K and stress-versus-base paired
  source-group cluster-bootstrap delta, separately from unanswerable cases.
- SQLite index build duration, byte size, chunk count, process max RSS.

**Measured p99 from tens of requests is not a statistical 99th-percentile
capacity/SLO qualification.** CPU scheduling, warmed OS file cache and
GitHub shared-runner variability dominate tiny differences. The benchmark
does not implement offered-load arrival control or production traffic.

## Actual pretrained reranker depth experiments

Run explicitly:

```bash
pip install -e '.[pretrained-benchmark]'
python scripts/stage12_rerank_depth.py \
  --fetch --per-class 3 --extra-corpus 8 --depths 4 8 12
```

The separate `stage12-depth.yml` GitHub workflow downloads the pinned
multilingual MiniLM embedding model and the pinned English MS MARCO
CrossEncoder from fixed allowlisted repos. **Each depth executes a real
model rerank pass** using Stage 11, with the same input snapshot and TEST
questions. It measures TEST source MRR@K, false-answer rate and actual CPU
P95 per depth. Paired source-group CIs are descriptive (3 answerable TEST
cases in the default model job), not scientific significance.

## Failure and threat controls

- Resource limits reject >8 workers, >150 requests per worker, >600 sources,
  oversized indexes, nonpositive query depth and invalid input schema.
- Positive test-source membership is validated before indexing.
- SQLite connections are NOT shared across threads; worker-access negatives
  check both tenant and group isolation.
- Only Stage01 FTS and public documents are exercised. No SQL writing on
  remote database, no arbitrary network endpoints or plant-control tools.
- The benchmark runner never writes a secret, raw public question, document
  body or model prompt in the report.
- End-to-end production SLO, security certification and availability are
  explicitly out of scope.

## Artifacts and acceptance

`outputs/stage12_scale.json` includes input revision and hashes,
concurrency/sampling settings, baseline/stress results, QA source-MRR and
paired CI. `outputs/stage12_rerank_depth.json` includes actual model full
revisions and real candidate-depth p95.

```bash
pytest -q tests/test_stage12.py tests/test_stage12_depth.py
ruff check src tests
```

Offline CI must pass both Python 3.10 and 3.12. Real public data has its own
GitHub CI lane; pretrained weights have an independent opt-in workflow.
When new stages change source scoring, golden tests must prove read-only
access and prevent TEST-label leakage.

## Next

S13 should consider source-side provenance scoring, independent evidence
annotation, end-to-end generative answer verification, externally calibrated
abstention, OTel collector traces and sustained independent-host open-loop
load tests. No code-stage success is a production OT deployment approval.
