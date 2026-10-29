"""Stage 10 offline schema, split, tuning and end-to-end QA checks."""
from __future__ import annotations

import json

import pytest

from industrial_rag_factory.hfbench.abstention import decide, metrics, tune
from industrial_rag_factory.hfbench.techqa import normalize_techqa
from industrial_rag_factory.hfbench.techqa_runner import evaluate_techqa

PIN="c"*40


def fixture_rows(n=180):
    rows=[]
    for i in range(n):
        impossible=i%2==1
        rows.append({"id":f"TRAIN_Q{i:04d}",
                     "question":f"Why does service Code_{i} report event ERR{i}?",
                     "answer":"-" if impossible else f"Check documentation Code_{i}",
                     "is_impossible":impossible,
                     "contexts":[] if impossible else [{
                         "filename":f"support_{i}.txt",
                         "text":f"# Service Code_{i}\n\n"
                                f"The documented error ERR{i} has resolution REPAIR{i}. "
                                f"Further references support_{i}.txt."}]})
    return json.dumps(rows).encode()


def test_balanced_real_schema_and_reproducible_split():
    data=fixture_rows()
    first=normalize_techqa(data,PIN,per_split_per_class=5,extra_corpus=10)
    assert first==normalize_techqa(data,PIN,per_split_per_class=5,extra_corpus=10)
    for split in ("train","dev","test"):
        assert first["counts"][split]=={"answerable":5,"unanswerable":5}
    assert first["unjudged_extra_docs"]==10
    assert all(not q["context_uris"] for q in first["queries"] if q["impossible"])
    assert {q["group_id"] for q in first["queries"] if q["split"]=="train"}.isdisjoint(
        {q["group_id"] for q in first["queries"] if q["split"]=="test"})


def test_reject_bad_or_unpinned_techqa_source():
    with pytest.raises(ValueError,match="pinned"):
        normalize_techqa(fixture_rows(),"main")
    with pytest.raises(ValueError,match="schema"):
        normalize_techqa(b'[{"id":"a"}]',PIN)
    with pytest.raises(ValueError,match="Duplicate"):
        records=json.loads(fixture_rows())
        normalize_techqa(json.dumps([records[0],records[0]]).encode(),PIN)


def test_selection_uses_dev_only_and_never_gold_in_inference():
    dev=[{"id":"p","impossible":False,"top_score":7.0},
         {"id":"n","impossible":True,"top_score":1.0}]
    result=tune(dev)
    assert result["dev_metrics"]["balanced_accuracy"]==1.0
    assert decide(7.0,result["threshold"])
    assert not decide(1.0,result["threshold"])
    assert not decide(None,result["threshold"])
    with pytest.raises(ValueError):
        metrics([dev[0]],1.0)


def test_actual_pipeline_answers_and_abstentions_are_evaluated():
    data=normalize_techqa(fixture_rows(),PIN,per_split_per_class=4,
                          extra_corpus=8)
    result=evaluate_techqa(data,k=3,chunk_size=100,overlap=20)
    assert result["stage"]=="S10"
    assert result["queries"]==24
    assert result["corpus_docs"]>=12
    assert 0<=result["evaluation"]["test"]["balanced_accuracy"]<=1
    assert result["evaluation"]["test"]["n"]==8
    assert all(q["predicted_answerable"]==decide(q["top_score"],
               result["threshold"]["threshold"]) for q in result["cases"])


def test_no_ground_truth_leak_to_index_or_report():
    normalized=normalize_techqa(fixture_rows(),PIN,per_split_per_class=4)
    assert all("is_impossible" not in d for d in normalized["docs"])
    assert all("answer" not in d for d in normalized["docs"])
    assert all("answer" not in q for q in normalized["queries"])
