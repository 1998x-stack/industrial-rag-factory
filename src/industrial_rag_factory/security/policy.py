"""Deny-by-default, reload-on-every-call demo principal and resource policy."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from industrial_rag_factory.agent.contracts import TOOLS

IDENT = re.compile(r"^[A-Za-z0-9_-]{1,80}$")


class AccessDenied(PermissionError):
    """No secret or policy detail should be returned to the caller."""


@dataclass(frozen=True)
class Principal:
    subject: str
    tenant_id: str
    groups: tuple[str, ...]
    allowed_tools: tuple[str, ...]
    source_prefixes: tuple[str, ...]
    generation: int
    policy_revision: int


class PolicyStore:
    """Reads policy file afresh: changes to active/generation are immediately observable.

    This is a development fixture. An enterprise policy service must provide
    authenticated updates, freshness guarantees and reliable revocation.
    """

    def __init__(self, path: str | Path):
        self.path = Path(path)

    def _read(self) -> dict:
        data = json.loads(self.path.read_text(encoding="utf-8"))
        if (not isinstance(data, dict) or
            set(data) != {"version", "revision", "principals"} or
            data["version"] != "stage06-v1" or
            type(data["revision"]) is not int or data["revision"] < 1 or
            not isinstance(data["principals"], dict)):
            raise AccessDenied("Invalid security policy")
        return data

    def get(self, subject: str) -> Principal:
        data=self._read()
        row=data["principals"].get(subject)
        if (not isinstance(row,dict) or row.get("active") is not True or
            not isinstance(subject,str) or not IDENT.fullmatch(subject) or
            not isinstance(row.get("tenant_id"),str) or
            not IDENT.fullmatch(row["tenant_id"]) or
            type(row.get("generation")) is not int or row["generation"] < 1):
            raise AccessDenied("Inactive or invalid principal")
        groups=row.get("groups")
        tools=row.get("allowed_tools")
        prefixes=row.get("source_prefixes")
        if (not isinstance(groups,list) or not groups or
            not all(isinstance(x,str) and IDENT.fullmatch(x) for x in groups) or
            not isinstance(tools,list) or not tools or
            not all(isinstance(x,str) and x in TOOLS for x in tools) or
            not isinstance(prefixes,list) or not prefixes or
            not all(isinstance(x,str) and (x.startswith("fixture://") or x.startswith("file://"))
                    and len(x)<200 for x in prefixes)):
            raise AccessDenied("Invalid principal authorization")
        return Principal(subject,row["tenant_id"],tuple(groups),tuple(tools),
                         tuple(prefixes),row["generation"],data["revision"])

    def assert_fresh(self, principal: Principal) -> Principal:
        current=self.get(principal.subject)
        if current != principal:
            raise AccessDenied("Principal policy changed or revoked")
        return current

    @staticmethod
    def check_source(principal: Principal, source_uri: str) -> None:
        if not isinstance(source_uri,str) or not any(
            source_uri.startswith(prefix) for prefix in principal.source_prefixes
        ):
            raise AccessDenied("Source outside approved policy scope")


def check_result_sources(result: object, principal: Principal) -> None:
    """Traverse every nested source_uri and fail closed rather than post-filtering.

    Does not imply that every field in arbitrary connectors has provenance.
    The registered S01-S05 adapters are responsible for source tagging.
    """
    if isinstance(result,dict):
        if "source_uri" in result:
            PolicyStore.check_source(principal,result["source_uri"])
        for item in result.values():
            check_result_sources(item,principal)
    elif isinstance(result,(list,tuple)):
        for item in result:
            check_result_sources(item,principal)
