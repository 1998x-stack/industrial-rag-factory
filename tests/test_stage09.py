"""Strict offline HF protocol tests using authored tiny CSV, no HF claims."""
from __future__ import annotations

import csv
import io
from copy import deepcopy

import pytest

from industrial_rag_factory.hfbench.adapter import load_industrybench_csv
from industrial_rag_factory.hfbench.metrics import score
from industrial_rag_factory.hfbench.runner import evaluate_benchmark

SHA="a"*40


def rows_csv(n=150):
    buffer=io.StringIO()
    columns=["id","question","answer","knowledge_text","industry_primary",
             "capability","difficulty","question_en","answer_en"]
    writer=csv.DictWriter(buffer,fieldnames=columns)
    writer.writeheader()
    for i in range(n):
        writer.writerow({
            "id":str(i),"question":f"What is regulator AX{i} inspection code?",
            "answer":f"AX{i}","knowledge_text":
                f"# Regulator family AX{i}\n\nEquipment inspection code AX{i} "
                f"is recorded in this entirely invented unit-test document. "
                f"Distinct calibration serial reference R{i:05d}.",
            "industry_primary":"Mechanical","capability":"metadata_lookup",
            "difficulty":"easy","question_en":f"Which reference for AX{i}?",
            "answer_en":f"AX{i}",
        })
    return buffer.getvalue().encode("utf-8")


def test_schema_group_holdout_and_version_provenance():
    raw=rows_csv()
    bench=load_industrybench_csv(raw,revision=SHA,limit_per_split=8)
    assert bench["dataset_id"]=="alibaba-multimodal-industrial-ai/IndustryBench"
    assert bench["raw_sha256"] and bench["revision"]==SHA
    assert all(4<=bench["counts"][s]<=8 for s in ("train","dev","test"))
    splits={s:{q["group_id"] for q in bench["queries"] if q["split"]==s}
            for s in ("train","dev","test")}
    assert splits["train"].isdisjoint(splits["dev"])
    assert splits["dev"].isdisjoint(splits["test"])
    assert splits["train"].isdisjoint(splits["test"])
    assert all(q["gold_source_uri"] in {d["source_uri"] for d in bench["documents"]}
               for q in bench["queries"])
    assert load_industrybench_csv(raw,revision=SHA,limit_per_split=8)==bench


def test_schema_rejects_unpinned_revision_and_duplicate_ids():
    with pytest.raises(ValueError,match="full"):
        load_industrybench_csv(rows_csv(),revision="main")
    input_rows=rows_csv().decode().splitlines()
    duplicate="\n".join(input_rows+[input_rows[1]])+"\n"
    with pytest.raises(ValueError,match="duplicate"):
        load_industrybench_csv(duplicate.encode(),revision=SHA)


def test_schema_missing_columns_fail_closed():
    with pytest.raises(ValueError,match="fields"):
        load_industrybench_csv(b"id,question\n1,something\n",
                               revision=SHA)


def test_duplicate_question_is_not_counted_twice():
    raw=rows_csv(151).decode("utf-8")
    duplicated=raw.replace("What is regulator AX150 inspection code?",
                            "What is regulator AX0 inspection code?")
    bench=load_industrybench_csv(duplicated.encode(),revision=SHA,limit_per_split=8)
    assert sum(q["question"]=="What is regulator AX0 inspection code?"
               for q in bench["queries"])<=1


def test_dataset_report_and_textual_claim_scope():
    bench=load_industrybench_csv(rows_csv(),revision=SHA,limit_per_split=7)
    report=evaluate_benchmark(bench,modes=("sparse","hybrid"),k=3,
                              chunk_size=120,overlap=20,resamples=100)
    assert report["stage"]=="S09"
    assert report["queries"]==sum(bench["counts"].values())
    assert report["corpus_docs"]==len(bench["documents"])
    assert set(report["modes"])=={"sparse","hybrid"}
    assert 0<=report["modes"]["sparse"]["scores"]["test"]["mrr"]<=1
    assert len(report["modes"]["sparse"]["cases"])==report["queries"]
    assert report["modes"]["sparse"]["scores"]["test"]["mrr_ci"]["independent_groups"]>=2
    assert all(item["grounding_status"] in (
        "retrieved_not_verified","insufficient_evidence")
        for item in report["modes"]["hybrid"]["cases"])
    assert all("supported"!=r["grounding_status"] for r in
               report["modes"]["sparse"]["cases"])
    assert "not independently" in " ".join(report["limitations"])


def test_missing_reference_or_bad_mode_rejected():
    bench=load_industrybench_csv(rows_csv(),revision=SHA,limit_per_split=8)
    wrong=deepcopy(bench)
    wrong["queries"][0]["gold_source_uri"]="hf://nonexistent"
    with pytest.raises(ValueError,match="Gold"):
        evaluate_benchmark(wrong,modes=("sparse",),resamples=100)
    with pytest.raises(ValueError,match="bounds"):
        evaluate_benchmark(bench,modes=("shell.exec",),resamples=100)


def test_document_level_dedup_metrics_are_bounded():
    a=score(["doc1","doc1","doc2"],{"doc2"},3)
    assert a["hit"]==1
    assert a["mrr"]==pytest.approx(.5)
    assert a["ndcg"]==pytest.approx(1/__import__("math").log2(3))
    miss=score(["doc1"],{"doc3"},3)
    assert miss["recall"]==0 and miss["mrr"]==0
    with pytest.raises(ValueError):
        score(["doc1"],set(),3)


def test_unjudged_distractor_sources_do_not_count_as_qrels():
    prepared=load_industrybench_csv(rows_csv(150),revision=SHA,
                                    limit_per_split=8,distractor_docs=30)
    assert prepared["unjudged_distractor_docs"]==30
    targets={q["gold_source_uri"] for q in prepared["queries"]}
    extras={d["source_uri"] for d in prepared["documents"]}-targets
    assert len(extras)==30
    report=evaluate_benchmark(prepared,modes=("sparse",),k=3,
                              chunk_size=120,overlap=20,resamples=100)
    assert report["unjudged_distractor_docs"]==30
    assert report["corpus_docs"]>report["queries"]
