"""skill_save 工具单元测试。

覆盖:
1. 校验失败:name 为空 / description 缺省 / when_to_use 非字符串 / tool_sequence 非 list
2. 正常路径:返回 draft_id + status="pending"
3. normalizer 注入:确认脏 tool_sequence 被裁剪到 ≤20
4. store.insert 被调用一次
5. 失败模式:review pipeline ValueError → 明确 error,store.insert 不被调
6. 失败模式:store.insert 抛异常 → 明确 error
7. Schema 声明必填字段
"""

from __future__ import annotations

import json
from typing import Any, Dict, List
from unittest.mock import AsyncMock, Mock, patch

import pytest

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_draft(name: str = "academic-search-cnki") -> Mock:
    draft = Mock()
    draft.id = "draft-uuid-1234"
    draft.name = name
    draft.status = "pending"
    return draft


def _make_review_service(draft: Mock) -> Mock:
    service = Mock()
    service.generate_draft = AsyncMock(return_value=draft)
    return service


def _make_store() -> Mock:
    store = Mock()
    store.insert = Mock()
    return store


def _ok_call(tool: str = "web_fetch") -> Dict[str, Any]:
    return {"tool": tool, "args": {"url": "https://example.com"}}


# ---------------------------------------------------------------------------
# 1. 校验失败:各类缺字段/类型错
# ---------------------------------------------------------------------------


class TestValidationFailures:
    def test_missing_name_returns_error(self):
        from backend.tools.skill_save_tool import SkillSaveTool

        tool = SkillSaveTool()
        result = tool.execute(
            name="",
            description="desc",
            when_to_use="when the user asks to search academic papers",
            tool_sequence=[_ok_call()],
        )
        assert result.success is False
        assert "name" in result.error

    def test_missing_description_returns_error(self):
        from backend.tools.skill_save_tool import SkillSaveTool

        tool = SkillSaveTool()
        result = tool.execute(
            name="academic-search",
            description="",
            when_to_use="when the user asks to search academic papers",
            tool_sequence=[_ok_call()],
        )
        assert result.success is False
        assert "description" in result.error

    def test_missing_when_to_use_returns_error(self):
        from backend.tools.skill_save_tool import SkillSaveTool

        tool = SkillSaveTool()
        result = tool.execute(
            name="academic-search",
            description="desc",
            when_to_use="",
            tool_sequence=[_ok_call()],
        )
        assert result.success is False
        assert "when_to_use" in result.error

    def test_tool_sequence_must_be_list(self):
        from backend.tools.skill_save_tool import SkillSaveTool

        tool = SkillSaveTool()
        result = tool.execute(
            name="academic-search",
            description="desc",
            when_to_use="when the user asks to search academic papers",
            tool_sequence="not-a-list",  # type: ignore[arg-type]
        )
        assert result.success is False
        assert "tool_sequence" in result.error


# ---------------------------------------------------------------------------
# 2. 正常路径
# ---------------------------------------------------------------------------


class TestSuccessPath:
    """happy path: normalizer → generate_draft → store.insert → 返回"""

    def test_normal_success_returns_draft_id(self):
        from backend.tools.skill_save_tool import SkillSaveTool

        draft = _make_draft()
        service = _make_review_service(draft)
        store = _make_store()

        tool = SkillSaveTool()
        with (
            patch(
                "backend.tools.skill_save_tool.get_review_service",
                return_value=service,
            ),
            patch(
                "backend.tools.skill_save_tool.get_skill_draft_store",
                return_value=store,
            ),
        ):
            result = tool.execute(
                name="academic-search-cnki",
                description="CNKI 学术检索",
                when_to_use="当用户在 CNKI 检索学术文献时",
                tool_sequence=[_ok_call("web_fetch"), _ok_call("ask_user_question")],
                session_id="sess-1",
            )

        assert result.success is True
        assert result.output == "draft-uuid-1234"
        assert result.content["draft_id"] == "draft-uuid-1234"
        assert result.content["name"] == "academic-search-cnki"
        assert result.content["status"] == "pending"

    def test_normalizer_truncates_dirty_tool_sequence(self):
        """确认 normalizer 被调用 — 传入 25 条脏数据后,context.tool_calls ≤20"""
        from backend.tools.skill_save_tool import SkillSaveTool

        draft = _make_draft()
        service = _make_review_service(draft)
        store = _make_store()

        seq: List[Dict[str, Any]] = []
        for i in range(15):
            seq.append(_ok_call(f"tool_{i}"))
        seq.append({"args": {}})  # 缺 tool
        seq.append({"tool": "x"})  # 缺 args
        seq.append("not-a-dict")  # 非 dict
        for i in range(7):
            seq.append(_ok_call(f"later_tool_{i}"))

        tool = SkillSaveTool()
        with (
            patch(
                "backend.tools.skill_save_tool.get_review_service",
                return_value=service,
            ),
            patch(
                "backend.tools.skill_save_tool.get_skill_draft_store",
                return_value=store,
            ),
        ):
            result = tool.execute(
                name="academic-search-cnki",
                description="CNKI 学术检索",
                when_to_use="当用户在 CNKI 检索学术文献时",
                tool_sequence=seq,
            )

        assert result.success is True
        ctx_arg = service.generate_draft.call_args.kwargs["context"]
        assert len(ctx_arg["tool_calls"]) == 20
        ctx_arg_json = json.dumps(ctx_arg, ensure_ascii=False)
        assert "user_provided_name" in ctx_arg_json

    def test_store_insert_called_exactly_once(self):
        from backend.tools.skill_save_tool import SkillSaveTool

        draft = _make_draft()
        service = _make_review_service(draft)
        store = _make_store()

        tool = SkillSaveTool()
        with (
            patch(
                "backend.tools.skill_save_tool.get_review_service",
                return_value=service,
            ),
            patch(
                "backend.tools.skill_save_tool.get_skill_draft_store",
                return_value=store,
            ),
        ):
            tool.execute(
                name="academic-search-cnki",
                description="CNKI 学术检索",
                when_to_use="当用户在 CNKI 检索学术文献时",
                tool_sequence=[_ok_call()],
            )

        store.insert.assert_called_once_with(draft)


# ---------------------------------------------------------------------------
# 3. 失败模式
# ---------------------------------------------------------------------------


class TestFailureModes:
    def test_review_pipeline_value_error_returns_clear_error(self):
        """LLM 输出不合规时 generate_draft 抛 ValueError,skill_save 不静默吞"""
        from backend.tools.skill_save_tool import SkillSaveTool

        service = Mock()
        service.generate_draft = AsyncMock(
            side_effect=ValueError("name 必须是 kebab-case")
        )
        store = _make_store()

        tool = SkillSaveTool()
        with (
            patch(
                "backend.tools.skill_save_tool.get_review_service",
                return_value=service,
            ),
            patch(
                "backend.tools.skill_save_tool.get_skill_draft_store",
                return_value=store,
            ),
        ):
            result = tool.execute(
                name="academic-search-cnki",
                description="CNKI 学术检索",
                when_to_use="当用户在 CNKI 检索学术文献时",
                tool_sequence=[_ok_call()],
            )

        assert result.success is False
        assert "review pipeline 拒绝草稿" in result.error
        store.insert.assert_not_called()

    def test_store_insert_failure_returns_clear_error(self):
        """草稿已生成但持久化失败时,返回明确 error"""
        from backend.tools.skill_save_tool import SkillSaveTool

        draft = _make_draft()
        service = _make_review_service(draft)
        store = Mock()
        store.insert = Mock(side_effect=RuntimeError("sqlite locked"))

        tool = SkillSaveTool()
        with (
            patch(
                "backend.tools.skill_save_tool.get_review_service",
                return_value=service,
            ),
            patch(
                "backend.tools.skill_save_tool.get_skill_draft_store",
                return_value=store,
            ),
        ):
            result = tool.execute(
                name="academic-search-cnki",
                description="CNKI 学术检索",
                when_to_use="当用户在 CNKI 检索学术文献时",
                tool_sequence=[_ok_call()],
            )

        assert result.success is False
        assert "持久化失败" in result.error


# ---------------------------------------------------------------------------
# 4. Schema
# ---------------------------------------------------------------------------


def test_schema_declares_required_fields():
    from backend.tools.skill_save_tool import SkillSaveTool

    tool = SkillSaveTool()
    schema = tool.schema
    assert schema.name == "skill_save"
    required = schema.parameters["required"]
    assert "name" in required
    assert "description" in required
    assert "when_to_use" in required
    assert "tool_sequence" in required
