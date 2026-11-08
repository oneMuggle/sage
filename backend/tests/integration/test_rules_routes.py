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


def _write_text_docx(path: Path, text: str) -> None:
    from docx import Document as DocxDocument

    document = DocxDocument()
    document.add_paragraph(text)
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
    assert client.post("/api/v1/rules/groups/group-missing/rules", json=RULE).status_code == 404
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

    enabled_rejected = client.put(f"/api/v1/rules/rules/{rule['id']}", json={"enabled": None})
    assert enabled_rejected.status_code == 422
    assert "enabled" in enabled_rejected.json()["detail"]

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


def test_audit_runs_regex_rules(client: TestClient, tmp_path: Path) -> None:
    group = client.post("/api/v1/rules/groups", json=GROUP).json()
    rule = client.post(f"/api/v1/rules/groups/{group['id']}/rules", json=RULE).json()
    _write_text_docx(tmp_path / "clean.docx", "这是一段干净的正文。")
    clean = client.post(
        "/api/v1/rules/audit",
        json={
            "workspace_path": str(tmp_path),
            "file_path": str(tmp_path / "clean.docx"),
            "rule_ids": [rule["id"]],
        },
    )
    assert clean.status_code == 200
    assert clean.json()["warning_count"] == 0

    _write_text_docx(tmp_path / "dirty.docx", "这一行包含违禁词：待定。")
    hit = client.post(
        "/api/v1/rules/audit",
        json={
            "workspace_path": str(tmp_path),
            "file_path": str(tmp_path / "dirty.docx"),
            "rule_ids": [rule["id"]],
        },
    )
    assert hit.status_code == 200
    body = hit.json()
    assert body["warning_count"] == 1
    assert body["findings"][0]["rule_id"] == rule["id"]
    assert body["findings"][0]["location"] == "第 1 段"


def test_audit_ai_rule_without_llm_returns_503(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    group = client.post("/api/v1/rules/groups", json=GROUP).json()
    ai_rule = dict(RULE, name="AI 规则", check_mode="ai", pattern=None, ai_prompt="检查术语")
    rule = client.post(f"/api/v1/rules/groups/{group['id']}/rules", json=ai_rule).json()
    _write_text_docx(tmp_path / "doc.docx", "正文")
    from backend.api import rules_routes

    monkeypatch.setattr(rules_routes, "build_llm_client_from_settings", lambda: None)
    response = client.post(
        "/api/v1/rules/audit",
        json={
            "workspace_path": str(tmp_path),
            "file_path": str(tmp_path / "doc.docx"),
            "rule_ids": [rule["id"]],
        },
    )
    assert response.status_code == 503


def test_audit_unknown_rule_returns_404(client: TestClient, tmp_path: Path) -> None:
    _write_text_docx(tmp_path / "doc.docx", "正文")
    response = client.post(
        "/api/v1/rules/audit",
        json={
            "workspace_path": str(tmp_path),
            "file_path": str(tmp_path / "doc.docx"),
            "rule_ids": ["rule-missing"],
        },
    )
    assert response.status_code == 404


def test_audit_dedupes_rule_ids(client: TestClient, tmp_path: Path) -> None:
    group = client.post("/api/v1/rules/groups", json=GROUP).json()
    rule = client.post(f"/api/v1/rules/groups/{group['id']}/rules", json=RULE).json()
    _write_text_docx(tmp_path / "dirty.docx", "这一行包含违禁词：待定。")
    response = client.post(
        "/api/v1/rules/audit",
        json={
            "workspace_path": str(tmp_path),
            "file_path": str(tmp_path / "dirty.docx"),
            "rule_ids": [rule["id"], rule["id"]],
        },
    )
    assert response.status_code == 200
    assert response.json()["warning_count"] == 1


def test_audit_rejects_empty_and_excessive_rule_ids(client: TestClient, tmp_path: Path) -> None:
    _write_text_docx(tmp_path / "doc.docx", "正文")
    payload = {
        "workspace_path": str(tmp_path),
        "file_path": str(tmp_path / "doc.docx"),
    }
    empty = client.post("/api/v1/rules/audit", json=dict(payload, rule_ids=[]))
    assert empty.status_code == 422

    too_many = client.post(
        "/api/v1/rules/audit",
        json=dict(payload, rule_ids=[f"rule-missing-{i}" for i in range(51)]),
    )
    assert too_many.status_code == 422


def test_audit_rejects_absurd_size_cap(client: TestClient, tmp_path: Path) -> None:
    group = client.post("/api/v1/rules/groups", json=GROUP).json()
    rule = client.post(f"/api/v1/rules/groups/{group['id']}/rules", json=RULE).json()
    _write_text_docx(tmp_path / "doc.docx", "正文")
    response = client.post(
        "/api/v1/rules/audit",
        json={
            "workspace_path": str(tmp_path),
            "file_path": str(tmp_path / "doc.docx"),
            "rule_ids": [rule["id"]],
            "max_size_bytes": 10**10,
        },
    )
    assert response.status_code == 422


def test_audit_rejects_oversized_file(client: TestClient, tmp_path: Path) -> None:
    group = client.post("/api/v1/rules/groups", json=GROUP).json()
    rule = client.post(f"/api/v1/rules/groups/{group['id']}/rules", json=RULE).json()
    oversized = tmp_path / "big.docx"
    oversized.write_bytes(b"x" * 2048)
    response = client.post(
        "/api/v1/rules/audit",
        json={
            "workspace_path": str(tmp_path),
            "file_path": str(oversized),
            "rule_ids": [rule["id"]],
            "max_size_bytes": 1024,
        },
    )
    assert response.status_code == 413


def test_check_conflicts_reports_duplicate_regex(client: TestClient) -> None:
    group = client.post("/api/v1/rules/groups", json=GROUP).json()
    first = client.post(f"/api/v1/rules/groups/{group['id']}/rules", json=RULE).json()
    second = client.post(
        f"/api/v1/rules/groups/{group['id']}/rules",
        json=dict(RULE, name="重复待定"),
    ).json()
    response = client.post(
        "/api/v1/rules/check-conflicts",
        json={"rule_ids": [first["id"], second["id"]]},
    )
    assert response.status_code == 200
    conflicts = response.json()["conflicts"]
    assert len(conflicts) == 1
    assert conflicts[0]["rule_ids"] == [first["id"], second["id"]]
    assert conflicts[0]["severity"] == "error"


def test_check_conflicts_unknown_rule_returns_404(client: TestClient) -> None:
    group = client.post("/api/v1/rules/groups", json=GROUP).json()
    rule = client.post(f"/api/v1/rules/groups/{group['id']}/rules", json=RULE).json()
    response = client.post(
        "/api/v1/rules/check-conflicts",
        json={"rule_ids": [rule["id"], "rule-missing"]},
    )
    assert response.status_code == 404


def test_check_conflicts_rejects_invalid_rule_id_lists(client: TestClient) -> None:
    group = client.post("/api/v1/rules/groups", json=GROUP).json()
    rule = client.post(f"/api/v1/rules/groups/{group['id']}/rules", json=RULE).json()

    empty = client.post("/api/v1/rules/check-conflicts", json={"rule_ids": []})
    assert empty.status_code == 422

    duplicated = client.post(
        "/api/v1/rules/check-conflicts",
        json={"rule_ids": [rule["id"], rule["id"]]},
    )
    assert duplicated.status_code == 422

    too_many = client.post(
        "/api/v1/rules/check-conflicts",
        json={"rule_ids": [f"rule-missing-{i}" for i in range(51)]},
    )
    assert too_many.status_code == 422


# ──────────────────────────────────────────────────────────────────────
# Task 7: export / import endpoints
# ──────────────────────────────────────────────────────────────────────


def test_export_returns_pack_for_selected_group(client: TestClient) -> None:
    group = client.post("/api/v1/rules/groups", json=GROUP).json()
    client.post(f"/api/v1/rules/groups/{group['id']}/rules", json=RULE)
    response = client.post(
        "/api/v1/rules/export",
        json={"group_ids": [group["id"]], "name": "我的规则包"},
    )
    assert response.status_code == 200
    pack = response.json()
    assert pack["name"] == "我的规则包"
    assert pack["version"] == "1.0"
    assert pack["exported_by"] == "local"
    assert pack["exported_at"].endswith("+00:00")
    assert len(pack["groups"]) == 1
    assert pack["groups"][0]["rules"][0]["pattern"] == RULE["pattern"]


def test_export_unknown_group_returns_404(client: TestClient) -> None:
    response = client.post(
        "/api/v1/rules/export",
        json={"group_ids": ["group-missing"], "name": "x"},
    )
    assert response.status_code == 404


def test_export_empty_group_ids_returns_422(client: TestClient) -> None:
    response = client.post(
        "/api/v1/rules/export",
        json={"group_ids": [], "name": "x"},
    )
    assert response.status_code == 422


def test_export_dedupes_group_ids(client: TestClient) -> None:
    group = client.post("/api/v1/rules/groups", json=GROUP).json()
    client.post(f"/api/v1/rules/groups/{group['id']}/rules", json=RULE)
    # Send the same id twice — should succeed (deduped to one) not 422.
    response = client.post(
        "/api/v1/rules/export",
        json={"group_ids": [group["id"], group["id"]], "name": "包"},
    )
    assert response.status_code == 200
    pack = response.json()
    assert len(pack["groups"]) == 1
    assert pack["groups"][0]["id"] == group["id"]


def test_export_too_many_group_ids_returns_422(client: TestClient) -> None:
    response = client.post(
        "/api/v1/rules/export",
        json={"group_ids": [f"group-{i}" for i in range(101)], "name": "x"},
    )
    assert response.status_code == 422


def test_import_creates_new_group_and_rules(client: TestClient) -> None:
    pack = {
        "name": "导入包",
        "version": "1.0",
        "exported_at": "2026-11-07T00:00:00+00:00",
        "exported_by": "other-machine",
        "groups": [
            {
                "id": "group-original",
                "name": "导入组",
                "description": "",
                "priority": 0,
                "builtin": False,
                "rules": [
                    {
                        "id": "rule-original",
                        "name": "禁用待定",
                        "type": "terminology",
                        "severity": "warning",
                        "scope": "body",
                        "description": "终稿不得出现占位词",
                        "check_mode": "regex",
                        "pattern": "待定",
                        "ai_prompt": None,
                        "enabled": True,
                        "group_id": "group-original",
                    }
                ],
            }
        ],
    }
    response = client.post("/api/v1/rules/import", json=pack)
    assert response.status_code == 200
    assert response.json() == {"groups": 1, "imported_rules": 1}

    groups = client.get("/api/v1/rules/groups").json()
    imported = [group for group in groups if group["name"] == "导入组"][0]
    assert imported["id"] != "group-original"
    assert imported["rules"][0]["id"] != "rule-original"
    assert imported["rules"][0]["group_id"] == imported["id"]
    assert imported["rules"][0]["description"] == "终稿不得出现占位词"


def test_import_rejects_empty_pack(client: TestClient) -> None:
    response = client.post(
        "/api/v1/rules/import",
        json={
            "name": "空",
            "version": "1.0",
            "exported_at": "2026-11-07T00:00:00+00:00",
            "exported_by": "local",
            "groups": [],
        },
    )
    assert response.status_code == 422


# ──────────────────────────────────────────────────────────────────────
# Final fix round — provider failures, unsafe patterns, group cap
# ──────────────────────────────────────────────────────────────────────


def _pack_with_rules(rules: list) -> dict:
    return {
        "name": "导入包",
        "version": "1.0",
        "exported_at": "2026-11-07T00:00:00+00:00",
        "exported_by": "other-machine",
        "groups": [
            {
                "id": "group-original",
                "name": "导入组",
                "description": "",
                "priority": 0,
                "builtin": False,
                "rules": rules,
            }
        ],
    }


def test_audit_ai_provider_failure_returns_502_json(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    group = client.post("/api/v1/rules/groups", json=GROUP).json()
    ai_rule = dict(RULE, name="AI 规则", check_mode="ai", pattern=None, ai_prompt="检查术语")
    rule = client.post(f"/api/v1/rules/groups/{group['id']}/rules", json=ai_rule).json()
    _write_text_docx(tmp_path / "doc.docx", "正文")

    class _BrokenClient:
        async def complete(self, prompt: str) -> str:
            raise RuntimeError("provider down")

    from backend.api import rules_routes

    monkeypatch.setattr(rules_routes, "build_llm_client_from_settings", lambda: _BrokenClient())
    response = client.post(
        "/api/v1/rules/audit",
        json={
            "workspace_path": str(tmp_path),
            "file_path": str(tmp_path / "doc.docx"),
            "rule_ids": [rule["id"]],
        },
    )
    assert response.status_code == 502, response.text
    body = response.json()
    assert body["error_type"] == "OfficeLLMError"
    assert body["message"] == "LLM 调用失败，请稍后重试"


def test_create_rejects_oversized_pattern(client: TestClient) -> None:
    group = client.post("/api/v1/rules/groups", json=GROUP).json()
    response = client.post(
        f"/api/v1/rules/groups/{group['id']}/rules",
        json=dict(RULE, pattern="a" * 1001),
    )
    assert response.status_code == 422, response.text


def test_update_and_create_reject_nested_quantifier(client: TestClient) -> None:
    group = client.post("/api/v1/rules/groups", json=GROUP).json()

    create_rejected = client.post(
        f"/api/v1/rules/groups/{group['id']}/rules",
        json=dict(RULE, pattern="^(a+)+$"),
    )
    assert create_rejected.status_code == 422, create_rejected.text

    rule = client.post(f"/api/v1/rules/groups/{group['id']}/rules", json=RULE).json()
    update_rejected = client.put(f"/api/v1/rules/rules/{rule['id']}", json={"pattern": "^(a+)+$"})
    assert update_rejected.status_code == 422, update_rejected.text


def test_import_rejects_nested_quantifier_pattern(client: TestClient) -> None:
    rule = {
        "id": "rule-original",
        "name": "危险正则",
        "type": "custom",
        "severity": "warning",
        "scope": "body",
        "description": "",
        "check_mode": "regex",
        "pattern": "^(a+)+$",
        "ai_prompt": None,
        "enabled": True,
        "group_id": "group-original",
    }
    response = client.post("/api/v1/rules/import", json=_pack_with_rules([rule]))
    assert response.status_code == 422, response.text


def test_import_rejects_too_many_groups(client: TestClient) -> None:
    groups = []
    for index in range(101):
        groups.append(
            {
                "id": f"group-{index}",
                "name": f"组 {index}",
                "description": "",
                "priority": 0,
                "builtin": False,
                "rules": [
                    {
                        "id": f"rule-{index}",
                        "name": "规则",
                        "type": "custom",
                        "severity": "warning",
                        "scope": "body",
                        "description": "",
                        "check_mode": "regex",
                        "pattern": "x",
                        "ai_prompt": None,
                        "enabled": True,
                        "group_id": f"group-{index}",
                    }
                ],
            }
        )
    payload = {
        "name": "过大",
        "version": "1.0",
        "exported_at": "2026-11-07T00:00:00+00:00",
        "exported_by": "local",
        "groups": groups,
    }
    response = client.post("/api/v1/rules/import", json=payload)
    assert response.status_code == 422, response.text
    assert "分组" in response.json()["message"]
