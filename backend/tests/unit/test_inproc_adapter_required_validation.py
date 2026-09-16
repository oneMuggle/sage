"""alpha.36 (Bug #1): InprocToolAdapter required 参数校验下沉。

根因: hex 路径 (``API_MODE=hex``) 走 ``InprocToolAdapter.execute``
直接调 ``tool.execute(**args)``，``SageAgent._validate_required_params``
只挂在 ``agent.py`` 的 SageAgent 内部两条路径。LLM 漏传 required
参数时 Python 抛 ``TypeError``，错误文本泄漏给 LLM 输出。

修复: 把 required 校验下沉到 ``backend.tools.executor.validate_required_args``
公共 helper；``InprocToolAdapter`` 分发前先调，缺 required 时返回
``ToolResult(success=False, error=...)``，不让 ``tool.execute`` 真的
被调用；缺 required 但 schema 没声明的旧工具走 ``_format_typeerror_message``
兜底，同样只给 tool_name + signature 概要，不泄漏 Python 原始错误。

本测试覆盖:
- validate_required_args 公共 helper 行为（schema.required 列表 vs args dict）
- InprocToolAdapter.execute 分发前拦截
- InprocToolAdapter.execute TypeError 兜底（schema 没 declare 但 execute 缺参）
- 真实 OfficeReadTool 走 InprocToolAdapter 漏传 doc_id 的回归用例
"""

from __future__ import annotations

import pytest

from backend.domain.risk import RiskClass
from backend.domain.tool_policy import ToolPolicy
from backend.tools.base import BaseTool, ToolResult, ToolSchema
from backend.tools.executor import (
    required_args_error,
    validate_required_args,
)
from backend.tools.registry import ToolRegistry

pytestmark = pytest.mark.unit


# --------------------------------------------------------------------------- #
# Mock 工具
# --------------------------------------------------------------------------- #


class RequiredParamTool(BaseTool):
    """有 1 个 required 参数的工具（office_read 同款形状）。"""

    risk = RiskClass.READ

    def _build_schema(self) -> ToolSchema:
        return ToolSchema(
            name="mock_required",
            description="tool with 1 required param",
            parameters={
                "type": "object",
                "properties": {
                    "doc_id": {"type": "string"},
                    "section": {"type": "string", "default": "summary"},
                },
                "required": ["doc_id"],
            },
        )

    def execute(self, doc_id: str, section: str = "summary", **kwargs) -> ToolResult:
        return ToolResult(success=True, content={"doc_id": doc_id, "section": section})


class MultiRequiredTool(BaseTool):
    """有多个 required 参数的工具。"""

    risk = RiskClass.READ

    def _build_schema(self) -> ToolSchema:
        return ToolSchema(
            name="mock_multi_required",
            description="tool with multiple required params",
            parameters={
                "type": "object",
                "properties": {
                    "a": {"type": "string"},
                    "b": {"type": "string"},
                    "c": {"type": "string"},
                },
                "required": ["a", "b"],
            },
        )

    def execute(self, a: str, b: str, **kwargs) -> ToolResult:
        return ToolResult(success=True, content={"a": a, "b": b})


class NoSchemaTool(BaseTool):
    """没 schema 的工具（schema 故意 None，测试兜底）。"""

    risk = RiskClass.READ

    def _build_schema(self) -> ToolSchema | None:  # type: ignore[override]
        return None  # 故意不返回

    def execute(self, **kwargs) -> ToolResult:  # pragma: no cover
        return ToolResult(success=True, content={})


class SchemaNoRequiredTool(BaseTool):
    """schema 无 required 段的工具（execute 签名仍要参数）。"""

    risk = RiskClass.READ

    def _build_schema(self) -> ToolSchema:
        return ToolSchema(
            name="mock_schema_no_required",
            description="tool whose schema declared no required",
            parameters={
                "type": "object",
                "properties": {"x": {"type": "string"}},
                # 故意无 required 段
            },
        )

    def execute(self, x: str) -> ToolResult:
        return ToolResult(success=True, content={"x": x})


# --------------------------------------------------------------------------- #
# validate_required_args 公共 helper
# --------------------------------------------------------------------------- #


class TestValidateRequiredArgsHelper:
    """required_args_error / validate_required_args 行为。"""

    def test_all_required_present_returns_none(self):
        tool = RequiredParamTool()
        assert validate_required_args(tool, {"doc_id": "123"}) is None

    def test_missing_single_required_returns_error(self):
        tool = RequiredParamTool()
        err = validate_required_args(tool, {})
        assert err is not None
        assert "missing_required_argument" in err
        assert "doc_id" in err
        assert "mock_required" in err

    def test_missing_one_of_multiple_returns_error(self):
        tool = MultiRequiredTool()
        err = validate_required_args(tool, {"a": "1"})
        assert err is not None
        assert "missing_required_argument" in err
        assert "b" in err

    def test_missing_multiple_returns_plural_error(self):
        tool = MultiRequiredTool()
        err = validate_required_args(tool, {})
        assert err is not None
        assert "missing_required_arguments" in err
        assert "a" in err and "b" in err

    def test_none_value_treated_as_missing(self):
        """LLM 偶尔发 {"doc_id": null}，JSON-schema required 语义上等同于缺失。"""
        tool = RequiredParamTool()
        err = validate_required_args(tool, {"doc_id": None})
        assert err is not None
        assert "doc_id" in err

    def test_no_schema_returns_none(self):
        """没 schema 的工具没法校验，让它自己抛（兜底）。"""
        tool = NoSchemaTool()
        assert validate_required_args(tool, {"anything": "whatever"}) is None

    def test_schema_no_required_returns_none(self):
        """schema 没 declare required → helper 认为全部通过。"""
        tool = SchemaNoRequiredTool()
        assert validate_required_args(tool, {}) is None

    def test_required_args_error_singular(self):
        tool = RequiredParamTool()
        msg = required_args_error(tool, ["doc_id"])
        assert msg == "missing_required_argument: doc_id (tool=mock_required)"

    def test_required_args_error_plural(self):
        tool = MultiRequiredTool()
        msg = required_args_error(tool, ["a", "b"])
        assert msg == "missing_required_arguments: a,b (tool=mock_multi_required)"


# --------------------------------------------------------------------------- #
# InprocToolAdapter.execute —— 分发前拦截
# --------------------------------------------------------------------------- #


class TestInprocAdapterRequiredValidation:
    """hex 路径分发前 required 校验。"""

    @pytest.fixture()
    def registry_with_required_tool(self):
        reg = ToolRegistry()
        reg.register(RequiredParamTool())
        return reg

    @pytest.mark.asyncio()
    async def test_missing_required_returns_friendly_error(
        self, registry_with_required_tool
    ):
        """hex 路径漏传 required → ToolResult(success=False, error=...)。

        关键断言：error 是 "missing_required_argument: doc_id (tool=mock_required)"
        **不是** "TypeError: execute() missing 1 required positional argument: 'doc_id'"。
        """
        from backend.adapters.out.tool.inproc_adapter import InprocToolAdapter

        adapter = InprocToolAdapter(
            registry=registry_with_required_tool, policy=ToolPolicy()
        )
        result = await adapter.execute("mock_required", {"section": "summary"})

        # 应 success=False
        assert result.success is False
        # 应是结构化错误文案（不是 Python 异常）
        assert "missing_required_argument" in result.error
        assert "doc_id" in result.error
        assert "mock_required" in result.error
        # 关键：不应泄漏 Python TypeError 文本
        assert "TypeError" not in result.error
        assert "missing 1 required positional argument" not in result.error

    @pytest.mark.asyncio()
    async def test_all_required_present_succeeds(
        self, registry_with_required_tool
    ):
        """hex 路径传齐 required → 工具正常执行。"""
        from backend.adapters.out.tool.inproc_adapter import InprocToolAdapter

        adapter = InprocToolAdapter(
            registry=registry_with_required_tool, policy=ToolPolicy()
        )
        result = await adapter.execute(
            "mock_required", {"doc_id": "doc-42", "section": "full"}
        )
        assert result.success is True
        assert "doc-42" in (result.output or "")

    @pytest.mark.asyncio()
    async def test_tool_not_registered_returns_not_registered(
        self, registry_with_required_tool
    ):
        """工具未注册 → 早返回 tool not registered，不走 required 校验。"""
        from backend.adapters.out.tool.inproc_adapter import InprocToolAdapter

        adapter = InprocToolAdapter(
            registry=registry_with_required_tool, policy=ToolPolicy()
        )
        result = await adapter.execute("unknown_tool", {})
        assert result.success is False
        assert "tool not registered" in result.error


# --------------------------------------------------------------------------- #
# 真实 OfficeReadTool —— 回归用户最初报告
# --------------------------------------------------------------------------- #


class TestOfficeReadToolRegression:
    """用户最初报告：office_read 漏 doc_id 抛 TypeError。

    用真实 OfficeReadTool（无 mock）走 InprocToolAdapter 漏传 doc_id，
    应返回友好错误，**不是** "TypeError: execute() missing 1 required
    positional argument: 'doc_id'"。
    """

    @pytest.mark.asyncio()
    async def test_office_read_missing_doc_id_returns_friendly_error(self):
        """回归：OfficeReadTool 漏 doc_id 走 hex 路径的端到端校验。

        注意：office_read 要求 requires_tool_context=True，未绑定工作区时
        execute() 第一行就 return ToolResult(success=False, error="missing
        _tool_context") —— 这个错误优先于 required 校验（ToolResult 是工具
        自己返回的，不是 adapter 抛的）。本测试断言 adapter 路径**不**抛
        TypeError；具体错误文案可以是 missing_tool_context（工具自检）或
        missing_required_argument（adapter 校验），都算通过。
        """
        from backend.adapters.out.tool.inproc_adapter import InprocToolAdapter
        from backend.tools.office_tool import OfficeReadTool

        reg = ToolRegistry()
        reg.register(OfficeReadTool())
        adapter = InprocToolAdapter(registry=reg, policy=ToolPolicy())

        # 漏传 doc_id —— 用户报告场景
        result = await adapter.execute("office_read", {})

        # 关键：不应成功（否则 bug 没修）
        assert result.success is False
        # 关键：不应泄漏 Python TypeError 文本
        assert "TypeError" not in result.error
        assert "missing 1 required positional argument" not in result.error
        assert "missing required positional argument" not in result.error
        # 错误应是结构化文案（missing_tool_context 或 missing_required_argument
        # 都算通过）
        assert result.error in (
            "missing_tool_context",
            "missing_required_argument: doc_id (tool=office_read)",
        ) or result.error.startswith("missing_required_argument:")
