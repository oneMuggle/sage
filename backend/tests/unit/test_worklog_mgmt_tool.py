"""工作日志 LLM 工具测试（P2）。

两个工具把 :class:`WorklogService` 暴露给 LLM：

- :class:`AddWorklogTool`   —— 记录「刚刚做了什么」
- :class:`ListWorklogsTool` —— 查询工作日志流

服务未初始化时退化为「未初始化」ToolResult，而不是 AttributeError。
"""
from __future__ import annotations

from unittest.mock import Mock

from backend.domain.risk import RiskClass
from backend.services.worklog_models import WorkLog
from backend.services.worklog_service import WorklogService
from backend.tools.worklog_mgmt_tool import AddWorklogTool, ListWorklogsTool


def _make_worklog(**overrides):
    base = {
        "id": 1,
        "session_id": None,
        "content": "写完了鉴权模块",
        "kind": "progress",
        "progress_text": None,
        "blocker": None,
        "todo_id": None,
        "project_id": None,
        "project_tag": None,
        "source_type": "agent",
        "source_ref": None,
        "status": "pending",
        "created_at": "2026-11-27T14:32:05.123456",
        "updated_at": "2026-11-27T14:32:05.123456",
    }
    base.update(overrides)
    return WorkLog(**base)


# ======================================================================
# Schema 与风险声明
# ======================================================================


def test_add_worklog_tool_schema():
    """schema 名、必填项与风险级别。"""
    tool = AddWorklogTool(worklog_service_getter=lambda: Mock())

    assert tool.schema.name == "add_worklog"
    assert "content" in tool.schema.parameters["properties"]
    assert "kind" in tool.schema.parameters["properties"]
    assert tool.schema.parameters["required"] == ["content"]
    assert tool.risk == RiskClass.WRITE_LOCAL


def test_list_worklogs_tool_schema():
    """查询工具无必填项 —— agent 可以裸调用。"""
    tool = ListWorklogsTool(worklog_service_getter=lambda: Mock())

    assert tool.schema.name == "list_worklogs"
    assert tool.schema.parameters["required"] == []
    assert tool.risk == RiskClass.READ


# ======================================================================
# add_worklog
# ======================================================================


def test_add_worklog_tool_execute():
    """调用 service 落库，source_type 固定为 agent。"""
    mock_service = Mock(spec=WorklogService)
    mock_service.create_worklog.return_value = _make_worklog(kind="done")

    tool = AddWorklogTool(worklog_service_getter=lambda: mock_service)
    result = tool.execute(content="写完了鉴权模块", kind="done")

    assert result.success is True
    assert result.content["id"] == 1
    assert result.content["kind"] == "done"
    assert result.content["status"] == "pending"

    mock_service.create_worklog.assert_called_once()
    kwargs = mock_service.create_worklog.call_args.kwargs
    assert kwargs["source_type"] == "agent"
    assert kwargs["content"] == "写完了鉴权模块"
    assert kwargs["kind"] == "done"


def test_add_worklog_tool_defaults_kind_to_progress():
    """不传 kind 时默认 progress。"""
    mock_service = Mock(spec=WorklogService)
    mock_service.create_worklog.return_value = _make_worklog()

    tool = AddWorklogTool(worklog_service_getter=lambda: mock_service)
    tool.execute(content="随手记一条")

    kwargs = mock_service.create_worklog.call_args.kwargs
    assert kwargs["kind"] == "progress"


def test_add_worklog_tool_forwards_optional_fields():
    """可选字段原样透传给服务层。"""
    mock_service = Mock(spec=WorklogService)
    mock_service.create_worklog.return_value = _make_worklog()

    tool = AddWorklogTool(worklog_service_getter=lambda: mock_service)
    tool.execute(content="x", todo_id=7, project_tag="sage", session_id="sess-1")

    kwargs = mock_service.create_worklog.call_args.kwargs
    assert kwargs["todo_id"] == 7
    assert kwargs["project_tag"] == "sage"
    assert kwargs["session_id"] == "sess-1"


# ======================================================================
# list_worklogs
# ======================================================================


def test_list_worklogs_tool_execute():
    """查询返回 worklogs 列表与计数。"""
    mock_service = Mock(spec=WorklogService)
    mock_service.list_worklogs.return_value = [_make_worklog()]

    tool = ListWorklogsTool(worklog_service_getter=lambda: mock_service)
    result = tool.execute()

    assert result.success is True
    assert result.content["count"] == 1
    assert len(result.content["worklogs"]) == 1
    assert result.content["worklogs"][0]["content"] == "写完了鉴权模块"


def test_list_worklogs_tool_status_all_maps_to_none():
    """status='all' 归一化成 None（不限状态）。"""
    mock_service = Mock(spec=WorklogService)
    mock_service.list_worklogs.return_value = []

    tool = ListWorklogsTool(worklog_service_getter=lambda: mock_service)
    tool.execute(status="all")

    kwargs = mock_service.list_worklogs.call_args.kwargs
    assert kwargs["status"] is None


def test_list_worklogs_tool_passes_filters_through():
    """日期/分类筛选原样透传。"""
    mock_service = Mock(spec=WorklogService)
    mock_service.list_worklogs.return_value = []

    tool = ListWorklogsTool(worklog_service_getter=lambda: mock_service)
    tool.execute(date_from="2026-11-20", date_to="2026-11-27", kind="done", limit=10)

    kwargs = mock_service.list_worklogs.call_args.kwargs
    assert kwargs["date_from"] == "2026-11-20"
    assert kwargs["date_to"] == "2026-11-27"
    assert kwargs["kind"] == "done"
    assert kwargs["limit"] == 10


# ======================================================================
# 降级路径
# ======================================================================


def test_worklog_tools_report_uninitialized_service():
    """getter 返回 None 时给友好错误，而不是 AttributeError。"""
    add_tool = AddWorklogTool(worklog_service_getter=lambda: None)
    list_tool = ListWorklogsTool(worklog_service_getter=lambda: None)

    add_result = add_tool.execute(content="x")
    list_result = list_tool.execute()

    assert add_result.success is False
    assert list_result.success is False
    assert "未初始化" in (add_result.error or "")
    assert "未初始化" in (list_result.error or "")


def test_add_worklog_tool_surfaces_service_exception():
    """service 异常 → ToolResult(success=False)，不炸穿。"""
    mock_service = Mock(spec=WorklogService)
    mock_service.create_worklog.side_effect = RuntimeError("db down")

    tool = AddWorklogTool(worklog_service_getter=lambda: mock_service)
    result = tool.execute(content="x")

    assert result.success is False
    assert "db down" in (result.error or "")


def test_list_worklogs_tool_surfaces_service_exception():
    """查询异常同样收敛成 ToolResult。"""
    mock_service = Mock(spec=WorklogService)
    mock_service.list_worklogs.side_effect = RuntimeError("query failed")

    tool = ListWorklogsTool(worklog_service_getter=lambda: mock_service)
    result = tool.execute()

    assert result.success is False
    assert "query failed" in (result.error or "")
