"""S11 design gates: gold isolation, paired ranking, score tuning, strict JSON."""
from __future__ import annotations

import json

import pytest

from industrial_rag_factory.hfbench.stage11 import (
    _fusion, evaluate_stage11, percentile,
)
from industrial_rag_factory.hfbench.techqa import normalize_techqa

REV="a"*40


def fixture(n=180):
    rows=[]
    for i in range(n):
        bad=i%2==1
        rows.append({
            "id":f"S11-{i:04d}",
            "question":f"Procedure REG{i} mentions serial SN{i}?",
            "is_impossible":bad,
            "answer":"should not enter index",
            "contexts":[] if bad else [{"filename":f"REG{i}.txt",
                "text":f"# REG{i}\n\nMachine reference SN{i} is a sample technical code. "
                       f"Work note REG{i} described with enough text to index."}],
        })
    return normalize_techqa(json.dumps(rows).encode(),REV,
                            per_split_per_class=3,extra_corpus=6)


class FakeEncoder:
    def encode(self,texts,*,batch_size=16,normalize_embeddings=True):
        assert normalize_embeddings
        return [[1.0,0.0] if "REG1" in t else [0.0,1.0] for t in texts]


class FakeReranker:
    def predict(self,pairs,*,batch_size,show_progress_bar):
        assert pairs and batch_size==8 and not show_progress_bar
        return [float(i+1) for i in range(len(pairs))]


def test_s11_fixture_real_stage01_four_lanes_offline():
    doc=fixture()
    result=evaluate_stage11(doc,encoder=FakeEncoder(),reranker=FakeReranker(),
                            k=3,candidates=7,chunk_size=120,overlap=20,
                            bootstrap_resamples=100)
    assert result["stage"]=="S11"
    assert set(result["lanes"])=={
        "sparse","dense","hybrid","hybrid_reranked"}
    assert result["models_executed"]
    assert len(result["paired_test_mrr_delta_vs_sparse"])==3
    for name,lane in result["lanes"].items():
        assert lane["splits"]["test"]["n"]==6
        assert 0<=lane["splits"]["test"]["mrr_at_k"]<=1
        assert 0<=lane["splits"]["test"]["false_answer_rate"]<=1
        assert len(lane["cases"])==18
    assert "is_impossible" not in " ".join(d["text"] for d in doc["docs"])
    json.dumps(result,allow_nan=False)


def test_sparse_alone_is_offline_and_does_not_fake_model_execution():
    result=evaluate_stage11(fixture(),k=3,chunk_size=120,overlap=20)
    assert not result["models_executed"]
    assert list(result["lanes"])==["sparse"]
    assert result["paired_test_mrr_delta_vs_sparse"]=={}


def test_invalid_backend_pair_and_resource_limits():
    data=fixture()
    with pytest.raises(ValueError,match="together"):
        evaluate_stage11(data,encoder=FakeEncoder())
    with pytest.raises(ValueError,match="budget"):
        evaluate_stage11(data,k=11)
    with pytest.raises(ValueError,match="budget"):
        evaluate_stage11(data,bootstrap_resamples=5)


def test_rrf_score_ties_and_percentile():
    assert _fusion(["a","b"],["b","a"])[0][0]=="a"
    assert percentile([5.,1.,9.],.5)==5.
    assert percentile([],.95) is None


def test_provenance_wrong_source_rejected():
    data=fixture()
    data["queries"][0]["context_uris"]=["hf://fabricated"]
    with pytest.raises(ValueError,match="Missing relevant"):
        evaluate_stage11(data)
