"""Stage 05 deterministic evidence-claim benchmark with immutable fixture hashes."""
from __future__ import annotations

import hashlib
import json
import tempfile
from dataclasses import replace
from pathlib import Path

from industrial_rag_factory.config import Settings
from industrial_rag_factory.grounding.evaluation import evaluate_claims
from industrial_rag_factory.grounding.service import GroundingService

ROOT=Path(__file__).resolve().parents[1]
gold=ROOT/"datasets/stage05/gold.jsonl"
with tempfile.TemporaryDirectory(prefix="irf-stage05-") as tmp:
    settings=replace(Settings(),db_path=str(Path(tmp)/"db.sqlite3"))
    service=GroundingService(settings,root=ROOT)
    try:
        result=evaluate_claims(service,gold)
    finally:
        service.close()
result["gold_sha256"]=hashlib.sha256(gold.read_bytes()).hexdigest()
output=ROOT/"outputs"/"stage05_evaluation.json"
output.parent.mkdir(parents=True,exist_ok=True)
output.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding="utf-8")
print(f"Stage 05: {result['passed']}/{result['total']} claim cases passed; report={output}")
if result["passed"]!=result["total"]:
    raise SystemExit(1)
