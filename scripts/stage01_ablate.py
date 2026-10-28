"""Run Stage 01 ablation and write a JSON report into outputs/."""
from __future__ import annotations
import json
from pathlib import Path
from industrial_rag_factory.ablation import run_stage01_ablation
from industrial_rag_factory.config import Settings

ROOT = Path(__file__).resolve().parents[1]
source_dir = ROOT/"datasets"/"stage01"
sources = {f"fixture://{name}": source_dir/name
           for name in ("pump_manual.md","maintenance.md","cut_spec.md")}
report = run_stage01_ablation(sources,source_dir/"gold.jsonl",settings=Settings.from_env())
output = ROOT/"outputs"/"stage01_ablation.json"
output.parent.mkdir(parents=True,exist_ok=True)
output.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
print(f"Saved {len(report['runs'])} runs to {output}")
