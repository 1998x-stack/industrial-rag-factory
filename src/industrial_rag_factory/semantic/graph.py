"""Versioned RDF graph with tenant-scoped, time-valid, evidence-linked assertions."""
from __future__ import annotations

import json
from pathlib import Path

from rdflib import Graph, Literal, Namespace, RDF, RDFS, URIRef, XSD
from .identity import valid_interval, instant

ONTO = Namespace("https://example.org/industrial/ontology/")
DATA = Namespace("https://example.org/industrial/id/")
IOF = Namespace("https://spec.industrialontologies.org/ontology/construct/")
PROV = Namespace("http://www.w3.org/ns/prov#")

ALLOWED_KINDS = {
    "EquipmentAsset", "EquipmentRole", "MeasurementPoint", "ProductionBatch",
    "WorkOrder", "Execution", "MaintenanceEvent", "Specification", "PlantArea",
    "MaterialComponent",
}
# Explicit enterprise relation allowlist; NO arbitrary user-defined SPARQL executed here.
ALLOWED_PREDICATES = {
    "hasRole", "hasMeasurementPoint", "measuresAsset", "forBatch", "implementsWorkOrder",
    "usesEquipment", "governedBySpecification", "hasMaintenanceEvent", "locatedIn",
    "hasPart", "requiresSpecification",
}


def node(identifier: str) -> URIRef:
    if not identifier or not all(c.isalnum() or c in "-_" for c in identifier):
        raise ValueError("Invalid canonical ID")
    return DATA[identifier]


class KnowledgeGraph:
    def __init__(self, payload: dict, ontology_path: str | Path):
        self.payload = payload
        self.ontology = Graph()
        self.ontology.parse(str(ontology_path), format="turtle")
        self.entities = {item["id"]: item for item in payload["entities"]}
        self.relations = payload["relations"]
        if len(self.entities) != len(payload["entities"]):
            raise ValueError("Duplicate entity ID")
        if len({r["id"] for r in self.relations}) != len(self.relations):
            raise ValueError("Duplicate relation ID")
        for item in self.entities.values():
            if item["kind"] not in ALLOWED_KINDS:
                raise ValueError(f"Unsupported kind: {item['kind']}")
            if not item.get("tenant_id") or not item.get("access_groups"):
                raise ValueError("Tenant and access groups required")
            node(item["id"])
            valid_interval(item.get("valid_from"),item.get("valid_to"),None)
        for r in self.relations:
            if r["predicate"] not in ALLOWED_PREDICATES:
                raise ValueError(f"Unknown predicate: {r['predicate']}")
            if r["from"] not in self.entities or r["to"] not in self.entities:
                raise ValueError("Dangling relation endpoint")
            if self.entities[r["from"]]["tenant_id"] != self.entities[r["to"]]["tenant_id"]:
                raise ValueError("Cross-tenant relation prohibited")
            if not r.get("source_uri") or not r.get("source_record_id"):
                raise ValueError("Relation provenance required")
            valid_interval(r.get("valid_from"), r.get("valid_to"), None)

    @classmethod
    def from_json(cls, path: str | Path, ontology_path: str | Path) -> "KnowledgeGraph":
        return cls(json.loads(Path(path).read_text(encoding="utf-8")), ontology_path)

    def visible(self, canonical_id: str, *, tenant_id: str, groups: tuple[str, ...],
                at_time: str | None = None) -> bool:
        item = self.entities.get(canonical_id)
        return bool(item and item["tenant_id"] == tenant_id
                    and set(groups).intersection(item["access_groups"])
                    and valid_interval(item.get("valid_from"),item.get("valid_to"),at_time))

    def scoped(self, *, tenant_id: str, groups: tuple[str, ...],
               at_time: str | None = None) -> Graph:
        """Build a separate authorized RDF dataset before any graph query or export."""
        if not tenant_id or not groups:
            raise ValueError("Tenant and groups are required")
        if at_time is not None:
            instant(at_time)
        g = Graph()
        g.bind("ex", ONTO)
        g.bind("id", DATA)
        g.bind("iof", IOF)
        g.bind("prov", PROV)
        visible = {id_: item for id_, item in self.entities.items()
                   if self.visible(id_,tenant_id=tenant_id,groups=groups,at_time=at_time)}
        for item in visible.values():
            s = node(item["id"])
            kind = IOF.EquipmentRole if item["kind"] == "EquipmentRole" else ONTO[item["kind"]]
            g.add((s,RDF.type,kind))
            g.add((s,RDFS.label,Literal(item["label"])))
            g.add((s,ONTO.tenantId,Literal(tenant_id)))
            g.add((s,ONTO.externalId,Literal(item["id"])))
            g.add((s,ONTO.sourceUri,Literal(item["source_uri"])))
            if item.get("valid_from"):
                g.add((s,ONTO.validFrom,Literal(item["valid_from"],datatype=XSD.dateTime)))
            if item.get("valid_to"):
                g.add((s,ONTO.validTo,Literal(item["valid_to"],datatype=XSD.dateTime)))
            for group in sorted(set(item["access_groups"]).intersection(groups)):
                g.add((s,ONTO.accessGroup,Literal(group)))
            if item["kind"] == "EquipmentAsset":
                g.add((s,ONTO.assetId,Literal(item["id"])))
            if item["kind"] == "MeasurementPoint":
                if "tag" in item:
                    g.add((s,ONTO.sensorTag,Literal(item["tag"])))
                if "quantity_kind" in item:
                    g.add((s,ONTO.quantityKind,Literal(item["quantity_kind"])))
        for rel in self.relations:
            if rel["from"] not in visible or rel["to"] not in visible:
                continue
            if not valid_interval(rel.get("valid_from"),rel.get("valid_to"),at_time):
                continue
            s, p, o = node(rel["from"]), (IOF.hasRole if rel["predicate"] == "hasRole" else ONTO[rel["predicate"]]), node(rel["to"])
            g.add((s,p,o))
            # Reified statement retains source provenance and effective interval.
            stmt = node("assertion-" + rel["id"])
            g.add((stmt,RDF.type,RDF.Statement))
            g.add((stmt,RDF.subject,s))
            g.add((stmt,RDF.predicate,p))
            g.add((stmt,RDF.object,o))
            g.add((stmt,PROV.wasDerivedFrom,URIRef(rel["source_uri"])))
            g.add((stmt,ONTO.sourceRecordId,Literal(rel["source_record_id"])))
            if rel.get("valid_from"):
                g.add((stmt,ONTO.validFrom,Literal(rel["valid_from"],datatype=XSD.dateTime)))
            if rel.get("valid_to"):
                g.add((stmt,ONTO.validTo,Literal(rel["valid_to"],datatype=XSD.dateTime)))
        return g

    def neighbors(self, canonical_id: str, predicate: str, direction: str, *,
                  tenant_id: str, groups: tuple[str, ...],
                  at_time: str | None) -> list[str]:
        if predicate not in ALLOWED_PREDICATES or direction not in ("in","out"):
            raise ValueError("Invalid graph traversal operator")
        if not self.visible(canonical_id,tenant_id=tenant_id,groups=groups,at_time=at_time):
            return []
        found = set()
        for r in self.relations:
            endpoint = r["from"] if direction == "out" else r["to"]
            target = r["to"] if direction == "out" else r["from"]
            if endpoint == canonical_id and r["predicate"] == predicate:
                if self.visible(target,tenant_id=tenant_id,groups=groups,at_time=at_time) and valid_interval(
                    r.get("valid_from"),r.get("valid_to"),at_time
                ):
                    found.add(target)
        return sorted(found)

    def traverse(self, start: str, steps: list[dict], *, tenant_id: str,
                 groups: tuple[str, ...], at_time: str | None = None) -> list[str]:
        if len(steps) > 5:
            raise ValueError("Maximum five graph hops allowed")
        if at_time is not None:
            instant(at_time)
        current = {start} if self.visible(start,tenant_id=tenant_id,groups=groups,at_time=at_time) else set()
        for step in steps:
            next_ids: set[str] = set()
            for identifier in current:
                next_ids.update(self.neighbors(identifier,step["predicate"],step["direction"],
                                               tenant_id=tenant_id,groups=groups,at_time=at_time))
            current = next_ids
        return sorted(current)

    def relationship_sources(self, subject: str, predicate: str, object_id: str, *,
                             tenant_id: str, groups: tuple[str, ...],
                             at_time: str | None = None) -> list[str]:
        """Return only provenance for authorized, time-valid matching relations."""
        if not (self.visible(subject,tenant_id=tenant_id,groups=groups,at_time=at_time)
                and self.visible(object_id,tenant_id=tenant_id,groups=groups,at_time=at_time)):
            return []
        return sorted({
            r["source_record_id"] for r in self.relations
            if r["from"] == subject and r["to"] == object_id
            and r["predicate"] == predicate
            and valid_interval(r.get("valid_from"),r.get("valid_to"),at_time)
        })
