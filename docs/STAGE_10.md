# Stage 10 — Second real public dataset and conservative abstention

## Dataset scope

[NVIDIA TechQA-RAG-Eval](https://huggingface.co/datasets/nvidia/TechQA-RAG-Eval)
is an Apache-2.0-labelled technical-support benchmark with a `train.json`
file containing IDs, questions, answers, `is_impossible` and provided
support contexts. This is sourced from IT support content, NOT industrial
sensor readings, approved factory documents or real OT systems.

## End-to-end design

    HF dataset_info (full revision/declared license)
      -> pinned train.json download + raw SHA-256
      -> validate schema/duplicate questions/IDs
      -> normalize context source URIs by content SHA
      -> group linked contexts, stable train/dev/test split
      -> balanced question selection (answerable vs impossible)
      -> add unmatched unjudged corpus documents
      -> Stage 01 parser/chunk/SQLite FTS5 retrieval
      -> rank deduplicated source documents
      -> score + gold evaluation (labels never enter retrieval)
      -> DEV-only cutoff selection
      -> TEST frozen threshold confusion/coverage + answerable retrieval
      -> JSON report, CI artifact

The `is_impossible` label must not be passed as an inference argument,
appended to indexed source documents, used in candidate ranking or used
in score cutoff prediction. It is used to compute outcomes after retrieval.

## Reproduce

```bash
pip install -e '.[huggingface,dev]'
python scripts/stage10_techqa.py --fetch --per-class 6 --extra-corpus 48 --k 3
python -m pytest -q
python -m ruff check src tests
```

Online GitHub CI pins the resolved commit, emits a source hash and computes
held-out TEST metrics; it does not use invented fallback data.
Offline unit tests use separately authored synthetic documents only and make
no network requests.

## Metrics and caveats

- Answerable source Hit@K/MRR@K against author-provided context refs
- Answerability confusion matrix, balanced accuracy, false-answer rate
  on labeled impossible cases, and coverage
- DEV tuning rule fixed before TEST evaluation
- Document-level rank measured from overfetched FTS chunks
- Original query texts, answers and raw document bodies never appear in
  GitHub Actions report artifacts

An FTS score depends on corpus size, length, tokenization, chunking and
retrieval backend. The resulting threshold is a reproducible experimental
decision rule, not a calibrated model probability, physical safety decision
or enterprise production gate. Because author contexts are incomplete and
unanswerable gold may be imperfect, observed false-answer rates are not
universal hallucination rates.

## Next steps

Introduce a pretrained multilingual embedding model with pinned model
revision and explicit opt-in GPU/CPU resource budget; compare to sparse on
several larger and independently labeled corpora. Add semantic/rerank
calibration, multi-domain class imbalance and bootstrapped uncertainty
before claiming significant model improvements. S06 real IAM/OT barriers
remain required for any production application.

## Opt-in true semantic embedding comparison

The existing S01 Pipeline already supports `sentence-transformers`; S10
adds an independently pinned model downloader for the fixed, public
`sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2` repository.
This is an Apache-2.0-labelled pretrained multilingual 384-D encoder.

```bash
pip install -e '.[huggingface,dense]'
python scripts/stage10_techqa.py --snapshot data/hf/techqa.json \
  --multilingual --mode dense --model-revision main
python scripts/stage10_techqa.py --snapshot data/hf/techqa.json \
  --multilingual --mode hybrid --model-revision main
```

The execution resolves and records the exact upstream model commit before
downloading to the local Hugging Face cache; the CI production lane retains
only sparse retrieval without a network model download. Compare reports by
query IDs and model revisions, not by indexing-order seeds. The CPU model
download may be hundreds of MB and inference may be slow; both operations
require an explicit CLI flag and optional dependency installation.

This path is **implemented but not claimed to have been run** as part of
the normal CI. Real semantic retrieval metrics need explicit execution
and head-to-head analysis; no learned reranker is yet integrated.
