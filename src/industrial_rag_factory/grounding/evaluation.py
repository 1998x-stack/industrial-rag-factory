"""Independent gold claim-status evaluation. No paid model requests."""
from __future__ import annotations

import json
from pathlib import Path

from .contracts import Claim
from .service import GroundingService


def evaluate_claims(service: GroundingService, path: str | Path) -> dict:
    rows=[json.loads(x) for x in Path(path).read_text(encoding="utf-8").splitlines()
          if x.strip()]
    if not rows or len({x["id"] for x in rows})!=len(rows):
        raise ValueError("Gold set must be nonempty and have unique IDs")
    output=[]
    cache={}
    for row in rows:
        batch=row["batch_id"]
        if batch not in cache:
            cache[batch]=service.capture_batch(batch)[1]
        claim=Claim.from_dict({
            "claim_id":row["id"],"subject":batch,"predicate":row["predicate"],
            "expected":row["expected"],"citation_ids":row.get("citation_ids",[]),
        })
        from .verifier import verify_claims
        result=verify_claims([claim],cache[batch])
        actual=result["claims"][0]["status"]
        output.append({"id":row["id"],"expected_status":row["expected_status"],
                       "actual_status":actual,"passed":actual==row["expected_status"]})
    total=len(output)
    return {"stage":"S05","total":total,"passed":sum(x["passed"] for x in output),
            "accuracy":sum(x["passed"] for x in output)/total,"cases":output}
