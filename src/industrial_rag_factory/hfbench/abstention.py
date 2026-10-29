"""Development-only score-threshold selection on DEV, frozen evaluation on TEST.

Never use impossible gold labels at inference. BM25 values are corpus- and
backend-dependent, not calibrated probabilities.
"""
from __future__ import annotations

import math


def decide(score: float | None, threshold: float) -> bool:
    """Return answerable prediction. A missing hit cannot be accepted."""
    return score is not None and math.isfinite(score) and score>=threshold


def metrics(rows: list[dict], threshold: float) -> dict:
    if not rows:
        raise ValueError("Empty benchmark split")
    tp=tn=fp=fn=0
    for row in rows:
        accepted=decide(row["top_score"],threshold)
        if accepted and not row["impossible"]:
            tp+=1
        elif accepted:
            fp+=1
        elif row["impossible"]:
            tn+=1
        else:
            fn+=1
    positive=tp+fn
    negative=tn+fp
    if positive==0 or negative==0:
        raise ValueError("Need both answerable and impossible examples")
    return {"n":len(rows),"tp":tp,"fp":fp,"tn":tn,"fn":fn,
            "answerable_recall":tp/positive,
            "impossible_specificity":tn/negative,
            "false_answer_rate":fp/negative,
            "balanced_accuracy":0.5*(tp/positive+tn/negative),
            "coverage":(tp+fp)/len(rows)}


def tune(dev: list[dict]) -> dict:
    """Choose score cutoff by balanced accuracy on DEV only.

    Threshold is not a robust confidence calibration or production safety gate.
    """
    finite=sorted({float(x["top_score"]) for x in dev
                   if x["top_score"] is not None and
                   math.isfinite(float(x["top_score"]))})
    # Include always-abstain threshold, and every score value.
    cutoffs=finite+[math.inf]
    if not cutoffs:
        cutoffs=[math.inf]
    scored=[(metrics(dev,x),x) for x in cutoffs]
    best=sorted(scored,key=lambda item:(
        -item[0]["balanced_accuracy"],
        item[0]["false_answer_rate"],
        -item[1] if math.isfinite(item[1]) else float("-inf")))[0]
    return {"threshold":best[1],"dev_metrics":best[0],
            "selection":"dev_balanced_accuracy_then_lower_false_answer_rate",
            "candidate_cutoffs":len(cutoffs)}
