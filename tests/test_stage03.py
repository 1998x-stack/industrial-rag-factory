"""Stage 03 offline integration and failure-mode tests."""
from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from industrial_rag_factory.multisource.contracts import Interval
from industrial_rag_factory.multisource.evaluation import evaluate
from industrial_rag_factory.multisource.historian import HistorianReadModel
from industrial_rag_factory.multisource.service import MultiSourceService
from industrial_rag_factory.multisource.specs import SpecificationRegistry
from industrial_rag_factory.multisource.sql import MESReadModel
from industrial_rag_factory.multisource.units import compare_upper, normalize

ROOT=Path(__file__).resolve().parents[1]
DATA=ROOT/"datasets/stage03"
OLD="2026-02-01T10:00:00+08:00"


def load(name):
    return json.loads((DATA/name).read_text(encoding="utf-8"))


@pytest.fixture
def source():
    result=MultiSourceService.from_defaults(ROOT)
    yield result
    result.close()


def modified(source, *, mes=None, historian=None, specifications=None, graph=None):
    return MultiSourceService(
        graph or source.graph,
        MESReadModel(mes or load("mes.json")),
        HistorianReadModel(historian or load("historian.json")),
        SpecificationRegistry((specifications or load("specifications.json"))["specifications"]),
        resolver=source.resolver,
    )


def assess(service,batch="B-104",**kwargs):
    return service.assess_batch(batch,tenant_id="demo",groups=("demo-readers",),**kwargs)


def test_gold_benchmarks(source):
    output=evaluate(source,DATA/"gold.jsonl",tenant_id="demo",groups=("demo-readers",))
    assert output["n"]==3 and output["passed"]==3


def test_exceedance_and_evidence(source):
    result=assess(source)
    assert result["status"]=="observed_exceedance"
    assert result["valid_sample_count"]==4
    assert result["exceedance_count"]==2
    assert result["rejected_sample_count"]==0
    kinds={e["kind"] for e in result["evidence"]}
    assert {"graph_relation","mes_execution","specification","measurement"} <= kinds
    assert all(e["source_uri"] and e["source_record_id"] for e in result["evidence"])
    assert "diagnosis" in " ".join(result["limitations"])


def test_normal_and_missing(source):
    assert assess(source,"B-105")["status"]=="within_observed_limits"
    assert assess(source,"B-999")["status"]=="insufficient_evidence"


def test_scopes_filter_sql_and_historian(source):
    assert source.mes.by_batch("B-104",tenant_id="other",groups=("demo-readers",))==[]
    assert source.mes.by_batch("B-104",tenant_id="demo",groups=("wrong",))==[]
    assert source.historian.read({"VIB03-B"},Interval(
        "2026-10-20T10:00:00+08:00","2026-10-20T10:40:00+08:00"),
        tenant_id="other",groups=("demo-readers",))==[]
    result=source.assess_batch("B-104",tenant_id="other",groups=("demo-readers",))
    assert result["status"]=="insufficient_evidence"
    assert result["evidence"]==[]


def test_sql_parameterization_and_limits(source):
    assert source.mes.by_batch("' OR 1=1 --",tenant_id="demo",groups=("demo-readers",))==[]
    with pytest.raises(ValueError):
        source.mes.by_batch("B-104",tenant_id="demo",groups=())
    with pytest.raises(ValueError):
        source.mes.by_batch("B-104",tenant_id="demo",groups=("demo-readers",),max_rows=0)


def test_unit_conversion_and_quantity_kind():
    assert normalize("0.0048","vibration_velocity","m/s")[0]==normalize(
        "4.8","vibration_velocity","mm/s")[0]
    assert compare_upper("0.0048","m/s","vibration_velocity","4.5","mm/s")[0]
    with pytest.raises(ValueError):
        normalize("4.8","vibration_velocity","degC")
    with pytest.raises(ValueError):
        normalize("NaN","vibration_velocity","mm/s")
    with pytest.raises(ValueError):
        normalize("Inf","vibration_velocity","mm/s")
    assert normalize("300","temperature","K")[0]==normalize(
        "26.85","temperature","degC")[0]


def test_incomplete_series_fails_closed(source):
    h=load("historian.json")
    h["samples"]=[x for x in h["samples"] if x["sample_id"]!="M-002"]
    s=modified(source,historian=h)
    try:
        result=assess(s)
        assert result["status"]=="insufficient_evidence"
        assert result["valid_sample_count"]==3
        assert "incomplete" in " ".join(result["limitations"])
    finally:
        s.close()


def test_bad_quality_fails_closed(source):
    h=load("historian.json")
    h["samples"][2]["quality"]="BAD"
    s=modified(source,historian=h)
    try:
        assert assess(s)["status"]=="insufficient_evidence"
        assert assess(s)["rejected_sample_count"]==1
    finally:
        s.close()


def test_mismatched_kind_unit_fails_closed(source):
    h=load("historian.json")
    h["samples"][1]["unit"]="degC"
    s=modified(source,historian=h)
    try:
        assert assess(s)["status"]=="insufficient_evidence"
        assert assess(s)["rejected_sample_count"]==1
    finally:
        s.close()


def test_old_sensor_is_not_current_mapping(source):
    h=load("historian.json")
    h["samples"][0]["point_id"]="VIB03-A"
    s=modified(source,historian=h)
    try:
        result=assess(s)
        assert result["status"]=="insufficient_evidence"
        assert result["rejected_sample_count"]==1
    finally:
        s.close()


def test_temporal_historian_old_equipment_mapping(source):
    m=load("mes.json")
    row=copy.deepcopy(m["executions"][0])
    row["record_id"]="MES-HISTORIC"
    row["started"]=OLD
    row["ended"]="2026-02-01T10:20:00+08:00"
    m["executions"]=[row]
    h=load("historian.json")
    rows=[copy.deepcopy(h["samples"][0]),copy.deepcopy(h["samples"][2])]
    for idx,sample in enumerate(rows):
        sample["point_id"]="VIB03-A"
        sample["sample_id"]="OLD-"+str(idx)
        sample["timestamp"]=["2026-02-01T10:00:00+08:00",
                             "2026-02-01T10:10:00+08:00"][idx]
    h["samples"]=rows
    s=modified(source,mes=m,historian=h)
    try:
        result=assess(s)
        assert result["status"]=="observed_exceedance"
        assert result["valid_sample_count"]==2
        assert result["exceedance_count"]==1
    finally:
        s.close()


def test_graph_sql_disagreement_is_not_overridden(source):
    m=load("mes.json")
    m["executions"][0]["equipment_id"]="CUT-04"
    s=modified(source,mes=m)
    try:
        result=assess(s)
        assert result["status"]=="insufficient_evidence"
        assert "unresolved" in " ".join(result["limitations"])
    finally:
        s.close()


def test_missing_or_conflicting_specs(source):
    cfg=load("specifications.json")
    cfg["specifications"][0]["approved"]=False
    s=modified(source,specifications=cfg)
    try:
        assert assess(s)["status"]=="insufficient_evidence"
    finally:
        s.close()
    cfg=load("specifications.json")
    duplicate=copy.deepcopy(cfg["specifications"][0])
    duplicate["source_record_id"]="SP-C-CONFLICT"
    cfg["specifications"].append(duplicate)
    s=modified(source,specifications=cfg)
    try:
        assert assess(s)["status"]=="insufficient_evidence"
        assert "conflicting" in " ".join(assess(s)["limitations"])
    finally:
        s.close()


def test_spec_expiry_with_offset(source):
    cfg=load("specifications.json")
    cfg["specifications"][0]["valid_to"]="2026-10-20T02:20:00+00:00"
    s=modified(source,specifications=cfg)
    try:
        assert assess(s)["status"]=="insufficient_evidence"
    finally:
        s.close()


def test_interval_boundaries():
    t=Interval("2026-10-20T10:00:00+08:00","2026-10-20T11:00:00+08:00")
    assert t.contains("2026-10-20T02:00:00+00:00")
    assert not t.contains("2026-10-20T03:00:00+00:00")
    with pytest.raises(ValueError):
        Interval("2026-10-20T11:00:00+08:00","2026-10-20T10:00:00+08:00")
    with pytest.raises(ValueError):
        Interval("2026-10-20T11:00:00","2026-10-20T12:00:00")


def test_document_context_only(source,tmp_path):
    from industrial_rag_factory.config import Settings
    from industrial_rag_factory.parsing import from_bytes
    from industrial_rag_factory.pipeline import Pipeline
    p=Pipeline(Settings(db_path=str(tmp_path/"retrieval.sqlite3")))
    try:
        d=from_bytes(b"# CUT-03\nProcess specification is synthetic, no real limits.",
                     "fixture://cut-doc.md",".md")
        p.ingest(d)
        source.doc_retriever=p.retriever
        output=assess(source,doc_query="CUT-03 synthetic")
        assert any(e["kind"]=="document_chunk" for e in output["evidence"])
        assert output["status"]=="observed_exceedance"
    finally:
        p.close()


def test_bad_sample_provenance_rejected(source):
    data=load("historian.json")
    data["samples"][0]["source_uri"]=""
    with pytest.raises(ValueError,match="provenance"):
        HistorianReadModel(data)


def test_historian_sample_budget(source):
    window=Interval("2026-10-20T10:00:00+08:00","2026-10-20T10:40:00+08:00")
    with pytest.raises(ValueError):
        source.historian.read({"VIB03-B"},window,tenant_id="demo",
                              groups=("demo-readers",),max_samples=2)


def test_flask_multisource_scope_and_inputs(tmp_path,monkeypatch):
    pytest.importorskip("flask")
    from industrial_rag_factory.api import create_app
    from industrial_rag_factory.config import Settings
    monkeypatch.chdir(ROOT)
    app=create_app(Settings(db_path=str(tmp_path/"flask.sqlite3")))
    client=app.test_client()
    ok=client.post("/v1/multisource/assess",json={"batch_id":"B-104"})
    assert ok.status_code==200 and ok.json["status"]=="observed_exceedance"
    assert client.post("/v1/multisource/assess",json={
        "batch_id":"B-104","tenant_id":"other"}).status_code==400
    assert client.post("/v1/multisource/assess",json={
        "batch_id":"B-104","spacing_seconds":0}).status_code==400


def test_unverified_external_id_cannot_join(source):
    m=load("mes.json")
    m["executions"][0]["equipment_external_id"]="EQ-UNKNOWN"
    s=modified(source,mes=m)
    try:
        result=assess(s)
        assert result["status"]=="insufficient_evidence"
        assert "source asset ID unresolved" in " ".join(result["limitations"])
    finally:
        s.close()


def test_wrong_external_to_canonical_mapping_denied(source):
    m=load("mes.json")
    m["executions"][0]["equipment_external_id"]="EQ-00038"
    s=modified(source,mes=m)
    try:
        assert assess(s)["status"]=="insufficient_evidence"
    finally:
        s.close()


def test_identity_mapping_evidence_is_preserved(source):
    result=assess(source)
    assert any(item["kind"]=="identity_mapping" and item["source_record_id"]=="MAP-002"
               for item in result["evidence"])
