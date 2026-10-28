"""Stable Stage 02 developer service. No live OT, arbitrary SPARQL, or mutating tools."""
from __future__ import annotations

from pathlib import Path
from .identity import EntityResolver
from .graph import KnowledgeGraph
from .validation import validate_knowledge_graph
from .competency import evaluate_competency_questions


class SemanticService:
    def __init__(self, graph: KnowledgeGraph, resolver: EntityResolver,
                 shapes_path: str | Path):
        self.graph = graph
        self.resolver = resolver
        self.shapes_path = Path(shapes_path)

    @classmethod
    def from_defaults(cls, root: str | Path = ".") -> "SemanticService":
        root = Path(root)
        return cls(
            KnowledgeGraph.from_json(root/"datasets/stage02/plant.json",
                                     root/"ontology/enterprise.ttl"),
            EntityResolver.from_json(root/"datasets/stage02/aliases.json"),
            root/"ontology/shapes.ttl",
        )

    def resolve(self, external_id: str, *, tenant_id: str,
                groups: tuple[str, ...], system: str | None = None,
                at_time: str | None = None) -> dict:
        resolved = self.resolver.resolve(external_id,tenant_id=tenant_id,
                                         groups=groups,system=system,
                                         at_time=at_time)
        # An approved alias does not by itself grant access to the referenced entity.
        if resolved.canonical_id and not self.graph.visible(
            resolved.canonical_id,tenant_id=tenant_id,groups=groups,at_time=at_time
        ):
            return {"status":"unresolved","canonical_id":None,
                    "candidates":[],"source_records":[]}
        return resolved.to_dict()

    def validate(self, *, tenant_id: str, groups: tuple[str, ...],
                 at_time: str | None = None) -> dict:
        return validate_knowledge_graph(self.graph,self.shapes_path,
                                        tenant_id=tenant_id,groups=groups,
                                        at_time=at_time).to_dict()

    def traverse(self, subject: str, steps: list[dict], *, tenant_id: str,
                 groups: tuple[str, ...], at_time: str | None = None) -> dict:
        matched = self.graph.traverse(subject,steps,tenant_id=tenant_id,
                                      groups=groups,at_time=at_time)
        return {"subject":subject,"results":matched,
                "status":"answered" if matched else "no_verified_path",
                "note":"Absence of a recorded graph path does not prove nonexistence."}

    def evaluate(self, path: str | Path, *, tenant_id: str,
                 groups: tuple[str, ...]) -> dict:
        return evaluate_competency_questions(self.graph,path,tenant_id=tenant_id,
                                             groups=groups)

    def export(self, output: str | Path, *, tenant_id: str, groups: tuple[str, ...],
               at_time: str | None = None) -> dict:
        g = self.graph.scoped(tenant_id=tenant_id,groups=groups,at_time=at_time)
        target = Path(output)
        target.parent.mkdir(parents=True,exist_ok=True)
        target.write_text(g.serialize(format="turtle"),encoding="utf-8")
        return {"output":str(target),"triples":len(g),"tenant_id":tenant_id,
                "note":"Only authorized, time-valid assertions were exported."}
