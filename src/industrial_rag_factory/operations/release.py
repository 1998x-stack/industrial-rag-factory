"""Stage 08: offline blue/green SQLite snapshots and atomic catalogue pointer.

Safe scope: local synthetic documents, trusted CLI, immutable SQLite snapshots,
signed metadata, CAS release operations. NO factory deployment, network
connectors, cloud control, live OT access or real enterprise IAM.
"""
from __future__ import annotations

import fcntl
import hashlib
import hmac
import json
import os
import sqlite3
import tempfile
import time
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path
from urllib.parse import quote

from industrial_rag_factory.config import Settings
from industrial_rag_factory.parsing import from_bytes
from industrial_rag_factory.pipeline import Pipeline
from industrial_rag_factory.retrieval import Retriever
from industrial_rag_factory.storage import Store

from .telemetry import span


class ReleaseError(RuntimeError):
    """Fail-closed local operation; do not log contents or private keys."""


def _canonical(data: object) -> bytes:
    return json.dumps(data,sort_keys=True,separators=(",",":"),
                      ensure_ascii=False).encode("utf-8")


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _db_uri(path: Path) -> str:
    return "file:" + quote(str(path),safe="/") + "?mode=ro&immutable=1"


class ReleaseManager:
    """One writer, many version-pinned local readers; linux/macOS POSIX locks."""

    def __init__(self, state_root: str | Path, workspace: str | Path, key: str,
                 *, settings: Settings | None = None):
        self.settings=settings or Settings()
        if self.settings.environment!="development":
            raise ReleaseError("Stage 08 is development-only")
        if not isinstance(key,str) or len(key.encode("utf-8"))<32:
            raise ReleaseError("Stage 08 needs a locally configured 32-byte HMAC key")
        self.key=key.encode("utf-8")
        self.root=Path(state_root).resolve()
        self.workspace=Path(workspace).resolve(strict=True)
        self.root.mkdir(parents=True,exist_ok=True)
        (self.root/"snapshots").mkdir(exist_ok=True)
        self.dbpath=self.root/"catalog.sqlite3"
        self.lockpath=self.root/"catalog.lock"
        with self._lock():
            with self._catalog() as db:
                db.executescript("""
                CREATE TABLE IF NOT EXISTS releases(
                  version TEXT PRIMARY KEY, payload TEXT NOT NULL,
                  signature TEXT NOT NULL, created_at INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS active(
                  singleton INTEGER PRIMARY KEY CHECK(singleton=1),
                  version TEXT
                );
                INSERT OR IGNORE INTO active(singleton,version) VALUES(1,NULL);
                CREATE TABLE IF NOT EXISTS op_events(
                  id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL,
                  elapsed_ms REAL NOT NULL, success INTEGER NOT NULL,
                  created_at INTEGER NOT NULL
                );
                """)

    @contextmanager
    def _lock(self, shared: bool = False):
        with self.lockpath.open("a+b") as handle:
            fcntl.flock(handle.fileno(),fcntl.LOCK_SH if shared else fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(handle.fileno(),fcntl.LOCK_UN)

    @contextmanager
    def _catalog(self):
        db=sqlite3.connect(self.dbpath,timeout=15)
        db.row_factory=sqlite3.Row
        try:
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def _sign(self, payload: dict) -> str:
        return hmac.new(self.key,_canonical(payload),hashlib.sha256).hexdigest()

    def _active(self, db) -> str | None:
        return db.execute("SELECT version FROM active WHERE singleton=1").fetchone()[0]

    def _row(self, db, version: str) -> dict:
        if not isinstance(version,str) or len(version)!=24 or any(
            c not in "0123456789abcdef" for c in version
        ):
            raise ReleaseError("Invalid version identifier")
        result=db.execute("SELECT payload,signature FROM releases WHERE version=?",
                          (version,)).fetchone()
        if result is None:
            raise ReleaseError("Unknown version")
        try:
            payload=json.loads(result["payload"])
        except ValueError as exc:
            raise ReleaseError("Corrupt release manifest") from exc
        if (payload.get("version")!=version or
            not hmac.compare_digest(result["signature"],self._sign(payload))):
            raise ReleaseError("Release lineage signature mismatch")
        return payload

    def _verify(self, db, version: str, *, integrity: bool = True) -> dict:
        payload=self._row(db,version)
        path=self.root/"snapshots"/(version+".sqlite3")
        if path.is_symlink() or not path.is_file() or _sha(path.read_bytes())!=payload["db_sha256"]:
            raise ReleaseError("Published snapshot is missing or corrupted")
        if integrity:
            with sqlite3.connect(_db_uri(path),uri=True) as index:
                if index.execute("PRAGMA quick_check").fetchone()[0]!="ok":
                    raise ReleaseError("SQLite snapshot quick_check failed")
        return payload

    def _inputs(self, manifest: dict) -> list[dict]:
        if (not isinstance(manifest,dict) or set(manifest)!={"version","sources"} or
            manifest["version"]!="stage08-v1" or
            not isinstance(manifest["sources"],list) or
            not 1<=len(manifest["sources"])<=64):
            raise ReleaseError("Invalid full-manifest schema")
        output=[]
        seen=set()
        total=0
        for spec in manifest["sources"]:
            if not isinstance(spec,dict) or set(spec)!={"source_uri","path","revision"}:
                raise ReleaseError("Invalid document source schema")
            uri,relative,rev=spec["source_uri"],spec["path"],spec["revision"]
            if (not isinstance(uri,str) or not uri.startswith("fixture://") or
                not 10<=len(uri)<=200 or
                not isinstance(relative,str) or relative.startswith("/") or
                not relative.startswith("datasets/") or
                not isinstance(rev,str) or not 1<=len(rev)<=40):
                raise ReleaseError("Only synthetic, repository-relative sources allowed")
            if uri in seen:
                raise ReleaseError("Duplicate source URI in full manifest")
            seen.add(uri)
            path=(self.workspace/relative).resolve(strict=True)
            if not path.is_relative_to(self.workspace) or not path.is_file():
                raise ReleaseError("Source escapes approved workspace")
            if path.suffix.lower() not in (".md",".markdown",".txt"):
                raise ReleaseError("Stage 08 only stages synthetic text documents")
            data=path.read_bytes()
            total+=len(data)
            if not data or len(data)>131072 or total>2097152:
                raise ReleaseError("Ingestion byte budget exceeded")
            output.append({"source_uri":uri,"path":relative,"revision":rev,
                           "sha256":_sha(data),"size_bytes":len(data),
                           "_bytes":data})
        return sorted(output,key=lambda x:x["source_uri"])

    def _copy_snapshot(self, source: Path, destination: Path) -> None:
        src=sqlite3.connect(_db_uri(source),uri=True)
        dest=sqlite3.connect(destination)
        try:
            src.backup(dest)
        finally:
            dest.close()
            src.close()

    def stage(self, manifest: dict, *, fail_at: str | None = None,
              max_change_bytes: int = 2_097_152) -> dict:
        """Build/verify a detached release, never modify active pointer."""
        if fail_at not in (None,"after_ingest","before_catalog"):
            raise ValueError("Unknown synthetic fault injection")
        if type(max_change_bytes) is not int or not 1<=max_change_bytes<=2097152:
            raise ValueError("Invalid ingest resource budget")
        sources=self._inputs(manifest)
        record_sources=[{k:v for k,v in row.items() if k!="_bytes"} for row in sources]
        by_source={x["source_uri"]:x for x in record_sources}
        with span("stage"):
            with self._lock():
                with self._catalog() as db:
                    parent=self._active(db)
                    prior=self._verify(db,parent) if parent else None
                    previous=prior["sources"] if prior else {}
                    changed=[item for item in sources if
                             previous.get(item["source_uri"])!=by_source[item["source_uri"]]]
                    removed=sorted(set(previous)-set(by_source))
                    change_bytes=sum(item["size_bytes"] for item in changed)
                    if change_bytes>max_change_bytes:
                        raise ReleaseError("Incremental change budget exceeded")
                    identity={"parent":parent,"sources":by_source,
                              "backend":"hashing","chunk_size":220,"overlap":40,
                              "tenant":"demo","groups":["demo-readers"]}
                    version=_sha(_canonical(identity))[:24]
                    existing=db.execute("SELECT 1 FROM releases WHERE version=?",
                                        (version,)).fetchone()
                    if existing:
                        return {"version":version,"status":"already_staged",
                                "parent":parent,"changed":0,"removed":0}
                    path=self.root/"snapshots"/(version+".sqlite3")
                    if path.exists() or path.is_symlink():
                        raise ReleaseError("Unregistered snapshot path collision")
                    handle=tempfile.NamedTemporaryFile(
                        prefix="build-",suffix=".sqlite3",dir=self.root,delete=False)
                    tmp=Path(handle.name)
                    handle.close()
                    output_tmp=path.with_suffix(".building")
                    created=False
                    try:
                        if prior:
                            self._copy_snapshot(self.root/"snapshots"/(parent+".sqlite3"),tmp)
                        local=replace(self.settings,db_path=str(tmp),generator="extractive",
                                      planner="rules",security_mode="off",
                                      dense_backend="hashing",deepseek_api_key="",
                                      tenant_id="demo",groups=("demo-readers",))
                        pipeline=Pipeline(local)
                        try:
                            for uri in removed+[x["source_uri"] for x in changed]:
                                pipeline.store.remove_source("demo",uri)
                            for entry in changed:
                                doc=from_bytes(entry["_bytes"],entry["source_uri"],
                                    Path(entry["path"]).suffix,
                                    revision=entry["revision"],tenant_id="demo",
                                    access_groups=("demo-readers",))
                                pipeline.ingest(doc,max_tokens=220,overlap=40)
                        finally:
                            pipeline.close()
                        if fail_at=="after_ingest":
                            raise ReleaseError("Injected fault after index preparation")
                        self._copy_snapshot(tmp,output_tmp)
                        result_bytes=output_tmp.read_bytes()
                        sha=_sha(result_bytes)
                        # Register only a verified immutable snapshot.
                        with sqlite3.connect(_db_uri(output_tmp),uri=True) as check:
                            if check.execute("PRAGMA quick_check").fetchone()[0]!="ok":
                                raise ReleaseError("Staged SQLite integrity failure")
                        os.replace(output_tmp,path)
                        created=True
                        with path.open("rb") as snapshot:
                            os.fsync(snapshot.fileno())
                        if fail_at=="before_catalog":
                            raise ReleaseError("Injected fault before registration")
                        payload={"version":version,"parent":parent,"sources":by_source,
                                 "source_count":len(by_source),"db_sha256":sha,
                                 "input_fingerprint":_sha(_canonical(identity)),
                                 "changed_count":len(changed),"removed_count":len(removed),
                                 "skipped_count":len(by_source)-len(changed),
                                 "change_bytes":change_bytes,
                                 "cost_proxy_input_units":(change_bytes+3)//4,
                                 "created_at":int(time.time()),
                                 "scope":"synthetic-local-only"}
                        db.execute("INSERT INTO releases VALUES(?,?,?,?)",(
                            version,json.dumps(payload,sort_keys=True),
                            self._sign(payload),payload["created_at"]))
                        return {"version":version,"status":"staged","parent":parent,
                                "changed":len(changed),"removed":len(removed),
                                "skipped":len(by_source)-len(changed),
                                "cost_proxy_input_units":payload["cost_proxy_input_units"]}
                    except BaseException:
                        if created:
                            path.unlink(missing_ok=True)
                        raise
                    finally:
                        tmp.unlink(missing_ok=True)
                        output_tmp.unlink(missing_ok=True)
                        for suffix in ("-wal","-shm"):
                            Path(str(tmp)+suffix).unlink(missing_ok=True)
                            Path(str(output_tmp)+suffix).unlink(missing_ok=True)

    def _switch(self, version: str, expected_active: str | None, *,
                rollback: bool = False) -> dict:
        with span("rollback" if rollback else "publish"):
            with self._lock():
                with self._catalog() as db:
                    current=self._active(db)
                    if current!=expected_active:
                        raise ReleaseError("CAS rejected: active version changed")
                    payload=self._verify(db,version)
                    if not rollback and payload["parent"]!=current:
                        raise ReleaseError("Staged release parent differs from active")
                    if rollback and current is None:
                        raise ReleaseError("No active release to roll back")
                    db.execute("UPDATE active SET version=? WHERE singleton=1",(version,))
                    return {"status":"rolled_back" if rollback else "published",
                            "active":version,"previous":current,
                            "signed_manifest_verified":True}

    def publish(self, version: str, *, expected_active: str | None) -> dict:
        return self._switch(version,expected_active)

    def rollback(self, version: str, *, expected_active: str) -> dict:
        return self._switch(version,expected_active,rollback=True)

    def query(self, question: str, *, tenant: str = "demo",
              groups: tuple[str,...] = ("demo-readers",), k: int = 3) -> dict:
        if (not isinstance(question,str) or not 1<=len(question)<=2000
            or tenant!="demo" or groups!=("demo-readers",)
            or type(k) is not int or not 1<=k<=10):
            raise ReleaseError("Invalid read-only query scope or budget")
        start=time.monotonic()
        success=False
        try:
            with span("query"):
                with self._lock(shared=True):
                    with self._catalog() as db:
                        version=self._active(db)
                        if version is None:
                            raise ReleaseError("No published snapshot")
                        self._verify(db,version)
                    path=self.root/"snapshots"/(version+".sqlite3")
                    # Store.__init__ would execute DDL and WAL; never use it
                    # for immutable published snapshots.
                    store=object.__new__(Store)
                    store.path=str(path)
                    store.con=sqlite3.connect(_db_uri(path),uri=True)
                    store.con.row_factory=sqlite3.Row
                    try:
                        retriever=Retriever(store,backend="hashing")
                        hits=retriever.search(question,tenant=tenant,groups=groups,
                                              mode="hybrid",top_k=k)
                        success=True
                        return {"version":version,
                                "status":"retrieved_not_verified" if hits
                                         else "insufficient_evidence",
                                "hits":[hit.to_dict() for hit in hits],
                                "limitations":["Snapshot verified, evidence claims not independently entailed.",
                                               "Local demo index; not live factory data."]}
                    finally:
                        store.close()
        finally:
            self._event("query",round((time.monotonic()-start)*1000,3),success)

    def _event(self, name: str, elapsed_ms: float, success: bool) -> None:
        if name not in ("query","drill") or elapsed_ms<0:
            raise ValueError("Only bounded operational events allowed")
        with self._lock():
            with self._catalog() as db:
                db.execute("INSERT INTO op_events(name,elapsed_ms,success,created_at)"
                           " VALUES(?,?,?,?)",
                           (name,elapsed_ms,int(success),int(time.time())))

    def status(self) -> dict:
        with self._lock(shared=True):
            with self._catalog() as db:
                ok=db.execute("PRAGMA quick_check").fetchone()[0]=="ok"
                active=self._active(db)
                count=db.execute("SELECT count(*) FROM releases").fetchone()[0]
                events=db.execute("SELECT elapsed_ms,success FROM op_events"
                                  " WHERE name='query' ORDER BY id DESC LIMIT 500").fetchall()
                verified=False
                queryable=False
                if active:
                    try:
                        self._verify(db,active)
                        verified=True
                        with sqlite3.connect(_db_uri(self.root/"snapshots"/
                                                     (active+".sqlite3")),uri=True) as check:
                            queryable=bool(check.execute(
                                "SELECT name FROM sqlite_master WHERE name='chunk_fts'"
                            ).fetchone())
                    except (ReleaseError,sqlite3.Error,OSError):
                        pass
                latencies=sorted(float(x["elapsed_ms"]) for x in events)
                p95=latencies[max(0,__import__("math").ceil(len(latencies)*.95)-1)] if latencies else None
                return {"stage":"S08","scope":"synthetic-local-only",
                        "active":active,"catalog_healthy":ok,
                        "active_verified":verified,"queryable":queryable,
                        "release_count":count,"query_samples":len(events),
                        "observed_query_p95_ms":p95,
                        "observed_query_successes":sum(x["success"] for x in events),
                        "slo_status":"not_qualified_no_production_traffic"}

    def history(self) -> list[dict]:
        with self._lock(shared=True):
            with self._catalog() as db:
                rows=db.execute("SELECT version FROM releases ORDER BY rowid").fetchall()
                return [{k:v for k,v in self._row(db,x["version"]).items()
                         if k in ("version","parent","source_count","changed_count",
                                  "removed_count","skipped_count","created_at","db_sha256")}
                        for x in rows]
