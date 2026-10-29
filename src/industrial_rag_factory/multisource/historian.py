"""In-memory historian fixture adapter with explicit sample quality and provenance."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from industrial_rag_factory.semantic.identity import instant
from .contracts import Interval


@dataclass(frozen=True)
class Sample:
    sample_id: str
    point_id: str
    timestamp: str
    value: str
    unit: str
    kind: str
    quality: str
    tenant_id: str
    access_groups: tuple[str, ...]
    source_uri: str


class HistorianReadModel:
    def __init__(self, payload: dict):
        samples=[]
        seen=set()
        for item in payload["samples"]:
            instant(item["timestamp"])
            if item["sample_id"] in seen:
                raise ValueError("Duplicate sample ID")
            seen.add(item["sample_id"])
            if not item["source_uri"] or not item["tenant_id"] or not item["access_groups"]:
                raise ValueError("Sample missing provenance or access scope")
            samples.append(Sample(
                item["sample_id"],item["point_id"],item["timestamp"],
                str(item["value"]),item["unit"],item["kind"],item["quality"],
                item["tenant_id"],tuple(item["access_groups"]),item["source_uri"]))
        self.samples = tuple(samples)

    @classmethod
    def from_json(cls,path: str | Path) -> "HistorianReadModel":
        return cls(json.loads(Path(path).read_text(encoding="utf-8")))

    def read(self, point_ids: set[str], interval: Interval, *, tenant_id: str,
             groups: tuple[str, ...], max_samples: int = 1000) -> list[Sample]:
        if not tenant_id or not groups:
            raise ValueError("Tenant and groups required")
        if not 1 <= max_samples <= 1000:
            raise ValueError("Invalid historian sample budget")
        output = [
            item for item in self.samples if item.point_id in point_ids
            and item.tenant_id == tenant_id
            and set(item.access_groups).intersection(groups)
            and interval.contains(item.timestamp)
        ]
        if len(output)>max_samples:
            raise ValueError("Historian row budget exceeded")
        return sorted(output,key=lambda s:(instant(s.timestamp),s.sample_id))
