"""Explicit operational go/no-go gate. No simulated CI result grants OT approval."""
from __future__ import annotations


PRODUCTION_BLOCKERS = (
    "No enterprise IdP/OIDC, source-of-truth authorization or multi-tenant isolation attestation.",
    "No independently enforced read-only industrial IT/OT network segmentation.",
    "No independently immutable external audit sink and controlled key lifecycle.",
    "No real industrial dataset qualification, resilience SLO history or site-owner sign-off.",
    "No deployed external telemetry backend or disaster-recovery restoration proof.",
)


def readiness_report(status: dict, *, target: str = "local-demo") -> dict:
    if target not in ("local-demo", "production"):
        raise ValueError("Unknown release target")
    checks={
        "catalog_healthy":status.get("catalog_healthy") is True,
        "active_snapshot_verified":status.get("active_verified") is True,
        "snapshot_queryable":status.get("queryable") is True,
        "release_history_available":status.get("release_count",0)>=1,
    }
    local=all(checks.values())
    return {"stage":"S08","target":target,"checks":checks,
            "local_demo_ready":local,
            "production_ready":False,
            "decision":"demo_only" if local else "blocked",
            "production_blockers":list(PRODUCTION_BLOCKERS),
            "interpretation":"Local readiness is an offline smoke gate, not production authorization."}
