"""Approved synthetic process specifications with effective-date and unit scopes."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from industrial_rag_factory.semantic.identity import valid_interval
from .contracts import Interval
from .units import normalize


@dataclass(frozen=True)
class Specification:
    record_id: str
    specification_id: str
    equipment_id: str
    mode: str
    kind: str
    upper_limit: str
    unit: str
    valid_from: str
    valid_to: str | None
    source_uri: str


class SpecificationRegistry:
    def __init__(self, rows: list[dict]):
        self.rows = rows
        for row in rows:
            if not row.get("approved",False):
                continue
            valid_interval(row.get("valid_from"),row.get("valid_to"),None)
            normalize(row["upper_limit"],row["kind"],row["unit"])
            if not row.get("source_uri") or not row.get("source_record_id"):
                raise ValueError("Specification provenance required")

    @classmethod
    def from_json(cls,path: str | Path) -> "SpecificationRegistry":
        return cls(json.loads(Path(path).read_text(encoding="utf-8"))["specifications"])

    def applicable(self, *, specification_id: str, equipment_id: str, mode: str,
                   interval: Interval, kind: str, tenant_id: str,
                   groups: tuple[str, ...]) -> Specification | None:
        if not tenant_id or not groups:
            raise ValueError("Tenant and access groups required")
        found=[]
        for row in self.rows:
            if not row.get("approved",False) or row["tenant_id"] != tenant_id:
                continue
            if not set(groups).intersection(row["access_groups"]):
                continue
            if (row["specification_id"],row["equipment_id"],row["mode"],row["kind"]) != (
                specification_id,equipment_id,mode,kind
            ):
                continue
            # Require one specification valid for the entire process interval.
            if not valid_interval(row.get("valid_from"),row.get("valid_to"),interval.start):
                continue
            if row.get("valid_to") and not interval.end <= row["valid_to"]:
                # ISO strings may have different offsets: compare datetimes instead.
                from industrial_rag_factory.semantic.identity import instant
                if instant(interval.end)>instant(row["valid_to"]):
                    continue
            found.append(Specification(row["source_record_id"],specification_id,
                equipment_id,mode,kind,str(row["upper_limit"]),row["unit"],
                row["valid_from"],row.get("valid_to"),row["source_uri"]))
        if len(found)>1:
            raise ValueError("Overlapping approved specification definitions")
        return found[0] if found else None
