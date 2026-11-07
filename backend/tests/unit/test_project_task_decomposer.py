<<<<<<< HEAD
"""ProjectTaskDecomposer 单元测试 (M1, 2026-10-12)。

覆盖:
- DecomposedMilestone / DecompositionResult dataclass
- _build_prompt()
- _parse_response(): 有效 JSON / markdown 包裹 / 嵌套子任务 / 无效 JSON / 空响应
- _parse_milestone(): 正常 / 无 title / 嵌套 children parent_ref 自动设置
- _safe_float()
- decompose(): LLM 调用 + not available + LLM failure
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.services.project_task_decomposer import (
    DecomposedMilestone,
    DecompositionResult,
    ProjectTaskDecomposer,
    _safe_float,
)

pytestmark = [pytest.mark.unit]


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture()
def mock_llm():
    llm = AsyncMock()
    llm.complete = AsyncMock(
        return_value=json.dumps(
            {
                "reasoning": "分解为认证和数据两个模块",
                "milestones": [
                    {
                        "_ref": "m1",
                        "title": "JWT 认证模块",
                        "description": "实现 token 签发和验证",
                        "stage": "development",
                        "due_date": "2026-10-20",
                        "estimated_days": 5,
                        "children": [
                            {
                                "_ref": "m1_1",
                                "parent_ref": "m1",
                                "title": "设计 token schema",
                                "description": "定义 JWT payload 结构",
                                "estimated_days": 1,
                            },
                            {
                                "_ref": "m1_2",
                                "parent_ref": "m1",
                                "title": "实现签发接口",
                                "description": "POST /auth/login",
                                "estimated_days": 2,
                            },
                        ],
                    },
                    {
                        "_ref": "m2",
                        "title": "用户数据模型",
                        "description": "数据库表设计",
                        "estimated_days": 2,
                    },
                ],
            }
        )
    )
    return llm


@pytest.fixture()
def decomposer(mock_llm):
    return ProjectTaskDecomposer(llm_client=mock_llm)


@pytest.fixture()
def mock_project():
    p = MagicMock()
    p.project_type = "coding"
    p.project_stage = "development"
    p.description = "A coding project"
    p.detected_type = None
    return p


# ── DecomposedMilestone ───────────────────────────────────────────────────────


class TestDecomposedMilestone:
    def test_to_create_dict_basic(self):
        ms = DecomposedMilestone(
            title="Test",
            description="desc",
            stage="dev",
            due_date="2026-10-20",
            estimated_days=3.0,
            sort_order=0,
        )
        d = ms.to_create_dict()
        assert d["title"] == "Test"
        assert d["description"] == "desc"
        assert d["stage"] == "dev"
        assert d["due_date"] == "2026-10-20"
        assert d["estimated_days"] == 3.0
        assert d["sort_order"] == 0
        assert "_ref" not in d

    def test_to_create_dict_with_ref(self):
        ms = DecomposedMilestone(
            title="Test", _ref="m1", parent_ref="parent"
        )
        d = ms.to_create_dict()
        assert d["_ref"] == "m1"
        assert d["parent_id"] == "parent"

    def test_defaults(self):
        ms = DecomposedMilestone(title="Test")
        assert ms.description is None
        assert ms.stage is None
        assert ms.due_date is None
        assert ms.estimated_days is None
        assert ms.sort_order == 0
        assert ms._ref is None
        assert ms.parent_ref is None
        assert ms.children == []


# ── DecompositionResult ──────────────────────────────────────────────────────


class TestDecompositionResult:
    def test_to_create_items_flat(self):
        result = DecompositionResult(
            milestones=[
                DecomposedMilestone(title="A"),
                DecomposedMilestone(title="B"),
            ]
        )
        items = result.to_create_items()
        assert len(items) == 2
        assert items[0]["title"] == "A"
        assert items[0]["sort_order"] == 0
        assert items[1]["title"] == "B"
        assert items[1]["sort_order"] == 1

    def test_to_create_items_nested(self):
        child = DecomposedMilestone(title="Child")
        parent = DecomposedMilestone(title="Parent", children=[child])
        result = DecompositionResult(milestones=[parent])
        items = result.to_create_items()
        assert len(items) == 2
        assert items[0]["title"] == "Parent"
        assert items[0]["sort_order"] == 0
        assert items[1]["title"] == "Child"
        assert items[1]["sort_order"] == 0  # child_index

    def test_to_preview(self):
        child = DecomposedMilestone(
            title="Child", estimated_days=1.0
        )
        parent = DecomposedMilestone(
            title="Parent",
            description="desc",
            stage="dev",
            children=[child],
        )
        result = DecompositionResult(milestones=[parent])
        preview = result.to_preview()
        assert len(preview) == 1
        assert preview[0]["title"] == "Parent"
        assert len(preview[0]["children"]) == 1
        assert preview[0]["children"][0]["title"] == "Child"

    def test_defaults(self):
        result = DecompositionResult(milestones=[])
        assert result.reasoning == ""
        assert result.tokens_used == 0
        assert result.raw_json is None


# ── _parse_response() ─────────────────────────────────────────────────────────


class TestParseResponse:
    def test_valid_json(self, decomposer):
        raw = json.dumps(
            {
                "reasoning": "test",
                "milestones": [
                    {"title": "A", "estimated_days": 2},
                    {"title": "B", "estimated_days": 3},
                ],
            }
        )
        result = decomposer._parse_response(raw)
        assert len(result.milestones) == 2
        assert result.milestones[0].title == "A"
        assert result.reasoning == "test"

    def test_markdown_code_block(self, decomposer):
        raw = (
            "```json\n"
            '{"reasoning": "ok", "milestones": [{"title": "X"}]}\n'
            "```"
        )
        result = decomposer._parse_response(raw)
        assert len(result.milestones) == 1
        assert result.milestones[0].title == "X"

    def test_markdown_code_block_no_lang(self, decomposer):
        raw = (
            "```\n"
            '{"reasoning": "ok", "milestones": [{"title": "Y"}]}\n'
            "```"
        )
        result = decomposer._parse_response(raw)
        assert len(result.milestones) == 1

    def test_json_with_surrounding_text(self, decomposer):
        raw = (
            "Here is the plan:\n"
            '{"reasoning": "ok", "milestones": [{"title": "Z"}]}\n'
            "Done."
        )
        result = decomposer._parse_response(raw)
        assert len(result.milestones) == 1
        assert result.milestones[0].title == "Z"

    def test_nested_children(self, decomposer):
        raw = json.dumps(
            {
                "reasoning": "test",
                "milestones": [
                    {
                        "_ref": "m1",
                        "title": "Parent",
                        "children": [
                            {
                                "_ref": "m1_1",
                                "title": "Child1",
                                "estimated_days": 1,
                            },
                            {
                                "_ref": "m1_2",
                                "title": "Child2",
                                "estimated_days": 2,
                            },
                        ],
                    }
                ],
            }
        )
        result = decomposer._parse_response(raw)
        assert len(result.milestones) == 1
        assert len(result.milestones[0].children) == 2
        assert result.milestones[0].children[0].parent_ref == "m1"

    def test_invalid_json_returns_empty(self, decomposer):
        result = decomposer._parse_response("not json at all")
        assert result.milestones == []
        assert "无法解析" in result.reasoning or "格式错误" in result.reasoning

    def test_empty_response(self, decomposer):
        result = decomposer._parse_response("")
        assert result.milestones == []
        assert "空响应" in result.reasoning

    def test_none_response(self, decomposer):
        result = decomposer._parse_response(None)
        assert result.milestones == []

    def test_milestones_not_list(self, decomposer):
        raw = json.dumps({"reasoning": "test", "milestones": "not a list"})
        result = decomposer._parse_response(raw)
        assert result.milestones == []
        assert "不是列表" in result.reasoning

    def test_milestone_without_title_skipped(self, decomposer):
        raw = json.dumps(
            {
                "reasoning": "test",
                "milestones": [
                    {"description": "no title"},
                    {"title": "Valid", "estimated_days": 1},
                ],
            }
        )
        result = decomposer._parse_response(raw)
        assert len(result.milestones) == 1
        assert result.milestones[0].title == "Valid"


# ── _build_prompt() ──────────────────────────────────────────────────────────


class TestBuildPrompt:
    def test_contains_requirement(self, decomposer, mock_project):
        prompt = decomposer._build_prompt(
            project=mock_project,
            requirement="添加用户认证",
            existing_titles=[],
            stage_enum=None,
            context=None,
        )
        assert "添加用户认证" in prompt
        assert "coding" in prompt

    def test_contains_existing_titles(self, decomposer, mock_project):
        prompt = decomposer._build_prompt(
            project=mock_project,
            requirement="test",
            existing_titles=["已有模块A", "已有模块B"],
            stage_enum=None,
            context=None,
        )
        assert "已有模块A" in prompt
        assert "已有模块B" in prompt
        assert "避免重复" in prompt

    def test_contains_stage_enum(self, decomposer, mock_project):
        prompt = decomposer._build_prompt(
            project=mock_project,
            requirement="test",
            existing_titles=[],
            stage_enum=["planning", "development", "testing"],
            context=None,
        )
        assert "planning" in prompt
        assert "development" in prompt

    def test_contains_context(self, decomposer, mock_project):
        prompt = decomposer._build_prompt(
            project=mock_project,
            requirement="test",
            existing_titles=[],
            stage_enum=None,
            context="补充说明",
        )
        assert "补充说明" in prompt


# ── _safe_float() ────────────────────────────────────────────────────────────


class TestSafeFloat:
    def test_normal_value(self):
        assert _safe_float(3.5) == 3.5

    def test_string_number(self):
        assert _safe_float("2.5") == 2.5

    def test_none(self):
        assert _safe_float(None) is None

    def test_zero_returns_none(self):
        assert _safe_float(0) is None

    def test_negative_returns_none(self):
        assert _safe_float(-1) is None

    def test_invalid_string(self):
        assert _safe_float("abc") is None

    def test_non_numeric(self):
        assert _safe_float([1, 2]) is None


# ── decompose() integration ──────────────────────────────────────────────────


class TestDecompose:
    @pytest.mark.asyncio()
    async def test_decompose_calls_llm(self, decomposer, mock_llm):
        with patch.object(
                decomposer, "_load_project", return_value=MagicMock(
                    project_type="coding",
                    project_stage="dev",
                    description="test",
                    detected_type=None,
                )
            ):
            with patch.object(
                    decomposer, "_get_existing_milestone_titles", return_value=[]
                ):
                with patch.object(
                        decomposer, "_get_stage_enum", return_value=None
                    ):
                    result = await decomposer.decompose(
                        project_id="proj-1",
                        requirement="添加认证系统",
                    )

        mock_llm.complete.assert_called_once()
        assert len(result.milestones) > 0
        assert result.raw_json is not None

    @pytest.mark.asyncio()
    async def test_decompose_not_available(self):
        decomposer = ProjectTaskDecomposer(llm_client=None)
        decomposer._llm = None
        with pytest.raises(RuntimeError, match="不可用"):
            await decomposer.decompose(
                project_id="proj-1",
                requirement="test",
            )

    @pytest.mark.asyncio()
    async def test_decompose_llm_failure(self, decomposer):
        decomposer._llm.complete = AsyncMock(
            side_effect=Exception("LLM timeout")
        )
        with patch.object(
                decomposer, "_load_project", return_value=MagicMock(
                    project_type="coding",
                    project_stage="dev",
                    description="test",
                    detected_type=None,
                )
            ):
            with patch.object(
                    decomposer, "_get_existing_milestone_titles", return_value=[]
                ):
                with patch.object(
                        decomposer, "_get_stage_enum", return_value=None
                    ):
                    with pytest.raises(RuntimeError, match="LLM 调用失败"):
                        await decomposer.decompose(
                            project_id="proj-1",
                            requirement="test",
                        )
=======
"""ProjectTaskDecomposer 单元测试 (M1, 2026-10-12)。

覆盖:
- DecomposedMilestone / DecompositionResult dataclass
- _build_prompt()
- _parse_response(): 有效 JSON / markdown 包裹 / 嵌套子任务 / 无效 JSON / 空响应
- _parse_milestone(): 正常 / 无 title / 嵌套 children parent_ref 自动设置
- _safe_float()
- decompose(): LLM 调用 + not available + LLM failure
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.services.project_task_decomposer import (
    DecomposedMilestone,
    DecompositionResult,
    ProjectTaskDecomposer,
    _safe_float,
)

pytestmark = [pytest.mark.unit]


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture()
def mock_llm():
    llm = AsyncMock()
    llm.complete = AsyncMock(
        return_value=json.dumps(
            {
                "reasoning": "分解为认证和数据两个模块",
                "milestones": [
                    {
                        "_ref": "m1",
                        "title": "JWT 认证模块",
                        "description": "实现 token 签发和验证",
                        "stage": "development",
                        "due_date": "2026-10-20",
                        "estimated_days": 5,
                        "children": [
                            {
                                "_ref": "m1_1",
                                "parent_ref": "m1",
                                "title": "设计 token schema",
                                "description": "定义 JWT payload 结构",
                                "estimated_days": 1,
                            },
                            {
                                "_ref": "m1_2",
                                "parent_ref": "m1",
                                "title": "实现签发接口",
                                "description": "POST /auth/login",
                                "estimated_days": 2,
                            },
                        ],
                    },
                    {
                        "_ref": "m2",
                        "title": "用户数据模型",
                        "description": "数据库表设计",
                        "estimated_days": 2,
                    },
                ],
            }
        )
    )
    return llm


@pytest.fixture()
def decomposer(mock_llm):
    return ProjectTaskDecomposer(llm_client=mock_llm)


@pytest.fixture()
def mock_project():
    p = MagicMock()
    p.project_type = "coding"
    p.project_stage = "development"
    p.description = "A coding project"
    p.detected_type = None
    return p


# ── DecomposedMilestone ───────────────────────────────────────────────────────


class TestDecomposedMilestone:
    def test_to_create_dict_basic(self):
        ms = DecomposedMilestone(
            title="Test",
            description="desc",
            stage="dev",
            due_date="2026-10-20",
            estimated_days=3.0,
            sort_order=0,
        )
        d = ms.to_create_dict()
        assert d["title"] == "Test"
        assert d["description"] == "desc"
        assert d["stage"] == "dev"
        assert d["due_date"] == "2026-10-20"
        assert d["estimated_days"] == 3.0
        assert d["sort_order"] == 0
        assert "_ref" not in d

    def test_to_create_dict_with_ref(self):
        ms = DecomposedMilestone(
            title="Test", _ref="m1", parent_ref="parent"
        )
        d = ms.to_create_dict()
        assert d["_ref"] == "m1"
        assert d["parent_id"] == "parent"

    def test_defaults(self):
        ms = DecomposedMilestone(title="Test")
        assert ms.description is None
        assert ms.stage is None
        assert ms.due_date is None
        assert ms.estimated_days is None
        assert ms.sort_order == 0
        assert ms._ref is None
        assert ms.parent_ref is None
        assert ms.children == []


# ── DecompositionResult ──────────────────────────────────────────────────────


class TestDecompositionResult:
    def test_to_create_items_flat(self):
        result = DecompositionResult(
            milestones=[
                DecomposedMilestone(title="A"),
                DecomposedMilestone(title="B"),
            ]
        )
        items = result.to_create_items()
        assert len(items) == 2
        assert items[0]["title"] == "A"
        assert items[0]["sort_order"] == 0
        assert items[1]["title"] == "B"
        assert items[1]["sort_order"] == 1

    def test_to_create_items_nested(self):
        child = DecomposedMilestone(title="Child")
        parent = DecomposedMilestone(title="Parent", children=[child])
        result = DecompositionResult(milestones=[parent])
        items = result.to_create_items()
        assert len(items) == 2
        assert items[0]["title"] == "Parent"
        assert items[0]["sort_order"] == 0
        assert items[1]["title"] == "Child"
        assert items[1]["sort_order"] == 0  # child_index

    def test_to_preview(self):
        child = DecomposedMilestone(
            title="Child", estimated_days=1.0
        )
        parent = DecomposedMilestone(
            title="Parent",
            description="desc",
            stage="dev",
            children=[child],
        )
        result = DecompositionResult(milestones=[parent])
        preview = result.to_preview()
        assert len(preview) == 1
        assert preview[0]["title"] == "Parent"
        assert len(preview[0]["children"]) == 1
        assert preview[0]["children"][0]["title"] == "Child"

    def test_defaults(self):
        result = DecompositionResult(milestones=[])
        assert result.reasoning == ""
        assert result.tokens_used == 0
        assert result.raw_json is None


# ── _parse_response() ─────────────────────────────────────────────────────────


class TestParseResponse:
    def test_valid_json(self, decomposer):
        raw = json.dumps(
            {
                "reasoning": "test",
                "milestones": [
                    {"title": "A", "estimated_days": 2},
                    {"title": "B", "estimated_days": 3},
                ],
            }
        )
        result = decomposer._parse_response(raw)
        assert len(result.milestones) == 2
        assert result.milestones[0].title == "A"
        assert result.reasoning == "test"

    def test_markdown_code_block(self, decomposer):
        raw = (
            "```json\n"
            '{"reasoning": "ok", "milestones": [{"title": "X"}]}\n'
            "```"
        )
        result = decomposer._parse_response(raw)
        assert len(result.milestones) == 1
        assert result.milestones[0].title == "X"

    def test_markdown_code_block_no_lang(self, decomposer):
        raw = (
            "```\n"
            '{"reasoning": "ok", "milestones": [{"title": "Y"}]}\n'
            "```"
        )
        result = decomposer._parse_response(raw)
        assert len(result.milestones) == 1

    def test_json_with_surrounding_text(self, decomposer):
        raw = (
            "Here is the plan:\n"
            '{"reasoning": "ok", "milestones": [{"title": "Z"}]}\n'
            "Done."
        )
        result = decomposer._parse_response(raw)
        assert len(result.milestones) == 1
        assert result.milestones[0].title == "Z"

    def test_nested_children(self, decomposer):
        raw = json.dumps(
            {
                "reasoning": "test",
                "milestones": [
                    {
                        "_ref": "m1",
                        "title": "Parent",
                        "children": [
                            {
                                "_ref": "m1_1",
                                "title": "Child1",
                                "estimated_days": 1,
                            },
                            {
                                "_ref": "m1_2",
                                "title": "Child2",
                                "estimated_days": 2,
                            },
                        ],
                    }
                ],
            }
        )
        result = decomposer._parse_response(raw)
        assert len(result.milestones) == 1
        assert len(result.milestones[0].children) == 2
        assert result.milestones[0].children[0].parent_ref == "m1"

    def test_invalid_json_returns_empty(self, decomposer):
        result = decomposer._parse_response("not json at all")
        assert result.milestones == []
        assert "无法解析" in result.reasoning or "格式错误" in result.reasoning

    def test_empty_response(self, decomposer):
        result = decomposer._parse_response("")
        assert result.milestones == []
        assert "空响应" in result.reasoning

    def test_none_response(self, decomposer):
        result = decomposer._parse_response(None)
        assert result.milestones == []

    def test_milestones_not_list(self, decomposer):
        raw = json.dumps({"reasoning": "test", "milestones": "not a list"})
        result = decomposer._parse_response(raw)
        assert result.milestones == []
        assert "不是列表" in result.reasoning

    def test_milestone_without_title_skipped(self, decomposer):
        raw = json.dumps(
            {
                "reasoning": "test",
                "milestones": [
                    {"description": "no title"},
                    {"title": "Valid", "estimated_days": 1},
                ],
            }
        )
        result = decomposer._parse_response(raw)
        assert len(result.milestones) == 1
        assert result.milestones[0].title == "Valid"


# ── _build_prompt() ──────────────────────────────────────────────────────────


class TestBuildPrompt:
    def test_contains_requirement(self, decomposer, mock_project):
        prompt = decomposer._build_prompt(
            project=mock_project,
            requirement="添加用户认证",
            existing_titles=[],
            stage_enum=None,
            context=None,
        )
        assert "添加用户认证" in prompt
        assert "coding" in prompt

    def test_contains_existing_titles(self, decomposer, mock_project):
        prompt = decomposer._build_prompt(
            project=mock_project,
            requirement="test",
            existing_titles=["已有模块A", "已有模块B"],
            stage_enum=None,
            context=None,
        )
        assert "已有模块A" in prompt
        assert "已有模块B" in prompt
        assert "避免重复" in prompt

    def test_contains_stage_enum(self, decomposer, mock_project):
        prompt = decomposer._build_prompt(
            project=mock_project,
            requirement="test",
            existing_titles=[],
            stage_enum=["planning", "development", "testing"],
            context=None,
        )
        assert "planning" in prompt
        assert "development" in prompt

    def test_contains_context(self, decomposer, mock_project):
        prompt = decomposer._build_prompt(
            project=mock_project,
            requirement="test",
            existing_titles=[],
            stage_enum=None,
            context="补充说明",
        )
        assert "补充说明" in prompt


# ── _safe_float() ────────────────────────────────────────────────────────────


class TestSafeFloat:
    def test_normal_value(self):
        assert _safe_float(3.5) == 3.5

    def test_string_number(self):
        assert _safe_float("2.5") == 2.5

    def test_none(self):
        assert _safe_float(None) is None

    def test_zero_returns_none(self):
        assert _safe_float(0) is None

    def test_negative_returns_none(self):
        assert _safe_float(-1) is None

    def test_invalid_string(self):
        assert _safe_float("abc") is None

    def test_non_numeric(self):
        assert _safe_float([1, 2]) is None


# ── decompose() integration ──────────────────────────────────────────────────


class TestDecompose:
    @pytest.mark.asyncio()
    async def test_decompose_calls_llm(self, decomposer, mock_llm):
        with (
            patch.object(
                decomposer, "_load_project", return_value=MagicMock(
                    project_type="coding",
                    project_stage="dev",
                    description="test",
                    detected_type=None,
                )
            ),
            patch.object(
                decomposer, "_get_existing_milestone_titles", return_value=[]
            ),
            patch.object(
                decomposer, "_get_stage_enum", return_value=None
            ),
        ):
            result = await decomposer.decompose(
                project_id="proj-1",
                requirement="添加认证系统",
            )

        mock_llm.complete.assert_called_once()
        assert len(result.milestones) > 0
        assert result.raw_json is not None

    @pytest.mark.asyncio()
    async def test_decompose_not_available(self):
        decomposer = ProjectTaskDecomposer(llm_client=None)
        decomposer._llm = None
        with pytest.raises(RuntimeError, match="不可用"):
            await decomposer.decompose(
                project_id="proj-1",
                requirement="test",
            )

    @pytest.mark.asyncio()
    async def test_decompose_llm_failure(self, decomposer):
        decomposer._llm.complete = AsyncMock(
            side_effect=Exception("LLM timeout")
        )
        with (  # noqa: SIM117
            patch.object(
                decomposer, "_load_project", return_value=MagicMock(
                    project_type="coding",
                    project_stage="dev",
                    description="test",
                    detected_type=None,
                )
            ),
            patch.object(
                decomposer, "_get_existing_milestone_titles", return_value=[]
            ),
            patch.object(
                decomposer, "_get_stage_enum", return_value=None
            ),
        ):
            with pytest.raises(RuntimeError, match="LLM 调用失败"):
                await decomposer.decompose(
                    project_id="proj-1",
                    requirement="test",
                )
>>>>>>> origin/main
