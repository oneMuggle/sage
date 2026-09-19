# ruff: noqa: UP006, UP007, UP035, UP045 — release/win7 Python 3.8 兼容，保留 typing 注解
"""runtime 三工具的输出契约测试。

``runtime_probe`` / ``project_diagnose`` / ``runtime_exec`` 同时设置两个字段：

- ``content``：结构化 ``dict``（``base.ToolResult`` 契约里 content 是结构化结果）
- ``output``：等价 JSON **字符串**，供 ``InprocToolAdapter`` 按字符串契约转发，
  再由 ``runtime REST`` 路由层 ``json.loads`` 还原给前端

两者缺一不可，因为下游有两个互不相同的消费者：

1. ``backend/cli/checks/runtime_env.py`` 的 doctor 检查**直接**调用工具并读
   ``result.content["runtimes"]`` —— 要求 content 是 dict；
2. ``InprocToolAdapter`` 优先取 ``output`` 并 ``str()`` 转发 —— 要求 output 是
   JSON 文本（若只有 content，``str(dict)`` 得到 Python repr 单引号文本，
   ``json.loads`` 会失败）。

本文件的存在理由：这两个消费者此前**没有任何测试覆盖**。content 一度被误改成
JSON 字符串而无人发现，导致 ``doctor`` 静默误报
``CRITICAL 探测到 Python ×0``（详见 test_doctor_runtime_env_does_not_false_alarm）。
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any, Dict

import pytest

from backend.cli.checks.runtime_env import RuntimeEnvCheck
from backend.cli.doctor import Severity
from backend.tools.project_diagnose import ProjectDiagnoseTool
from backend.tools.runtime_exec import RuntimeExecTool
from backend.tools.runtime_probe import RuntimeProbeTool

pytestmark = pytest.mark.unit


def _assert_tool_result_contract(result: Any) -> Dict[str, Any]:
    """断言 content 是 dict 且 output 是内容等价的 JSON 字符串。"""
    assert isinstance(result.content, dict), (
        f"content 必须是结构化 dict（doctor 直接读它），实为 {type(result.content).__name__}"
    )
    assert isinstance(result.output, str), (
        f"output 必须是 JSON 字符串（adapter 字符串契约），实为 {type(result.output).__name__}"
    )
    decoded = json.loads(result.output)
    assert decoded == result.content, "output 反序列化后应与 content 完全一致"
    return decoded


# --- probe ---


def test_probe_exposes_structured_content_and_string_output():
    result = RuntimeProbeTool().execute()

    assert result.success is True
    payload = _assert_tool_result_contract(result)
    assert set(payload) >= {"runtimes", "recommended", "errors"}
    assert isinstance(payload["runtimes"], list)


# --- diagnose ---


def test_diagnose_exposes_structured_content_and_string_output():
    result = ProjectDiagnoseTool().execute()

    assert result.success is True
    payload = _assert_tool_result_contract(result)
    assert set(payload) >= {
        "level",
        "diagnostics",
        "manifests",
        "recommended_runtime",
        "probe_errors",
    }


def test_diagnose_downgrades_level_when_adapter_raises(monkeypatch):
    """适配器抛异常时只写 diagnostics、不进 per_language —— 等级必须跟着降级。

    否则会出现 level=satisfied 却带着 WARNING 诊断的自相矛盾结果，前端同时
    显示「✓ 全部满足」和一条警告。
    """

    class _BoomAdapter:
        def discover(self, request, ctx):
            return []

        def diagnose(self, root, runtimes, ctx):
            raise RuntimeError("boom")

    class _FakeRegistry:
        def languages(self):
            return ["python"]

        def get(self, lang):
            return _BoomAdapter() if lang == "python" else None

    monkeypatch.setattr("backend.tools.project_diagnose.registry", _FakeRegistry())

    result = ProjectDiagnoseTool().execute(languages=["python"])

    payload = _assert_tool_result_contract(result)
    assert any(d["code"] == "DIAGNOSE_INTERNAL_ERROR" for d in payload["diagnostics"])
    assert payload["level"] != "satisfied", "存在警告诊断时不得报告 satisfied"


# --- exec ---


def test_exec_exposes_structured_content_and_string_output():
    result = RuntimeExecTool().execute(
        language="python",
        runtime_path=sys.executable,
        code='print("contract")',
        workspace_root=str(Path.cwd()),
    )

    assert result.success is True, f"exec 失败: {result.error}"
    payload = _assert_tool_result_contract(result)
    assert payload["stdout"].replace("\r\n", "\n") == "contract\n"
    assert payload["exit_code"] == 0
    # ExecutionResult.to_dict() 的字段集合（前端 ExecutionResult 镜像这些字段）
    assert set(payload) == {
        "exit_code",
        "stdout",
        "stderr",
        "duration_seconds",
        "timed_out",
        "output_truncated",
        "error",
        "command",
    }


def test_exec_spawn_failure_marks_success_false(monkeypatch):
    """子进程启动失败（exit_code=None）必须 report success=False。

    回归测试：旧语义是 ``exit_code in (0, None)``，把「找不到可执行文件」
    和「超时被杀死」都误标成 success=True，前端会把这类失败渲染成「成功
    但 stdout 为空」。修复后只有 ``exit_code == 0 and not timed_out`` 才算
    成功。

    由于 ``validate_runtime_path`` 会在 ``safe_run`` 之前拦截不存在的路径，
    这里 monkeypatch 掉它让 nonexistent 路径直达 ``safe_run``，触发
    ``FileNotFoundError`` → exit_code=None。
    """
    monkeypatch.setattr(
        "backend.tools.runtime_exec.validate_runtime_path",
        lambda path, workspace_root: path,
    )

    nonexistent = "/no/such/interpreter/anywhere"
    result = RuntimeExecTool().execute(
        language="python",
        runtime_path=nonexistent,
        code="print('unreachable')",
        workspace_root=str(Path.cwd()),
    )

    assert result.success is False, (
        "spawn 失败时必须 success=False（旧语义 exit_code in (0, None) 会把 "
        "FileNotFoundError 误标成 success=True）"
    )
    assert result.output, "spawn 失败时 output 必须仍是 JSON 字符串（含 ExecutionResult）"
    payload = json.loads(result.output)
    assert payload["exit_code"] is None
    assert payload["error"], "spawn 失败时 error 字段必须非空"
    assert payload["timed_out"] is False


def test_exec_nonzero_exit_marks_success_false():
    """子进程 exit_code != 0 必须 report success=False。"""
    result = RuntimeExecTool().execute(
        language="python",
        runtime_path=sys.executable,
        code="import sys; sys.exit(7)",
        workspace_root=str(Path.cwd()),
    )

    assert result.success is False
    payload = json.loads(result.output)
    assert payload["exit_code"] == 7


# --- doctor ↔ probe 绑定回归 ---


@pytest.mark.skipif(
    os.name == "nt",
    reason="runtime_probe PATH 扫描在 Windows conda 环境下探测不到运行时（产品缺口，另行修复）",
)
def test_doctor_runtime_env_does_not_false_alarm():
    """doctor 直接读 probe 的 content，content 一旦不是 dict 就会误报 CRITICAL。"""
    check_result = RuntimeEnvCheck().run()

    assert check_result.severity is not Severity.CRITICAL, (
        f"doctor runtime_env 误报 CRITICAL: {check_result.message} —— "
        "通常是 runtime_probe 的 content 不再是 dict"
    )
