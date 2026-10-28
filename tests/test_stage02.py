"""Stage 02 semantic acceptance tests: offline, scoped, time-aware, no LLM."""
from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
from rdflib import RDF, URIRef

from industrial_rag_factory.semantic.graph import DATA, IOF, KnowledgeGraph, ONTO, PROV
from industrial_rag_factory.semantic.service import SemanticService
from industrial_rag_factory.semantic.validation import validate_knowledge_graph

ROOT = Path(__file__).resolve().parents[1]
PLANT = ROOT / "datasets/stage02/plant.json"
ALIASES = ROOT / "datasets/stage02/aliases.json"
CQS = ROOT / "datasets/stage02/competency.jsonl"
ONTOLOGY = ROOT / "ontology/enterprise.ttl"
SHAPES = ROOT / "ontology/shapes.ttl"
OLD = "2026-02-01T10:00:00+08:00"
NEW = "2026-10-20T10:00:00+08:00"
TENANT = "demo"
GROUPS = ("demo-readers",)


@pytest.fixture
def service():
    return SemanticService.from_defaults(ROOT)


def test_shacl_current_and_historical_graphs(service):
    for timestamp in (OLD,NEW):
        outcome = service.validate(tenant_id=TENANT,groups=GROUPS,at_time=timestamp)
        assert outcome["conforms"], outcome["report_text"]
        assert outcome["checked_triples"] > 50


def test_36_golden_competency_questions(service):
    report = service.evaluate(CQS,tenant_id=TENANT,groups=GROUPS)
    assert report["total"] == 36
    assert report["passed"] == 36, [r for r in report["results"] if not r["passed"]]
    assert report["accuracy"] == 1.0


def test_equipment_role_uses_official_iof_iri(service):
    g = service.graph.scoped(tenant_id=TENANT,groups=GROUPS,at_time=NEW)
    assert (DATA["CUT-03"],IOF.hasRole,DATA["ROLE-CUT03"]) in g
    assert (DATA["ROLE-CUT03"],RDF.type,IOF.EquipmentRole) in g
    assert (DATA["CUT-03"],ONTO.hasRole,DATA["ROLE-CUT03"]) not in g


def test_temporal_relation_filtering_and_provenance(service):
    g_old = service.graph.scoped(tenant_id=TENANT,groups=GROUPS,at_time=OLD)
    g_new = service.graph.scoped(tenant_id=TENANT,groups=GROUPS,at_time=NEW)
    assert (DATA["CUT-03"],ONTO.hasMeasurementPoint,DATA["VIB03-A"]) in g_old
    assert (DATA["CUT-03"],ONTO.hasMeasurementPoint,DATA["VIB03-A"]) not in g_new
    assert (DATA["CUT-03"],ONTO.hasMeasurementPoint,DATA["VIB03-B"]) in g_new
    assert (DATA["VIB03-A"],RDF.type,ONTO.MeasurementPoint) not in g_new
    assert (DATA["VIB03-B"],RDF.type,ONTO.MeasurementPoint) not in g_old
    assert service.graph.relationship_sources("CUT-03","hasMeasurementPoint","VIB03-B",
        tenant_id=TENANT,groups=GROUPS,at_time=NEW) == ["REC-R005"]
    stmt = DATA["assertion-R005"]
    assert (stmt,PROV.wasDerivedFrom,URIRef("fixture://relations/R005")) in g_new


def test_mapping_resolution_and_no_llm_merging(service):
    resolver = service.resolver
    now = resolver.resolve("EQ-00037",system="ERP",tenant_id=TENANT,groups=GROUPS,at_time=NEW)
    assert now.status == "resolved" and now.canonical_id == "CUT-03"
    assert resolver.resolve("SENSOR-LEGACY",system="SCADA",tenant_id=TENANT,
                            groups=GROUPS,at_time=OLD).canonical_id == "VIB03-A"
    assert resolver.resolve("SENSOR-LEGACY",system="SCADA",tenant_id=TENANT,
                            groups=GROUPS,at_time=NEW).canonical_id == "VIB03-B"
    assert resolver.resolve("SENSOR-LEGACY",system="SCADA",tenant_id=TENANT,
                            groups=GROUPS).status == "ambiguous"
    assert resolver.resolve("DUPLICATE",tenant_id=TENANT,groups=GROUPS).status == "ambiguous"
    assert resolver.resolve("NOT-APPROVED",tenant_id=TENANT,groups=GROUPS).status == "unresolved"
    assert resolver.resolve("CUT-03",system="MES",tenant_id="other-tenant",
                            groups=("other-readers",)).canonical_id == "CUT-03"
    assert resolver.resolve("CUT-03",system="MES",tenant_id="other-tenant",
                            groups=GROUPS).status == "unresolved"
    assert service.resolve("CUT-03",system="MES",tenant_id="other-tenant",
                           groups=("other-readers",))["status"] == "unresolved"


def test_acl_no_graph_leak(service,tmp_path):
    assert service.graph.traverse("CUT-03",[{"predicate":"hasRole","direction":"out"}],
                                  tenant_id="other-tenant",groups=GROUPS,at_time=NEW) == []
    assert len(service.graph.scoped(tenant_id="other-tenant",groups=GROUPS,at_time=NEW)) == 0
    output = service.export(tmp_path/"scoped.ttl",tenant_id="other-tenant",
                            groups=GROUPS,at_time=NEW)
    assert output["triples"] == 0


def test_shacl_fails_missing_sensor_tag():
    payload = json.loads(PLANT.read_text(encoding="utf-8"))
    target = next(e for e in payload["entities"] if e["id"] == "VIB04")
    del target["tag"]
    graph = KnowledgeGraph(payload,ONTOLOGY)
    result = validate_knowledge_graph(graph,SHAPES,tenant_id=TENANT,groups=GROUPS,at_time=NEW)
    assert not result.conforms
    assert "sensorTag" in result.report_text


def test_shacl_fails_missing_role_relation():
    payload = json.loads(PLANT.read_text(encoding="utf-8"))
    payload["relations"] = [r for r in payload["relations"] if not (
        r["from"] == "CUT-04" and r["predicate"] == "hasRole"
    )]
    graph = KnowledgeGraph(payload,ONTOLOGY)
    result = validate_knowledge_graph(graph,SHAPES,tenant_id=TENANT,groups=GROUPS,at_time=NEW)
    assert not result.conforms
    assert "hasRole" in result.report_text


def test_bad_relation_and_invalid_times():
    data = json.loads(PLANT.read_text(encoding="utf-8"))
    other = copy.deepcopy(data)
    other["relations"][0]["to"] = "UNKNOWN"
    with pytest.raises(ValueError,match="Dangling"):
        KnowledgeGraph(other,ONTOLOGY)
    other = copy.deepcopy(data)
    other["relations"][0]["predicate"] = "executeShellCommand"
    with pytest.raises(ValueError,match="Unknown predicate"):
        KnowledgeGraph(other,ONTOLOGY)
    other = copy.deepcopy(data)
    other["relations"][0]["valid_from"] = "2026-01-01"
    other["relations"][0]["valid_to"] = "2026-02-01T00:00:00+08:00"
    with pytest.raises(ValueError,match="offset"):
        KnowledgeGraph(other,ONTOLOGY)


def test_invalid_query_and_untrusted_schema(service):
    with pytest.raises(ValueError):
        service.traverse("CUT-03",[{"predicate":"arbitrary","direction":"out"}],
                         tenant_id=TENANT,groups=GROUPS,at_time=NEW)
    with pytest.raises(ValueError):
        service.traverse("CUT-03",[{"predicate":"hasRole","direction":"out"}]*6,
                         tenant_id=TENANT,groups=GROUPS,at_time=NEW)
    with pytest.raises(ValueError):
        service.resolve("CUT-03",system=12,tenant_id=TENANT,groups=GROUPS)


def test_cli_compatibility_and_flask_semantic_routes(service,tmp_path,monkeypatch):
    pytest.importorskip("flask")
    from industrial_rag_factory.api import create_app
    from industrial_rag_factory.config import Settings
    monkeypatch.chdir(ROOT)
    client = create_app(Settings(db_path=str(tmp_path/"demo.sqlite3"))).test_client()
    result = client.post("/v1/semantic/resolve",json={"external_id":"EQ-00037",
                          "system":"ERP","at_time":NEW})
    assert result.status_code == 200
    assert result.json["canonical_id"] == "CUT-03"
    result = client.post("/v1/semantic/traverse",json={"subject":"B-104",
             "steps":[{"predicate":"forBatch","direction":"in"},
                      {"predicate":"usesEquipment","direction":"out"}],"at_time":NEW})
    assert result.json["results"] == ["CUT-03"]
    assert client.post("/v1/semantic/traverse",json={
        "subject":"B-104","steps":[],"tenant_id":"other-tenant"}).status_code == 400


def test_shacl_detects_provenance_gap():
    payload = json.loads(PLANT.read_text(encoding="utf-8"))
    graph = KnowledgeGraph(payload,ONTOLOGY)
    from rdflib import Graph
    from pyshacl import validate as shacl_validate
    data = graph.scoped(tenant_id=TENANT,groups=GROUPS,at_time=NEW)
    statement = DATA["assertion-R001"]
    data.remove((statement,PROV.wasDerivedFrom,None))
    shape = Graph().parse(str(SHAPES),format="turtle")
    conforms,_,report = shacl_validate(data,shacl_graph=shape,inference="none")
    assert not conforms
    assert "wasDerivedFrom" in str(report)
