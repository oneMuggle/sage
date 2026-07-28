"""M2 repl 工具单元测试。

hello world / 异常 traceback（非零退出仍 success=True）/ 超时杀进程
（success=False）/ 输出 100 KiB 截断 / 超时夹取 / 参数校验。
"""

from __future__ import annotations

import time

import pytest

from backend.tools.repl_tool import (
    MAX_OUTPUT_BYTES,
    REPL_DEFAULT_TIMEOUT_SECONDS,
    REPL_MAX_TIMEOUT_SECONDS,
    REPL_MIN_TIMEOUT_SECONDS,
    ReplTool,
    clamp_timeout,
)

pytestmark = pytest.mark.unit


@pytest.fixture()
def tool():
    return ReplTool()


# ---------------------------------------------------------------------------
# 正常执行路径
# ---------------------------------------------------------------------------


def test_repl_prints_hello_world_with_exit_zero(tool):
    """print → stdout 回传，exit_code=0，success=True。"""
    # Act
    result = tool.execute(code="print('hello world')")

    # Assert
    assert result.success is True
    assert result.content["exit_code"] == 0
    assert result.content["stdout"].strip() == "hello world"
    assert result.content["stderr"] == ""
    assert result.content["duration_seconds"] >= 0
    assert result.content["truncated"] is False


def test_repl_runs_in_isolated_mode_without_user_site(tool):
    """-I 隔离模式：sys.flags 反映 isolated，PYTHON* 环境被忽略。"""
    # Act
    result = tool.execute(code="import sys; print(sys.flags.isolated)")

    # Assert
    assert result.success is True
    assert result.content["stdout"].strip() == "1"


def test_repl_exception_traceback_is_success_true_with_nonzero_exit(tool):
    """未捕获异常 → exit_code=1 + traceback 在 stderr，但 success=True。"""
    # Act
    result = tool.execute(code="raise ValueError('boom')")

    # Assert —— agent 需要看到 traceback 自行纠错，故仍算"成功执行"
    assert result.success is True
    assert result.content["exit_code"] == 1
    assert "ValueError: boom" in result.content["stderr"]
    assert "Traceback" in result.content["stderr"]


def test_repl_stderr_from_warnings_captured(tool):
    """子进程写 stderr（非异常）→ 完整回传。"""
    # Act
    result = tool.execute(code="import sys; sys.stderr.write('warn\\n')")

    # Assert
    assert result.success is True
    assert result.content["stderr"].strip() == "warn"


# ---------------------------------------------------------------------------
# 超时与资源边界
# ---------------------------------------------------------------------------


def test_repl_timeout_kills_subprocess_and_fails(tool):
    """超时 → 子进程被杀，success=False，实际耗时远小于代码 sleep 时长。"""
    # Arrange / Act
    started = time.monotonic()
    result = tool.execute(code="import time; time.sleep(30)", timeout=2)
    elapsed = time.monotonic() - started

    # Assert
    assert result.success is False
    assert "超时" in result.error
    assert elapsed < 10  # 夹取后 2s 超时，留足进程启动余量


@pytest.mark.parametrize(
    ("requested", "expected"),
    [
        (REPL_DEFAULT_TIMEOUT_SECONDS, REPL_DEFAULT_TIMEOUT_SECONDS),
        (0.1, REPL_MIN_TIMEOUT_SECONDS),  # 低于下限 → 夹到 1s
        (999, REPL_MAX_TIMEOUT_SECONDS),  # 高于上限 → 夹到 120s
        (-5, REPL_MIN_TIMEOUT_SECONDS),
    ],
)
def test_repl_timeout_clamped_to_bounds(requested, expected):
    """超时夹取矩阵: [1s, 120s]。"""
    # Act / Assert
    assert clamp_timeout(requested) == expected


def test_repl_output_capped_at_100kib(tool):
    """stdout 超 100 KiB → 截断并置 truncated=True。"""
    # Arrange: 打印约 300 KiB
    code = "print('x' * 300000)"

    # Act
    result = tool.execute(code=code)

    # Assert
    assert result.success is True
    assert result.content["truncated"] is True
    stdout_bytes = len(result.content["stdout"].encode("utf-8"))
    assert stdout_bytes <= MAX_OUTPUT_BYTES + 100  # 截断标记尾巴余量
    assert "已截断" in result.content["stdout"]


# ---------------------------------------------------------------------------
# 参数校验
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("bad_code", ["", "   ", "\n", None, 123])
def test_repl_rejects_empty_or_nonstring_code(tool, bad_code):
    """空/纯空白/非字符串 code → 干净错误。"""
    # Act
    result = tool.execute(code=bad_code)

    # Assert
    assert result.success is False
    assert "code 不能为空" in result.error


@pytest.mark.parametrize("bad_timeout", ["fast", None, [30], True])
def test_repl_rejects_non_numeric_timeout(tool, bad_timeout):
    """timeout 非数字（含 bool）→ 干净错误。"""
    # Act
    result = tool.execute(code="print(1)", timeout=bad_timeout)

    # Assert
    assert result.success is False
    assert "timeout 必须是数字" in result.error
