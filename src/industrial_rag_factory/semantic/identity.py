"""Deterministic, time-aware entity resolution. Never auto-merge by embedding similarity."""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


def instant(value: str) -> datetime:
    """Require timezone-aware ISO-8601 timestamps (no implicit local time)."""
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.tzinfo is None or result.utcoffset() is None:
        raise ValueError("timestamp must carry a UTC offset")
    return result


def valid_interval(start: str | None, end: str | None, at_time: str | None) -> bool:
    if start and end and instant(start) >= instant(end):
        raise ValueError("valid_from must be before valid_to")
    if at_time is None:
        return True
    query = instant(at_time)
    return (start is None or query >= instant(start)) and (end is None or query < instant(end))


@dataclass(frozen=True)
class Resolution:
    status: str
    canonical_id: str | None
    candidates: tuple[str, ...]
    source_records: tuple[str, ...]

    def to_dict(self) -> dict:
        return {
            "status": self.status,
            "canonical_id": self.canonical_id,
            "candidates": list(self.candidates),
            "source_records": list(self.source_records),
        }


class EntityResolver:
    """Only approved aliases can resolve; ambiguous aliases never silently merge."""

    def __init__(self, mappings: list[dict]):
        self.mappings = mappings
        for entry in mappings:
            required = {"tenant_id", "system", "external_id", "canonical_id",
                        "access_groups", "source_record_id", "approved"}
            if not required.issubset(entry):
                raise ValueError("Mapping missing required fields")
            valid_interval(entry.get("valid_from"), entry.get("valid_to"), None)

    @classmethod
    def from_json(cls, path: str | Path) -> "EntityResolver":
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        if not isinstance(data, list):
            raise ValueError("Expected a list of identity mappings")
        return cls(data)

    def resolve(self, external_id: str, *, tenant_id: str, groups: tuple[str, ...],
                system: str | None = None, at_time: str | None = None) -> Resolution:
        if not tenant_id or not groups or not external_id.strip():
            raise ValueError("tenant, access groups, and identifier are required")
        if at_time is not None:
            instant(at_time)
        candidates = [
            entry for entry in self.mappings
            if entry["tenant_id"] == tenant_id
            and set(entry["access_groups"]).intersection(groups)
            and entry["approved"] is True
            and entry["external_id"].strip().casefold() == external_id.strip().casefold()
            and (system is None or entry["system"].casefold() == system.casefold())
            and valid_interval(entry.get("valid_from"), entry.get("valid_to"), at_time)
        ]
        unique = sorted({entry["canonical_id"] for entry in candidates})
        records = tuple(sorted({entry["source_record_id"] for entry in candidates}))
        if not unique:
            return Resolution("unresolved", None, (), ())
        # Without a time, a recycled alias with disjoint validity periods remains ambiguous.
        temporal_reuse = (
            at_time is None and len({
                (entry.get("valid_from"), entry.get("valid_to"))
                for entry in candidates
            }) > 1
        )
        if len(unique) != 1 or temporal_reuse:
            return Resolution("ambiguous", None, tuple(unique), records)
        return Resolution("resolved", unique[0], tuple(unique), records)
