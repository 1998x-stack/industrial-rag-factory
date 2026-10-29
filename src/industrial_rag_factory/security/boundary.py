"""Explicit negative guarantees for Stage 06 OT and LLM trust boundaries."""
from __future__ import annotations

from urllib.parse import urlparse

from industrial_rag_factory.agent.contracts import TOOLS

# A source URL is provenance only, NEVER an automatically fetched endpoint.
FORBIDDEN_SCHEMES = {
    "opc.tcp","modbus","modbus.tcp","plc","s7","ethernetip","mqtt","amqp",
    "telnet","ftp","tftp","ssh"
}
SAFE_READ_TOOLS = frozenset(TOOLS)


def reject_operational_target(target: str) -> None:
    """Deny operational protocols; this is NOT a network-layer firewall."""
    if not isinstance(target,str) or not target.strip() or len(target)>2048:
        raise ValueError("Invalid endpoint")
    parsed=urlparse(target)
    if parsed.scheme.lower() in FORBIDDEN_SCHEMES:
        raise PermissionError("OT protocol endpoints are prohibited")
    # No remote connector exists in S06; remote URLs are never allowed as tools.
    if parsed.scheme.lower() not in ("fixture","file"):
        raise PermissionError("Unapproved network/execution endpoint")


def assert_read_only_tool(tool: str) -> None:
    if tool not in SAFE_READ_TOOLS:
        raise PermissionError("Tool outside fixed read-only runtime")
