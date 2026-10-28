"""Stable Stage 01 data contracts."""
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class Document:
    document_id: str
    source_uri: str
    revision: str
    title: str
    text: str
    tenant_id: str
    access_groups: tuple[str, ...]
    sha256: str
    parser: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Chunk:
    chunk_id: str
    document_id: str
    ordinal: int
    section_path: str
    text: str
    token_estimate: int


@dataclass(frozen=True)
class Hit:
    chunk: Chunk
    source_uri: str
    revision: str
    title: str
    score: float
    channels: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return dict(chunk_id=self.chunk.chunk_id, document_id=self.chunk.document_id,
                    source_uri=self.source_uri, revision=self.revision, title=self.title,
                    section_path=self.chunk.section_path, text=self.chunk.text,
                    score=round(self.score, 6), channels=list(self.channels))


@dataclass(frozen=True)
class Answer:
    question: str
    answer: str
    status: str
    evidence: tuple[Hit, ...]
    warnings: tuple[str, ...] = ()
    model: str = "extractive"

    def to_dict(self) -> dict[str, Any]:
        return dict(question=self.question, answer=self.answer, status=self.status,
                    model=self.model, warnings=list(self.warnings),
                    evidence=[hit.to_dict() for hit in self.evidence])
