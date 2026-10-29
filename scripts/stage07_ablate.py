"""Offline Stage 07 full pipeline evidence/ablation receipt. No API requests."""
from __future__ import annotations

import json
from pathlib import Path

from industrial_rag_factory.experiments.report import render_html
from industrial_rag_factory.experiments.runner import run_factory

ROOT=Path(__file__).resolve().parents[1]
report=run_factory(ROOT)
output=ROOT/"outputs"
output.mkdir(parents=True,exist_ok=True)
(output/"stage07_ablation.json").write_text(
    json.dumps(report,ensure_ascii=False,indent=2,sort_keys=True),encoding="utf-8")
(output/"stage07_report.html").write_text(render_html(report),encoding="utf-8")
print(f"Stage 07: {report['summary']['retrieval_trials']} retrieval trials, "
      f"{report['summary']['retrieval_test_cases']} synthetic test questions, "
      f"experiment={report['experiment_id']}")
print("Saved outputs/stage07_ablation.json and outputs/stage07_report.html")
