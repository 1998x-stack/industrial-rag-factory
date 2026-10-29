"""Fixed synthetic cross-source gold benchmark; deterministic and free of LLM API calls."""
from __future__ import annotations

import json
from pathlib import Path

from .service import MultiSourceService


def evaluate(service: MultiSourceService, path: str | Path, *,
             tenant_id: str, groups: tuple[str, ...]) -> dict:
    entries=[json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines()
             if line.strip()]
    if not entries or len({r["id"] for r in entries})!=len(entries):
        raise ValueError("Nonempty benchmark with unique IDs required")
    results=[]
    for row in entries:
        outcome=service.assess_batch(row["batch_id"],tenant_id=tenant_id,groups=groups)
        match=(outcome["status"]==row["expected_status"]
               and outcome["equipment"]==row["expected_equipment"]
               and outcome["exceedance_count"]==row["expected_exceedance_count"])
        results.append({"id":row["id"],"passed":match,"expected_status":row["expected_status"],
                        "actual_status":outcome["status"],"exceedance_count":outcome["exceedance_count"],
                        "evidence_count":len(outcome["evidence"])})
    return {"stage":"S03","n":len(results),"passed":sum(x["passed"] for x in results),
            "accuracy":sum(x["passed"] for x in results)/len(results),"results":results}
