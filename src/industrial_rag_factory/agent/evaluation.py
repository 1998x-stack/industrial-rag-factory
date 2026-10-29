"""Offline planner-selection and DAG execution benchmark on synthetic fixtures."""
from __future__ import annotations

import json
from pathlib import Path

from .planner import RulePlanner
from .runner import DAGRunner
from .tools import RunContext


def evaluate_planner(planner: RulePlanner, runner: DAGRunner, path: str | Path,
                     context: RunContext) -> dict:
    entries=[json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines()
             if line.strip()]
    if not entries or len({x["id"] for x in entries})!=len(entries):
        raise ValueError("Evaluation dataset must have unique, nonempty IDs")
    outputs=[]
    for row in entries:
        plan=planner.plan(row["question"])
        selected=[step.tool for step in plan.ordered_steps()]
        expected=row["expected_tools"]
        correct_tools=selected==expected
        correct_intent=plan.intent==row["expected_intent"]
        execution=runner.run(plan,context)
        status=execution["status"]
        expected_status=row["expected_execution"]
        result_key=row.get("inspect_step")
        output_status=(execution["results"].get(result_key,{}).get("status")
                       if result_key else None)
        expected_output_status=row.get("expected_output_status")
        expected_entities=row.get("expected_entities")
        entity_ok=True
        if expected_entities is not None:
            entities=execution["results"].get(result_key,{}).get("results",[])
            entity_ok=entities==expected_entities
        passed_all=(correct_tools and correct_intent and status==expected_status
                    and output_status==expected_output_status and entity_ok)
        outputs.append({"id":row["id"],"tools_correct":correct_tools,
                        "intent_correct":correct_intent,
                        "execution_correct":status==expected_status,
                        "output_correct":output_status==expected_output_status and entity_ok,
                        "passed":passed_all})
    total=len(outputs)
    return {"stage":"S04","total":total,
            "passed":sum(x["passed"] for x in outputs),
            "planner_tool_accuracy":sum(x["tools_correct"] for x in outputs)/total,
            "intent_accuracy":sum(x["intent_correct"] for x in outputs)/total,
            "execution_accuracy":sum(x["execution_correct"] for x in outputs)/total,
            "case_accuracy":sum(x["passed"] for x in outputs)/total,
            "details":outputs}
