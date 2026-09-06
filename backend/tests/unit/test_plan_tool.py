"""plan_write 工具单元测试（G3 Plan 模式）。"""

from __future__ import annotations

import pytest

from backend.domain.tool_policy import ToolPolicy
from backend.tools.plan_tool import PlanWriteTool, get_plan_store
from backend.tools.todo_state import resolve_session_id

pytestmark = [pytest.mark.unit]


@pytest.fixture(autouse=True)
def _clean_store():
    get_plan_store().clear()
    yield
    get_plan_store().clear()


def _tool():
    return PlanWriteTool(policy=ToolPolicy())


def test_write_and_shape():
    result = _tool().execute(
        goal="重构登录模块",
        steps=[
            {"title": "梳理现有流程", "detail": "读 auth/ 目录"},
            {"title": "改代码", "status": "pending"},
        ],
    )
    assert result.success is True
    assert result.content["steps_total"] == 2
    assert result.content["steps_done"] == 0

    stored = get_plan_store().get(resolve_session_id())
    assert stored["goal"] == "重构登录模块"
    assert stored["steps"][0]["status"] == "pending"


def test_update_progress_replaces_whole_plan():
    _tool().execute(goal="g", steps=[{"title": "a"}, {"title": "b"}])
    result = _tool().execute(
        goal="g",
        steps=[{"title": "a", "status": "done"}, {"title": "b", "status": "in_progress"}],
    )
    assert result.success is True
    assert result.content["steps_done"] == 1


def test_validation_rejects_bad_shapes():
    tool = _tool()
    assert tool.execute(goal="", steps=[{"title": "x"}]).success is False
    assert tool.execute(goal="g", steps=[]).success is False
    assert tool.execute(goal="g", steps=["not-dict"]).success is False
    assert tool.execute(goal="g", steps=[{"title": " "}]).success is False
    assert tool.execute(goal="g", steps=[{"title": "a", "status": "flying"}]).success is False
    assert tool.execute(goal="g", steps=[{"title": "a"}], extra=1).success is False
    assert tool.execute(goal="g", steps=[{"title": "a"} for _ in range(21)]).success is False


def test_status_defaults_to_pending_and_detail_stripped():
    result = _tool().execute(
        goal=" g ", steps=[{"title": " a ", "detail": "  d  "}]
    )
    assert result.success is True
    stored = get_plan_store().get(resolve_session_id())
    assert stored["goal"] == "g"
    assert stored["steps"][0] == {"title": "a", "detail": "d", "status": "pending"}
