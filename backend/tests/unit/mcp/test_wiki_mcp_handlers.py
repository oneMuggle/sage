"""R107 — Wiki MCP server handler 面单测（happy path，补充既有安全回归）。

既有 test_wiki_mcp_security.py 只覆盖路径逃逸；本文件走 tmp 项目 +
``SAGE_MCP_WIKI_PROJECT_ROOTS`` 授权，覆盖 7 工具的正常返回面与 call_tool
分发/错误兜底。handlers 调用 ``_require_posix_safety()``，Windows 跳过
（与安全回归同口径）；CI 在 Linux 上全量执行。
"""

from __future__ import annotations

import json
import os

import pytest

from backend.wiki import mcp_server

pytestmark = [
    pytest.mark.unit,
    pytest.mark.skipif(os.name == "nt", reason="handlers 依赖 POSIX 安全原语"),
]


def _make_project(tmp_path):
    """建两页互链 wiki：A.md --[[B]]--> B.md。"""
    wiki = tmp_path / "wiki"
    wiki.mkdir()
    (wiki / "A.md").write_text("# A\n\n正文，见 [[B]]。\n", encoding="utf-8")
    (wiki / "B.md").write_text("# B\n\n被引用页。\n", encoding="utf-8")
    return tmp_path


@pytest.fixture()
def project(tmp_path, monkeypatch):
    root = _make_project(tmp_path)
    monkeypatch.setenv("SAGE_MCP_WIKI_PROJECT_ROOTS", str(root))
    return root


def _json(result) -> dict:
    assert len(result) == 1
    return json.loads(result[0].text)


@pytest.mark.asyncio()
async def test_list_tools_exposes_seven_wiki_tools(project):
    tools = await mcp_server.list_tools()
    names = [t.name for t in tools]
    assert names == [
        "wiki_status",
        "wiki_files",
        "wiki_search",
        "wiki_read",
        "wiki_graph",
        "wiki_communities",
        "wiki_insights",
    ]
    assert all(isinstance(t.inputSchema, dict) for t in tools)


@pytest.mark.asyncio()
async def test_status_reports_page_and_graph_counts(project):
    out = await mcp_server.call_tool("wiki_status", {"project_path": str(project)})
    body = _json(out)
    assert body["project_path"] == str(project)
    assert body["wiki_pages"] == 2
    assert "graph_nodes" in body
    assert "graph_edges" in body
    assert "source_files" in body


@pytest.mark.asyncio()
async def test_files_lists_root_and_subdir(project):
    root_listing = _json(await mcp_server.call_tool("wiki_files", {"project_path": str(project)}))
    wiki_entry = next(e for e in root_listing if e["name"] == "wiki")
    assert wiki_entry["is_dir"] is True

    sub = _json(
        await mcp_server.call_tool(
            "wiki_files", {"project_path": str(project), "path": "wiki"}
        )
    )
    names = {e["name"] for e in sub}
    assert names == {"A.md", "B.md"}
    for e in sub:
        assert e["is_dir"] is False
        assert e["path"].startswith("wiki/")


@pytest.mark.asyncio()
async def test_search_returns_envelope(project):
    out = await mcp_server.call_tool(
        "wiki_search", {"project_path": str(project), "query": "A", "limit": 5}
    )
    body = _json(out)
    assert body["query"] == "A"
    assert isinstance(body["results"], list)
    for r in body["results"]:
        assert {"path", "title", "snippet", "score"} <= set(r)


@pytest.mark.asyncio()
async def test_read_returns_page_content(project):
    out = await mcp_server.call_tool(
        "wiki_read", {"project_path": str(project), "path": "wiki/A.md"}
    )
    body = _json(out)
    assert body["path"] == "wiki/A.md"
    assert "[[B]]" in body["content"]


@pytest.mark.asyncio()
async def test_graph_returns_nodes_and_edges(project):
    out = await mcp_server.call_tool("wiki_graph", {"project_path": str(project)})
    body = _json(out)
    assert isinstance(body["nodes"], list)
    assert isinstance(body["edges"], list)


@pytest.mark.asyncio()
async def test_communities_and_insights_return_json(project):
    communities = _json(await mcp_server.call_tool("wiki_communities", {"project_path": str(project)}))
    assert isinstance(communities, dict)
    insights = _json(await mcp_server.call_tool("wiki_insights", {"project_path": str(project)}))
    assert isinstance(insights, dict)


@pytest.mark.asyncio()
async def test_unknown_tool_returns_message(project):
    out = await mcp_server.call_tool("wiki_nonexistent", {"project_path": str(project)})
    assert out[0].text == "未知工具: wiki_nonexistent"


@pytest.mark.asyncio()
async def test_missing_required_arg_falls_into_swallowed_error(project):
    # 缺 project_path → KeyError → call_tool 统一吞掉并返回固定错误文案
    out = await mcp_server.call_tool("wiki_status", {})
    assert out[0].text == "错误: Wiki 工具执行失败"
