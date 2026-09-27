"""R147 — 工作区语义检索工具（codebase_search）单元测试。

覆盖：schema 契约、未知参数拒绝、query 最短长度、limit 钳位、
embedding 配置门、工作区绑定门、索引/检索两级异常降级、成功路径的
content 聚合（query/results/index 统计合并）。
协作者全部 monkeypatch，不触真实 embedding 与文件系统。
"""

from __future__ import annotations

import pytest

from backend.domain.risk import RiskClass
from backend.domain.tool_policy import ToolPolicy
from backend.tools.codebase_search_tool import CodebaseSearchTool

pytestmark = pytest.mark.unit


@pytest.fixture()
def tool_with_root():
    return CodebaseSearchTool(policy=ToolPolicy(workspace_root="C:/ws"))


@pytest.fixture()
def stub_cst(monkeypatch):
    """打桩四个协作者；默认 embedding 已配置、索引/检索成功。"""
    from backend.tools import codebase_search_tool as cst

    state = {
        "config": {"model": "embed-1"},
        "index_info": {"indexed": 3, "chunks": 40},
        "stats": {"files_total": 10, "chunks_total": 40},
        "results": [{"file": "a.py", "line": 1, "snippet": "hit"}],
        "index_exc": None,
        "search_exc": None,
    }

    def fake_index(root, config):
        if state["index_exc"]:
            raise state["index_exc"]
        return state["index_info"]

    def fake_search(root, config, query, limit):
        if state["search_exc"]:
            raise state["search_exc"]
        return state["results"]

    monkeypatch.setattr(cst, "load_embedding_config", lambda: state["config"])
    monkeypatch.setattr(cst, "_index_workspace", fake_index)
    monkeypatch.setattr(cst, "_search_workspace", fake_search)
    monkeypatch.setattr(cst, "workspace_index_stats", lambda root: state["stats"])
    return state


# ---------------------------------------------------------------------------
# schema
# ---------------------------------------------------------------------------


def test_schema_contract():
    schema = CodebaseSearchTool().schema
    assert schema.name == "codebase_search"
    assert schema.parameters["required"] == ["query"]
    assert CodebaseSearchTool.risk == RiskClass.READ


# ---------------------------------------------------------------------------
# 参数校验
# ---------------------------------------------------------------------------


def test_unknown_kwargs_rejected(tool_with_root, stub_cst):
    out = tool_with_root.execute(query="abc", bogus="x", another=1)
    assert out.success is False
    assert "another, bogus" in out.error  # sorted(unknown kwargs)


def test_query_too_short_rejected(tool_with_root, stub_cst):
    out = tool_with_root.execute(query=" a ")
    assert out.success is False
    assert "2 个字符" in out.error


def test_query_non_string_rejected(tool_with_root, stub_cst):
    out = tool_with_root.execute(query=123)
    assert out.success is False


def test_limit_clamped_to_range(monkeypatch, stub_cst):
    seen = {}
    from backend.tools import codebase_search_tool as cst

    def fake_search(root, config, query, limit):
        seen["limit"] = limit
        return []

    monkeypatch.setattr(cst, "load_embedding_config", lambda: {"model": "m"})
    monkeypatch.setattr(cst, "_index_workspace", lambda root, config: {"indexed": 0, "chunks": 0})
    monkeypatch.setattr(cst, "_search_workspace", fake_search)
    monkeypatch.setattr(cst, "workspace_index_stats", lambda root: {})
    tool = CodebaseSearchTool(policy=ToolPolicy(workspace_root="C:/ws"))
    tool.execute(query="abc", limit=0)
    assert seen["limit"] == 1
    tool.execute(query="abc", limit=100)
    assert seen["limit"] == 20


# ---------------------------------------------------------------------------
# 配置与绑定门
# ---------------------------------------------------------------------------


def test_missing_embedding_config_guides_user(monkeypatch):
    from backend.tools import codebase_search_tool as cst

    monkeypatch.setattr(cst, "load_embedding_config", lambda: None)
    tool = CodebaseSearchTool(policy=ToolPolicy(workspace_root="C:/ws"))
    out = tool.execute(query="abc")
    assert out.success is False
    assert "embedding 模型" in out.error


def test_missing_workspace_rejected(stub_cst):
    tool = CodebaseSearchTool()  # 默认 ToolPolicy 无 workspace_root
    out = tool.execute(query="abc")
    assert out.success is False
    assert "工作区" in out.error


# ---------------------------------------------------------------------------
# 异常降级与成功路径
# ---------------------------------------------------------------------------


def test_index_failure_degrades(tool_with_root, stub_cst):
    stub_cst["index_exc"] = RuntimeError("embed endpoint down")
    out = tool_with_root.execute(query="abc")
    assert out.success is False
    assert "索引构建失败" in out.error


def test_search_failure_degrades(tool_with_root, stub_cst):
    stub_cst["search_exc"] = RuntimeError("cosine boom")
    out = tool_with_root.execute(query="abc")
    assert out.success is False
    assert "检索失败" in out.error


def test_success_aggregates_results_and_stats(tool_with_root, stub_cst):
    out = tool_with_root.execute(query="abc", limit=3)
    assert out.success is True
    content = out.content
    assert content["query"] == "abc"
    assert content["results"] == [{"file": "a.py", "line": 1, "snippet": "hit"}]
    assert content["index"]["indexed_files_delta"] == 3
    assert content["index"]["chunks_total"] == 40
    assert content["index"]["files_total"] == 10  # workspace_index_stats 合并
