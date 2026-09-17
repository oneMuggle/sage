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


class TestAbnormalExitErrorSerialization:
    """回归测试: 子进程异常退出时 ToolResult.error 必须是字符串,
    而非 dict (避免穿透到前端 React 触发 'Objects are not valid as a React child')。

    历史 bug (2026-09-17 win7 安装包):
    - execute_code_tool._run 的 `if final is None` 分支把 error 字段写成 dict
    - dict 穿透到 Message.tsx ToolCallResult 组件直接渲染 → Minified React error #31
    """

    def _make_abnormal_process(self, stderr_text: str, exit_code: int = 1):
        """构造一个假 subprocess.Popen 返回值:
        - stdout/stderr 立即 EOF (reader 立即结束, 触发 done_event.set)
        - returncode 非零
        - 不发出任何 RPC_PREFIX/done 行 → 触发 `final is None` 分支
        """

        class _FakeStream:
            def __init__(self, content: str):
                self._content = content
                self._closed = False

            def readline(self):
                if self._closed or not self._content:
                    return ""
                if "\n" in self._content:
                    line, self._content = self._content.split("\n", 1)
                    return line + "\n"
                line, self._content = self._content, ""
                return line

            def close(self):
                self._closed = True

        class _FakeProcess:
            def __init__(self):
                self.stdin = _FakeStream("")
                self.stdout = _FakeStream("")
                self.stderr = _FakeStream(stderr_text)
                self.returncode = exit_code

            def poll(self):
                return self.returncode

            def kill(self):
                pass

            def wait(self, timeout=None):  # noqa: ARG001 — 模拟上游接口
                return self.returncode

        return _FakeProcess()

    def test_abnormal_exit_returns_string_error_not_dict(self, monkeypatch, tool):
        """子进程异常退出 + stderr 有内容 → error 必须是字符串 (JSON 序列化)"""
        import subprocess as sp

        fake = self._make_abnormal_process("FATAL: out of memory\n", exit_code=137)

        monkeypatch.setattr(sp, "Popen", lambda *a, **kw: fake)
        monkeypatch.setattr(tool, "_write_script", lambda code: "/tmp/_fake_script.py")

        result = tool.execute(code="x = 1")

        assert result.success is False
        # 核心断言: error 必须是 str, 不能是 dict
        assert isinstance(result.error, str), (
            f"ToolResult.error must be str, got {type(result.error).__name__}: {result.error!r}"
        )
        # 内容必须包含子进程退出提示和 stderr 截断
        assert "子进程异常退出" in result.error
        assert "out of memory" in result.error
        # 验证是合法 JSON (治本方案: 把 dict 用 json.dumps 序列化)
        import json

        parsed = json.loads(result.error)
        assert parsed["exit_code"] == 137
        assert "out of memory" in parsed["stderr"]

    def test_abnormal_exit_no_stderr_returns_plain_string(self, monkeypatch, tool):
        """子进程异常退出 + stderr 为空 → error 退化为纯字符串, 不抛 JSON 序列化错误"""
        import subprocess as sp

        fake = self._make_abnormal_process("", exit_code=1)

        monkeypatch.setattr(sp, "Popen", lambda *a, **kw: fake)
        monkeypatch.setattr(tool, "_write_script", lambda code: "/tmp/_fake_script.py")

        result = tool.execute(code="x = 1")

        assert result.success is False
        assert isinstance(result.error, str)
        assert "子进程异常退出" in result.error
