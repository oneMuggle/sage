"""Integration tests for the Office staging quarantine API routes.

Covers the four endpoints added for application integration:

- GET  /api/v1/office/quarantine/plan
- POST /api/v1/office/quarantine/run
- GET  /api/v1/office/quarantine/report
- POST /api/v1/office/quarantine/{quarantine_id}/restore

Tests exercise the real FastAPI stack via ``TestClient`` (matching
``test_office_phase2_routes.py``) so the route guards, the legacy error
envelope (``error_contract.error_json``) and the response models are all
under test — not just the quarantine module, which has its own unit suite
in ``backend/tests/unit/office/test_staging_quarantine.py``.

Document ids are randomized per test on purpose: the shared test database is
a full application schema whose text tables are scanned for id tokens, so a
generic id such as ``doc-orphan`` can legitimately collide with unrelated
fixture data and be classified ``referenced``. Unique ids keep the assertion
about *this* candidate's evidence.

Safety contract asserted here (must never regress):

1. ``read_only`` / ``safe_to_delete`` stay True / False on every plan.
2. ``dry_run`` defaults to True and moves nothing.
3. An active Electron import lease is retained even through the API.
4. No purge route exists — permanent deletion stays CLI-only behind the
   triple gate (``--allow-permanent-deletion`` + ``--confirm-id`` + retention).
5. Restore returns byte-identical content and is not repeatable.
"""

from __future__ import annotations

import json
import os
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Optional

import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from backend.api import office_quarantine_routes as routes
from backend.data.database import get_database
from backend.main import app
from backend.office.staging_quarantine import STAGING_MARKER

pytestmark = pytest.mark.integration

PLAN_URL = "/api/v1/office/quarantine/plan"
RUN_URL = "/api/v1/office/quarantine/run"
REPORT_URL = "/api/v1/office/quarantine/report"

#: Minimal office_documents shape used by the reference scan. Created only if
#: the shared test database does not already provide it (init_db usually does).
SCHEMA = """
CREATE TABLE IF NOT EXISTS office_documents (
    id TEXT PRIMARY KEY, workspace_path TEXT NOT NULL, doc_type TEXT NOT NULL,
    original_filename TEXT, generated_filename TEXT NOT NULL, status TEXT NOT NULL,
    created_at INTEGER NOT NULL, updated_at INTEGER NOT NULL, metadata TEXT,
    derived_from TEXT, archived_at INTEGER);
"""


# ──────────────────────────────────────────────────────────────────────
# Fixtures / helpers
# ──────────────────────────────────────────────────────────────────────


@pytest.fixture()
def client() -> TestClient:
    """Authenticated client exercising the real FastAPI route stack."""
    return TestClient(
        app,
        headers={"X-Sage-Local-Authorization": "Bearer test-local-auth-token"},
    )


@pytest.fixture()
def env(tmp_path: Path):
    """Leftover workspace (never registered) + per-test unique document ids.

    ``referenced`` appears in ``office_documents.id`` so the plan must retain
    it; ``orphan`` has no evidence anywhere and is the only candidate eligible
    for quarantine; ``sheet`` is an excel-type orphan used by the doc-type
    filter test.
    """
    suffix = uuid.uuid4().hex[:8]
    ids = {
        "orphan": f"qa-orphan-{suffix}",
        "referenced": f"qa-ref-{suffix}",
        "sheet": f"qa-sheet-{suffix}",
    }
    ws = tmp_path / "leftover"
    (ws / "office").mkdir(parents=True)
    # The referenced id is registered against a DIFFERENT workspace on purpose.
    # ``office_documents.workspace_path`` doubles as the workspace registry:
    # registering the scanned workspace would retain *everything* in it (a
    # safety rule the module enforces), which is not what these tests assert.
    # Id matching is global, so the reference still counts from another ws.
    registered_ws = tmp_path / "registered"
    (registered_ws / "office").mkdir(parents=True)
    _register_document(Path(get_database().db_path), ids["referenced"], registered_ws)
    _mk(ws, "word", ids["referenced"])
    _mk(ws, "word", ids["orphan"])
    return ws, ids


def _register_document(database: Path, doc_id: str, workspace: Path) -> None:
    conn = sqlite3.connect(str(database))
    try:
        conn.executescript(SCHEMA)
        now = int(time.time() * 1000)
        conn.execute(
            "INSERT OR REPLACE INTO office_documents "
            "(id, workspace_path, doc_type, original_filename, generated_filename,"
            " status, created_at, updated_at, metadata, derived_from, archived_at)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (
                doc_id,
                str(workspace),
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
    """Create a managed staging directory older than the quiet window."""
    directory = ws / "office" / doc_type / doc_id
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / name
    target.write_bytes(content)
    stamp = time.time() - age_hours * 3600
    os.utime(str(target), (stamp, stamp))
    os.utime(str(directory), (stamp, stamp))
    return directory


def _write_import_marker(directory: Path, doc_id: str, *, owner_pid: Optional[int] = None) -> None:
    """Write the Electron staging sentinel (``.sage-import-v1.json``)."""
    evidence = {
        "version": 1,
        "token": doc_id,
        "filename": doc_id + ".docx",
        "createdAt": int(time.time() * 1000),
        "ownerPid": owner_pid or os.getpid(),
    }
    (directory / STAGING_MARKER).write_text(json.dumps(evidence), encoding="utf-8")


def _statuses(payload: dict) -> dict:
    return {c["document_id"]: c["status"] for c in payload["candidates"]}


def _quarantine_root(ws: Path) -> Path:
    return ws / "office" / ".quarantine"


def _restore_url(quarantine_id: str) -> str:
    return f"/api/v1/office/quarantine/{quarantine_id}/restore"


# ──────────────────────────────────────────────────────────────────────
# GET /plan — read-only classification + guards
# ──────────────────────────────────────────────────────────────────────


def test_plan_is_read_only_and_classifies_candidates(client: TestClient, env) -> None:
    ws, ids = env

    response = client.get(PLAN_URL, params={"workspace_path": str(ws)})

    assert response.status_code == 200
    payload = response.json()
    assert payload["read_only"] is True
    assert payload["safe_to_delete"] is False
    assert payload["mode"] == "quarantine"
    assert payload["candidates_total"] == 2
    assert payload["candidates_truncated"] is False
    assert _statuses(payload) == {
        ids["referenced"]: "referenced",
        ids["orphan"]: "no_reference_found",
    }
    assert payload["summary"]["no_reference_found"] == 1
    assert Path(payload["quarantine_root"]).name == ".quarantine"
    # Nothing moved: the plan endpoint must not create the quarantine dir.
    assert not _quarantine_root(ws).exists()
    assert (ws / "office" / "word" / ids["orphan"] / "doc.bin").is_file()


def test_plan_surfaces_import_lease_model(client: TestClient, env) -> None:
    """The sentinel verdict must reach the wire, not stay inside the module."""
    ws, ids = env
    orphan = ws / "office" / "word" / ids["orphan"]
    _write_import_marker(orphan, ids["orphan"])

    payload = client.get(PLAN_URL, params={"workspace_path": str(ws)}).json()

    entry = {c["document_id"]: c for c in payload["candidates"]}[ids["orphan"]]
    assert entry["status"] == "referenced"
    assert entry["reason"] == "import_in_progress_or_pending_review"
    assert entry["import_lease"]["state"] == "active"
    assert entry["import_lease"]["marker_present"] is True
    assert "import_lease_active:active" in entry["references"]


def test_plan_rejects_relative_workspace_path(client: TestClient) -> None:
    response = client.get(PLAN_URL, params={"workspace_path": "relative/ws"})

    assert response.status_code == 400
    body = response.json()
    assert body["ok"] is False
    assert body["error"] == "workspace_path_must_be_absolute"
    assert body["message"]


def test_plan_rejects_missing_workspace(client: TestClient, tmp_path: Path) -> None:
    response = client.get(PLAN_URL, params={"workspace_path": str(tmp_path / "nope")})

    assert response.status_code == 404
    assert response.json()["error"] == "workspace_not_found"


def test_plan_requires_workspace_path(client: TestClient) -> None:
    """FastAPI validation: the query parameter is mandatory."""
    assert client.get(PLAN_URL).status_code == 422


def test_plan_tolerates_database_without_office_tables(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A degraded schema must degrade the verdict, never 500 the endpoint."""
    from backend.data.database import Database

    ws = tmp_path / "ws"
    (ws / "office").mkdir(parents=True)
    _mk(ws, "word", f"qa-degraded-{uuid.uuid4().hex[:8]}")
    empty_db = tmp_path / "empty.db"
    sqlite3.connect(str(empty_db)).close()
    monkeypatch.setattr(routes, "get_database", lambda: Database(db_path=str(empty_db)))

    response = client.get(PLAN_URL, params={"workspace_path": str(ws)})

    assert response.status_code == 200
    payload = response.json()
    assert payload["db_scan_status"] == "incomplete"
    # Incomplete evidence ⇒ conservative retention, never "safe to remove".
    assert set(_statuses(payload).values()) == {"unknown"}
    assert payload["safe_to_delete"] is False


def test_plan_retains_everything_in_a_registered_workspace(
    client: TestClient, tmp_path: Path
) -> None:
    """``office_documents.workspace_path`` is the workspace registry.

    A workspace still registered in the database is in active use: every
    staging directory inside it must be retained, even one with no other
    evidence. This is the module's blanket-safety rule, asserted through the
    API so a route-layer regression cannot quietly drop it.
    """
    registered = tmp_path / "registered"
    (registered / "office").mkdir(parents=True)
    suffix = uuid.uuid4().hex[:8]
    orphan_id = f"qa-registered-orphan-{suffix}"
    _register_document(Path(get_database().db_path), f"qa-registered-doc-{suffix}", registered)
    _mk(registered, "word", orphan_id)

    payload = client.get(PLAN_URL, params={"workspace_path": str(registered)}).json()

    assert payload["safe_to_delete"] is False
    assert set(_statuses(payload).values()) == {"referenced"}
    run = client.post(RUN_URL, json={"workspace_path": str(registered), "dry_run": False}).json()
    assert run["planned"] == []
    assert run["quarantined"] == []
    assert (registered / "office" / "word" / orphan_id / "doc.bin").is_file()


def test_plan_truncates_long_candidate_lists(
    client: TestClient, env, monkeypatch: pytest.MonkeyPatch
) -> None:
    ws, _ids = env
    monkeypatch.setattr(routes, "MAX_RESPONSE_CANDIDATES", 1)

    payload = client.get(PLAN_URL, params={"workspace_path": str(ws)}).json()

    assert payload["candidates_total"] == 2
    assert len(payload["candidates"]) == 1
    assert payload["candidates_truncated"] is True


# ──────────────────────────────────────────────────────────────────────
# POST /run — dry run by default, reversible moves only
# ──────────────────────────────────────────────────────────────────────


def test_run_defaults_to_dry_run_and_moves_nothing(client: TestClient, env) -> None:
    ws, ids = env

    response = client.post(RUN_URL, json={"workspace_path": str(ws)})

    assert response.status_code == 200
    payload = response.json()
    assert payload["dry_run"] is True
    assert payload["safe_to_delete"] is False
    assert [item["document_id"] for item in payload["planned"]] == [ids["orphan"]]
    assert payload["quarantined"] == []
    assert (ws / "office" / "word" / ids["orphan"] / "doc.bin").is_file()


def test_run_dry_run_false_quarantines_only_unreferenced(client: TestClient, env) -> None:
    ws, ids = env

    payload = client.post(RUN_URL, json={"workspace_path": str(ws), "dry_run": False}).json()

    assert payload["dry_run"] is False
    quarantined = payload["quarantined"]
    assert len(quarantined) == 1
    assert quarantined[0]["document_id"] == ids["orphan"]
    assert quarantined[0]["status"] == "quarantined"
    assert quarantined[0]["source_removed"] is True
    # Referenced candidate stays put.
    assert (ws / "office" / "word" / ids["referenced"] / "doc.bin").is_file()
    # Source is gone, copy is inside the quarantine dir.
    assert not (ws / "office" / "word" / ids["orphan"]).exists()
    assert _quarantine_root(ws).is_dir()


def test_run_retains_candidate_with_active_import_lease(client: TestClient, env) -> None:
    """Even with dry_run=False an in-flight import must never be moved."""
    ws, ids = env
    orphan = ws / "office" / "word" / ids["orphan"]
    _write_import_marker(orphan, ids["orphan"])

    payload = client.post(RUN_URL, json={"workspace_path": str(ws), "dry_run": False}).json()

    assert payload["planned"] == []
    assert payload["quarantined"] == []
    assert (orphan / "doc.bin").is_file()
    retained = {item["document_id"]: item for item in payload["retained"]}
    assert retained[ids["orphan"]]["status"] == "referenced"
    assert retained[ids["orphan"]]["reason"] == "import_in_progress_or_pending_review"


def test_run_honours_doc_type_filter(client: TestClient, env) -> None:
    ws, ids = env
    _mk(ws, "excel", ids["sheet"], content=b"xlsx-bytes")

    payload = client.post(
        RUN_URL, json={"workspace_path": str(ws), "dry_run": False, "doc_types": ["excel"]}
    ).json()

    assert [item["document_id"] for item in payload["quarantined"]] == [ids["sheet"]]
    assert (ws / "office" / "word" / ids["orphan"] / "doc.bin").is_file()


def test_run_rejects_unknown_doc_type(client: TestClient, env) -> None:
    """Fail loud: a silently ignored filter would quarantine more than asked."""
    ws, ids = env

    response = client.post(RUN_URL, json={"workspace_path": str(ws), "doc_types": ["zip"]})

    assert response.status_code == 400
    assert response.json()["error"] == "invalid_doc_type"
    assert (ws / "office" / "word" / ids["orphan"] / "doc.bin").is_file()


def test_run_rejects_unknown_fields(client: TestClient, env) -> None:
    """``extra="forbid"``: an imagined safety switch must 422, not be ignored."""
    ws, _ids = env

    response = client.post(
        RUN_URL, json={"workspace_path": str(ws), "allow_permanent_deletion": True}
    )

    assert response.status_code == 422


def test_run_validates_bounds(client: TestClient, env) -> None:
    ws, _ids = env

    response = client.post(RUN_URL, json={"workspace_path": str(ws), "retention_days": 0})

    assert response.status_code == 422


def test_run_rejects_relative_workspace_path(client: TestClient) -> None:
    response = client.post(RUN_URL, json={"workspace_path": "relative/ws"})

    assert response.status_code == 400
    assert response.json()["error"] == "workspace_path_must_be_absolute"


# ──────────────────────────────────────────────────────────────────────
# GET /report + POST /restore — the recovery path
# ──────────────────────────────────────────────────────────────────────


def _run_and_get_quarantine_id(client: TestClient, ws: Path) -> str:
    payload = client.post(RUN_URL, json={"workspace_path": str(ws), "dry_run": False}).json()
    return str(payload["quarantined"][0]["quarantine_id"])


def test_report_lists_recoverable_entries(client: TestClient, env) -> None:
    ws, ids = env
    qid = _run_and_get_quarantine_id(client, ws)

    response = client.get(REPORT_URL, params={"workspace_path": str(ws)})

    assert response.status_code == 200
    payload = response.json()
    assert payload["automatic_deletion"] is False
    assert payload["purge_requires_human_confirmation"] is True
    assert payload["total_entries"] == 1
    assert payload["recoverable"] == 1
    entry = payload["entries"][0]
    assert entry["quarantine_id"] == qid
    assert entry["document_id"] == ids["orphan"]
    assert entry["present"] is True
    assert entry["recoverable"] is True
    assert entry["eligible_for_purge_after"]


def test_report_on_empty_quarantine(client: TestClient, env) -> None:
    ws, _ids = env

    payload = client.get(REPORT_URL, params={"workspace_path": str(ws)}).json()

    assert payload["total_entries"] == 0
    assert payload["entries"] == []
    assert payload["automatic_deletion"] is False


def test_report_rejects_missing_workspace(client: TestClient, tmp_path: Path) -> None:
    response = client.get(REPORT_URL, params={"workspace_path": str(tmp_path / "nope")})

    assert response.status_code == 404
    assert response.json()["error"] == "workspace_not_found"


def test_restore_returns_identical_bytes_and_is_not_repeatable(client: TestClient, env) -> None:
    ws, ids = env
    source = ws / "office" / "word" / ids["orphan"] / "doc.bin"
    original = source.read_bytes()
    qid = _run_and_get_quarantine_id(client, ws)

    response = client.post(_restore_url(qid), json={"workspace_path": str(ws)})

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "restored"
    assert payload["quarantine_id"] == qid
    # The module records the resolved source path; assert on the file itself
    # rather than on string casing (Windows drive letters can differ).
    assert source.is_file()
    assert source.read_bytes() == original
    assert Path(payload["restored_to"]).name == ids["orphan"]

    # Second restore must be refused (the entry is no longer in state "done").
    again = client.post(_restore_url(qid), json={"workspace_path": str(ws)}).json()
    assert again["status"] == "error"
    assert again["error"].startswith("not_restorable")


def test_restore_refuses_occupied_original_path(client: TestClient, env) -> None:
    ws, ids = env
    qid = _run_and_get_quarantine_id(client, ws)
    occupied = ws / "office" / "word" / ids["orphan"]
    occupied.mkdir(parents=True)
    (occupied / "someone-elses.docx").write_bytes(b"keep me")

    payload = client.post(_restore_url(qid), json={"workspace_path": str(ws)}).json()

    assert payload["status"] == "error"
    assert payload["error"] == "original_path_occupied"
    assert (occupied / "someone-elses.docx").read_bytes() == b"keep me"


def test_restore_unknown_id_is_a_business_error(client: TestClient, env) -> None:
    ws, _ids = env

    response = client.post(
        _restore_url("20260101T000000Z-word-nope-1-abcdef01"),
        json={"workspace_path": str(ws)},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "error"
    assert payload["error"] == "unknown_quarantine_id"


def test_restore_rejects_malformed_quarantine_id(client: TestClient, env) -> None:
    """Charset validation happens before any manifest / disk access."""
    ws, _ids = env

    response = client.post(_restore_url("bad id!"), json={"workspace_path": str(ws)})

    assert response.status_code == 400
    assert response.json()["error"] == "invalid_quarantine_id"


def test_restore_rejects_path_traversal_id(client: TestClient, env) -> None:
    """An id that decodes to a path separator must never reach the filesystem.

    Starlette decodes ``%2F`` before route matching, so the request never
    reaches the handler and answers 404; a literal separator that does match
    is refused by the charset guard with 400. Both are acceptable: neither
    touches disk.
    """
    ws, _ids = env

    encoded = client.post(_restore_url("..%2F..%2Fetc"), json={"workspace_path": str(ws)})
    assert encoded.status_code in (400, 404)

    literal = client.post(_restore_url(".."), json={"workspace_path": str(ws)})
    assert literal.status_code in (400, 404)


def test_restore_rejects_relative_workspace_path(client: TestClient) -> None:
    response = client.post(
        _restore_url("20260101T000000Z-word-doc-1-abcdef01"),
        json={"workspace_path": "relative/ws"},
    )

    assert response.status_code == 400
    assert response.json()["error"] == "workspace_path_must_be_absolute"


# ──────────────────────────────────────────────────────────────────────
# Route-surface contract
# ──────────────────────────────────────────────────────────────────────


def _iter_effective_routes(routes, prefix=""):
    """Flatten ``app.routes``, unwrapping FastAPI's lazy ``_IncludedRouter``.

    Mirrors ``backend/tests/api/test_router_registration.py``: without the
    unwrap, routers added via ``include_router`` never appear as APIRoute.
    """
    for route in routes:
        if type(route).__name__ == "_IncludedRouter":
            context = getattr(route, "include_context", None)
            sub_prefix = (getattr(context, "prefix", "") or "") if context is not None else ""
            sub_router = getattr(route, "original_router", None)
            if sub_router is not None:
                yield from _iter_effective_routes(sub_router.routes, prefix + sub_prefix)
        else:
            yield route, prefix


def test_no_purge_route_is_exposed() -> None:
    """Permanent deletion must stay CLI-only (triple gate), never an endpoint."""
    paths = [
        (tuple(sorted(route.methods or [])), prefix + route.path)
        for route, prefix in _iter_effective_routes(app.routes)
        if isinstance(route, APIRoute)
    ]

    quarantine_routes = [path for _methods, path in paths if "/office/quarantine" in path]
    assert quarantine_routes, "隔离区路由未注册"
    assert not [path for path in quarantine_routes if "purge" in path.lower()]
    assert not [
        path for path in quarantine_routes if "delete" in path.lower() or "remove" in path.lower()
    ]
    # DELETE must not be an allowed method on any quarantine route.
    assert not [
        (methods, path)
        for methods, path in paths
        if "/office/quarantine" in path and "DELETE" in methods
    ]
