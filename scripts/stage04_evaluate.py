"""Evaluate offline planner + bounded read-only DAG on fixed synthetic questions."""
from __future__ import annotations
import hashlib
import json
import tempfile
from dataclasses import replace
from pathlib import Path

from industrial_rag_factory.agent.evaluation import evaluate_planner
from industrial_rag_factory.agent.planner import RulePlanner
from industrial_rag_factory.agent.runner import DAGRunner
from industrial_rag_factory.agent.tools import RunContext, build_tool_registry
from industrial_rag_factory.config import Settings

ROOT=Path(__file__).resolve().parents[1]
gold=ROOT/"datasets/stage04/gold.jsonl"
with tempfile.TemporaryDirectory(prefix="irf-s04-") as tmp:
    settings=replace(Settings(),db_path=str(Path(tmp)/"index.sqlite3"))
    registry=build_tool_registry(settings,ROOT)
    try:
        result=evaluate_planner(RulePlanner(),DAGRunner(registry),gold,
                                RunContext("demo",("demo-readers",)))
    finally:
        registry.close()
result["gold_sha256"]=hashlib.sha256(gold.read_bytes()).hexdigest()
output=ROOT/"outputs"/"stage04_evaluation.json"
output.parent.mkdir(parents=True,exist_ok=True)
output.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding="utf-8")
print(f"Stage 04: {result['passed']}/{result['total']} cases passed; report={output}")
if result["passed"]!=result["total"]:
    raise SystemExit(1)
