"""Stage 04 trusted execution boundary, DAG and planner regression tests."""
from __future__ import annotations

import json
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from industrial_rag_factory.agent.contracts import PlanValidationError, QueryPlan
from industrial_rag_factory.agent.evaluation import evaluate_planner
from industrial_rag_factory.agent.planner import DeepSeekPlanner, RulePlanner
from industrial_rag_factory.agent.runner import DAGRunner, ExecutionPolicy
from industrial_rag_factory.agent.service import AgentService
from industrial_rag_factory.agent.tools import (
    ReadOnlyTool, RunContext, ToolRegistry, TransientToolError, build_tool_registry,
)
from industrial_rag_factory.config import Settings

ROOT=Path(__file__).resolve().parents[1]
C=RunContext("demo",("demo-readers",))


def plan(steps):
    return QueryPlan.from_dict({"intent":"test","steps":steps})


@pytest.fixture
def registry(tmp_path):
    r=build_tool_registry(Settings(db_path=str(tmp_path/"s04.sqlite3")),ROOT)
    yield r
    r.close()


def test_golden_offline_planning_and_execution(registry):
    result=evaluate_planner(RulePlanner(),DAGRunner(registry),
                            ROOT/"datasets/stage04/gold.jsonl",C)
    assert result["total"]==8
    assert result["passed"]==8, [x for x in result["details"] if not x["passed"]]


def test_dynamic_references_and_lineage(registry):
    proposal=RulePlanner().plan("请查 ERP EQ-00037 的测点")
    assert proposal.steps[1].args["subject"]=={"$ref":"identity.canonical_id"}
    result=DAGRunner(registry).run(proposal,C)
    assert result["status"]=="completed"
    assert result["results"]["identity"]["canonical_id"]=="CUT-03"
    assert result["results"]["points"]["results"]==["TEMP03","VIB03-B"]
    assert [x["state"] for x in result["trace"]]==["succeeded","succeeded"]


def test_stage03_batch_assessment_is_unchanged(registry):
    result=DAGRunner(registry).run(RulePlanner().plan("B-104 是否有振动异常"),C)
    assert result["status"]=="completed"
    assert result["results"]["assessment"]["status"]=="observed_exceedance"
    assert result["results"]["assessment"]["exceedance_count"]==2
    assert all("secret" not in str(x).lower() for x in result["trace"])


def test_no_cross_tenant_data(registry):
    result=DAGRunner(registry).run(RulePlanner().plan("B-104 是否异常"),
                                  RunContext("other",("demo-readers",)))
    assert result["results"]["mes"]["records"]==[]
    assert result["results"]["assessment"]["status"]=="insufficient_evidence"


@pytest.mark.parametrize("bad",[
    {"intent":"x","steps":[{"id":"a","tool":"shell.exec","args":{"command":"x"}}]},
    {"intent":"x","steps":[{"id":"a","tool":"mes.by_batch",
                           "args":{"batch_id":"B-104","tenant_id":"other"}}]},
    {"intent":"x","steps":[{"id":"a","tool":"mes.by_batch","args":{"batch_id":"B-104"},
                            "max_retries":3}]},
    {"intent":"x","steps":[{"id":"a","tool":"mes.by_batch","args":{"batch_id":"B-104"},
                           "depends_on":["b"]},{"id":"b","tool":"mes.by_batch",
                           "args":{"batch_id":"B-104"},"depends_on":["a"]}]},
    {"intent":"x","steps":[{"id":"a","tool":"mes.by_batch","args":{"batch_id":"B-104"}},
                           {"id":"b","tool":"graph.traverse",
                            "args":{"subject":{"$ref":"a.records.0.batch_id"},
                             "steps":[{"predicate":"forBatch","direction":"in"}]}}]},
    {"intent":"x","steps":[{"id":"a","tool":"graph.traverse","args":{
        "subject":"CUT-03","steps":[{"predicate":"dropEverything","direction":"out"}]}}]},
    {"intent":"x","steps":[{"id":"a","tool":"historian.read","args":{
        "point_ids":["VIB03-B"],"start":"2026-10-20T10:00:00+08:00",
        "end":"2026-10-20T10:00:00+08:00"}}]},
])
def test_bad_plan_is_rejected(bad):
    with pytest.raises((PlanValidationError,ValueError)):
        QueryPlan.from_dict(bad)


def test_missing_dependency_is_blocked_and_never_executes():
    calls=[]
    def never(args,context):
        calls.append(1)
        return {"status":"called"}
    r=ToolRegistry([ReadOnlyTool("graph.traverse",never),
                    ReadOnlyTool("entity.resolve",lambda a,c:{"status":"unresolved",
                                                               "canonical_id":None})])
    p=plan([
        {"id":"a","tool":"entity.resolve","args":{"external_id":"UNKNOWN"}},
        {"id":"b","tool":"graph.traverse","args":{
            "subject":{"$ref":"a.canonical_id"},
            "steps":[{"predicate":"hasRole","direction":"out"}]},"depends_on":["a"]},
        {"id":"c","tool":"graph.traverse","args":{
            "subject":{"$ref":"b.results.0"},
            "steps":[{"predicate":"hasRole","direction":"in"}]},"depends_on":["b"]},
    ])
    result=DAGRunner(r).run(p,C)
    assert result["status"]=="partial"
    assert result["step_status"]=={"a":"succeeded","b":"failed","c":"blocked"}
    assert not calls


def test_retries_only_transient_failure():
    calls=[]
    def flaky(args,context):
        calls.append(1)
        if len(calls)==1:
            raise TransientToolError("pretend provider unavailable")
        return {"status":"recovered"}
    r=ToolRegistry([ReadOnlyTool("mes.by_batch",flaky)])
    p=plan([{"id":"attempt","tool":"mes.by_batch","args":{"batch_id":"B-104"},
             "max_retries":1}])
    result=DAGRunner(r).run(p,C)
    assert result["status"]=="completed"
    assert result["trace"][0]["attempts"]==2
    assert result["results"]["attempt"]["status"]=="recovered"


def test_step_timeout_prevents_dependent_tools():
    called=[]
    def delayed(args,context):
        time.sleep(0.12)
        return {"status":"late"}
    def next_tool(args,context):
        called.append(True)
        return {"status":"bad"}
    registry=ToolRegistry([ReadOnlyTool("mes.by_batch",delayed),
                           ReadOnlyTool("batch.assess",next_tool)])
    p=plan([
        {"id":"slow","tool":"mes.by_batch","args":{"batch_id":"B-104"},
         "timeout_ms":50,"max_retries":1},
        {"id":"next","tool":"batch.assess","args":{"batch_id":"B-104"},
         "depends_on":["slow"]},
    ])
    output=DAGRunner(registry).run(p,C)
    assert output["status"]=="failed"
    assert output["trace"][0]["error_code"]=="step_timeout"
    assert output["trace"][0]["attempts"]==1
    assert output["step_status"]["next"]=="blocked"
    assert not called


def test_output_budget_and_total_budget():
    r=ToolRegistry([ReadOnlyTool("mes.by_batch",lambda a,c:{"large":"x"*3000})])
    p=plan([{"id":"big","tool":"mes.by_batch","args":{"batch_id":"B-104"}}])
    output=DAGRunner(r,ExecutionPolicy(max_output_chars=1000)).run(p,C)
    assert output["trace"][0]["error_code"]=="output_budget_exceeded"


def test_invalid_reference_path_does_not_execute_target():
    seen=[]
    r=ToolRegistry([ReadOnlyTool("entity.resolve",lambda a,c:{"status":"resolved"}),
                    ReadOnlyTool("graph.traverse",lambda a,c:(seen.append(True) or {}))])
    p=plan([{"id":"id","tool":"entity.resolve","args":{"external_id":"EQ-00037"}},
            {"id":"graph","tool":"graph.traverse",
            "args":{"subject":{"$ref":"id.no_such_field"},
                    "steps":[{"predicate":"hasRole","direction":"out"}]},
             "depends_on":["id"]}])
    result=DAGRunner(r).run(p,C)
    assert result["step_status"]["graph"]=="failed" and not seen


def test_deepseek_model_proposal_validated_and_mocked():
    class FakeClient:
        def __init__(self,body):
            self.body=body
            self.chat=SimpleNamespace(completions=SimpleNamespace(create=self.create))
        def create(self,**kwargs):
            assert kwargs["response_format"]=={"type":"json_object"}
            return SimpleNamespace(choices=[SimpleNamespace(finish_reason="stop",
                message=SimpleNamespace(content=json.dumps(self.body)))])
    good={"intent":"document_lookup","steps":[{"id":"docs","tool":"document.search",
          "args":{"question":"pump noise","top_k":3}}]}
    p=DeepSeekPlanner(api_key="mock-key",base_url="https://api.deepseek.com",
                       model="deepseek-flash",client=FakeClient(good)).plan("pump noise")
    assert p.steps[0].tool=="document.search"
    bad={"intent":"unsafe","steps":[{"id":"exec","tool":"os.system",
          "args":{"command":"echo unsafe"}}]}
    with pytest.raises(PlanValidationError):
        DeepSeekPlanner(api_key="mock-key",base_url="https://api.deepseek.com",
                        model="deepseek-flash",client=FakeClient(bad)).plan("request")
    with pytest.raises(ValueError):
        DeepSeekPlanner(api_key="",base_url="https://api.deepseek.com",model="deepseek-flash")


def test_agent_service_no_actual_llm_key_and_rule_fallback(registry):
    svc=AgentService(Settings(),registry=registry,planner=RulePlanner())
    result=svc.query("B-105 的振动情况")
    assert result["status"]=="completed"
    assert result["planner"]=="rules-stage04-v1"
    assert result["results"]["assessment"]["status"]=="within_observed_limits"


def test_flask_agent_route_local_and_scoped(tmp_path,monkeypatch):
    pytest.importorskip("flask")
    from industrial_rag_factory.api import create_app
    monkeypatch.chdir(ROOT)
    c=create_app(Settings(db_path=str(tmp_path/"api.sqlite3"))).test_client()
    response=c.post("/v1/agent/query",json={"question":"B-104 状态怎么样"})
    assert response.status_code==200
    assert response.json["results"]["assessment"]["exceedance_count"]==2
    assert c.post("/v1/agent/query",json={
        "question":"B-104","tenant_id":"another"}).status_code==400
    assert c.post("/v1/agent/query",json={
        "question":"B-104","planner":"deepseek"}).status_code==400
