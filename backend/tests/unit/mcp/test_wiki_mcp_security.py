"""MCP Wiki 路径安全回归测试。"""

import json

import pytest
from fastapi import HTTPException

from backend.wiki import mcp_server
from backend.wiki.mcp_server import _wiki_files, _wiki_read, _wiki_status


@pytest.mark.asyncio()
@pytest.mark.parametrize("path", ["../outside", "/etc", "wiki/../../outside"])
async def test_mcp_files_rejects_path_escape(tmp_path, path, monkeypatch):
    root = tmp_path / "project"
    root.mkdir()
    monkeypatch.setenv("SAGE_MCP_WIKI_PROJECT_ROOTS", str(root))
    with pytest.raises(HTTPException) as exc:
        await _wiki_files({"project_path": str(root), "path": path})
    assert exc.value.status_code == 400


@pytest.mark.asyncio()
async def test_mcp_read_accepts_legal_relative_path(tmp_path, monkeypatch):
    root = tmp_path / "project"
    (root / "wiki").mkdir(parents=True)
    (root / "wiki" / "page.md").write_text("safe", encoding="utf-8")
    monkeypatch.setenv("SAGE_MCP_WIKI_PROJECT_ROOTS", str(root))
    result = await _wiki_read({"project_path": str(root), "path": "wiki/page.md"})
    assert '"content": "safe"' in result[0].text


@pytest.mark.asyncio()
async def test_mcp_rejects_symlink_project_root(tmp_path, monkeypatch):
    real = tmp_path / "real"
    real.mkdir()
    link = tmp_path / "link"
    link.symlink_to(real, target_is_directory=True)
    monkeypatch.setenv("SAGE_MCP_WIKI_PROJECT_ROOTS", str(link))
    with pytest.raises(HTTPException) as exc:
        await _wiki_read({"project_path": str(link), "path": "wiki/page.md"})
    assert exc.value.status_code == 400


@pytest.mark.asyncio()
async def test_mcp_rejects_unregistered_project_root(tmp_path, monkeypatch):
    root = tmp_path / "untrusted"
    root.mkdir()
    monkeypatch.delenv("SAGE_MCP_WIKI_PROJECT_ROOTS", raising=False)
    with pytest.raises(HTTPException) as exc:
        await _wiki_read({"project_path": str(root), "path": "wiki/page.md"})
    assert exc.value.status_code == 403


@pytest.mark.asyncio()
async def test_mcp_status_reports_regular_source_file_count(tmp_path, monkeypatch):
    root = tmp_path / "project"
    (root / "wiki").mkdir(parents=True)
    sources = root / "raw" / "sources"
    sources.mkdir(parents=True)
    (sources / "one.md").write_text("one", encoding="utf-8")
    nested = sources / "nested"
    nested.mkdir()
    (nested / "two.txt").write_text("two", encoding="utf-8")
    monkeypatch.setenv("SAGE_MCP_WIKI_PROJECT_ROOTS", str(root))
    monkeypatch.setattr(
        mcp_server,
        "build_graph",
        lambda _: type("Graph", (), {"nodes": [], "edges": []})(),
    )

    result = await _wiki_status({"project_path": str(root)})

    status = json.loads(result[0].text)
    assert status["source_files"] == 2


@pytest.mark.asyncio()
async def test_mcp_status_fails_closed_without_verified_nofollow(tmp_path, monkeypatch):
    root = tmp_path / "project"
    root.mkdir()
    monkeypatch.setenv("SAGE_MCP_WIKI_PROJECT_ROOTS", str(root))
    monkeypatch.setattr(
        mcp_server,
        "_require_posix_safety",
        lambda: (_ for _ in ()).throw(OSError("unsupported")),
    )

    with pytest.raises(HTTPException) as exc:
        await _wiki_status({"project_path": str(root)})
    assert exc.value.status_code == 400


def test_mcp_status_count_skips_reparse_entry(tmp_path, monkeypatch):
    sources = tmp_path / "sources"
    sources.mkdir()
    (sources / "safe.md").write_text("safe", encoding="utf-8")
    reparse = sources / "reparse.md"
    reparse.write_text("unsafe", encoding="utf-8")
    monkeypatch.setattr(mcp_server, "is_reparse_point", lambda path: path == reparse)

    assert mcp_server._count_regular_files_without_following_links(sources) == 1
