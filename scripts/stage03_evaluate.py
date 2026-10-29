"""Run Stage 03 fixture benchmark; never calls an LLM or plant interface."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from industrial_rag_factory.multisource.evaluation import evaluate
from industrial_rag_factory.multisource.service import MultiSourceService

ROOT=Path(__file__).resolve().parents[1]
service=MultiSourceService.from_defaults(ROOT)
try:
    result=evaluate(service,ROOT/"datasets/stage03/gold.jsonl",
                    tenant_id="demo",groups=("demo-readers",))
finally:
    service.close()
hashes={}
for filename in ("mes.json","historian.json","specifications.json","gold.jsonl"):
    path=ROOT/"datasets/stage03"/filename
    hashes[filename]=hashlib.sha256(path.read_bytes()).hexdigest()
result["fixture_sha256"]=hashes
output=ROOT/"outputs"/"stage03_evaluation.json"
output.parent.mkdir(parents=True,exist_ok=True)
output.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding="utf-8")
print(f"Stage 03: {result['passed']}/{result['n']} passed; report={output}")
if result["passed"]!=result["n"]:
    raise SystemExit(1)
