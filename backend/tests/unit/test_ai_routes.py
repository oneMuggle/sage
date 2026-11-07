"""P2 AI 侧栏端点契约测试。"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from fastapi import FastAPI  # noqa: E402

from backend.api.ai_routes import router as ai_router  # noqa: E402
from backend.data.database import get_database  # noqa: E402


@pytest.fixture()
def client(tmp_path: Path) -> TestClient:
    app = FastAPI()
    # 真实挂载点：office_routes.router（prefix="/office"）→ include(prefix="/ai") → main（prefix="/api/v1"）
    app.include_router(ai_router, prefix="/api/v1/office/ai")
    return TestClient(app)


@pytest.fixture()
def workspace(tmp_path: Path) -> Path:
    ws = tmp_path / "ws"
    ws.mkdir()
    return ws


def _llm_client(text: str = "改写结果") -> MagicMock:
    client = MagicMock()
    client.complete = AsyncMock(return_value=text)
    return client


def _seed_document(workspace: Path, document_id: str = "doc-1") -> None:
    """端点要求 document_id 登记在该工作区内；测试库是空的，先种一行。"""
    conn = get_database().get_connection()
    conn.execute(
        "INSERT OR REPLACE INTO office_documents "
        "(id, workspace_path, doc_type, original_filename, generated_filename, "
        "status, created_at, updated_at, metadata) "
        "VALUES (?, ?, 'word', 'draft.docx', 'draft.docx', 'managed', 1000, 1000, '{}')",
        (document_id, str(workspace.resolve())),
    )
    conn.commit()


def test_rewrite_returns_llm_output(client: TestClient, workspace: Path) -> None:
    _seed_document(workspace)
    with patch(
        "backend.api.ai_routes.build_llm_client_from_settings",
        return_value=_llm_client("新的段落文本"),
    ):
        resp = client.post(
            "/api/v1/office/ai/rewrite",
            json={
                "workspace_path": str(workspace),
                "document_id": "doc-1",
                "text": "原始段落",
                "instruction": "polish",
            },
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body == {"ok": True, "result": "新的段落文本", "model": None}


def test_rewrite_rejects_unknown_instruction(client: TestClient, workspace: Path) -> None:
    resp = client.post(
        "/api/v1/office/ai/rewrite",
        json={
            "workspace_path": str(workspace),
            "document_id": "doc-1",
            "text": "x",
            "instruction": "destroy",
        },
    )
    assert resp.status_code == 422


def test_rewrite_rejects_custom_without_instruction(client: TestClient, workspace: Path) -> None:
    _seed_document(workspace)
    resp = client.post(
        "/api/v1/office/ai/rewrite",
        json={
            "workspace_path": str(workspace),
            "document_id": "doc-1",
            "text": "x",
            "instruction": "custom",
        },
    )
    assert resp.status_code == 422


def test_rewrite_returns_502_when_llm_missing(client: TestClient, workspace: Path) -> None:
    _seed_document(workspace)
    with patch("backend.api.ai_routes.build_llm_client_from_settings", return_value=None):
        resp = client.post(
            "/api/v1/office/ai/rewrite",
            json={
                "workspace_path": str(workspace),
                "document_id": "doc-1",
                "text": "x",
                "instruction": "rewrite",
            },
        )

    assert resp.status_code == 502
    assert resp.json()["detail"]["code"] == "llm_unavailable"


def test_rewrite_returns_502_when_llm_raises(client: TestClient, workspace: Path) -> None:
    _seed_document(workspace)
    failing = MagicMock()
    failing.complete = AsyncMock(side_effect=RuntimeError("boom"))
    with patch("backend.api.ai_routes.build_llm_client_from_settings", return_value=failing):
        resp = client.post(
            "/api/v1/office/ai/rewrite",
            json={
                "workspace_path": str(workspace),
                "document_id": "doc-1",
                "text": "x",
                "instruction": "rewrite",
            },
        )

    assert resp.status_code == 502
    assert resp.json()["detail"]["code"] == "llm_error"


def test_chat_forwards_history(client: TestClient, workspace: Path) -> None:
    _seed_document(workspace)
    llm = MagicMock()
    response = MagicMock()
    response.content = "回答"
    llm.chat = AsyncMock(return_value=response)

    with patch("backend.api.ai_routes.build_llm_client_from_settings", return_value=llm):
        resp = client.post(
            "/api/v1/office/ai/chat",
            json={
                "workspace_path": str(workspace),
                "document_id": "doc-1",
                "message": "这段什么意思？",
                "history": [{"role": "user", "content": "你好"}],
                "document_context": "第一段\n第二段",
            },
        )

    assert resp.status_code == 200
    assert resp.json() == {"ok": True, "reply": "回答", "model": None}

    sent = llm.chat.await_args.args[0]
    assert sent[0]["role"] == "system"
    assert "第一段" in sent[0]["content"]
    assert sent[1] == {"role": "user", "content": "你好"}
    assert sent[-1] == {"role": "user", "content": "这段什么意思？"}


def test_rewrite_translate_uses_target_lang(client: TestClient, workspace: Path) -> None:
    """translate 在 _INSTRUCTION_TASKS 之外单独处理，不能落进 dict 查找（否则 KeyError→500）。"""
    _seed_document(workspace)
    llm = _llm_client("Hello")
    with patch("backend.api.ai_routes.build_llm_client_from_settings", return_value=llm):
        resp = client.post(
            "/api/v1/office/ai/rewrite",
            json={
                "workspace_path": str(workspace),
                "document_id": "doc-1",
                "text": "你好",
                "instruction": "translate",
                "target_lang": "英文",
            },
        )

    assert resp.status_code == 200
    prompt = llm.complete.await_args.args[0]
    assert "翻译为英文" in prompt
