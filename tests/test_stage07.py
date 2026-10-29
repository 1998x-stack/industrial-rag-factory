"""Stage 07 reproducibility, leakage, paired inference and honest missing factors."""
from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import pytest

from industrial_rag_factory.experiments.contracts import (
    canonical_hash, load_cases, validate_config,
)
from industrial_rag_factory.experiments.cross_stage import negative_controls
from industrial_rag_factory.experiments.report import render_html
from industrial_rag_factory.experiments.runner import run_factory
from industrial_rag_factory.experiments.stats import (
    cluster_bootstrap_ci, paired_cluster_delta_ci,
)

ROOT=Path(__file__).resolve().parents[1]
CASES=ROOT/"datasets/stage07/retrieval_cases.jsonl"
CONF=ROOT/"config/stage07_experiments.json"


def test_group_holdout_and_source_splits():
    rows=load_cases(CASES)
    assert len(rows)==54
    assert {s:sum(row["split"]==s for row in rows) for s in ("train","dev","test")}=={
        "train":18,"dev":18,"test":18
    }
    groups={s:{row["group_id"] for row in rows if row["split"]==s}
            for s in ("train","dev","test")}
    assert all(len(groups[s])==9 for s in groups)
    assert all(groups[a].isdisjoint(groups[b]) for a,b in (
        ("train","dev"),("dev","test"),("train","test"))


@pytest.mark.parametrize("change",[
    lambda rows:rows[18].update(group_id=rows[0]["group_id"]),
    lambda rows:rows[18].update(source_uri=rows[0]["source_uri"]),
    lambda rows:rows[18].update(document_text=rows[0]["document_text"]),
    lambda rows:rows[18].update(question=rows[0]["question"]),
    lambda rows:rows[18].update(id=rows[0]["id"]),
])
def test_leakage_rejected(tmp_path,change):
    rows=load_cases(CASES)
    change(rows)
    file=tmp_path/"bad.jsonl"
    file.write_text("\n".join(json.dumps(x) for x in rows),encoding="utf-8")
    with pytest.raises(ValueError):
        load_cases(file)


def test_invalid_config_dimensions():
    conf=json.loads(CONF.read_text(encoding="utf-8"))
    assert len(conf["chunk_sizes"])*len(conf["overlaps"])*len(
        conf["modes"])*len(conf["seeds"])==36
    with pytest.raises(ValueError):
        validate_config({**conf,"seeds":[11,11]})
    with pytest.raises(ValueError):
        validate_config({**conf,"overlaps":[300]})
    with pytest.raises(ValueError):
        validate_config({**conf,"modes":["oracle"]})
    with pytest.raises(ValueError):
        validate_config({**conf,"bootstrap_resamples":1})


def test_cluster_bootstrap_deterministic_and_bounded():
    rows=[{"id":f"q{i}","group_id":f"g{i//2}","hit":int(i%3==0)}
          for i in range(20)]
    a=cluster_bootstrap_ci(rows,"hit",resamples=250,seed=11)
    b=cluster_bootstrap_ci(list(reversed(rows)),"hit",resamples=250,seed=11)
    assert a==b
    assert 0<=a["lower"]<=a["estimate"]<=a["upper"]<=1
    assert a["independent_groups"]==10
    assert a["resamples"]==250


def test_paired_alignment_and_zero_delta():
    rows=[{"id":f"a{i}","group_id":f"g{i//2}","hit":i%2} for i in range(8)]
    identical=paired_cluster_delta_ci(rows,list(reversed(rows)),"hit",
                                      resamples=200,seed=5)
    assert identical["estimate"]==pytest.approx(0)
    assert identical["lower"]==pytest.approx(0)
    assert identical["upper"]==pytest.approx(0)
    bad=deepcopy(rows)
    bad[0]["id"]="different"
    with pytest.raises(ValueError):
        paired_cluster_delta_ci(rows,bad,"hit")
    bad=deepcopy(rows)
    bad[0]["group_id"]="other"
    with pytest.raises(ValueError):
        paired_cluster_delta_ci(rows,bad,"hit")


def test_negative_controls_execute_real_stages():
    report=negative_controls(ROOT)
    assert report["graph"][0]["n"]==36
    assert report["graph"][0]["exact_match"]==1
    assert report["graph"][1]["exact_match"]<1
    assert report["planner"][0]["n"]==8
    assert report["planner"][0]["tool_sequence_accuracy"]==1
    assert report["planner"][1]["tool_sequence_accuracy"]<1
    assert report["claims"][0]["n"]==14
    assert report["claims"][0]["status_accuracy"]==1
    assert report["claims"][1]["status_accuracy"]<1
    assert "never disabled" in report["security"]


def test_factory_short_protocol_is_reproducible(tmp_path):
    cfg=json.loads(CONF.read_text(encoding="utf-8"))
    cfg.update(chunk_sizes=[100],overlaps=[0],modes=["sparse","hybrid"],
               seeds=[11,29],bootstrap_resamples=200)
    config=tmp_path/"protocol.json"
    config.write_text(json.dumps(cfg),encoding="utf-8")
    first=run_factory(ROOT,config_path=config)
    second=run_factory(ROOT,config_path=config)
    assert first["experiment_id"]==second["experiment_id"]
    assert first["summary"]==second["summary"]
    assert len(first["retrieval"]["runs"])==4
    assert first["retrieval"]["champion_test_ci"]==second[
        "retrieval"]["champion_test_ci"]
    assert first["data_splits"]["test"]=={"n":18,"groups":9}
    assert first["mes_gold"]["passed"]==3
    # Selection must be DEV-only and registry explicitly discloses unavailable factors.
    assert first["retrieval"]["selection_rule"].startswith("max_dev")
    assert any(x["id"]=="model" for x in first["non_measured_factors"])
    assert "production" in " ".join(first["limitations"])
    html=render_html(first)
    assert "<!doctype html>" in html and "Cluster" not in html
    assert first["experiment_id"] in html


def test_report_escapes_untrusted_labels():
    sample={"stage":"S07","experiment_id":"test",
            "summary":{"retrieval_trials":1,"retrieval_test_cases":3,
                       "claim_enabled_accuracy":.5,
                       "graph_enabled_accuracy":.5,"graph_fail_closed_accuracy":0.,
                       "planner_enabled_tool_accuracy":.5,
                       "planner_document_only_accuracy":.0,
                       "claim_fail_closed_accuracy":.0},
            "retrieval":{"champion_dev_selected":{"run_id":"abc",
                 "factor":{"chunk_size":100,"overlap":0,"mode":"sparse","seed":1}},
                 "champion_test_ci":{"mrr_at_k":{"estimate":.5,"lower":.1,
                 "upper":.9,"independent_groups":3}},
                 "paired_delta_vs_sparse":{"mrr_at_k":{"estimate":0.,"lower":-.2,
                 "upper":.2}},
                 "runs":[{"run_id":"<script>alert(1)</script>",
                          "factor":{"chunk_size":100,"overlap":0,
                                    "mode":"sparse","seed":1},
                          "metrics":{"dev":{"mrr_at_k":.5},
                                     "test":{"mrr_at_k":.5}}}]},
            "limitations":["<img src=x onerror=alert(1)>"],
            "identity":{"input_fingerprints":{}}}
    content=render_html(sample)
    assert "&lt;script&gt;" in content
    assert "&lt;img" in content
    assert "<script>alert(1)</script>" not in content


def test_run_ids_are_stable():
    x={"k":3,"mode":"hybrid","chunk":100}
    assert canonical_hash(x)==canonical_hash({"mode":"hybrid","chunk":100,"k":3})
