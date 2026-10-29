"""Stage 03 deterministic mixed-source query without LLM-generated SQL or control actions."""
from __future__ import annotations

from datetime import timedelta
from pathlib import Path
from typing import Any

from industrial_rag_factory.semantic.graph import KnowledgeGraph
from industrial_rag_factory.semantic.identity import EntityResolver, instant
from .contracts import DiagnosticResult, Evidence, Interval
from .historian import HistorianReadModel
from .specs import SpecificationRegistry
from .sql import MESReadModel
from .units import compare_upper


class MultiSourceService:
    """Read-only batch-to-asset-to-time-series joins with evidence provenance.

    Report describes *observed synthetic sample threshold exceedances*, not actual
    equipment safety, product quality or fault causes.
    """

    def __init__(self, graph: KnowledgeGraph, mes: MESReadModel,
                 historian: HistorianReadModel, specs: SpecificationRegistry,
                 resolver: EntityResolver | None = None, doc_retriever: Any = None):
        self.graph=graph
        self.mes=mes
        self.historian=historian
        self.specs=specs
        self.doc_retriever=doc_retriever
        self.resolver=resolver

    @classmethod
    def from_defaults(cls,root: str | Path = ".",doc_retriever: Any = None):
        root=Path(root)
        return cls(
            KnowledgeGraph.from_json(root/"datasets/stage02/plant.json",
                                     root/"ontology/enterprise.ttl"),
            MESReadModel.from_json(root/"datasets/stage03/mes.json"),
            HistorianReadModel.from_json(root/"datasets/stage03/historian.json"),
            SpecificationRegistry.from_json(root/"datasets/stage03/specifications.json"),
            resolver=EntityResolver.from_json(root/"datasets/stage02/aliases.json"),
            doc_retriever=doc_retriever,
        )

    def _graph_link(self, source: str, predicate: str, target: str,
                    timestamp: str, tenant_id: str, groups: tuple[str,...]) -> bool:
        return target in self.graph.neighbors(source,predicate,"out",
            tenant_id=tenant_id,groups=groups,at_time=timestamp)

    def _evidence_link(self, source: str, predicate: str, target: str,
                       timestamp: str, tenant_id: str, groups: tuple[str,...]) -> list[Evidence]:
        ids=self.graph.relationship_sources(source,predicate,target,
            tenant_id=tenant_id,groups=groups,at_time=timestamp)
        provenance={r["source_record_id"]:r["source_uri"] for r in self.graph.relations
                    if r["from"]==source and r["to"]==target and r["predicate"]==predicate}
        return [Evidence("graph:"+id_,"graph_relation",provenance[id_],
                         id_,source,timestamp,f"{source} {predicate} {target}")
                for id_ in ids]

    @staticmethod
    def _sampling_grid(interval: Interval, spacing_seconds: int) -> list[str]:
        if not 1 <= spacing_seconds <= 86400:
            raise ValueError("Invalid sample cadence")
        t=instant(interval.start)
        stop=instant(interval.end)
        output=[]
        while t<stop:
            output.append(t.isoformat())
            if len(output)>1000:
                raise ValueError("Sampling grid too large")
            t+=timedelta(seconds=spacing_seconds)
        return output

    def assess_batch(self, batch_id: str, *, tenant_id: str, groups: tuple[str,...],
                     kind: str = "vibration_velocity", spacing_seconds: int = 600,
                     doc_query: str | None = None) -> dict:
        if not tenant_id or not groups or not batch_id or not kind:
            raise ValueError("Batch, quantity kind and authorized scope required")
        records=self.mes.by_batch(batch_id,tenant_id=tenant_id,groups=groups)
        if not records:
            return DiagnosticResult(batch_id,"insufficient_evidence",(),0,0,0,(),
                ("No authorized MES execution record; absence is not proof of nonexistence.",)).to_dict()

        evidence:list[Evidence]=[]
        limitations:list[str]=[]
        valid_count=0
        exceed_count=0
        rejected_count=0
        all_equipment=set()
        unexpected=False
        for record in records:
            start=record.interval.start
            if self.resolver is not None:
                identity=self.resolver.resolve(record.equipment_external_id,
                    tenant_id=tenant_id,groups=groups,system=record.equipment_source_system,
                    at_time=start)
                finish=self.resolver.resolve(record.equipment_external_id,
                    tenant_id=tenant_id,groups=groups,system=record.equipment_source_system,
                    at_time=(instant(record.interval.end)-timedelta(microseconds=1)).isoformat())
                if (identity.status!="resolved" or finish.status!="resolved"
                    or identity.canonical_id!=record.equipment_id
                    or finish.canonical_id!=record.equipment_id):
                    unexpected=True
                    limitations.append(f"{record.record_id}: source asset ID unresolved, changed, or conflicts with canonical ID.")
                    continue
                for rec in identity.source_records:
                    evidence.append(Evidence("mapping:"+rec,"identity_mapping",
                        "fixture://identity/"+rec,rec,record.equipment_id,start,
                        f"{record.equipment_source_system}:{record.equipment_external_id} -> {record.equipment_id}"))
            # Check graph at start and just before end, not just the query time.
            end_check=(instant(record.interval.end)-timedelta(microseconds=1)).isoformat()
            relations=(
                (record.execution_id,"forBatch",record.batch_id),
                (record.execution_id,"usesEquipment",record.equipment_id),
                (record.execution_id,"implementsWorkOrder",record.work_order_id),
                (record.execution_id,"governedBySpecification",record.specification_id),
            )
            if not all(
                self._graph_link(a,p,b,t,tenant_id,groups)
                for a,p,b in relations for t in (start,end_check)
            ):
                limitations.append(f"{record.record_id}: MES/graph relation mismatch or invalid time.")
                unexpected=True
                continue
            all_equipment.add(record.equipment_id)
            for a,p,b in relations:
                evidence.extend(self._evidence_link(a,p,b,start,tenant_id,groups))
            evidence.append(Evidence("mes:"+record.record_id,"mes_execution",
                record.source_uri,record.record_id,record.execution_id,start,
                f"{record.batch_id} {record.equipment_id} {record.interval.start}..{record.interval.end}"))

            try:
                specification=self.specs.applicable(
                    specification_id=record.specification_id,equipment_id=record.equipment_id,
                    mode=record.mode,interval=record.interval,kind=kind,
                    tenant_id=tenant_id,groups=groups)
            except ValueError:
                limitations.append(f"{record.record_id}: conflicting approved specifications.")
                unexpected=True
                continue
            if specification is None:
                limitations.append(f"{record.record_id}: no approved, interval-valid specification.")
                unexpected=True
                continue
            evidence.append(Evidence("spec:"+specification.record_id,"specification",
                specification.source_uri,specification.record_id,record.specification_id,
                start,f"upper limit {specification.upper_limit} {specification.unit}; {kind}"))

            # Find all point candidates: *each sample* must be mapped both ways at
            # its own timestamp. Never assume the current sensor was always installed.
            candidates={r["to"] for r in self.graph.relations
                if r["from"]==record.equipment_id and r["predicate"]=="hasMeasurementPoint"
                and self.graph.visible(r["to"],tenant_id=tenant_id,groups=groups)}
            samples=self.historian.read(candidates,record.interval,
                tenant_id=tenant_id,groups=groups)
            samples=[sample for sample in samples if sample.kind==kind]
            cadence=self._sampling_grid(record.interval,spacing_seconds)
            expected={instant(t) for t in cadence}
            usable_times=set()
            for sample in samples:
                in_window=instant(sample.timestamp) in expected
                point_kind=self.graph.entities.get(sample.point_id,{}).get("quantity_kind")
                mapped=(point_kind==kind and self._graph_link(record.equipment_id,"hasMeasurementPoint",
                        sample.point_id,sample.timestamp,tenant_id,groups)
                        and self._graph_link(sample.point_id,"measuresAsset",
                        record.equipment_id,sample.timestamp,tenant_id,groups))
                if not in_window or not mapped or sample.quality!="GOOD":
                    rejected_count+=1
                    limitations.append(f"{sample.sample_id}: wrong cadence, point quantity kind, mapping, or quality.")
                    unexpected=True
                    continue
                if instant(sample.timestamp) in usable_times:
                    rejected_count+=1
                    limitations.append(f"{sample.sample_id}: duplicate readings at same cadence slot.")
                    unexpected=True
                    continue
                try:
                    exceeded,value,unit=compare_upper(
                        sample.value,sample.unit,sample.kind,
                        specification.upper_limit,specification.unit)
                except ValueError:
                    rejected_count+=1
                    limitations.append(f"{sample.sample_id}: incompatible measurement unit or value.")
                    unexpected=True
                    continue
                usable_times.add(instant(sample.timestamp))
                valid_count+=1
                exceed_count+=int(exceeded)
                evidence.append(Evidence("sample:"+sample.sample_id,"measurement",
                    sample.source_uri,sample.sample_id,sample.point_id,sample.timestamp,
                    f"{value} {unit}; exceeded={exceeded}"))
                evidence.extend(self._evidence_link(record.equipment_id,
                    "hasMeasurementPoint",sample.point_id,sample.timestamp,tenant_id,groups))
                evidence.extend(self._evidence_link(sample.point_id,
                    "measuresAsset",record.equipment_id,sample.timestamp,tenant_id,groups))

            if usable_times!=expected:
                unexpected=True
                limitations.append(f"{record.record_id}: incomplete required sampling grid "
                                   f"({len(usable_times)}/{len(expected)} valid).")

        # Deduplicate repeated relationship evidence without discarding sources.
        evidence=list({item.id:item for item in evidence}.values())
        if doc_query and self.doc_retriever is not None:
            hits=self.doc_retriever.search(doc_query,tenant=tenant_id,groups=groups,
                                           mode="hybrid",top_k=3)
            for hit in hits:
                evidence.append(Evidence("doc:"+hit.chunk.chunk_id,"document_chunk",
                    hit.source_uri,hit.chunk.chunk_id,hit.chunk.document_id,None,
                    hit.chunk.text[:400],"Context only; not a validated threshold source."))
        if unexpected or valid_count == 0:
            status="insufficient_evidence"
        else:
            status="observed_exceedance" if exceed_count else "within_observed_limits"
        limitations.append(
            "Synthetic observations only; not a diagnosis, product-quality ruling, "
            "or authorization for physical equipment operations."
        )
        return DiagnosticResult(batch_id,status,tuple(sorted(all_equipment)),
            exceed_count,valid_count,rejected_count,tuple(evidence),
            tuple(dict.fromkeys(limitations))).to_dict()

    def close(self) -> None:
        self.mes.close()
