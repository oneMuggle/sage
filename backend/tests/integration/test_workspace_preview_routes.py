# ruff: noqa: UP006, UP007, UP035, UP045 — release/win7 Python 3.8 兼容，保留 typing 注解
"""工作区文件预览 / 批量解析端点集成测试。

覆盖 ``GET /sessions/{id}/workspace/preview`` 与 ``POST /sessions/{id}/workspace/resolve``：
文本读取与截断、二进制拒绝、path traversal 边界、绝对路径边界、
图片 / PDF / Office / HTML 分派、批量存在性解析。
fixture 模式沿用 test_workspace_changes_routes.py（内存 DB + ASGITransport）。
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import AsyncIterator

import httpx
import pytest
import pytest_asyncio

from backend.data import database as database_module
from backend.data.database import Database
from backend.main import app
from backend.office.session_workspace import bind_session_workspace

#: 与 workspace_routes._WS_FILE_PREVIEW_CONTENT_CAP 对齐（512 KiB 字符）
CONTENT_CAP = 512 * 1024


@pytest.fixture()
def db(monkeypatch: pytest.MonkeyPatch) -> Database:
    test_db = Database(":memory:")
    test_db.init_db()
    monkeypatch.setattr(database_module, "_db", test_db)
    return test_db


@pytest.fixture()
def conn(db: Database) -> sqlite3.Connection:
    return db.get_connection()


@pytest.fixture()
def session_id(conn: sqlite3.Connection) -> str:
    value = "session-preview"
    conn.execute(
        "INSERT INTO sessions (id, title, created_at, updated_at) VALUES (?, ?, ?, ?)",
        (value, "Preview", 1, 1),
    )
    conn.commit()
    return value


@pytest.fixture()
def workspace(tmp_path: Path) -> Path:
    path = tmp_path / "workspace"
    path.mkdir()
    return path


@pytest_asyncio.fixture()
async def client(db: Database) -> AsyncIterator[httpx.AsyncClient]:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as value:
        yield value


@pytest.fixture()
def bound_session(
    conn: sqlite3.Connection, session_id: str, workspace: Path
) -> str:
    bind_session_workspace(conn, session_id, str(workspace))
    return session_id


def _preview_url(session_id: str, path: str) -> str:
    return f"/api/v1/sessions/{session_id}/workspace/preview?path={path}"


# ---------------------------------------------------------------------------
# 前置条件
# ---------------------------------------------------------------------------


@pytest.mark.asyncio()
async def test_preview_requires_existing_session(client: httpx.AsyncClient) -> None:
    response = await client.get(_preview_url("nope", "a.txt"))
    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "session_not_found"


@pytest.mark.asyncio()
async def test_preview_requires_bound_workspace(
    client: httpx.AsyncClient, session_id: str
) -> None:
    response = await client.get(_preview_url(session_id, "a.txt"))
    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "workspace_not_bound"


@pytest.mark.asyncio()
async def test_resolve_requires_bound_workspace(
    client: httpx.AsyncClient, session_id: str
) -> None:
    response = await client.post(
        f"/api/v1/sessions/{session_id}/workspace/resolve",
        json={"paths": ["a.txt"]},
    )
    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "workspace_not_bound"


# ---------------------------------------------------------------------------
# 文本预览
# ---------------------------------------------------------------------------


@pytest.mark.asyncio()
async def test_preview_text_relative_path(
    client: httpx.AsyncClient, bound_session: str, workspace: Path
) -> None:
    (workspace / "notes").mkdir()
    target = workspace / "notes" / "readme.md"
    target.write_text("# Title\n\nbody\n", encoding="utf-8")

    response = await client.get(_preview_url(bound_session, "notes/readme.md"))
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["kind"] == "markdown"
    assert body["content"] == "# Title\n\nbody\n"
    assert body["truncated"] is False


@pytest.mark.asyncio()
async def test_preview_code_kind(
    client: httpx.AsyncClient, bound_session: str, workspace: Path
) -> None:
    target = workspace / "app.py"
    target.write_text("print('hi')\n", encoding="utf-8")

    response = await client.get(_preview_url(bound_session, "app.py"))
    assert response.status_code == 200
    body = response.json()
    assert body["kind"] == "code"
    assert body["content"] == "print('hi')\n"


@pytest.mark.asyncio()
async def test_preview_truncates_large_text(
    client: httpx.AsyncClient, bound_session: str, workspace: Path
) -> None:
    target = workspace / "big.txt"
    target.write_text("x" * (CONTENT_CAP + 10_000), encoding="utf-8")

    response = await client.get(_preview_url(bound_session, "big.txt"))
    assert response.status_code == 200
    body = response.json()
    assert body["truncated"] is True
    assert len(body["content"]) == CONTENT_CAP


@pytest.mark.asyncio()
async def test_preview_rejects_binary(
    client: httpx.AsyncClient, bound_session: str, workspace: Path
) -> None:
    target = workspace / "blob.bin"
    target.write_bytes(b"\x00\x01\x02binary")

    response = await client.get(_preview_url(bound_session, "blob.bin"))
    assert response.status_code == 415
    assert response.json()["detail"]["code"] == "binary_file"


@pytest.mark.asyncio()
async def test_preview_missing_file(
    client: httpx.AsyncClient, bound_session: str
) -> None:
    response = await client.get(_preview_url(bound_session, "missing.txt"))
    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "file_not_found"


# ---------------------------------------------------------------------------
# 路径边界
# ---------------------------------------------------------------------------


@pytest.mark.asyncio()
async def test_preview_rejects_path_traversal(
    client: httpx.AsyncClient, bound_session: str, tmp_path: Path
) -> None:
    secret = tmp_path / "secret.txt"
    secret.write_text("top secret", encoding="utf-8")

    response = await client.get(_preview_url(bound_session, "../secret.txt"))
    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "path_outside_workspace"


@pytest.mark.asyncio()
async def test_preview_rejects_absolute_outside_workspace(
    client: httpx.AsyncClient, bound_session: str, tmp_path: Path
) -> None:
    secret = tmp_path / "secret.txt"
    secret.write_text("top secret", encoding="utf-8")

    response = await client.get(_preview_url(bound_session, str(secret)))
    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "path_outside_workspace"


@pytest.mark.asyncio()
async def test_preview_accepts_absolute_inside_workspace(
    client: httpx.AsyncClient, bound_session: str, workspace: Path
) -> None:
    target = workspace / "note.txt"
    target.write_text("inside", encoding="utf-8")

    response = await client.get(_preview_url(bound_session, str(target)))
    assert response.status_code == 200
    assert response.json()["content"] == "inside"


# ---------------------------------------------------------------------------
# 类型分派
# ---------------------------------------------------------------------------


@pytest.mark.asyncio()
async def test_preview_image_returns_data_url(
    client: httpx.AsyncClient, bound_session: str, workspace: Path
) -> None:
    # 最小 PNG 头 + 任意字节——本端点只做 base64 包装，不解码图片
    target = workspace / "pixel.png"
    target.write_bytes(b"\x89PNG\r\n\x1a\nfake-image-bytes")

    response = await client.get(_preview_url(bound_session, "pixel.png"))
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["kind"] == "image"
    assert body["data_url"].startswith("data:image/png;base64,")


@pytest.mark.asyncio()
async def test_preview_pdf_returns_data_url(
    client: httpx.AsyncClient, bound_session: str, workspace: Path
) -> None:
    target = workspace / "doc.pdf"
    target.write_bytes(b"%PDF-1.4\n%fake\n")

    response = await client.get(_preview_url(bound_session, "doc.pdf"))
    assert response.status_code == 200
    body = response.json()
    assert body["kind"] == "pdf"
    assert body["data_url"].startswith("data:application/pdf;base64,")


@pytest.mark.asyncio()
async def test_preview_html_kind(
    client: httpx.AsyncClient, bound_session: str, workspace: Path
) -> None:
    target = workspace / "page.html"
    target.write_text("<h1>hi</h1>", encoding="utf-8")

    response = await client.get(_preview_url(bound_session, "page.html"))
    assert response.status_code == 200
    assert response.json()["kind"] == "html"


@pytest.mark.asyncio()
async def test_preview_docx_returns_html_and_structured(
    client: httpx.AsyncClient, bound_session: str, workspace: Path
) -> None:
    docx = pytest.importorskip("docx")
    document = docx.Document()
    document.add_heading("Preview Title", level=1)
    document.add_paragraph("hello office")
    target = workspace / "report.docx"
    document.save(str(target))

    response = await client.get(_preview_url(bound_session, "report.docx"))
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["kind"] == "docx"
    assert "Preview Title" in body["html"]
    assert isinstance(body.get("structured"), dict)


# ---------------------------------------------------------------------------
# 批量解析
# ---------------------------------------------------------------------------


@pytest.mark.asyncio()
async def test_resolve_files_batch(
    client: httpx.AsyncClient, bound_session: str, workspace: Path, tmp_path: Path
) -> None:
    (workspace / "a.md").write_text("# a", encoding="utf-8")
    (workspace / "app.py").write_text("x = 1", encoding="utf-8")
    outside = tmp_path / "secret.txt"
    outside.write_text("nope", encoding="utf-8")

    response = await client.post(
        f"/api/v1/sessions/{bound_session}/workspace/resolve",
        json={
            "paths": [
                "a.md",
                "app.py",
                "missing.txt",
                "../secret.txt",
                str(workspace / "a.md"),
            ]
        },
    )
    assert response.status_code == 200
    results = {r["path"]: r for r in response.json()["results"]}
    assert results["a.md"]["exists"] is True
    assert results["a.md"]["kind"] == "markdown"
    assert results["app.py"]["exists"] is True
    assert results["app.py"]["kind"] == "code"
    assert results["missing.txt"]["exists"] is False
    assert results["../secret.txt"]["exists"] is False
    assert results[str(workspace / "a.md")]["exists"] is True


@pytest.mark.asyncio()
async def test_resolve_rejects_too_many_paths(
    client: httpx.AsyncClient, bound_session: str
) -> None:
    response = await client.post(
        f"/api/v1/sessions/{bound_session}/workspace/resolve",
        json={"paths": [f"f{i}.txt" for i in range(51)]},
    )
    assert response.status_code == 422


@pytest.mark.asyncio()
async def test_preview_latex_returns_structured_blocks(
    client: httpx.AsyncClient, bound_session: str, workspace: Path
) -> None:
    paper = workspace / "paper"
    paper.mkdir()
    (paper / "main.tex").write_text(
        r"""
\documentclass{article}
\title{Preview Demo}
\begin{document}
\section{Intro}
Inline $x^2$.
\end{document}
""",
        encoding="utf-8",
    )

    response = await client.get(_preview_url(bound_session, "paper/main.tex"))

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["kind"] == "latex"
    assert payload["structured"]["metadata"]["title"] == "Preview Demo"
    types = [block["type"] for block in payload["structured"]["blocks"]]
    assert "heading" in types
    assert "paragraph" in types


# ---------------------------------------------------------------------------
# F2 (2026-11-17): 消息蓝链 404 —— file:// 形态与产物文件名回退
# ---------------------------------------------------------------------------


@pytest.mark.asyncio()
async def test_preview_accepts_file_scheme_path(
    client: httpx.AsyncClient, bound_session: str, workspace: Path
) -> None:
    """file:///abs/path 形态（模型/历史消息常见）应剥离 scheme 后正常预览。"""
    target = workspace / "报告 final.md"
    target.write_text("# hi", encoding="utf-8")

    response = await client.get(
        f"/api/v1/sessions/{bound_session}/workspace/preview",
        params={"path": f"file://{target}"},
    )

    assert response.status_code == 200
    assert response.json()["ok"] is True


@pytest.mark.asyncio()
async def test_preview_falls_back_to_session_artifact_by_name(
    client: httpx.AsyncClient,
    conn: sqlite3.Connection,
    session_id: str,
    workspace: Path,
) -> None:
    """裸文件名（受管 Office 文档场景）按会话产物表回退解析真实路径。

    受管文档落在 ``office/<doc_type>/<doc_id>/<文件名>``，而真实路径从不
    回显给模型 —— 模型给出的 ``[文件名](文件名)`` 链接按工作区根解析必然
    404。预览端点应回退到本会话登记的 artifact 路径。
    """
    from backend.data import artifact_repo

    managed_dir = workspace / "office" / "word" / "doc123"
    managed_dir.mkdir(parents=True)
    report = managed_dir / "季度报告.md"
    report.write_text("# 季度汇报\n", encoding="utf-8")
    artifact_repo.record_artifact(
        session_id, str(report), report.name, "markdown", report.stat().st_size
    )
    bind_session_workspace(conn, session_id, str(workspace))

    response = await client.get(
        f"/api/v1/sessions/{session_id}/workspace/preview",
        params={"path": "季度报告.md"},
    )

    assert response.status_code == 200
    assert response.json()["content"] == "# 季度汇报\n"


@pytest.mark.asyncio()
async def test_preview_tilde_path_expands_then_falls_back_to_artifact(
    client: httpx.AsyncClient,
    conn: sqlite3.Connection,
    session_id: str,
    workspace: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """~/x 形态：先展开家目录（超出工作区 → 403 路径），再按会话产物回退。"""
    from backend.data import artifact_repo

    home = tmp_path / "home"
    home.mkdir()
    target = home / "导出报告.md"
    target.write_text("# 导出", encoding="utf-8")
    # Path.expanduser 在 POSIX 读 HOME、Windows 读 USERPROFILE —— 两者都设
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    artifact_repo.record_artifact(
        session_id, str(target), target.name, "markdown", target.stat().st_size
    )
    bind_session_workspace(conn, session_id, str(workspace))

    response = await client.get(
        f"/api/v1/sessions/{session_id}/workspace/preview",
        params={"path": f"~/{target.name}"},
    )

    assert response.status_code == 200
    assert response.json()["content"] == "# 导出"


@pytest.mark.asyncio()
async def test_preview_artifact_fallback_scoped_to_session(
    client: httpx.AsyncClient,
    conn: sqlite3.Connection,
    session_id: str,
    workspace: Path,
    tmp_path: Path,
) -> None:
    """回退只查本会话产物 —— 其他会话同名产物不可预览（防跨会话泄露）。"""
    from backend.data import artifact_repo

    other_dir = tmp_path / "other"
    other_dir.mkdir()
    other_file = other_dir / "机密.md"
    other_file.write_text("# secret", encoding="utf-8")
    artifact_repo.record_artifact(
        "another-session", str(other_file), other_file.name, "markdown", 8
    )
    bind_session_workspace(conn, session_id, str(workspace))

    response = await client.get(
        f"/api/v1/sessions/{session_id}/workspace/preview",
        params={"path": "机密.md"},
    )

    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "file_not_found"


@pytest.mark.asyncio()
async def test_preview_no_fallback_for_relative_path_with_dirs(
    client: httpx.AsyncClient,
    conn: sqlite3.Connection,
    session_id: str,
    workspace: Path,
) -> None:
    """带目录的相对路径 404 时不按同名产物回退（避免张冠李戴）。"""
    from backend.data import artifact_repo

    real = workspace / "office" / "report.md"
    real.parent.mkdir(parents=True)
    real.write_text("# real", encoding="utf-8")
    artifact_repo.record_artifact(session_id, str(real), real.name, "markdown", 6)
    bind_session_workspace(conn, session_id, str(workspace))

    response = await client.get(
        f"/api/v1/sessions/{session_id}/workspace/preview",
        params={"path": "output/report.md"},
    )

    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "file_not_found"


@pytest.mark.asyncio()
async def test_preview_accepts_file_scheme_localhost_form(
    client: httpx.AsyncClient, bound_session: str, workspace: Path
) -> None:
    """file://localhost/abs/path（RFC 8089 同义写法）同样归一化。"""
    target = workspace / "note.md"
    target.write_text("# note", encoding="utf-8")

    response = await client.get(
        f"/api/v1/sessions/{bound_session}/workspace/preview",
        params={"path": f"file://localhost{target}"},
    )

    assert response.status_code == 200
    assert response.json()["content"] == "# note"


@pytest.mark.asyncio()
async def test_resolve_confirms_bare_artifact_name(
    client: httpx.AsyncClient,
    conn: sqlite3.Connection,
    session_id: str,
    workspace: Path,
) -> None:
    """resolve 与 preview 同口径：受管 Office 裸文件名按会话产物确认存在。"""
    from backend.data import artifact_repo

    managed_dir = workspace / "office" / "word" / "doc999"
    managed_dir.mkdir(parents=True)
    report = managed_dir / "会议纪要.md"
    report.write_text("# 纪要\n", encoding="utf-8")
    artifact_repo.record_artifact(
        session_id, str(report), report.name, "markdown", report.stat().st_size
    )
    bind_session_workspace(conn, session_id, str(workspace))

    response = await client.post(
        f"/api/v1/sessions/{session_id}/workspace/resolve",
        json={"paths": ["会议纪要.md", "不存在的.docx", "sub/会议纪要.md"]},
    )

    assert response.status_code == 200
    by_path = {r["path"]: r for r in response.json()["results"]}
    assert by_path["会议纪要.md"]["exists"] is True
    assert by_path["会议纪要.md"]["kind"] == "markdown"
    assert by_path["不存在的.docx"]["exists"] is False
    # 带目录的相对路径不走产物回退（避免张冠李戴）
    assert by_path["sub/会议纪要.md"]["exists"] is False
