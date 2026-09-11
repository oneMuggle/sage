"""ExecuteCode Tool 测试（Round 8: 零上下文 RPC 工具调用）"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from backend.tools.execute_code_tool import ExecuteCodeTool

pytestmark = pytest.mark.unit


def _result_value(result):
    return result.content.get("result") if result.content else None


class _FakeCalc:
    def execute(self, **arguments):
        value = eval(arguments.get("expression", "0"), {"__builtins__": {}})  # noqa: S307 — 测试替身
        return SimpleNamespace(success=True, content={"result": value}, output=value)


class _FakeBroken:
    def execute(self, **arguments):
        raise RuntimeError("boom")


class FakeRegistry:
    """最小注册表 —— calculator + 恒失败工具"""

    def __init__(self):
        self.calls: list = []

    def get(self, name):
        self.calls.append(name)
        if name == "calculator":
            return _FakeCalc()
        if name == "broken":
            return _FakeBroken()
        return None


@pytest.fixture()
def tool(tmp_db=None):
    return ExecuteCodeTool(registry=FakeRegistry())


class TestBasicExecution:
    def test_plain_code_no_rpc(self, tool):
        result = tool.execute(code="print('hi')\nx = 1 + 1")
        assert result.success is True
        content = result.content
        assert content["rpc_calls"] == 0
        assert "hi" in content["stderr"]  # 用户 print 重定向到 stderr

    def test_rpc_call_returns_value(self, tool):
        result = tool.execute(
            code="v = sage.call('calculator', expression='6*7')\nprint(v)"
        )
        assert result.success is True
        assert result.content["rpc_calls"] == 1
        assert result.content["result"] is None
        assert "42" in result.content["stderr"]

    def test_rpc_loop_many_calls_one_roundtrip(self, tool):
        """循环内 N 次 sage.call —— 零上下文调用的核心收益"""
        code = (
            "total = 0\n"
            "for i in range(5):\n"
            "    total += sage.call('calculator', expression=str(i)) or 0\n"
            "print(total)"
        )
        result = tool.execute(code=code)
        assert result.success is True
        assert result.content["rpc_calls"] == 5
        assert "10" in result.content["stderr"]

    def test_rpc_error_raises_runtime_error_in_script(self, tool):
        code = (
            "try:\n"
            "    sage.call('broken')\n"
            "    print('no')\n"
            "except RuntimeError as e:\n"
            "    print('caught:', e)"
        )
        result = tool.execute(code=code)
        assert result.success is True
        assert "caught: boom" in result.content["stderr"]

    def test_unknown_tool_error_surfaces(self, tool):
        code = "sage.call('no-such-tool')"
        result = tool.execute(code=code)
        assert result.success is False
        assert "工具不存在" in (result.content or {}).get("error", "")


class TestValidationAndTimeout:
    def test_empty_code_rejected(self, tool):
        assert tool.execute(code="   ").success is False

    def test_unknown_kwargs_rejected(self, tool):
        assert tool.execute(code="x=1", bogus=1).success is False

    def test_timeout_kills_subprocess(self, tool):
        result = tool.execute(code="while True:\n    pass", timeout=1)
        assert result.success is False
        assert "超时" in (result.error or "")

    def test_syntax_error_reports_failure(self, tool):
        result = tool.execute(code="def broken(:")
        assert result.success is False
