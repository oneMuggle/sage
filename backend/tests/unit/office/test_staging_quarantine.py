"""Quarantine collector tests: recoverable moves, conservative retention.

Every test asserts the safety contract, not just the happy path: referenced,
registered-workspace, fresh, unknown, empty, linked and over-budget candidates
must be retained, and permanent deletion must stay behind an explicit gate.
"""

from __future__ import annotations

import json
import os
import sqlite3
import time
import zipfile
from pathlib import Path
from typing import Optional

import pytest

from backend.office import staging_quarantine as sq

SCHEMA = """
CREATE TABLE office_documents (
    id TEXT PRIMARY KEY, workspace_path TEXT NOT NULL, doc_type TEXT NOT NULL,
    original_filename TEXT, generated_filename TEXT NOT NULL, status TEXT NOT NULL,
    created_at INTEGER NOT NULL, updated_at INTEGER NOT NULL, metadata TEXT,
    derived_from TEXT, archived_at INTEGER);
CREATE TABLE office_self_checks (
    id INTEGER PRIMARY KEY AUTOINCREMENT, doc_id TEXT NOT NULL, action TEXT NOT NULL,
    ok INTEGER NOT NULL, summary TEXT, created_at INTEGER NOT NULL);
CREATE TABLE office_journal_specs (
    spec_id TEXT PRIMARY KEY, template_sha256 TEXT NOT NULL, template_filename TEXT NOT NULL,
    workspace_path TEXT NOT NULL, spec_json TEXT NOT NULL, created_at INTEGER NOT NULL);
CREATE TABLE office_journal_generations (
    gen_id TEXT PRIMARY KEY, spec_id TEXT NOT NULL, output_path TEXT NOT NULL,
    mode TEXT NOT NULL, created_at INTEGER NOT NULL, llm_model TEXT,
    bytes_written INTEGER NOT NULL DEFAULT 0, workspace_path TEXT NOT NULL);
"""


def _make_db(path: Path, registered_workspace: Optional[Path]) -> None:
    """Create the office schema; rows are only added for a registered ws."""
    conn = sqlite3.connect(str(path))
    try:
        conn.executescript(SCHEMA)
        if registered_workspace is None:
            conn.commit()
            return
        now = int(time.time() * 1000)
        rows = [
            (
                "doc-referenced",
                str(registered_workspace),
                "word",
                None,
                "a.docx",
                "generated",
                now,
                now,
                None,
                None,
                None,
            ),
            (
                "doc-child",
                str(registered_workspace),
                "word",
                None,
                "b.docx",
                "generated",
                now,
                now,
                None,
                "doc-derived",
                None,
            ),
            (
                "doc-archived",
                str(registered_workspace),
                "word",
                None,
                "c.docx",
                "archived",
                now,
                now,
                None,
                None,
                now,
            ),
        ]
        conn.executemany("INSERT INTO office_documents VALUES (?,?,?,?,?,?,?,?,?,?,?)", rows)
        conn.execute(
            "INSERT INTO office_self_checks (doc_id, action, ok, summary, created_at) "
            "VALUES (?,?,?,?,?)",
            ("doc-selfcheck", "create", 1, "readback ok", now),
        )
        conn.execute(
            "INSERT INTO office_journal_specs VALUES (?,?,?,?,?,?)",
            (
                "spec-1",
                "sha",
                "tpl.docx",
                str(registered_workspace),
                json.dumps({"template": "doc-spec-template"}),
                now,
            ),
        )
        conn.execute(
            "INSERT INTO office_journal_generations VALUES (?,?,?,?,?,?,?,?)",
            (
                "gen-1",
                "spec-1",
                str(registered_workspace / "office" / "word" / "doc-journal" / "out.docx"),
                "pandoc",
                now,
                None,
                10,
                str(registered_workspace),
            ),
        )
        conn.commit()
    finally:
        conn.close()


def _mk(
    ws: Path,
    doc_type: str,
    doc_id: str,
    *,
    age_hours: int = 48,
    name: str = "doc.bin",
    content: bytes = b"payload",
) -> Path:
    directory = ws / "office" / doc_type / doc_id
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / name
    target.write_bytes(content)
    stamp = time.time() - age_hours * 3600
    os.utime(str(target), (stamp, stamp))
    os.utime(str(directory), (stamp, stamp))
    return directory


def _populate(ws: Path) -> None:
    """Staging candidates whose ids match the DB rows written by _make_db."""
    for doc_id in (
        "doc-referenced",
        "doc-derived",
        "doc-journal",
        "doc-selfcheck",
        "doc-spec-template",
        "doc-archived",
        "doc-orphan",
    ):
        _mk(ws, "word", doc_id)
    _mk(ws, "word", "doc-fresh", age_hours=0)
    _mk(ws, "excel", "doc-embedded", content=b"xlsx-bytes")
    (ws / "office" / "word" / "doc-empty").mkdir(parents=True, exist_ok=True)
    container = ws / "office" / "word" / "doc-referenced" / "container.docx"
    with zipfile.ZipFile(str(container), "w") as archive:
        archive.writestr(
            "word/_rels/document.xml.rels",
            '<Relationship Target="../../excel/doc-embedded/sheet.xlsx"/>',
        )


@pytest.fixture()
def env(tmp_path: Path):
    """Leftover workspace that the database no longer registers."""
    ws = tmp_path / "leftover"
    (ws / "office").mkdir(parents=True)
    active = tmp_path / "active"
    active.mkdir()
    db = tmp_path / "sage.db"
    _make_db(db, active)
    _populate(ws)
    return ws, db


@pytest.fixture()
def registered_env(tmp_path: Path):
    """Workspace still registered in office_documents / journal tables."""
    ws = tmp_path / "active"
    (ws / "office").mkdir(parents=True)
    db = tmp_path / "sage.db"
    _make_db(db, ws)
    _populate(ws)
    return ws, db


def _statuses(plan: dict) -> dict:
    return {c["document_id"]: c["status"] for c in plan["candidates"]}


def test_plan_classifies_every_reference_source(env) -> None:
    ws, db = env
    plan = sq.plan_quarantine(db, ws)
    assert plan["read_only"] is True
    assert plan["safe_to_delete"] is False
    assert plan["db_scan_status"] == "complete"
    assert plan["filesystem_scan_status"] == "complete"
    statuses = _statuses(plan)
    assert statuses["doc-referenced"] == "referenced"
    assert statuses["doc-derived"] == "referenced"
    assert statuses["doc-journal"] == "referenced"
    assert statuses["doc-selfcheck"] == "referenced"
    assert statuses["doc-archived"] == "referenced"
    assert statuses["doc-spec-template"] == "referenced"
    assert statuses["doc-embedded"] == "referenced"
    assert statuses["doc-fresh"] == "fresh"
    assert statuses["doc-empty"] == "unknown"
    assert statuses["doc-orphan"] == "no_reference_found"
    by_id = {c["document_id"]: c for c in plan["candidates"]}
    assert by_id["doc-journal"]["references"]
    assert "derived_document_lineage" in by_id["doc-derived"]["references"]
    assert any(r.startswith("workspace_file:") for r in by_id["doc-embedded"]["references"])
    assert any(r.endswith("_text_scan") for r in by_id["doc-spec-template"]["references"])
    assert plan["purge_requires_human_confirmation"] is True


def test_journal_output_path_match_is_exact(env, tmp_path: Path) -> None:
    """output_path must match by resolved path segments, not by id text."""
    ws, db = env
    conn = sqlite3.connect(str(db))
    conn.execute(
        "INSERT INTO office_journal_generations VALUES (?,?,?,?,?,?,?,?)",
        (
            "gen-2",
            "spec-1",
            str(ws / "office" / "word" / "doc-orphan" / "out.docx"),
            "pandoc",
            int(time.time() * 1000),
            None,
            10,
            str(ws),
        ),
    )
    conn.commit()
    conn.close()
    plan = sq.plan_quarantine(db, ws)
    by_id = {c["document_id"]: c for c in plan["candidates"]}
    assert "journal_output" in by_id["doc-orphan"]["references"]
    assert by_id["doc-orphan"]["status"] == "referenced"
    assert sq.quarantine_run(db, ws, dry_run=False)["planned"] == []


def test_registered_workspace_retains_all_staging(registered_env) -> None:
    """A workspace the app still knows about is never a cleanup target."""
    ws, db = registered_env
    plan = sq.plan_quarantine(db, ws)
    assert plan["summary"]["no_reference_found"] == 0
    orphan = {c["document_id"]: c for c in plan["candidates"]}["doc-orphan"]
    assert orphan["status"] == "referenced"
    assert any(r.startswith("registered_workspace:") for r in orphan["references"])
    result = sq.quarantine_run(db, ws, dry_run=False)
    assert result["planned"] == []
    assert result["quarantined"] == []
    assert (ws / "office" / "word" / "doc-orphan" / "doc.bin").is_file()


def test_non_canonical_registered_path_still_retains(tmp_path: Path) -> None:
    ws = tmp_path / "active"
    (ws / "office").mkdir(parents=True)
    db = tmp_path / "sage.db"
    _make_db(db, ws)
    _mk(ws, "word", "doc-orphan")
    conn = sqlite3.connect(str(db))
    conn.execute("UPDATE office_documents SET workspace_path = ?", (str(ws) + "/./",))
    conn.commit()
    conn.close()
    assert _statuses(sq.plan_quarantine(db, ws))["doc-orphan"] == "referenced"


def test_plan_survives_degraded_schema(tmp_path: Path) -> None:
    """Missing columns/tables degrade to unknown, never to clearance."""
    ws = tmp_path / "leftover"
    (ws / "office").mkdir(parents=True)
    db = tmp_path / "sage.db"
    conn = sqlite3.connect(str(db))
    conn.execute("CREATE TABLE office_documents (id TEXT PRIMARY KEY, derived_from TEXT)")
    conn.commit()
    conn.close()
    _mk(ws, "word", "doc-orphan")
    plan = sq.plan_quarantine(db, ws)
    assert _statuses(plan)["doc-orphan"] == "unknown"
    assert "missing_workspace_column:office_documents" in plan["notes"]
    assert plan["db_scan_status"] == "incomplete"


def test_scan_budget_exhaustion_retains_candidates(env) -> None:
    ws, db = env
    plan = sq.plan_quarantine(db, ws, scan_budget_bytes=64)
    assert plan["db_scan_status"] == "incomplete"
    assert _statuses(plan)["doc-orphan"] == "unknown"
    assert plan["summary"]["no_reference_found"] == 0


def test_dry_run_changes_nothing(env) -> None:
    ws, db = env
    before = sorted(p.as_posix() for p in ws.rglob("*"))
    result = sq.quarantine_run(db, ws)
    assert result["dry_run"] is True
    assert [p["document_id"] for p in result["planned"]] == ["doc-orphan"]
    assert result["quarantined"] == []
    assert (ws / "office" / "word" / "doc-orphan" / "doc.bin").is_file()
    assert not (ws / sq.QUARANTINE_SUBDIR).exists()
    assert sorted(p.as_posix() for p in ws.rglob("*")) == before


def test_execute_quarantines_only_unreferenced(env) -> None:
    ws, db = env
    result = sq.quarantine_run(db, ws, dry_run=False)
    entries = result["quarantined"]
    assert len(entries) == 1
    entry = entries[0]
    assert entry["document_id"] == "doc-orphan"
    assert entry["status"] == "quarantined"
    assert entry["source_removed"] is True
    assert not (ws / "office" / "word" / "doc-orphan").exists()
    for doc_id in (
        "doc-referenced",
        "doc-derived",
        "doc-journal",
        "doc-selfcheck",
        "doc-spec-template",
        "doc-archived",
        "doc-fresh",
    ):
        assert (ws / "office" / "word" / doc_id).is_dir()
    assert (ws / "office" / "excel" / "doc-embedded").is_dir()
    quarantined = Path(entry["quarantine_path"])
    assert quarantined.is_dir()
    assert (quarantined / "doc.bin").read_bytes() == b"payload"
    manifest = (ws / sq.QUARANTINE_SUBDIR / sq.MANIFEST_NAME).read_text(encoding="utf-8")
    actions = [json.loads(line)["action"] for line in manifest.splitlines() if line.strip()]
    assert actions == ["intent", "done", "source_removed"]


def test_doc_type_filter_limits_scope(env) -> None:
    ws, db = env
    result = sq.quarantine_run(db, ws, dry_run=False, doc_types=["ppt"])
    assert result["planned"] == []
    assert result["quarantined"] == []
    assert (ws / "office" / "word" / "doc-orphan").is_dir()


def test_report_lists_recoverable_entries(env) -> None:
    ws, db = env
    sq.quarantine_run(db, ws, dry_run=False)
    report = sq.quarantine_report(ws)
    assert report["total_entries"] == 1
    assert report["recoverable"] == 1
    assert report["automatic_deletion"] is False
    item = report["entries"][0]
    assert item["state"] == "done"
    assert item["present"] is True
    assert item["days_since_eligible"] is not None
    assert item["days_since_eligible"] < 0


def test_restore_returns_identical_bytes(env) -> None:
    ws, db = env
    run = sq.quarantine_run(db, ws, dry_run=False)
    qid = run["quarantined"][0]["quarantine_id"]
    source = ws / "office" / "word" / "doc-orphan"
    result = sq.restore_entry(ws, qid)
    assert result["status"] == "restored"
    assert (source / "doc.bin").read_bytes() == b"payload"
    assert not Path(run["quarantined"][0]["quarantine_path"]).exists()
    report = sq.quarantine_report(ws)
    assert report["entries"][0]["state"] == "restored"
    assert report["recoverable"] == 0
    assert sq.restore_entry(ws, qid)["status"] == "error"


def test_restore_refuses_occupied_original_path(env) -> None:
    ws, db = env
    run = sq.quarantine_run(db, ws, dry_run=False)
    qid = run["quarantined"][0]["quarantine_id"]
    source = ws / "office" / "word" / "doc-orphan"
    source.mkdir(parents=True)
    (source / "new-file.docx").write_bytes(b"user wrote here")
    result = sq.restore_entry(ws, qid)
    assert result["error"] == "original_path_occupied"
    assert (source / "new-file.docx").read_bytes() == b"user wrote here"
    assert Path(run["quarantined"][0]["quarantine_path"]).is_dir()


def test_interrupted_move_is_completed_on_next_run(env) -> None:
    ws, db = env
    root = ws / sq.QUARANTINE_SUBDIR
    source = ws / "office" / "word" / "doc-orphan"
    staging = root / "crash-1.tmp-quarantine"
    staging.mkdir(parents=True)
    files, total = sq._tree_digest(source)
    sq._copy_tree_verified(source, staging, files)
    sq._Manifest(root).append(
        {
            "action": "intent",
            "quarantine_id": "crash-1",
            "at": sq._utc(sq._now_ms()),
            "doc_type": "word",
            "document_id": "doc-orphan",
            "source_path": str(source),
            "staging_path": str(staging),
            "bytes": total,
            "files": files,
            "eligible_for_purge_after": sq._utc(sq._now_ms()),
        }
    )
    result = sq.quarantine_run(db, ws, dry_run=False)
    assert {"quarantine_id": "crash-1", "resumed": "completed"} in result["resumed"]
    assert (root / "crash-1").is_dir()
    assert not staging.exists()
    assert not source.exists()


def test_partial_copy_is_discarded_and_source_retained(env) -> None:
    ws, db = env
    root = ws / sq.QUARANTINE_SUBDIR
    source = ws / "office" / "word" / "doc-orphan"
    staging = root / "crash-2.tmp-quarantine"
    staging.mkdir(parents=True)
    (staging / "doc.bin").write_bytes(b"truncated")
    files, total = sq._tree_digest(source)
    sq._Manifest(root).append(
        {
            "action": "intent",
            "quarantine_id": "crash-2",
            "at": sq._utc(sq._now_ms()),
            "doc_type": "word",
            "document_id": "doc-orphan",
            "source_path": str(source),
            "staging_path": str(staging),
            "bytes": total,
            "files": files,
            "eligible_for_purge_after": sq._utc(sq._now_ms()),
        }
    )
    result = sq.quarantine_run(db, ws, dry_run=False)
    assert {"quarantine_id": "crash-2", "resumed": "discarded_partial_copy"} in result["resumed"]
    assert not staging.exists()
    assert not (root / "crash-2").exists()
    # doc-orphan stays a candidate and is quarantined normally afterwards
    assert [e["document_id"] for e in result["quarantined"]] == ["doc-orphan"]
    assert result["quarantined"][0]["source_removed"] is True
    assert not source.exists()
    moved = Path(result["quarantined"][0]["quarantine_path"]) / "doc.bin"
    assert moved.read_bytes() == b"payload"


def test_purge_requires_explicit_gates(env) -> None:
    ws, db = env
    run = sq.quarantine_run(db, ws, dry_run=False)
    qid = run["quarantined"][0]["quarantine_id"]
    quarantined = Path(run["quarantined"][0]["quarantine_path"])

    refused = sq.purge_entry(ws, qid, confirmed_id=qid)
    assert refused["status"] == "refused"
    assert refused["error"] == "permanent_deletion_not_allowed"
    assert quarantined.is_dir()

    mismatched = sq.purge_entry(
        ws, qid, confirmed_id="something-else", allow_permanent_deletion=True
    )
    assert mismatched["error"] == "confirmation_id_mismatch"
    assert quarantined.is_dir()

    early = sq.purge_entry(ws, qid, confirmed_id=qid, allow_permanent_deletion=True)
    assert early["error"] == "retention_window_not_elapsed"
    assert quarantined.is_dir()

    unknown = sq.purge_entry(
        ws, "does-not-exist", confirmed_id="does-not-exist", allow_permanent_deletion=True
    )
    assert unknown["error"] == "unknown_or_not_purgeable_entry"
    assert quarantined.is_dir()


def test_purge_after_retention_is_recorded(env) -> None:
    ws, db = env
    run = sq.quarantine_run(db, ws, dry_run=False)
    qid = run["quarantined"][0]["quarantine_id"]
    root = ws / sq.QUARANTINE_SUBDIR
    manifest = sq._Manifest(root)
    done = [r for r in manifest.records() if r["action"] == "done"][0]
    expired = dict(done)
    expired["eligible_for_purge_after"] = sq._utc(sq._now_ms() - 1000)
    manifest.append(expired)
    result = sq.purge_entry(ws, qid, confirmed_id=qid, allow_permanent_deletion=True)
    assert result["status"] == "purged"
    assert not Path(done["quarantine_path"]).exists()
    assert sq.quarantine_report(ws)["entries"][0]["state"] == "purged"


def test_busy_lock_retains_everything(env) -> None:
    ws, db = env
    root = ws / sq.QUARANTINE_SUBDIR
    root.mkdir(parents=True)
    lock = sq._Lock(root)
    lock.__enter__()
    try:
        result = sq.quarantine_run(db, ws, dry_run=False)
    finally:
        lock.__exit__()
    assert result["error"] == "quarantine_busy"
    assert result["quarantined"] == []
    assert not (root / sq.MANIFEST_NAME).exists()
    assert (ws / "office" / "word" / "doc-orphan" / "doc.bin").is_file()
    assert len(sq.quarantine_run(db, ws, dry_run=False)["quarantined"]) == 1


def test_symlinked_candidate_is_never_quarantined(env, tmp_path: Path) -> None:
    ws, db = env
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "important.docx").write_bytes(b"do not touch")
    link = ws / "office" / "word" / "doc-linked"
    try:
        link.symlink_to(outside, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("symlink creation unsupported on this platform")
    plan = sq.plan_quarantine(db, ws)
    entry = {c["document_id"]: c for c in plan["candidates"]}["doc-linked"]
    assert entry["status"] == "unknown"
    assert entry["reason"] == "linked_managed_directory"
    result = sq.quarantine_run(db, ws, dry_run=False)
    assert all(e["document_id"] != "doc-linked" for e in result["quarantined"])
    assert (outside / "important.docx").read_bytes() == b"do not touch"


def test_changed_source_is_flagged_and_retained(env, monkeypatch: pytest.MonkeyPatch) -> None:
    """A concurrent writer between copy and remove must keep the source."""
    ws, db = env
    source = ws / "office" / "word" / "doc-orphan"
    original_copy = sq._copy_tree_verified

    def copy_then_mutate(src: Path, dst: Path, entries) -> None:
        original_copy(src, dst, entries)
        if src == source:
            (source / "doc.bin").write_bytes(b"mutated during quarantine")

    monkeypatch.setattr(sq, "_copy_tree_verified", copy_then_mutate)
    result = sq.quarantine_run(db, ws, dry_run=False)
    entries = [e for e in result["quarantined"] if e["document_id"] == "doc-orphan"]
    assert entries, result
    assert entries[0]["status"] == "retained"
    assert entries[0]["reason"] == "candidate_changed_during_copy"
    assert (source / "doc.bin").read_bytes() == b"mutated during quarantine"
    assert not list((ws / sq.QUARANTINE_SUBDIR).glob("*.tmp-quarantine"))
    actions = [
        json.loads(line)["action"]
        for line in (ws / sq.QUARANTINE_SUBDIR / sq.MANIFEST_NAME)
        .read_text(encoding="utf-8")
        .splitlines()
        if line.strip()
    ]
    assert actions == ["intent", "failed"]
    assert sq.quarantine_report(ws)["entries"] == []


def test_cli_exit_codes(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    ws = tmp_path / "leftover"
    (ws / "office").mkdir(parents=True)
    active = tmp_path / "active"
    active.mkdir()
    db = tmp_path / "sage.db"
    _make_db(db, active)
    _mk(ws, "word", "doc-orphan")
    assert sq.main(["plan", "--database", str(db), "--workspace", str(ws)]) == 0
    assert json.loads(capsys.readouterr().out)["safe_to_delete"] is False
    assert sq.main(["quarantine", "--database", str(db), "--workspace", str(ws)]) == 0
    assert json.loads(capsys.readouterr().out)["dry_run"] is True
    assert (ws / "office" / "word" / "doc-orphan").is_dir()
    assert sq.main(["quarantine", "--database", str(db), "--workspace", str(ws), "--execute"]) == 0
    qid = json.loads(capsys.readouterr().out)["quarantined"][0]["quarantine_id"]
    assert sq.main(["report", "--workspace", str(ws)]) == 0
    assert json.loads(capsys.readouterr().out)["recoverable"] == 1
    assert sq.main(["restore", "--workspace", str(ws), "--quarantine-id", qid]) == 0
    capsys.readouterr()
    assert (ws / "office" / "word" / "doc-orphan" / "doc.bin").is_file()
    # purge without the explicit flag exits 2 and deletes nothing
    sq.quarantine_run(db, ws, dry_run=False)
    live = [e for e in sq.quarantine_report(ws)["entries"] if e["state"] == "done"]
    assert len(live) == 1
    qid2 = live[0]["quarantine_id"]
    assert (
        sq.main(["purge", "--workspace", str(ws), "--quarantine-id", qid2, "--confirm-id", qid2])
        == 2
    )
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "refused"
    assert payload["error"] == "permanent_deletion_not_allowed"
    assert [e for e in sq.quarantine_report(ws)["entries"] if e["state"] == "done"][0][
        "present"
    ] is True
