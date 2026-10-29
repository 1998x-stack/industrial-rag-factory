"""Stage 08 offline controlled release and disaster-recovery smoke.

Uses an ephemeral local workspace, never production data or live endpoints.
"""
from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
from pathlib import Path

from industrial_rag_factory.operations import ReleaseManager, ReleaseError, readiness_report

ROOT=Path(__file__).resolve().parents[1]
INPUT=ROOT/"config/stage08_manifest.json"
cases=[]


def verify(name: str, condition: bool) -> None:
    cases.append({"id":name,"passed":bool(condition)})
    if not condition:
        raise AssertionError(name)


with tempfile.TemporaryDirectory(prefix="irf-stage08-drill-") as folder:
    work=Path(folder)/"workspace"
    manifest=json.loads(INPUT.read_text(encoding="utf-8"))
    for item in manifest["sources"]:
        target=work/item["path"]
        target.parent.mkdir(parents=True,exist_ok=True)
        shutil.copy2(ROOT/item["path"],target)
    mgr=ReleaseManager(Path(folder)/"state",work,
                       "stage08-ci-ephemeral-never-production-signing-key-000")
    initial=mgr.stage(manifest)
    verify("detached_stage",mgr.status()["active"] is None)
    verify("signed_snapshot",bool(initial["version"]))
    mgr.publish(initial["version"],expected_active=None)
    verify("first_publish_query",mgr.query("轴承")[
        "status"]=="retrieved_not_verified")
    edit=work/"datasets/stage01/maintenance.md"
    edit.write_text("# Synthetic maintenance\n\nStage08DrillNewMarker892",
                    encoding="utf-8")
    for fault in ("after_ingest","before_catalog"):
        denied=False
        try:
            mgr.stage(manifest,fail_at=fault)
        except ReleaseError:
            denied=True
        verify("safe_"+fault,denied and mgr.status()["active"]==initial["version"])
    staged=mgr.stage(manifest)
    verify("incremental_change",staged["changed"]==1 and staged["skipped"]==2)
    before=mgr.query("Stage08DrillNewMarker892")["status"]
    verify("unpublished_not_visible",before=="insufficient_evidence")
    cas_denied=False
    try:
        mgr.publish(staged["version"],expected_active=None)
    except ReleaseError:
        cas_denied=True
    verify("stale_CAS_denied",cas_denied)
    mgr.publish(staged["version"],expected_active=initial["version"])
    verify("new_snapshot_visible",mgr.query("Stage08DrillNewMarker892")[
        "status"]=="retrieved_not_verified")
    mgr.rollback(initial["version"],expected_active=staged["version"])
    verify("rollback_restores_prior_index",mgr.query("Stage08DrillNewMarker892")[
        "status"]=="insufficient_evidence")
    archive=Path(folder)/"verified-snapshot.zip"
    exported=mgr.export_bundle(initial["version"],archive)
    verify("backup_archive_created",archive.is_file() and bool(exported["archive_sha256"]))
    restored=ReleaseManager(Path(folder)/"restored-catalog",work,
                            "stage08-ci-ephemeral-never-production-signing-key-000")
    imported=restored.import_bundle(archive)
    verify("backup_restored_but_inactive",imported["status"]=="imported_inactive"
           and restored.status()["active"] is None)
    recovered=restored.recover(initial["version"],expected_active=None)
    verify("restored_index_queryable",recovered["status"]=="recovered"
           and restored.query("轴承")["status"]=="retrieved_not_verified")
    status=mgr.status()
    gate=readiness_report(status,target="production")
    verify("readiness_no_production_approval",gate["local_demo_ready"] and
           not gate["production_ready"])
    verify("catalog_and_snapshot_integrity",status["active_verified"] and
           status["catalog_healthy"])
report={
    "stage":"S08",
    "scope":"synthetic_offline_release_drills",
    "passed":sum(x["passed"] for x in cases),"total":len(cases),
    "cases":cases,"manifest_sha256":hashlib.sha256(INPUT.read_bytes()).hexdigest(),
    "operational_status":status,"release_gate":gate,
    "limitations":[
        "Only ephemeral local SQLite indices and signed demo metadata were tested.",
        "No independent DR site, enterprise IdP, real traffic SLO, OT connectivity, or immutable audit.",
        "Change-byte proxy is not DeepSeek token billing or actual GPU/cloud cost.",
        "Manual production approval remains blocked even with green simulation tests.",
    ],
}
out=ROOT/"outputs"/"stage08_release_drill.json"
out.parent.mkdir(parents=True,exist_ok=True)
out.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
print(f"Stage 08: {report['passed']}/{report['total']} offline release drills passed")
print(f"Report: {out}")
if report["passed"]!=report["total"]:
    raise SystemExit(1)
