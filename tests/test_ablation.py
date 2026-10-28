"""Factory ablation invariants: stable IDs, isolated indexing, no provider calls."""
from pathlib import Path
import pytest
from industrial_rag_factory.ablation import run_stage01_ablation
from industrial_rag_factory.config import Settings

ROOT = Path(__file__).parents[1]/"datasets"/"stage01"


def test_small_ablation_offline():
    sources = {"fixture://pump_manual.md":ROOT/"pump_manual.md",
               "fixture://maintenance.md":ROOT/"maintenance.md",
               "fixture://cut_spec.md":ROOT/"cut_spec.md"}
    options = dict(settings=Settings(),chunk_sizes=(30,60),overlaps=(0,),
                   modes=("sparse","dense","hybrid"),k=3)
    one = run_stage01_ablation(sources,ROOT/"gold.jsonl",**options)
    two = run_stage01_ablation(sources,ROOT/"gold.jsonl",**options)
    assert one == two
    assert len(one["runs"]) == 6
    assert all(0 <= r["metrics"]["recall_at_k"] <= 1 for r in one["runs"])
    assert len({r["run_id"] for r in one["runs"]}) == 6


def test_ablation_rejects_invalid_grid():
    with pytest.raises(ValueError):
        run_stage01_ablation({"fixture://x":ROOT/"pump_manual.md"},ROOT/"gold.jsonl",
                             chunk_sizes=(20,),overlaps=(20,))
