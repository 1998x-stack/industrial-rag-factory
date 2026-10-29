"""Demo authenticated, policy-scoped façade over the existing read-only RAG system.

Only secure-specific routes use these controls. In demo security mode the
Flask application must disable ALL legacy /v1/* routes to prevent bypass.
"""
from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from industrial_rag_factory.agent.planner import RulePlanner
from industrial_rag_factory.agent.service import AgentService
from industrial_rag_factory.agent.tools import RunContext, build_tool_registry
from industrial_rag_factory.config import Settings
from industrial_rag_factory.grounding.contracts import Claim
from industrial_rag_factory.grounding.service import GroundingService

from .audit import AuditTrail
from .auth import TokenVerifier
from .boundary import assert_read_only_tool
from .policy import AccessDenied, PolicyStore, Principal, check_result_sources


def _redact(value: object, fields: tuple[str, ...]) -> object:
    if isinstance(value,dict):
        return {key:("[REDACTED]" if key in fields else _redact(v,fields))
                for key,v in value.items()}
    if isinstance(value,list):
        return [_redact(v,fields) for v in value]
    return value


class GuardedRegistry:
    """Enforce current policy before AND after individual read-only tool calls."""

    def __init__(self, underlying, policy: PolicyStore, principal: Principal):
        self.underlying=underlying
        self.policy=policy
        self.principal=principal

    def names(self) -> tuple[str, ...]:
        return tuple(tool for tool in self.underlying.names()
                     if tool in self.principal.allowed_tools)

    def execute(self, tool: str, args: dict, context: RunContext) -> dict:
        current=self.policy.assert_fresh(self.principal)
        if (context.tenant_id!=current.tenant_id or
            context.groups!=current.groups or tool not in current.allowed_tools):
            raise AccessDenied("Unapproved tool context")
        assert_read_only_tool(tool)
        result=self.underlying.execute(tool,args,context)
        self.policy.assert_fresh(current)
        check_result_sources(result,current)
        return result

    def close(self):
        self.underlying.close()


class SecureGateway:
    def __init__(self, settings: Settings, *, root: str | Path = "."):
        if settings.environment!="development" or settings.security_mode!="demo":
            raise RuntimeError("S06 capabilities are developer demonstration only")
        self.settings=settings
        self.root=Path(root)
        self.policy=PolicyStore(settings.policy_path)
        self.verifier=TokenVerifier(settings.gateway_secret,self.policy)
        self.audit=AuditTrail(settings.audit_path,settings.gateway_secret)

    def _authenticate(self, header: str | None) -> Principal:
        return self.verifier.authenticate(header)

    def _operation(self, action: str, authorization: str | None, call):
        subject="unverified"
        try:
            principal=self._authenticate(authorization)
            subject=principal.subject
            if not self.audit.verify():
                raise RuntimeError("Audit log integrity failure")
            result=call(principal)
            self.policy.assert_fresh(principal)
            check_result_sources(result,principal)
            redacted=_redact(result,principal.redact_fields)
            request_id=self.audit.append(subject=subject,action=action,outcome="allowed")
            return {"request_id":request_id,"principal":principal.subject,
                    "policy_revision":principal.policy_revision,"result":redacted}
        except AccessDenied:
            self.audit.append(subject=subject,action=action,outcome="denied")
            raise
        except Exception:
            self.audit.append(subject=subject,action=action,outcome="error")
            raise

    def verify_batch(self, authorization: str | None, batch_id: str,
                     claims: list[Claim] | None = None) -> dict:
        def run(principal: Principal):
            mandatory={"mes.by_batch","batch.assess"}
            if not mandatory<=set(principal.allowed_tools):
                raise AccessDenied("Insufficient approved tools")
            scoped=replace(self.settings,tenant_id=principal.tenant_id,
                           groups=principal.groups)
            registry=GuardedRegistry(build_tool_registry(scoped,self.root),
                                     self.policy,principal)
            try:
                service=GroundingService(scoped,registry=registry)
                return service.verify_batch(batch_id,claims)
            finally:
                registry.close()
        return self._operation("grounding",authorization,run)

    def query(self, authorization: str | None, question: str) -> dict:
        def run(principal: Principal):
            scoped=replace(self.settings,tenant_id=principal.tenant_id,
                           groups=principal.groups,planner="rules",
                           generator="extractive")
            registry=GuardedRegistry(build_tool_registry(scoped,self.root),
                                     self.policy,principal)
            try:
                service=AgentService(scoped,registry=registry,planner=RulePlanner())
                result=service.query(question)
                if result["status"] != "completed":
                    # No partial tool result is returned after source-policy
                    # failure or an invalid dependency.
                    return {"status":"insufficient_evidence",
                            "reason":"Query incomplete or access denied.",
                            "trace":result["trace"]}
                return result
            finally:
                registry.close()
        return self._operation("agent",authorization,run)
