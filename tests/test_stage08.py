"""Stage 08: offline immutable-index release, rollback, failures and trust boundaries."""
from __future__ import annotations

import json
import shutil
import sqlite3
from dataclasses import replace
from pathlib import Path

import pytest

from industrial_rag_factory.config import Settings
from industrial_rag_factory.operations import ReleaseManager, ReleaseError, readiness_report

PROJECT=Path(__file__).resolve().parents[1]
KEY="ephemeral-stage08-fixture-local-key-do-not-deploy-000000"


@pytest.fixture
def release(tmp_path):
    ws=tmp_path/"workspace"
    (ws/"datasets/stage01").mkdir(parents=True)
    original=json.loads((PROJECT/"config/stage08_manifest.json").read_text())
    for entry in original["sources"]:
        dest=ws/entry["path"]
        shutil.copy2(PROJECT/entry["path"],dest)
    manager=ReleaseManager(tmp_path/"state",ws,KEY,settings=Settings())
    return manager,ws,original


def test_stage_publish_query_rollback(release):
    m,ws,data=release
    initial=m.stage(data)
    assert initial["status"]=="staged" and initial["parent"] is None
    assert m.status()["active"] is None
    with pytest.raises(ReleaseError,match="No published"):
        m.query("maintenance")
    first=m.publish(initial["version"],expected_active=None)
    assert first["status"]=="published"
    assert m.status()["active_verified"]
    assert m.query("bearing maintenance")["status"]=="retrieved_not_verified"
    content=ws/"datasets/stage01/maintenance.md"
    content.write_text("# Maintenance\n\nStage08UniqueMarkerXY991 device documentation.",
                       encoding="utf-8")
    revised=m.stage(data)
    assert revised["parent"]==initial["version"]
    assert revised["changed"]==1 and revised["skipped"]==2
    assert m.query("Stage08UniqueMarkerXY991")["status"]=="insufficient_evidence"
    with pytest.raises(ReleaseError,match="CAS"):
        m.publish(revised["version"],expected_active=None)
    assert m.status()["active"]==initial["version"]
    m.publish(revised["version"],expected_active=initial["version"])
    assert m.query("Stage08UniqueMarkerXY991")["status"]=="retrieved_not_verified"
    m.rollback(initial["version"],expected_active=revised["version"])
    assert m.query("Stage08UniqueMarkerXY991")["status"]=="insufficient_evidence"
    assert m.status()["release_count"]==2


def test_revision_removal_has_no_stale_fts(release):
    manager,_,manifest=release
    original=manager.stage(manifest)
    manager.publish(original["version"],expected_active=None)
    new={"version":"stage08-v1","sources":[x for x in manifest["sources"]
                                            if x["source_uri"]!="fixture://maintenance.md"]}
    result=manager.stage(new)
    assert result["removed"]==1
    manager.publish(result["version"],expected_active=original["version"])
    assert manager.query("bearing noise maintenance")["status"] in (
        "insufficient_evidence","retrieved_not_verified"
    )
    # Verify source absent from materialized active SQLite, not merely hidden.
    path=manager.root/"snapshots"/(result["version"]+".sqlite3")
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT COUNT(*) FROM documents WHERE source_uri=?",
                          ("fixture://maintenance.md",)).fetchone()[0]==0
        assert db.execute("PRAGMA foreign_key_check").fetchall()==[]


@pytest.mark.parametrize("fault",["after_ingest","before_catalog"])
def test_stage_injected_fault_cannot_replace_active(release,fault):
    manager,ws,manifest=release
    first=manager.stage(manifest)
    manager.publish(first["version"],expected_active=None)
    (ws/"datasets/stage01/maintenance.md").write_text(
        "# Maintenance\n\nINJECTED_DOCUMENT_SHOULD_NOT_PUBLISH",encoding="utf-8")
    with pytest.raises(ReleaseError,match="Injected"):
        manager.stage(manifest,fail_at=fault)
    assert manager.status()["active"]==first["version"]
    assert manager.status()["release_count"]==1
    assert manager.query("bearing")["version"]==first["version"]


def test_stage_is_reproducible_and_reuses_identical_inputs(release):
    manager,_,manifest=release
    a=manager.stage(manifest)
    b=manager.stage(manifest)
    assert b["version"]==a["version"] and b["status"]=="already_staged"
    assert manager.status()["release_count"]==1


def test_corrupt_snapshot_blocks_query_and_publication(release):
    manager,_,manifest=release
    result=manager.stage(manifest)
    path=manager.root/"snapshots"/(result["version"]+".sqlite3")
    path.write_bytes(path.read_bytes()+b"unauthorized-change")
    with pytest.raises(ReleaseError,match="corrupted"):
        manager.publish(result["version"],expected_active=None)
    assert manager.status()["active"] is None


def test_wrong_key_rejects_existing_release(release):
    manager,ws,manifest=release
    record=manager.stage(manifest)
    manager.publish(record["version"],expected_active=None)
    other=ReleaseManager(manager.root,ws,"another-local-hmac-key-long-enough-to-test-991")
    with pytest.raises(ReleaseError,match="signature"):
        other.query("maintenance")


def test_untrusted_source_manifest_rejected(release,tmp_path):
    manager,ws,manifest=release
    modified=json.loads(json.dumps(manifest))
    modified["sources"][0]["path"]="../../etc/passwd"
    with pytest.raises(ReleaseError):
        manager.stage(modified)
    modified=json.loads(json.dumps(manifest))
    modified["sources"][0]["source_uri"]="https://factory-control.example"
    with pytest.raises(ReleaseError):
        manager.stage(modified)
    modified=json.loads(json.dumps(manifest))
    modified["sources"].append(modified["sources"][0])
    with pytest.raises(ReleaseError,match="Duplicate"):
        manager.stage(modified)
    symlink=ws/"datasets/stage01/outside.md"
    symlink.symlink_to(tmp_path/"outside.md")
    (tmp_path/"outside.md").write_text("secret",encoding="utf-8")
    modified=json.loads(json.dumps(manifest))
    modified["sources"][0]["path"]="datasets/stage01/outside.md"
    with pytest.raises(ReleaseError,match="escapes"):
        manager.stage(modified)


def test_budget_and_unauthorized_read_denied(release):
    manager,_,manifest=release
    with pytest.raises(ReleaseError,match="budget"):
        manager.stage(manifest,max_change_bytes=1)
    a=manager.stage(manifest)
    manager.publish(a["version"],expected_active=None)
    with pytest.raises(ReleaseError):
        manager.query("maintenance",tenant="other")
    with pytest.raises(ReleaseError):
        manager.query("maintenance",groups=("other",))
    with pytest.raises(ReleaseError):
        manager.query("maintenance",k=100)
    assert manager.status()["query_samples"]==0


def test_readiness_remains_explicitly_not_production_ready(release):
    manager,_,manifest=release
    assert readiness_report(manager.status())["decision"]=="blocked"
    a=manager.stage(manifest)
    manager.publish(a["version"],expected_active=None)
    manager.query("bearing")
    result=readiness_report(manager.status(),target="production")
    assert result["local_demo_ready"] and not result["production_ready"]
    assert result["decision"]=="demo_only"
    assert result["production_blockers"]
    assert manager.status()["query_samples"]==1
    assert manager.status()["slo_status"]=="not_qualified_no_production_traffic"


def test_manifest_drift_is_explicit_resource_change(release):
    manager,ws,manifest=release
    first=manager.stage(manifest)
    manager.publish(first["version"],expected_active=None)
    path=ws/"datasets/stage01/maintenance.md"
    path.write_bytes(path.read_bytes()+b"\nExtra validated synthetic text.")
    revised=manager.stage(manifest)
    assert revised["changed"]==1
    hist=manager.history()
    assert len(hist)==2
    assert hist[1]["parent"]==first["version"]
    assert hist[1]["db_sha256"]


def test_production_environment_rejected(release):
    manager,ws,_=release
    with pytest.raises(ReleaseError,match="development-only"):
        ReleaseManager(manager.root,ws,KEY,
                       settings=replace(Settings(),environment="production"))


def test_export_restore_bundle_roundtrip_and_explicit_recovery(release,tmp_path):
    manager,ws,manifest=release
    staged=manager.stage(manifest)
    manager.publish(staged["version"],expected_active=None)
    backup=tmp_path/"archive"/"snapshot.zip"
    exported=manager.export_bundle(staged["version"],backup)
    assert exported["status"]=="exported"
    restored=ReleaseManager(tmp_path/"recovery-state",ws,KEY)
    imported=restored.import_bundle(backup)
    assert imported["status"]=="imported_inactive"
    assert restored.status()["active"] is None
    recovered=restored.recover(staged["version"],expected_active=None)
    assert recovered["status"]=="recovered"
    assert restored.query("bearing maintenance")["status"]=="retrieved_not_verified"
    assert restored.status()["active_verified"]
    assert restored.import_bundle(backup)["status"]=="already_imported"


def test_backup_rejected_when_content_is_tampered(release,tmp_path):
    import zipfile
    manager,ws,manifest=release
    staged=manager.stage(manifest)
    backup=tmp_path/"backup.zip"
    manager.export_bundle(staged["version"],backup)
    broken=tmp_path/"tampered.zip"
    with zipfile.ZipFile(backup) as src, zipfile.ZipFile(broken,"w") as dest:
        dest.writestr("manifest.json",src.read("manifest.json"))
        dest.writestr("snapshot.sqlite3",src.read("snapshot.sqlite3")+b"tampered")
    restored=ReleaseManager(tmp_path/"recover",ws,KEY)
    with pytest.raises(ReleaseError,match="digest"):
        restored.import_bundle(broken)
    assert restored.status()["release_count"]==0


def test_backup_signature_wrong_key_rejected(release,tmp_path):
    manager,ws,manifest=release
    record=manager.stage(manifest)
    backup=tmp_path/"backup.zip"
    manager.export_bundle(record["version"],backup)
    different=ReleaseManager(tmp_path/"new-state",ws,
                             "different-signing-key-that-is-more-than-32-characters")
    with pytest.raises(ReleaseError,match="signature"):
        different.import_bundle(backup)


def test_prune_keeps_active_and_rollback_parent(release):
    manager,ws,manifest=release
    versions=[]
    for step in range(5):
        if step:
            (ws/"datasets/stage01/maintenance.md").write_text(
                f"# Synthetic maintenance\\n\\nRevisionBatchNo{step}",
                encoding="utf-8")
        current=manager.status()["active"]
        entry=manager.stage(manifest)
        manager.publish(entry["version"],expected_active=current)
        versions.append(entry["version"])
    output=manager.prune(keep=2)
    assert output["removed_versions"]
    assert manager.status()["active"]==versions[-1]
    assert manager.status()["active_verified"]
    assert versions[-2] in {x["version"] for x in manager.history()}
    manager.rollback(versions[-2],expected_active=versions[-1])
    assert manager.status()["active"]==versions[-2]
