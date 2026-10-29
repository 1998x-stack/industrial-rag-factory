"""True Stage11 execution with injected deterministic fake models."""
from __future__ import annotations

import json

import pytest

from industrial_rag_factory.hfbench.depth import benchmark_depths
from industrial_rag_factory.hfbench.techqa import normalize_techqa

PIN="e"*40


class FakeEncoder:
    def encode(self,texts,*,batch_size=16,normalize_embeddings=True):
        return [[1.,0.] if "CTRL" in text else [0.,1.] for text in texts]


class FakeReranker:
    def predict(self,pairs,*,batch_size=8,show_progress_bar=False):
        return [float(len(text)) for _,text in pairs]


def fixture():
    rows=[]
    for n in range(180):
        rows.append({
            "id":f"DP{n:04d}",
            "question":f"Explain CTRL{n} incident note CODE{n}?",
            "is_impossible":bool(n%2),
            "contexts":[] if n%2 else [{
                "filename":f"CTRL{n}.txt",
                "text":f"# CTRL{n}\n\nIncident CODE{n} describes a "
                       "synthetic calibration note."}],
        })
    return normalize_techqa(json.dumps(rows).encode(),PIN,
                            per_split_per_class=3,extra_corpus=6)


def test_real_stage11_depth_execution_with_mock_weights():
    result=benchmark_depths(fixture(),FakeEncoder(),FakeReranker(),
                             depths=(4,7),k=3)
    assert result["stage"]=="S12"
    assert list(result["runs"])==["4","7"]
    assert "7" in result["paired_test_mrr_vs_min_depth"]
    assert result["runs"]["4"]["test"]["n"]==6
    assert result["runs"]["7"]["test"]["p95_latency_ms"]>=0
    json.dumps(result,allow_nan=False)


def test_depth_budget_fails_closed():
    with pytest.raises(ValueError,match="candidate-depth"):
        benchmark_depths(fixture(),FakeEncoder(),FakeReranker(),
                         depths=(2,),k=3)
    with pytest.raises(ValueError,match="candidate-depth"):
        benchmark_depths(fixture(),FakeEncoder(),FakeReranker(),
                         depths=(4,4),k=3)
