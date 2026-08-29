"""M2 repl 工具单元测试。

hello world / 异常 traceback（非零退出仍 success=True）/ 超时杀进程
（success=False）/ 输出 100 KiB 截断 / 超时夹取 / 参数校验。
审查修复回归：进程组 kill（FIX-4，孙进程不留孤儿）/ 临时代码文件
绕开 Windows argv 上限（FIX-4）/ 输出经临时文件只读前 100 KiB
（FIX-5）/ 未知参数拒绝（FIX-2）。
"""

from __future__ import annotations

import math
import os
import time
from unittest.mock import Mock

import pytest

import backend.tools.repl_tool as repl_module
from backend.tools.repl_tool import (
    MAX_CODE_BYTES,
    MAX_OUTPUT_BYTES,
    REPL_DEFAULT_TIMEOUT_SECONDS,
    REPL_MAX_TIMEOUT_SECONDS,
    REPL_MIN_TIMEOUT_SECONDS,
    ReplTool,
    clamp_timeout,
)
from backend.tools.subprocess_util import file_identity

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


def test_repl_rejects_non_finite_timeout(tool):
    for timeout in (math.nan, math.inf, -math.inf):
        result = tool.execute(code="print(1)", timeout=timeout)
        assert result.success is False
        assert "timeout 必须是有限数字" in result.error


def test_repl_rejects_timeout_integer_that_cannot_be_converted_to_float(tool):
    result = tool.execute(code="print(1)", timeout=10**1000)

    assert result.success is False
    assert "timeout 必须是有限数字" in result.error


@pytest.mark.skipif(os.name == "nt", reason="进程组 kill 仅 POSIX 支持")
def test_repl_normal_exit_kills_descendant_process_group(tool, tmp_path):
    """父片段正常退出时仍清理同组 descendant。"""
    marker = tmp_path / "normal-exit-descendant.txt"
    grandchild = (
        f"import time; time.sleep(4); open({str(marker)!r}, 'w').write('orphan')"
    )
    code = (
        "import subprocess, sys\n"
        f"subprocess.Popen([sys.executable, '-c', {grandchild!r}])\n"
    )

    result = tool.execute(code=code, timeout=2)

    assert result.success is True
    assert result.content["exit_code"] == 0
    time.sleep(5)
    assert not marker.exists()


def test_repl_initialization_failure_removes_created_output_files(tool, monkeypatch, tmp_path):
    script = tmp_path / "script.py"
    script.write_text("print(1)", encoding="utf-8")
    stdout_path = tmp_path / "stdout.out"
    stdout_path.touch()
    call_count = 0

    def make_output_file():
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return str(stdout_path)
        raise OSError("stderr allocation failed")

    monkeypatch.setattr(repl_module, "_write_temp_script", lambda _code: str(script))
    monkeypatch.setattr(repl_module, "_make_temp_output_file", make_output_file)

    result = tool.execute(code="print(1)")

    assert result.success is False
    assert not script.exists()
    assert not stdout_path.exists()


def test_repl_pending_cleanup_is_retained_then_retried(monkeypatch, tmp_path):
    process = Mock()
    process.poll.return_value = None
    collector = Mock()
    collector.is_alive = True
    collector.finish.return_value = False
    collector.stop.return_value = False
    stdout_path = tmp_path / "stdout.out"
    stderr_path = tmp_path / "stderr.out"
    stdout_path.touch()
    stderr_path.touch()
    kill = Mock(return_value=False)
    reap = Mock(return_value=False)
    monkeypatch.setattr(repl_module, "kill_process_tree", kill)
    monkeypatch.setattr(repl_module, "reap_process", reap)
    repl_module._PENDING_CLEANUPS.clear()

    try:
        repl_module._retain_pending_cleanup(
            process=process,
            collectors=(collector,),
            stdout_path=str(stdout_path),
            stderr_path=str(stderr_path),
            process_group_id=None,
            stdout_identity=file_identity(str(stdout_path)),
            stderr_identity=file_identity(str(stderr_path)),
            process_group_killed=True,
        )
        repl_module._retry_pending_cleanups()

        assert len(repl_module._PENDING_CLEANUPS) == 1
        assert stdout_path.exists()
        assert stderr_path.exists()

        process.poll.return_value = 0
        collector.is_alive = False
        reap.return_value = True
        repl_module._retry_pending_cleanups()

        assert [] == repl_module._PENDING_CLEANUPS
        assert not stdout_path.exists()
        assert not stderr_path.exists()
    finally:
        repl_module._PENDING_CLEANUPS.clear()


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


def test_repl_rejects_code_above_input_limit(tool):
    result = tool.execute(code="x" * (MAX_CODE_BYTES + 1))

    assert result.success is False
    assert "大小上限" in result.error


def test_repl_spawn_group_verification_failure_retains_process(monkeypatch, tool, tmp_path):
    from backend.tools.subprocess_util import ProcessGroupVerificationError

    process = Mock()
    process.poll.return_value = None
    stdout = tmp_path / "stdout.out"
    stderr = tmp_path / "stderr.out"
    stdout.touch()
    stderr.touch()
    process.stdout = Mock()
    process.stderr = Mock()
    monkeypatch.setattr(repl_module, "spawn_verified", Mock(
        side_effect=ProcessGroupVerificationError("group unavailable", process)
    ))
    monkeypatch.setattr(repl_module, "file_identity", file_identity)
    monkeypatch.setattr(repl_module, "kill_process_tree", Mock(return_value=False))
    repl_module._PENDING_CLEANUPS.clear()

    try:
        with pytest.raises(ProcessGroupVerificationError):
            tool._run_subprocess(
                str(tmp_path / "script.py"), str(stdout), str(stderr), 1
            )
        assert repl_module._PENDING_CLEANUPS
        assert repl_module._PENDING_CLEANUPS[0].process is process
    finally:
        repl_module._PENDING_CLEANUPS.clear()


def test_repl_group_kill_failure_does_not_reap_live_process(monkeypatch, tmp_path):
    process = Mock()
    process.poll.return_value = None
    process.stdout = Mock()
    process.stderr = Mock()
    stdout = tmp_path / "stdout.out"
    stderr = tmp_path / "stderr.out"
    stdout.touch()
    stderr.touch()
    monkeypatch.setattr(repl_module, "spawn_verified", Mock(
        return_value=Mock(process=process, process_group_id=process.pid)
    ))
    monkeypatch.setattr(repl_module, "start_bounded_output_collectors", Mock(return_value=()))
    monkeypatch.setattr(repl_module, "observe_process_exit", Mock(return_value=False))
    monkeypatch.setattr(repl_module, "kill_process_tree", Mock(return_value=False))
    reap = Mock(return_value=False)
    monkeypatch.setattr(repl_module, "reap_process", reap)
    repl_module._PENDING_CLEANUPS.clear()

    try:
        result = ReplTool()._run_subprocess(str(tmp_path / "script.py"), str(stdout), str(stderr), 1)
        assert result.success is False
        reap.assert_not_called()
        assert repl_module._PENDING_CLEANUPS
    finally:
        repl_module._PENDING_CLEANUPS.clear()




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


def test_repl_rejects_unknown_kwargs(tool):
    """FIX-2 回归：拼错的参数名 → 干净错误。"""
    # Act —— 模拟 LLM 把 timeout 拼成 timout
    result = tool.execute(code="print(1)", timout=5)

    # Assert
    assert result.success is False
    assert "未知参数" in result.error
    assert "timout" in result.error


# ---------------------------------------------------------------------------
# FIX-4: 进程组 kill + 临时代码文件（绕开 Windows argv 上限）
# ---------------------------------------------------------------------------


@pytest.mark.skipif(os.name == "nt", reason="进程组 kill 仅 POSIX 支持（Windows 退化为 p.kill）")
def test_repl_timeout_kills_grandchild_via_process_group(tool, tmp_path):
    """超时杀整个进程组：孙进程也被收掉，不留孤儿写标记文件。"""
    # Arrange: 子进程派生孙进程，孙进程睡醒后写标记；父片段睡 30s 触发超时
    marker = tmp_path / "orphan_marker.txt"
    grandchild = (
        f"import time; time.sleep(4); open({str(marker)!r}, 'w').write('orphan')"
    )
    code = (
        "import subprocess, sys, time\n"
        f"subprocess.Popen([sys.executable, '-c', {grandchild!r}])\n"
        "time.sleep(30)\n"
    )

    # Act
    started = time.monotonic()
    result = tool.execute(code=code, timeout=2)
    elapsed = time.monotonic() - started

    # Assert: 超时即时返回（killpg 不拖泥带水）
    assert result.success is False
    assert "超时" in result.error
    assert elapsed < 10

    # 等过孙进程"本该写出标记"的窗口，标记仍未出现 → 孙进程随组被杀
    time.sleep(6)
    assert not marker.exists()


def test_repl_large_code_snippet_runs_via_temp_script(tool):
    """4 万+字符代码片段正常执行——走临时脚本文件，不吃 argv 上限。

    Windows CreateProcess 命令行上限 32 767 字符，``-c`` argv 传大片段
    必挂；本测试在 Linux 上证明临时代码文件路径可用（Windows 回归保障）。
    """
    # Arrange
    code = "counter = 0\n" * 3_500 + "print('big-ok', counter)"
    assert len(code) > 40_000

    # Act
    result = tool.execute(code=code)

    # Assert
    assert result.success is True
    assert result.content["exit_code"] == 0
    assert "big-ok 0" in result.content["stdout"]


# ---------------------------------------------------------------------------
# FIX-5: 输出经临时文件只读前 100 KiB（父进程内存有界）
# ---------------------------------------------------------------------------


def test_repl_huge_output_capped_at_100kib(tool):
    """打印 5 MiB → 只读回前 100 KiB + 截断标记，父进程不做全量缓冲。"""
    # Arrange
    code = "import sys; sys.stdout.write('y' * (5 * 1024 * 1024))"

    # Act
    result = tool.execute(code=code)

    # Assert
    assert result.success is True
    assert result.content["exit_code"] == 0
    assert result.content["truncated"] is True
    stdout_bytes = len(result.content["stdout"].encode("utf-8"))
    assert stdout_bytes <= MAX_OUTPUT_BYTES + 100  # 截断标记尾巴余量
    assert "已截断" in result.content["stdout"]
