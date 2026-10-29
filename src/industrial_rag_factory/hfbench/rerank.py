"""Pinned, allowlisted public pretrained encoder + English reranker.

No arbitrary model name, pickle code execution requests, or runtime model
download without explicit opt-in. Local weights are untrusted data until
provenanced; this does not certify software supply-chain integrity.
"""
from __future__ import annotations

import re
from pathlib import Path

ENCODER="sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
RERANKER="cross-encoder/ms-marco-MiniLM-L6-v2"
LICENSE="apache-2.0"
SHA=re.compile(r"^[a-f0-9]{40}$")


def prepare_models(*, revision_encoder: str = "main",
                   revision_reranker: str = "main") -> dict:
    from huggingface_hub import HfApi, snapshot_download
    api=HfApi()
    report={}
    for kind,repo,revision in (
        ("encoder",ENCODER,revision_encoder),("reranker",RERANKER,revision_reranker)
    ):
        if revision!="main" and not SHA.fullmatch(revision):
            raise ValueError("Model revision must be a full pinned SHA or main")
        info=api.model_info(repo,revision=revision)
        sha=str(info.sha)
        if not SHA.fullmatch(sha):
            raise ValueError("Model revision could not be pinned")
        if (info.card_data or {}).get("license")!=LICENSE:
            raise ValueError("Unexpected model license declaration")
        directory=snapshot_download(
            repo_id=repo,repo_type="model",revision=sha,
            ignore_patterns=["*.h5","*.onnx","*.tflite","*.ot",
                             "*.msgpack","openvino/*","*.bin",
                             "*.ckpt","*.pt"]
        )
        if not Path(directory).is_dir():
            raise RuntimeError("Model snapshot unavailable")
        report[kind]={"repo_id":repo,"revision":sha,"license_tag":LICENSE,
                      "local_path":str(Path(directory).resolve())}
    return report


def load_pretrained(paths: dict):
    """Load pinned local weights; no further network or remote code execution."""
    from sentence_transformers import CrossEncoder, SentenceTransformer
    for name in ("encoder","reranker"):
        if not Path(paths[name]["local_path"]).is_dir():
            raise ValueError("Prepared local snapshot absent")
    try:
        import torch
        torch.set_num_threads(2)
    except ImportError:
        pass
    encoder=SentenceTransformer(paths["encoder"]["local_path"],device="cpu",
                                trust_remote_code=False)
    reranker=CrossEncoder(paths["reranker"]["local_path"],device="cpu",
                          trust_remote_code=False,max_length=256)
    return encoder,reranker
