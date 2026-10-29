"""Opt-in actual multilingual encoder with full model SHA and fixed repo allowlist."""
from __future__ import annotations

import re
from pathlib import Path

MODEL="sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
SHA=re.compile(r"^[a-f0-9]{40}$")


def prepare_multilingual(*, revision: str = "main") -> dict:
    """Explicitly download a vetted public model into the HF cache.

    This action can download hundreds of MB and consume CPU/GPU resources.
    Never called from default CI or without --multilingual opt-in.
    """
    from huggingface_hub import HfApi, snapshot_download

    if revision!="main" and not SHA.fullmatch(revision):
        raise ValueError("Model revision must be main or full commit SHA")
    card=HfApi().model_info(MODEL,revision=revision)
    pinned=str(card.sha)
    if not SHA.fullmatch(pinned):
        raise ValueError("Model revision was not resolved")
    license_tag=(card.card_data or {}).get("license")
    if license_tag!="apache-2.0":
        raise ValueError("Model declared license changed")
    local=snapshot_download(repo_id=MODEL,repo_type="model",revision=pinned,
                            ignore_patterns=["*.h5","*.onnx","*.tflite",
                                             "openvino/*","*.msgpack","*.ot"])
    if not Path(local).is_dir():
        raise RuntimeError("Model snapshot not downloaded")
    return {"model_id":MODEL,"model_revision":pinned,"license_tag":license_tag,
            "local_snapshot":str(Path(local).resolve()),
            "limitations":"Model card/license are declarations, not an external approval."}
