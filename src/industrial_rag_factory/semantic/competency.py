"""Executable competency questions against an authorized, time-valid relation graph."""
from __future__ import annotations
import json
from pathlib import Path

from .graph import KnowledgeGraph


def evaluate_competency_questions(
    kg: KnowledgeGraph, path: str | Path, *,
    tenant_id: str, groups: tuple[str, ...],
) -> dict:
    entries = [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines()
               if line.strip()]
    if not entries:
        raise ValueError("Empty competency-question set")
    if len({x["id"] for x in entries}) != len(entries):
        raise ValueError("Competency question IDs must be unique")
    results = []
    for item in entries:
        actual = kg.traverse(item["subject"],item["steps"],tenant_id=tenant_id,
                             groups=groups,at_time=item.get("at_time"))
        expected = sorted(set(item["expected"]))
        results.append({
            "id":item["id"],"question":item["question"],
            "expected":expected,"actual":actual,"passed":actual == expected,
            "status":"answered" if actual else "no_verified_path",
        })
    passed = sum(x["passed"] for x in results)
    return {"total":len(results),"passed":passed,
            "accuracy":passed/len(results),"results":results}
