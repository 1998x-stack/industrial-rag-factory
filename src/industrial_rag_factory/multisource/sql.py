"""Allowlisted, parameterized, read-only SQL over synthetic MES rows.

No arbitrary SQL input. Real MES adapters require service credentials, IAM and OT review.
"""
from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from .contracts import Interval


@dataclass(frozen=True)
class ExecutionRecord:
    record_id: str
    execution_id: str
    batch_id: str
    equipment_id: str
    equipment_external_id: str
    equipment_source_system: str
    work_order_id: str
    specification_id: str
    mode: str
    interval: Interval
    source_uri: str


class MESReadModel:
    """Ephemeral SQLite materialization, prepared statements, scoped before results escape."""

    def __init__(self, payload: dict):
        self.con = sqlite3.connect(":memory:")
        self.con.row_factory = sqlite3.Row
        self.con.execute("""CREATE TABLE mes_execution(
            record_id TEXT PRIMARY KEY, execution_id TEXT NOT NULL,
            batch_id TEXT NOT NULL, equipment_id TEXT NOT NULL,
            equipment_external_id TEXT NOT NULL, equipment_source_system TEXT NOT NULL,
            work_order_id TEXT NOT NULL, specification_id TEXT NOT NULL,
            mode TEXT NOT NULL, started TEXT NOT NULL, ended TEXT NOT NULL,
            tenant_id TEXT NOT NULL, access_groups TEXT NOT NULL,
            source_uri TEXT NOT NULL)""")
        for row in payload["executions"]:
            Interval(row["started"],row["ended"])
            if not row["tenant_id"] or not row["access_groups"] or not row["source_uri"]:
                raise ValueError("MES row missing tenancy or provenance")
            self.con.execute("INSERT INTO mes_execution VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                             (row["record_id"],row["execution_id"],row["batch_id"],
                              row["equipment_id"],row["equipment_external_id"],row["equipment_source_system"],row["work_order_id"],
                              row["specification_id"],row["mode"],row["started"],row["ended"],
                              row["tenant_id"],json.dumps(row["access_groups"]),row["source_uri"]))
        self.con.commit()

    @classmethod
    def from_json(cls, path: str | Path) -> "MESReadModel":
        return cls(json.loads(Path(path).read_text(encoding="utf-8")))

    def by_batch(self, batch_id: str, *, tenant_id: str,
                 groups: tuple[str, ...], max_rows: int = 100) -> list[ExecutionRecord]:
        if not batch_id or not tenant_id or not groups:
            raise ValueError("Batch, tenant and access groups required")
        if not 1 <= max_rows <= 100:
            raise ValueError("Invalid row limit")
        sql = """SELECT * FROM mes_execution WHERE batch_id = ? AND tenant_id = ?
                 AND EXISTS (SELECT 1 FROM json_each(mes_execution.access_groups)
                             WHERE value IN (""" + ",".join("?" for _ in groups) + """))
                 ORDER BY started,record_id LIMIT ?"""
        rows = self.con.execute(sql,(batch_id,tenant_id,*groups,max_rows+1)).fetchall()
        if len(rows) > max_rows:
            raise ValueError("MES result exceeds allowed row budget")
        return [ExecutionRecord(
            r["record_id"],r["execution_id"],r["batch_id"],r["equipment_id"],
            r["equipment_external_id"],r["equipment_source_system"],r["work_order_id"],r["specification_id"],r["mode"],
            Interval(r["started"],r["ended"]),r["source_uri"]
        ) for r in rows]

    def close(self) -> None:
        self.con.close()
