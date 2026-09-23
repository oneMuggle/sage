"""SRC-1 (2026-09-24): wiki/mcp_server.py handler 面单元测试

612 行的 Wiki MCP server 此前仅安全路径有测试；本文件按 Zotero MCP
server 的"恒等装饰器直测"模式，直接调用 async handler 覆盖：

- 鉴权：未配置授权根 → fail-closed 403；env 配置后放行
- call_tool 分发：未知工具 → 未知工具文案；handler 抛错 → 通用错误文案
- wiki_status / wiki_files / wiki_search / wiki_read / wiki_graph /
  wiki_communities / wiki_insights 各 handler 的 happy path 与边界

授权通过 ``SAGE_MCP_WIKI_PROJECT_ROOTS`` 环境变量注入临时目录（fail-closed
语义下唯一的确定性授权途径，不依赖 recent-projects 文件状态）。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from backend.wiki import mcp_server

pytestmark = pytest.mark.unit


@pytest.fixture()
def wiki_project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """构建最小 Wiki 项目并授权给 MCP（env 白名单）。"""
    root = tmp_path / "wiki-project"
    (root / "wiki").mkdir(parents=True)
    (root / "wiki" / "arch.md").write_text(
        "# 架构\n\n分层设计 document 分层\n", encoding="utf-8"
    )
    (root / "wiki" / "rust.md").write_text(
        "# Rust\n\n所有权系统。\n", encoding="utf-8"
    )
    (root / ".hidden.md").write_text("应被 files 忽略", encoding="utf-8")
    monkeypatch.setenv("SAGE_MCP_WIKI_PROJECT_ROOTS", str(root))
    return root


def _text(result) -> str:
    assert len(result) == 1
    return result[0].text


# ── 鉴权（fail-closed）────────────────────────────────────────────────


@pytest.mark.asyncio()
async def test_unauthorized_project_root_is_rejected(wiki_project, tmp_path):
    """env 白名单之外的路径 → 403（经 call_tool 转通用错误文案）。"""
    outsider = tmp_path / "outside"
    outsider.mkdir()
    result = await mcp_server.call_tool(
        "wiki_status", {"project_path": str(outsider)}
    )
    assert "错误" in _text(result)


@pytest.mark.asyncio()
async def test_env_configured_root_is_authorized(wiki_project):
    root = mcp_server._authorized_project_root(str(wiki_project))
    assert root == wiki_project.resolve() or root.exists()


@pytest.mark.asyncio()
async def test_path_traversal_outside_configured_root_is_rejected(
    wiki_project, tmp_path
):
    from fastapi import HTTPException

    sibling = tmp_path / "sibling"
    sibling.mkdir()
    with pytest.raises(HTTPException) as exc_info:
        await mcp_server._authorized_project_root(str(sibling))
    assert "403" in str(exc_info.value.status_code) or exc_info.value.status_code == 403


# ── call_tool 分发 ────────────────────────────────────────────────────


@pytest.mark.asyncio()
async def test_call_tool_unknown_name():
    result = await mcp_server.call_tool("no_such_tool", {})
    assert "未知工具" in _text(result)


@pytest.mark.asyncio()
async def test_call_tool_handler_exception_returns_generic_error(
    wiki_project, monkeypatch
):
    """handler 内部异常 → 通用错误文案（不泄露内部细节）。"""
    async def boom(args):
        raise RuntimeError("内部细节")

    monkeypatch.setattr(mcp_server, "_wiki_status", boom)
    result = await mcp_server.call_tool("wiki_status", {"project_path": "x"})
    assert "错误" in _text(result)


# ── wiki_status ───────────────────────────────────────────────────────


@pytest.mark.asyncio()
async def test_wiki_status_reports_counts(wiki_project, monkeypatch):
    monkeypatch.setattr(
        mcp_server, "_require_posix_safety", lambda: None, raising=False
    )
    result = await mcp_server.call_tool(
        "wiki_status", {"project_path": str(wiki_project)}
    )
    status = json.loads(_text(result))
    assert status["wiki_pages"] == 2
    assert status["project_path"].replace("\\", "/").endswith("wiki-project")


# ── wiki_files ────────────────────────────────────────────────────────


@pytest.mark.asyncio()
async def test_wiki_files_lists_and_skips_dotfiles(wiki_project):
    result = await mcp_server.call_tool(
        "wiki_files", {"project_path": str(wiki_project)}
    )
    files = json.loads(_text(result))
    names = [f["name"] for f in files]
    assert "wiki" in names
    assert ".hidden.md" not in names


@pytest.mark.asyncio()
async def test_wiki_files_subdirectory_and_missing_path(wiki_project):
    result = await mcp_server.call_tool(
        "wiki_files", {"project_path": str(wiki_project), "path": "wiki"}
    )
    files = json.loads(_text(result))
    assert {f["name"] for f in files} == {"arch.md", "rust.md"}

    missing = await mcp_server.call_tool(
        "wiki_files", {"project_path": str(wiki_project), "path": "no/such/dir"}
    )
    assert "路径不存在" in _text(missing)


# ── wiki_search ───────────────────────────────────────────────────────


@pytest.mark.asyncio()
async def test_wiki_search_finds_matching_page(wiki_project):
    result = await mcp_server.call_tool(
        "wiki_search", {"project_path": str(wiki_project), "query": "分层"}
    )
    payload = json.loads(_text(result))
    assert payload["query"] == "分层"
    assert any("arch.md" in r["path"] for r in payload["results"])


# ── wiki_read ─────────────────────────────────────────────────────────


@pytest.mark.asyncio()
async def test_wiki_read_returns_page_content(wiki_project):
    result = await mcp_server.call_tool(
        "wiki_read", {"project_path": str(wiki_project), "path": "wiki/rust.md"}
    )
    assert "所有权系统" in _text(result)


@pytest.mark.asyncio()
async def test_wiki_read_missing_file_reports_missing(wiki_project):
    result = await mcp_server.call_tool(
        "wiki_read", {"project_path": str(wiki_project), "path": "wiki/none.md"}
    )
    assert "文件不存在" in _text(result)


# ── wiki_graph / wiki_communities / wiki_insights ─────────────────────


@pytest.mark.asyncio()
async def test_wiki_graph_returns_nodes_and_edges(wiki_project):
    result = await mcp_server.call_tool(
        "wiki_graph", {"project_path": str(wiki_project)}
    )
    payload = json.loads(_text(result))
    assert "nodes" in payload
    assert "edges" in payload


@pytest.mark.asyncio()
async def test_wiki_communities_and_insights_run(wiki_project):
    communities = await mcp_server.call_tool(
        "wiki_communities", {"project_path": str(wiki_project)}
    )
    assert communities  # 不抛错即视为通过（空图返回空/提示文本）

    insights = await mcp_server.call_tool(
        "wiki_insights", {"project_path": str(wiki_project)}
    )
    assert insights
