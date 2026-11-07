from __future__ import annotations

import os
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.data.database import Database

GROUP = {"name": "Style", "description": "样式规则", "priority": 10}
RULE = {
    "name": "禁用占位词",
    "type": "terminology",
    "severity": "warning",
    "scope": "body",
    "description": "终稿中不应出现「待定」等占位词",
    "check_mode": "regex",
    "pattern": "待定",
    "enabled": True,
}


@pytest.fixture()
def db(monkeypatch: pytest.MonkeyPatch) -> Database:
    database = Database(":memory:")
    database.init_db()  # base DDL + every migration, including v17
    from backend.api import rules_routes

    monkeypatch.setattr(rules_routes, "_db", lambda: database)
    return database


@pytest.fixture()
def client(db: Database) -> TestClient:
    from backend.api.office_routes import register_office_exception_handlers
    from backend.api.rules_routes import router

    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    register_office_exception_handlers(app)
    return TestClient(app)


def _write_docx(path: Path) -> None:
    from docx import Document as DocxDocument

    document = DocxDocument()
    document.add_heading("第一章 总则", level=1)
    document.add_paragraph("正文应当使用宋体小四号。")
    document.save(str(path))


def test_group_crud_roundtrip(client: TestClient) -> None:
    created = client.post("/api/v1/rules/groups", json=GROUP)
    assert created.status_code == 201
    group = created.json()
    assert group["id"].startswith("group-")
    assert group["rules"] == []
    assert group["priority"] == 10

    listed = client.get("/api/v1/rules/groups")
    assert listed.status_code == 200
    assert [item["id"] for item in listed.json()] == [group["id"]]

    updated = client.put(f"/api/v1/rules/groups/{group['id']}", json={"name": "Style v2"})
    assert updated.status_code == 200
    assert updated.json()["name"] == "Style v2"
    assert updated.json()["description"] == GROUP["description"]

    assert client.delete(f"/api/v1/rules/groups/{group['id']}").json() == {
        "deleted": True,
        "id": group["id"],
    }
    assert client.get("/api/v1/rules/groups").json() == []


def test_rule_crud_roundtrip_persists_description(client: TestClient) -> None:
    group = client.post("/api/v1/rules/groups", json=GROUP).json()
    created = client.post(f"/api/v1/rules/groups/{group['id']}/rules", json=RULE)
    assert created.status_code == 201
    rule = created.json()
    assert rule["id"].startswith("rule-")
    assert rule["group_id"] == group["id"]
    assert rule["description"] == RULE["description"]
    assert rule["check_mode"] == "regex"

    listed = client.get("/api/v1/rules/groups").json()
    assert [item["id"] for item in listed[0]["rules"]] == [rule["id"]]

    updated = client.put(
        f"/api/v1/rules/rules/{rule['id']}", json={"severity": "error", "enabled": False}
    )
    assert updated.status_code == 200
    assert updated.json()["severity"] == "error"
    assert updated.json()["enabled"] is False
    assert updated.json()["description"] == RULE["description"]

    assert client.delete(f"/api/v1/rules/rules/{rule['id']}").json() == {
        "deleted": True,
        "id": rule["id"],
    }
    assert client.get("/api/v1/rules/groups").json()[0]["rules"] == []


def test_unknown_ids_return_404(client: TestClient) -> None:
    assert client.put("/api/v1/rules/groups/group-missing", json={"name": "x"}).status_code == 404
    assert client.delete("/api/v1/rules/groups/group-missing").status_code == 404
    assert (
        client.post("/api/v1/rules/groups/group-missing/rules", json=RULE).status_code == 404
    )
    assert client.put("/api/v1/rules/rules/rule-missing", json={"name": "x"}).status_code == 404
    assert client.delete("/api/v1/rules/rules/rule-missing").status_code == 404


def test_delete_group_cascades_rules(client: TestClient, db: Database) -> None:
    group = client.post("/api/v1/rules/groups", json=GROUP).json()
    client.post(f"/api/v1/rules/groups/{group['id']}/rules", json=RULE)
    # Wire contract: deletes return 200 + JSON body (never 204 — the Electron
    # generic relay calls response.json() unconditionally).
    assert client.delete(f"/api/v1/rules/groups/{group['id']}").status_code == 200
    remaining = db.get_connection().execute("SELECT COUNT(*) FROM office_rules").fetchone()
    assert remaining[0] == 0


def test_extract_maps_word_specs_to_ai_rules(client: TestClient, tmp_path: Path) -> None:
    _write_docx(tmp_path / "spec.docx")
    response = client.post(
        "/api/v1/rules/extract",
        json={"workspace_path": str(tmp_path), "file_path": str(tmp_path / "spec.docx")},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["warnings"] == []
    assert len(payload["rules"]) >= 1
    for rule in payload["rules"]:
        assert rule["check_mode"] == "ai"
        assert rule["group_id"] == ""
        assert rule["ai_prompt"]
        assert rule["type"] in {"format", "terminology", "citation", "structure", "custom"}


def test_extract_rejects_path_outside_workspace(client: TestClient, tmp_path: Path) -> None:
    response = client.post(
        "/api/v1/rules/extract",
        json={"workspace_path": str(tmp_path), "file_path": "../escape.docx"},
    )
    assert response.status_code == 400


def test_extract_rejects_oversized_file(client: TestClient, tmp_path: Path) -> None:
    oversized = tmp_path / "big.docx"
    oversized.write_bytes(b"x" * 2048)
    response = client.post(
        "/api/v1/rules/extract",
        json={
            "workspace_path": str(tmp_path),
            "file_path": str(oversized),
            "max_size_bytes": 1024,
        },
    )
    assert response.status_code == 413


def test_update_rule_rejects_explicit_null_on_required_fields(client: TestClient) -> None:
    group = client.post("/api/v1/rules/groups", json=GROUP).json()
    rule = client.post(f"/api/v1/rules/groups/{group['id']}/rules", json=RULE).json()

    rejected = client.put(f"/api/v1/rules/rules/{rule['id']}", json={"name": None})
    assert rejected.status_code == 422
    assert "name" in rejected.json()["detail"]

    # pattern is NULLable — an explicit null is accepted.
    nullable = client.put(f"/api/v1/rules/rules/{rule['id']}", json={"pattern": None})
    assert nullable.status_code == 200
    assert nullable.json()["pattern"] is None


def test_extract_rejects_symlink_escape(client: TestClient, tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outside = tmp_path / "outside.docx"
    _write_docx(outside)
    link = workspace / "linked.docx"
    try:
        os.symlink(outside, link)
    except OSError:
        pytest.skip("symlink creation not supported on this platform")

    response = client.post(
        "/api/v1/rules/extract",
        json={"workspace_path": str(workspace), "file_path": str(link)},
    )
    assert response.status_code == 400
