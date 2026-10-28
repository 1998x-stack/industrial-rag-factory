"""SHACL closed-world data-quality validation; does not establish source truth."""
from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path

from rdflib import Graph

from .graph import KnowledgeGraph


@dataclass(frozen=True)
class ValidationResult:
    conforms: bool
    report_text: str
    checked_triples: int

    def to_dict(self) -> dict:
        return {"conforms":self.conforms,
                "report_text":self.report_text,
                "checked_triples":self.checked_triples}


def validate_knowledge_graph(
    kg: KnowledgeGraph, shapes_path: str | Path, *,
    tenant_id: str, groups: tuple[str, ...], at_time: str | None = None
) -> ValidationResult:
    try:
        from pyshacl import validate
    except ImportError as exc:
        raise RuntimeError("Install industrial-rag-factory[ontology]") from exc
    shapes = Graph().parse(str(shapes_path),format="turtle")
    data = kg.scoped(tenant_id=tenant_id,groups=groups,at_time=at_time)
    conforms, _, report = validate(
        data, shacl_graph=shapes, ont_graph=kg.ontology,
        inference="rdfs", abort_on_first=False, allow_infos=False,
        allow_warnings=False, advanced=False,
    )
    return ValidationResult(bool(conforms),str(report),len(data))
