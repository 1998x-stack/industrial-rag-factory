"""Typed evidence and immutable time-interval contracts for cross-source retrieval."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime

from industrial_rag_factory.semantic.identity import instant


@dataclass(frozen=True)
class Interval:
    start: str
    end: str

    def __post_init__(self) -> None:
        if instant(self.start) >= instant(self.end):
            raise ValueError("Interval must have a positive length")

    def contains(self, timestamp: str) -> bool:
        return instant(self.start) <= instant(timestamp) < instant(self.end)

    def overlaps(self, other: "Interval") -> bool:
        return instant(self.start) < instant(other.end) and instant(other.start) < instant(self.end)


@dataclass(frozen=True)
class Evidence:
    id: str
    kind: str
    source_uri: str
    source_record_id: str
    entity_id: str
    time: str | None
    value: str
    note: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class DiagnosticResult:
    batch_id: str
    status: str
    equipment: tuple[str, ...]
    exceedance_count: int
    valid_sample_count: int
    rejected_sample_count: int
    evidence: tuple[Evidence, ...]
    limitations: tuple[str, ...]

    def to_dict(self) -> dict:
        return {"batch_id":self.batch_id, "status":self.status,
                "equipment":list(self.equipment),
                "exceedance_count":self.exceedance_count,
                "valid_sample_count":self.valid_sample_count,
                "rejected_sample_count":self.rejected_sample_count,
                "evidence":[e.to_dict() for e in self.evidence],
                "limitations":list(self.limitations)}


def iso(value: str) -> datetime:
    return instant(value)
