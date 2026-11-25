"""Integration tests for the rule extraction draft / commit / refine endpoints.

Split out from test_rules_routes.py (architecture line gate): these cover the
draft-review workflow — extraction to a non-persisted draft, batch commit,
and AI refine action validation.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.data.database import Database

GROUP = {"name": "Style", "description": "样式规则", "priority": 10}


@pytest.fixture()
def db(monkeypatch: pytest.MonkeyPatch) -> Database:
    database = Database(":memory:")
    database.init_db()
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


def test_extract_draft_returns_structured_rules_without_persisting(
    client: TestClient, db: Database, tmp_path: Path
) -> None:
    _write_docx(tmp_path / "spec.docx")
    response = client.post(
        "/api/v1/rules/extract/draft",
        json={"workspace_path": str(tmp_path), "file_path": str(tmp_path / "spec.docx")},
    )
    assert response.status_code == 200
    payload = response.json()
    assert len(payload["rules"]) >= 1
    for item in payload["rules"]:
        assert item["temp_id"].startswith("draft_")
        assert item["kind"]  # structured kind preserved
        assert isinstance(item["params"], dict)
        assert 0.0 <= item["confidence"] <= 1.0
        assert item["suggested_check_mode"] == "ai"
        assert item["suggested_ai_prompt"]
    # Draft extraction must not write to the database.
    assert db.get_connection().execute("SELECT COUNT(*) FROM office_rules").fetchone()[0] == 0
    assert db.get_connection().execute("SELECT COUNT(*) FROM office_rule_groups").fetchone()[0] == 0


def test_commit_persists_group_and_extraction_metadata(client: TestClient, db: Database) -> None:
    body = {
        "group_name": "论文格式规范 · 抽取的规则",
        "rules": [
            {
                "name": "正文字体",
                "type": "format",
                "severity": "warning",
                "scope": "body",
                "description": "正文应使用宋体小四",
                "check_mode": "ai",
                "ai_prompt": "检查正文字体是否为宋体小四",
                "enabled": True,
                "structured_params": {"cjk_font": "宋体", "size_pt": 12},
                "confidence": 0.95,
                "source_excerpt": "模板统计 156/164 段",
            },
            {
                "name": "行间距",
                "type": "format",
                "severity": "warning",
                "scope": "body",
                "check_mode": "ai",
                "ai_prompt": "检查行间距是否为 1.5 倍",
                "enabled": True,
                "structured_params": {"line_spacing": "multiple_1.5"},
                "confidence": 0.72,
            },
        ],
    }
    response = client.post("/api/v1/rules/extract/commit", json=body)
    assert response.status_code == 201
    result = response.json()
    assert result["rules_created"] == 2
    assert result["group_id"].startswith("group-")

    groups = client.get("/api/v1/rules/groups").json()
    assert len(groups) == 1
    assert groups[0]["name"] == body["group_name"]
    rules = groups[0]["rules"]
    assert len(rules) == 2
    by_name = {rule["name"]: rule for rule in rules}
    assert by_name["正文字体"]["structured_params"] == {"cjk_font": "宋体", "size_pt": 12}
    assert by_name["正文字体"]["confidence"] == 0.95
    assert by_name["正文字体"]["source_excerpt"] == "模板统计 156/164 段"
    assert by_name["行间距"]["confidence"] == 0.72
    assert by_name["行间距"]["source_excerpt"] is None


def test_commit_appends_to_existing_group(client: TestClient) -> None:
    group = client.post("/api/v1/rules/groups", json=GROUP).json()
    response = client.post(
        "/api/v1/rules/extract/commit",
        json={
            "group_name": "ignored",
            "target_group_id": group["id"],
            "rules": [
                {
                    "name": "页边距",
                    "type": "format",
                    "severity": "warning",
                    "scope": "full",
                    "check_mode": "ai",
                    "ai_prompt": "检查页边距",
                }
            ],
        },
    )
    assert response.status_code == 201
    assert response.json()["group_id"] == group["id"]
    groups = client.get("/api/v1/rules/groups").json()
    assert len(groups) == 1
    assert [rule["name"] for rule in groups[0]["rules"]] == ["页边距"]


def test_commit_rejects_unknown_target_group(client: TestClient) -> None:
    response = client.post(
        "/api/v1/rules/extract/commit",
        json={"group_name": "x", "target_group_id": "group-missing", "rules": []},
    )
    assert response.status_code == 404


def test_commit_rejects_catastrophic_regex_pattern(client: TestClient) -> None:
    response = client.post(
        "/api/v1/rules/extract/commit",
        json={
            "group_name": "x",
            "rules": [
                {
                    "name": "坏规则",
                    "type": "format",
                    "severity": "warning",
                    "scope": "full",
                    "check_mode": "regex",
                    "pattern": "(a+)+",
                }
            ],
        },
    )
    assert response.status_code == 422


def test_commit_rejects_overlong_pattern(client: TestClient) -> None:
    response = client.post(
        "/api/v1/rules/extract/commit",
        json={
            "group_name": "x",
            "rules": [
                {
                    "name": "坏规则",
                    "type": "format",
                    "severity": "warning",
                    "scope": "full",
                    "check_mode": "regex",
                    "pattern": "x" * 2000,
                }
            ],
        },
    )
    assert response.status_code == 422


def test_commit_rejects_out_of_range_confidence(client: TestClient) -> None:
    response = client.post(
        "/api/v1/rules/extract/commit",
        json={
            "group_name": "x",
            "rules": [
                {
                    "name": "坏规则",
                    "type": "format",
                    "severity": "warning",
                    "scope": "full",
                    "check_mode": "ai",
                    "confidence": 5.0,
                }
            ],
        },
    )
    assert response.status_code == 422


def test_refine_requires_configured_llm(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from backend.api import rules_routes

    monkeypatch.setattr(rules_routes, "build_llm_client_from_settings", lambda: None)
    response = client.post(
        "/api/v1/rules/refine",
        json={
            "instruction": "加上参考文献格式",
            "rules": [{"temp_id": "draft_0", "name": "正文字体"}],
        },
    )
    assert response.status_code == 503


def test_refine_returns_validated_actions(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    import json as jsonlib

    from backend.api import rules_routes

    class FakeClient:
        async def complete(self, prompt: str) -> str:  # noqa: ARG002
            return jsonlib.dumps(
                [
                    {
                        "type": "modify",
                        "temp_id": "draft_0",
                        "patch": {"params": {"size_pt": 14}},
                        "explanation": "字号改为四号",
                    },
                    {"type": "modify", "temp_id": "ghost", "patch": {"name": "x"}},
                ],
                ensure_ascii=False,
            )

    monkeypatch.setattr(rules_routes, "build_llm_client_from_settings", lambda: FakeClient())
    response = client.post(
        "/api/v1/rules/refine",
        json={
            "instruction": "正文字号改成四号",
            "rules": [
                {
                    "temp_id": "draft_0",
                    "name": "正文字体",
                    "kind": "style.font",
                    "params": {"cjk_font": "宋体", "size_pt": 12},
                }
            ],
        },
    )
    assert response.status_code == 200
    payload = response.json()
    # Invalid temp_id action was dropped and reported.
    assert len(payload["actions"]) == 1
    assert payload["actions"][0]["type"] == "modify"
    assert payload["actions"][0]["patch"] == {"params": {"size_pt": 14}}
    assert any(item["code"] == "refine_action_rejected" for item in payload["warnings"])

