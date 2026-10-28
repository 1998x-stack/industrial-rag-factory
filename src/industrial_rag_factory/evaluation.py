"""Deterministic retrieval evaluation; no paid LLM calls."""
from __future__ import annotations
import json
from pathlib import Path
from .pipeline import Pipeline


def evaluate_jsonl(pipeline: Pipeline, path: str | Path, *, tenant: str,
                   groups: tuple[str, ...], mode: str = "hybrid", k: int = 5) -> dict:
    rows = []
    for line_number,line in enumerate(Path(path).read_text(encoding="utf-8").splitlines(),1):
        if not line.strip():
            continue
        item = json.loads(line)
        question = item["question"]
        gold = set(item["relevant_source_uris"])
        if not gold:
            raise ValueError(f"Row {line_number} must have gold source URIs")
        hits = pipeline.retriever.search(question,tenant=tenant,groups=groups,mode=mode,top_k=k)
        ranked = [hit.source_uri for hit in hits]
        unique = list(dict.fromkeys(ranked))
        found = set(unique)&gold
        rr = next((1/(i+1) for i,uri in enumerate(unique) if uri in gold),0.0)
        rows.append(dict(question=question,recall=len(found)/len(gold),
                         reciprocal_rank=rr,hit=bool(found),retrieved=unique))
    if not rows:
        raise ValueError("Evaluation dataset is empty")
    return dict(mode=mode,k=k,n=len(rows),recall_at_k=sum(x["recall"] for x in rows)/len(rows),
                mrr_at_k=sum(x["reciprocal_rank"] for x in rows)/len(rows),
                hit_rate_at_k=sum(x["hit"] for x in rows)/len(rows),details=rows)
