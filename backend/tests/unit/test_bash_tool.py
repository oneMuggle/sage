"""BashTool 同步执行单元测试。

重点覆盖改动前被硬拦截的 shell 操作符命令——那是本次改动的核心价值。
"""

from __future__ import annotations

import os
import sys
import time

import pytest

from backend.domain.risk import RiskClass
from backend.domain.tool_policy import ToolPolicy
from backend.tools.bash_session import MAX_BACKGROUND_SESSIONS, get_registry
from backend.tools.bash_tool import (
    BASH_MAX_OUTPUT_BYTES,
    BASH_MAX_TIMEOUT_SECONDS,
    BASH_MIN_TIMEOUT_SECONDS,
    BashOutputTool,
    BashTool,
    KillShellTool,
    clamp_bash_timeout,
)

pytestmark = pytest.mark.unit


@pytest.fixture()
def tool():
    return BashTool()


# ---------- Schema 与风险声明 ----------


def test_bash_schema_name_and_params(tool):
    """工具名为 bash（对齐 Claude Code），参数含 run_in_background。"""
    # Arrange / Act
    schema = tool.schema

    # Assert
    assert schema.name == "bash"
    props = schema.parameters["properties"]
    assert set(props) == {"command", "cwd", "timeout", "run_in_background"}
    assert schema.parameters["required"] == ["command"]


def test_bash_declares_exec_risk(tool):
    """risk=EXEC 让权限引擎按 shell 工具门控。"""
    # Arrange / Act / Assert
    assert tool.risk is RiskClass.EXEC


# ---------- 核心价值：shell 操作符不再被拦截 ----------


@pytest.mark.parametrize(
    ("command", "expected_fragment"),
    [
        ("echo hello | tr a-z A-Z", "HELLO"),
        ("true && echo chained", "chained"),
        ("echo first; echo second", "second"),
        ("echo $(echo substituted)", "substituted"),
    ],
)
def test_bash_executes_shell_operator_commands(tool, command, expected_fragment):
    """管道/串联/分号/命令替换全部可执行（改动前一律被拒）。"""
    # Arrange / Act
    result = tool.execute(command=command)

    # Assert
    assert result.success is True, result.error
    assert result.content["exit_code"] == 0
    assert expected_fragment in result.content["stdout"]


def test_bash_redirect_writes_file(tool, tmp_path):
    """重定向写文件后再读回（改动前 > 被当作危险操作符）。"""
    # Arrange
    target = tmp_path / "out.txt"

    # Act
    result = tool.execute(command=f"echo written > {target} && cat {target}")

    # Assert
    assert result.success is True, result.error
    assert "written" in result.content["stdout"]


# ---------- 退出码语义 ----------


def test_bash_nonzero_exit_still_reports_success(tool):
    """非零退出 → success=True + exit_code，让模型看到 stderr 自行纠错。"""
    # Arrange / Act
    result = tool.execute(command="echo oops >&2; exit 7")

    # Assert
    assert result.success is True
    assert result.content["exit_code"] == 7
    assert "oops" in result.content["stderr"]


def test_bash_unknown_command_reports_nonzero_exit_not_tool_failure(tool):
    """不存在的可执行文件是命令失败而非工具故障。"""
    # Arrange / Act
    result = tool.execute(command="this_command_does_not_exist_12345")

    # Assert
    assert result.success is True
    assert result.content["exit_code"] != 0


# ---------- cwd ----------


def test_bash_runs_in_given_cwd(tool, tmp_path):
    """cwd 参数生效。"""
    # Arrange / Act
    result = tool.execute(command="pwd", cwd=str(tmp_path))

    # Assert
    assert result.success is True
    out = result.content["stdout"].strip()
    assert str(tmp_path.resolve()) in out or str(tmp_path) in out


def test_bash_rejects_cwd_outside_workspace(tmp_path):
    """policy.workspace_root 绑定后，cwd 越界被拒且命令不执行。"""
    # Arrange
    workspace = tmp_path / "ws"
    workspace.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    tool = BashTool(policy=ToolPolicy(workspace_root=str(workspace)))

    # Act
    result = tool.execute(command="pwd", cwd=str(outside))

    # Assert
    assert result.success is False
    assert "path_outside_workspace" in result.error


def test_bash_defaults_cwd_to_workspace_root(tmp_path):
    """未传 cwd 时默认落在 workspace_root。"""
    # Arrange
    workspace = tmp_path / "ws"
    workspace.mkdir()
    tool = BashTool(policy=ToolPolicy(workspace_root=str(workspace)))

    # Act
    result = tool.execute(command="pwd")

    # Assert
    assert result.success is True
    assert str(workspace.resolve()) in result.content["stdout"]


# ---------- 超时 ----------


def test_bash_timeout_kills_and_reports_failure(tool):
    """超时 → success=False，错误含超时秒数。"""
    # Arrange / Act
    result = tool.execute(command="sleep 30", timeout=1)

    # Assert
    assert result.success is False
    assert "超时" in result.error


@pytest.mark.skipif(os.name == "nt", reason="进程组语义仅在 POSIX 验证")
def test_bash_timeout_kills_grandchild_process(tool, tmp_path):
    """超时杀整个进程组：后台孙进程不得存活写 marker。"""
    # Arrange
    marker = tmp_path / "orphan.txt"
    command = f"(sleep 3; echo orphan > {marker}) & sleep 30"

    # Act
    result = tool.execute(command=command, timeout=1)

    # Assert
    assert result.success is False
    time.sleep(4)
    assert not marker.exists(), "孙进程存活 → 进程组未被完整终止"


def test_clamp_bash_timeout_clamps_out_of_range():
    """越界超时被夹到区间内。"""
    # Arrange / Act / Assert
    assert clamp_bash_timeout(0.1) == BASH_MIN_TIMEOUT_SECONDS
    assert clamp_bash_timeout(99_999) == BASH_MAX_TIMEOUT_SECONDS
    assert clamp_bash_timeout(60) == 60.0


# ---------- 输出上限 ----------


def test_bash_huge_output_is_capped(tool):
    """输出远超上限 → 截断标记 + truncated=True，父进程内存有界。"""
    # Arrange
    command = f"{sys.executable} -c \"import sys; sys.stdout.write('y' * (5 * 1024 * 1024))\""

    # Act
    result = tool.execute(command=command)

    # Assert
    assert result.success is True
    assert result.content["truncated"] is True
    assert len(result.content["stdout"].encode("utf-8")) <= BASH_MAX_OUTPUT_BYTES + 100
    assert "已截断" in result.content["stdout"]


# ---------- 结果元数据 ----------


def test_bash_result_reports_shell_and_duration(tool):
    """content 带 shell 种类与耗时，便于模型与用户理解执行环境。"""
    # Arrange / Act
    result = tool.execute(command="echo x")

    # Assert
    assert result.content["shell"] in {"bash", "sh", "powershell"}
    assert result.content["duration_seconds"] >= 0
    assert "cwd" in result.content


# ---------- 参数校验 ----------


def test_bash_empty_command_rejected(tool):
    """空命令 → 明确错误，不起子进程。"""
    # Arrange / Act
    result = tool.execute(command="   ")

    # Assert
    assert result.success is False
    assert "command" in result.error


def test_bash_unknown_kwarg_rejected(tool):
    """未知参数 → 明确错误（模型拼错参数名时立刻可见）。"""
    # Arrange / Act
    result = tool.execute(command="echo x", shel="bash")

    # Assert
    assert result.success is False
    assert "shel" in result.error


# ---------- 后台执行 ----------


@pytest.fixture()
def clean_registry():
    """每个后台测试用干净的全局注册表。"""
    registry = get_registry()
    registry.clear()
    yield registry
    registry.clear()


def _await_status(output_tool, shell_id, target, timeout=15.0):
    """轮询直到 status 变为 target，返回最后一次结果（超时则返回最后所见）。"""
    import time as _time

    deadline = _time.monotonic() + timeout
    last = None
    while _time.monotonic() < deadline:
        last = output_tool.execute(shell_id=shell_id)
        if last.content["status"] == target:
            return last
        _time.sleep(0.1)
    return last


def test_bash_background_returns_shell_id_immediately(tool, clean_registry):
    """run_in_background=true → 立即返回 shell_id + running 状态。"""
    # Arrange / Act
    result = tool.execute(command="sleep 30", run_in_background=True)

    # Assert
    assert result.success is True, result.error
    assert result.content["status"] == "running"
    assert len(result.content["shell_id"]) == 32
    assert clean_registry.count() == 1


def test_bash_background_does_not_block(tool, clean_registry):
    """后台执行不等待命令结束（sleep 30 立刻返回）。"""
    # Arrange
    import time as _time

    started = _time.monotonic()

    # Act
    tool.execute(command="sleep 30", run_in_background=True)

    # Assert
    assert _time.monotonic() - started < 5.0


def test_bash_output_reads_incrementally(tool, clean_registry):
    """bash_output 两次调用不重复返回同一段输出。"""
    # Arrange
    import time as _time

    output_tool = BashOutputTool()
    command = "echo first; sleep 2; echo second"
    spawned = tool.execute(command=command, run_in_background=True)
    shell_id = spawned.content["shell_id"]

    # Act
    _time.sleep(0.8)
    first = output_tool.execute(shell_id=shell_id)
    _time.sleep(2.5)
    second = output_tool.execute(shell_id=shell_id)

    # Assert
    assert "first" in first.content["stdout"]
    assert "first" not in second.content["stdout"]
    assert "second" in second.content["stdout"]


def test_bash_output_reports_exit_code_after_completion(tool, clean_registry):
    """命令结束后 status=exited 且带 exit_code。"""
    # Arrange
    output_tool = BashOutputTool()
    spawned = tool.execute(command="exit 5", run_in_background=True)
    shell_id = spawned.content["shell_id"]

    # Act
    final = _await_status(output_tool, shell_id, "exited")

    # Assert
    assert final.content["status"] == "exited"
    assert final.content["exit_code"] == 5


def test_bash_output_unknown_shell_id_errors(clean_registry):
    """未知 shell_id → 明确错误。"""
    # Arrange
    output_tool = BashOutputTool()

    # Act
    result = output_tool.execute(shell_id="0" * 32)

    # Assert
    assert result.success is False
    assert "shell_id" in result.error


def test_bash_output_path_traversal_shell_id_rejected(clean_registry, tmp_path):
    """路径穿越形态的 shell_id 只是查表 miss，不读任何文件。"""
    # Arrange
    secret = tmp_path / "secret.txt"
    secret.write_text("classified", encoding="utf-8")
    output_tool = BashOutputTool()

    # Act
    result = output_tool.execute(shell_id=f"../../{secret}")

    # Assert
    assert result.success is False
    assert result.content is None
    assert "classified" not in (result.error or "")


def test_kill_shell_terminates_running_command(tool, clean_registry):
    """kill_shell 终止后台命令并清空注册表。"""
    # Arrange
    kill_tool = KillShellTool()
    spawned = tool.execute(command="sleep 30", run_in_background=True)
    shell_id = spawned.content["shell_id"]

    # Act
    result = kill_tool.execute(shell_id=shell_id)

    # Assert
    assert result.success is True
    assert result.content["killed"] is True
    assert clean_registry.count() == 0


def test_kill_shell_unknown_id_errors(clean_registry):
    """未知 shell_id → 明确错误。"""
    # Arrange
    kill_tool = KillShellTool()

    # Act
    result = kill_tool.execute(shell_id="f" * 32)

    # Assert
    assert result.success is False
    assert "shell_id" in result.error


def test_bash_background_rejects_beyond_session_limit(tool, clean_registry):
    """后台会话达上限 → 拒绝新建并提示用 kill_shell。"""
    # Arrange
    for _ in range(MAX_BACKGROUND_SESSIONS):
        tool.execute(command="sleep 30", run_in_background=True)

    # Act
    result = tool.execute(command="sleep 30", run_in_background=True)

    # Assert
    assert result.success is False
    assert "kill_shell" in result.error


def test_background_tools_declare_expected_risk():
    """bash_output 只读输出（READ）；kill_shell 改系统状态（WRITE_LOCAL）。"""
    # Arrange / Act / Assert
    assert BashOutputTool().risk is RiskClass.READ
    assert KillShellTool().risk is RiskClass.WRITE_LOCAL
