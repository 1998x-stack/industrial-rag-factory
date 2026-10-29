"""Stage 07 reproducible offline execution with honest uncertainty and metadata."""
from __future__ import annotations

import os
import platform
from pathlib import Path

from industrial_rag_factory.config import Settings
from industrial_rag_factory.multisource.evaluation import evaluate as evaluate_mes
from industrial_rag_factory.multisource.service import MultiSourceService
from industrial_rag_factory.prompts import PROMPT_VERSION

from .contracts import (canonical_hash, data_fingerprint, digest, load_cases,
                        validate_config)
from .cross_stage import negative_controls
from .retrieval import experiment


def run_factory(root: str | Path, *, config_path: str | Path | None = None,
                cases_path: str | Path | None = None,
                settings: Settings | None = None) -> dict:
    root=Path(root)
    config_path=Path(config_path or root/"config/stage07_experiments.json")
    cases_path=Path(cases_path or root/"datasets/stage07/retrieval_cases.jsonl")
    config=validate_config(__import__("json").loads(
        config_path.read_text(encoding="utf-8")))
    cases=load_cases(cases_path)
    fingerprints=data_fingerprint(config_path,cases_path)
    factors=root/"config/stage07_factors.json"
    fingerprints["factor_registry_sha256"]=digest(factors.read_bytes())
    for name in ("stage02/competency.jsonl","stage03/gold.jsonl",
                 "stage04/gold.jsonl","stage05/gold.jsonl"):
        fingerprints[name]=digest((root/"datasets"/name).read_bytes())
    retrieval=experiment(cases,config,settings=settings,
                         dataset_sha=fingerprints["cases_sha256"],
                         resamples=config["bootstrap_resamples"])
    controls=negative_controls(root,settings=settings)
    mes=MultiSourceService.from_defaults(root)
    try:
        s03=evaluate_mes(mes,root/"datasets/stage03/gold.jsonl",
                         tenant_id="demo",groups=("demo-readers",))
    finally:
        mes.close()
    summary={
        "retrieval_trials":len(retrieval["runs"]),
        "retrieval_test_cases":sum(x["split"]=="test" for x in cases),
        "retrieval_test_groups":len({
            x["group_id"] for x in cases if x["split"]=="test"
        }),
        "graph_enabled_accuracy":controls["graph"][0]["exact_match"],
        "graph_fail_closed_accuracy":controls["graph"][1]["exact_match"],
        "planner_enabled_tool_accuracy":controls["planner"][0]["tool_sequence_accuracy"],
        "planner_document_only_accuracy":controls["planner"][1]["tool_sequence_accuracy"],
        "claim_enabled_accuracy":controls["claims"][0]["status_accuracy"],
        "claim_fail_closed_accuracy":controls["claims"][1]["status_accuracy"],
        "mes_gold_accuracy":s03["accuracy"],
    }
    identity={
        "protocol_version":"stage07-v1",
        "input_fingerprints":fingerprints,
        "selected_dev_run":retrieval["champion_dev_selected"]["run_id"],
        "prompt_version":PROMPT_VERSION,
        "code_revision":os.getenv("GITHUB_SHA","unrecorded-local"),
    }
    return {
        "stage":"S07","kind":"synthetic_offline_ablation",
        "experiment_id":canonical_hash(identity)[:20],
        "identity":identity,"configuration":config,
        "python_version":platform.python_version(),
        "data_splits":{s:{"n":sum(r["split"]==s for r in cases),
                         "groups":len({r["group_id"] for r in cases if r["split"]==s})}
                       for s in ("train","dev","test")},
        "summary":summary,
        "retrieval":retrieval,"negative_controls":controls,
        "mes_gold":s03,
        "non_measured_factors":[x for x in __import__("json").loads(
            factors.read_text(encoding="utf-8"))["factors"]
            if x["status"] not in ("measured","measured_determinism",
                                   "negative_control_measured")],
        "limitations":[
            "All source records and expected answers are synthetic; no live industrial evaluation.",
            "Lexical hashing is NOT semantic embeddings; paid DeepSeek model/prompt ablations not run.",
            "Seeds perturb ingestion order; they are not independently retrained LLM models.",
            "Cluster bootstrap resamples held-out asset groups; intervals are descriptive with small n.",
            "All config TEST scores are exploratory comparisons; champion chosen solely from DEV.",
            "S02/S04/S05 disabled paths are safe negative controls, not causal effect estimates.",
            "S06 security remains enforced; it is tested independently, not deliberately bypassed.",
            "No production IAM, certified OT access, physical fault diagnosis or model faithfulness claim.",
        ]
    }
