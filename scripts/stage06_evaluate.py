"""Offline S06 security evaluation, with ephemeral per-run policy and audit."""
from __future__ import annotations

import hashlib
import json
import tempfile
from dataclasses import replace
from pathlib import Path

from industrial_rag_factory.config import Settings
from industrial_rag_factory.security.auth import TokenVerifier, mint_demo_token
from industrial_rag_factory.security.gateway import SecureGateway
from industrial_rag_factory.security.policy import AccessDenied, PolicyStore

ROOT=Path(__file__).resolve().parents[1]
source=ROOT/"config/security_demo_policy.json"
checks=[]


def measure(name, check):
    try:
        passed=bool(check())
    except Exception:
        passed=False
    checks.append({"id":name,"passed":passed})


with tempfile.TemporaryDirectory(prefix="irf-s06-") as tmp:
    policy=Path(tmp)/"policy.json"
    policy.write_bytes(source.read_bytes())
    secret="stage06-ci-only-ephemeral-demo-key-0000000000"
    settings=replace(Settings(),security_mode="demo",gateway_secret=secret,
                     policy_path=str(policy),audit_path=str(Path(tmp)/"audit.jsonl"),
                     db_path=str(Path(tmp)/"index.sqlite3"))
    auth=TokenVerifier(secret,PolicyStore(policy))
    analyst=mint_demo_token(auth,"analyst")
    limited=mint_demo_token(auth,"limited")
    gateway=SecureGateway(settings,root=ROOT)

    measure("authorized_claim",lambda:gateway.verify_batch(
        "Bearer "+analyst,"B-104")["result"]["verification"]["status"]=="supported")
    measure("missing_source",lambda:gateway.verify_batch(
        "Bearer "+analyst,"B-999")["result"]["verification"]["abstain"])
    measure("authorized_agent",lambda:gateway.query(
        "Bearer "+analyst,"B-105 的振动情况")["result"]["status"]=="completed")

    def denies(token):
        try:
            gateway.verify_batch(token,"B-104")
        except AccessDenied:
            return True
        return False

    measure("missing_token",lambda:denies(None))
    measure("garbled_token",lambda:denies("Bearer invalid"))
    measure("tool_denial",lambda:denies("Bearer "+limited))
    measure("audit_integrity",lambda:gateway.audit.verify())
    def revocation():
        before=json.loads(policy.read_text(encoding="utf-8"))
        before["revision"]+=1
        before["principals"]["analyst"]["active"]=False
        policy.write_text(json.dumps(before),encoding="utf-8")
        return denies("Bearer "+analyst)
    measure("principal_revocation",revocation)

report={"stage":"S06","total":len(checks),
        "passed":sum(x["passed"] for x in checks),
        "tests":checks,"policy_sha256":hashlib.sha256(source.read_bytes()).hexdigest(),
        "note":"Local demo security only; no production IAM or OT network validation."}
output=ROOT/"outputs"/"stage06_security_evaluation.json"
output.parent.mkdir(parents=True,exist_ok=True)
output.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
print(f"Stage 06: {report['passed']}/{report['total']} security cases passed")
if report["passed"]!=report["total"]:
    raise SystemExit(1)
