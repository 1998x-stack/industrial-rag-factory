"""Stage 12 workload and isolation golden tests; authored fixture only."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from industrial_rag_factory.hfbench.scale import (
    _build_index, _open_readonly, _snapshot_documents, percentile, run_scale,
)
from industrial_rag_factory.hfbench.techqa import normalize_techqa

SHA="b"*40


def sample(rows=180):
    content=[]
    for index in range(rows):
        impossible=bool(index%2)
        content.append({
            "id":f"WORKLOAD_{index:04d}",
            "question":f"Why does equipment tag CAL_{index:04d} mention ALM_{index:04d}?",
            "answer":"gold text never indexed",
            "is_impossible":impossible,
            "contexts":[] if impossible else [{
                "filename":f"cal_{index}.md",
                "text":f"# Calibration Tag CAL_{index:04d}\n\n"
                        f"Alarm ALM_{index:04d} appears in the public test context. "
                        f"Check synthetic operation notes reference LOT_{index:04d}."
            }]
        })
    return normalize_techqa(json.dumps(content).encode(),SHA,
                            per_split_per_class=4,extra_corpus=12)


def test_closed_loop_independent_threads_and_robustness():
    snapshot=sample()
    result=run_scale(snapshot,concurrencies=(1,2,4),requests_per_worker=8,
                     warmups=1,k=3)
    assert result["stage"]=="S12"
    assert result["test_questions"]==8
    assert set(result["scenarios"])=={"base","stress"}
    assert result["scenarios"]["stress"]["index"]["synthetic_decoys"]>0
    assert result["scenarios"]["base"]["index"]["synthetic_decoys"]==0
    assert result["paired_test_mrr_stress_minus_base"]["paired"] is True
    for item in result["scenarios"].values():
        assert len(item["load"])==3
        for run in item["load"]:
            assert run["errors"]==0
            assert run["requests"]==run["concurrency"]*8
            assert run["closed_loop_qps"]>0
            assert 0<=run["p50_ms"]<=run["p95_ms"]<=run["p99_ms"]
            assert run["access_boundary_checks_per_worker"]==2
    assert "not real" not in " ".join(result["limitations"])


def test_train_only_decoy_never_contains_test_queries():
    snapshot=sample()
    docs,count=_snapshot_documents(snapshot,stress=True)
    synthetic=[d for d in docs if d["source_uri"].startswith("fixture://s12/")]
    assert count==len(synthetic)>0
    body=" ".join(d["text"] for d in synthetic)
    for query in snapshot["queries"]:
        if query["split"]=="test":
            assert query["question"] not in body
    assert all("gold text never indexed" not in d["text"] for d in synthetic)


def test_readonly_handle_denies_ddl_and_foreign_tenant(tmp_path):
    snapshot=sample()
    db=tmp_path/"index.sqlite3"
    _build_index(snapshot,db,stress=False)
    store=_open_readonly(db)
    try:
        with pytest.raises(sqlite3.DatabaseError):
            store.con.execute("DROP TABLE documents")
        assert not store.sparse("CAL_0000",tenant="another",
                                groups=("techqa-benchmark",))
    finally:
        store.close()


def test_resource_limits_and_percentile():
    snapshot=sample()
    with pytest.raises(ValueError,match="concurrency"):
        run_scale(snapshot,concurrencies=(0,))
    with pytest.raises(ValueError,match="concurrency"):
        run_scale(snapshot,concurrencies=(1,1))
    with pytest.raises(ValueError,match="workload"):
        run_scale(snapshot,concurrencies=(1,),requests_per_worker=0)
    assert percentile([10,20,30,40,50],.95)==48.
    assert percentile([10,20,30,40,50],.99)==49.6
    with pytest.raises(ValueError):
        percentile([],.5)


def test_only_public_sources_and_no_raw_question_in_summary():
    snapshot=sample()
    result=run_scale(snapshot,concurrencies=(1,),requests_per_worker=8,
                     warmups=0,stress=False)
    assert "stress" not in result["scenarios"]
    assert result["test_questions"]==8
    serialized=json.dumps(result)
    assert "Why does equipment tag" not in serialized
    assert "gold text never indexed" not in serialized
