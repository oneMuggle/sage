"""M5 测试: 沙箱 Port + Adapter。

覆盖 backend.skills.skill_md.sandbox:
- SandboxRequest/SandboxResult dataclass
- SandboxPort Protocol

覆盖 backend.adapters.out.skill_script.subprocess_sandbox:
- SubprocessSandboxAdapter 完整实现
- argv/env/cwd/timeout 校验
- 敏感环境变量过滤
- 超时 kill
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from backend.adapters.out.skill_script.subprocess_sandbox import SubprocessSandboxAdapter
from backend.skills.skill_md.sandbox import (
    DEFAULT_ENV_DENYLIST,
    SandboxPort,
    SandboxRequest,
    SandboxResult,
)

pytestmark = pytest.mark.unit


# =====================================================================
# SandboxRequest dataclass
# =====================================================================


def test_sandbox_request_default_values():
    """SandboxRequest 默认值。"""
    req = SandboxRequest(script_path=Path("/tmp/script.py"))
    assert req.script_path == Path("/tmp/script.py")
    assert req.args == ()
    assert req.cwd is None
    assert req.env == {}
    assert req.timeout_s == 30.0
    assert req.stdin_data is None


def test_sandbox_request_custom_values():
    """SandboxRequest 自定义值。"""
    req = SandboxRequest(
        script_path=Path("/tmp/script.py"),
        args=("arg1", "arg2"),
        cwd=Path("/tmp/work"),
        env={"MY_VAR": "value"},
        timeout_s=60.0,
        stdin_data=b"input",
    )
    assert req.args == ("arg1", "arg2")
    assert req.cwd == Path("/tmp/work")
    assert req.env == {"MY_VAR": "value"}
    assert req.timeout_s == 60.0
    assert req.stdin_data == b"input"


# =====================================================================
# SandboxResult dataclass
# =====================================================================


def test_sandbox_result_success():
    """SandboxResult 成功路径。"""
    result = SandboxResult(
        success=True,
        exit_code=0,
        stdout="output",
        stderr="",
        duration_ms=100,
    )
    assert result.success is True
    assert result.exit_code == 0
    assert result.stdout == "output"
    assert result.stderr == ""
    assert result.duration_ms == 100
    assert result.timed_out is False
    assert result.error is None


def test_sandbox_result_timeout():
    """SandboxResult 超时路径。"""
    result = SandboxResult(
        success=False,
        exit_code=-1,
        stdout="",
        stderr="",
        duration_ms=5000,
        timed_out=True,
        error="timeout after 5.0s",
    )
    assert result.success is False
    assert result.timed_out is True
    assert result.error == "timeout after 5.0s"


# =====================================================================
# SandboxPort Protocol
# =====================================================================


def test_sandbox_port_is_protocol():
    """SandboxPort 应该是 Protocol 类型。"""
    assert hasattr(SandboxPort, "run")
    adapter = SubprocessSandboxAdapter()
    assert hasattr(adapter, "run")


# =====================================================================
# DEFAULT_ENV_DENYLIST
# =====================================================================


def test_default_env_denylist_contains_common_secrets():
    """DEFAULT_ENV_DENYLIST 应包含常见敏感键。"""
    sensitive_keys = [
        "AWS_SECRET_ACCESS_KEY",
        "AWS_ACCESS_KEY_ID",
        "OPENAI_API_KEY",
        "ANTHROPIC_API_KEY",
        "GITHUB_TOKEN",
    ]
    for key in sensitive_keys:
        assert key in DEFAULT_ENV_DENYLIST


def test_default_env_denylist_is_frozenset():
    """DEFAULT_ENV_DENYLIST 应为 frozenset。"""
    assert isinstance(DEFAULT_ENV_DENYLIST, frozenset)


# =====================================================================
# SubprocessSandboxAdapter - 基本功能
# =====================================================================


def test_adapter_default_construction():
    """SubprocessSandboxAdapter 默认构造。"""
    adapter = SubprocessSandboxAdapter()
    assert adapter._python_executable == sys.executable
    assert adapter._default_timeout_s == 30.0
    assert adapter._max_timeout_s == 300.0


def test_adapter_custom_construction():
    """SubprocessSandboxAdapter 自定义构造。"""
    custom_denylist = frozenset({"SECRET"})
    adapter = SubprocessSandboxAdapter(
        python_executable="/usr/bin/python3",
        default_timeout_s=60.0,
        max_timeout_s=120.0,
        env_denylist=custom_denylist,
    )
    assert adapter._python_executable == "/usr/bin/python3"
    assert adapter._default_timeout_s == 60.0
    assert adapter._max_timeout_s == 120.0
    assert adapter._env_denylist == custom_denylist


# =====================================================================
# SubprocessSandboxAdapter - argv 构造
# =====================================================================


def test_adapter_constructs_argv_with_script_and_args(tmp_path):
    """adapter.run 构造正确的 argv 包含 script 和 args。"""
    adapter = SubprocessSandboxAdapter()
    script = tmp_path / "test_script.py"
    script.write_text("print('hello')\n", encoding="utf-8")
    req = SandboxRequest(
        script_path=script,
        args=("arg1", "arg2"),
    )

    mock_process = AsyncMock()
    mock_process.communicate = AsyncMock(return_value=(b"hello\n", b""))
    mock_process.returncode = 0

    with patch("asyncio.create_subprocess_exec", return_value=mock_process) as mock_exec:
        result = asyncio.run(adapter.run(req))

    call_args = mock_exec.call_args
    argv = call_args.args
    assert argv[0] == sys.executable
    assert Path(argv[1]) == script.resolve()
    assert argv[2] == "arg1"
    assert argv[3] == "arg2"

    assert result.success is True
    assert result.exit_code == 0


def test_adapter_argv_no_shell_injection(tmp_path):
    """adapter.run argv 不使用 shell=True (防命令注入)。"""
    adapter = SubprocessSandboxAdapter()
    script = tmp_path / "test_script.py"
    script.write_text("print('hello')\n", encoding="utf-8")

    req = SandboxRequest(
        script_path=script,
        args=("; rm -rf /", "$(echo evil)"),
    )

    mock_process = AsyncMock()
    mock_process.communicate = AsyncMock(return_value=(b"", b""))
    mock_process.returncode = 0

    with patch("asyncio.create_subprocess_exec", return_value=mock_process) as mock_exec:
        asyncio.run(adapter.run(req))

    call_kwargs = mock_exec.call_args.kwargs
    assert "shell" not in call_kwargs or call_kwargs.get("shell") is False


# =====================================================================
# SubprocessSandboxAdapter - 环境变量过滤
# =====================================================================


def test_adapter_filters_sensitive_env_vars(tmp_path):
    """adapter.run 过滤敏感环境变量。"""
    adapter = SubprocessSandboxAdapter()
    script = tmp_path / "test_script.py"
    script.write_text("import os; print(os.environ.get('MY_VAR', 'missing'))\n", encoding="utf-8")

    req = SandboxRequest(
        script_path=script,
        env={"MY_VAR": "safe_value", "OPENAI_API_KEY": "sk-secret"},
    )

    mock_process = AsyncMock()
    mock_process.communicate = AsyncMock(return_value=(b"", b""))
    mock_process.returncode = 0

    with patch("asyncio.create_subprocess_exec", return_value=mock_process) as mock_exec:
        asyncio.run(adapter.run(req))

    env_arg = mock_exec.call_args.kwargs.get("env", {})
    assert "OPENAI_API_KEY" not in env_arg
    assert env_arg.get("MY_VAR") == "safe_value"


def test_adapter_filters_all_denylist_keys(tmp_path):
    """adapter.run 过滤所有 denylist 中的键。"""
    adapter = SubprocessSandboxAdapter()
    script = tmp_path / "test_script.py"
    script.write_text("print('test')\n", encoding="utf-8")

    req = SandboxRequest(
        script_path=script,
        env={
            "AWS_SECRET_ACCESS_KEY": "secret1",
            "GITHUB_TOKEN": "token",
            "SAFE_VAR": "safe",
        },
    )

    mock_process = AsyncMock()
    mock_process.communicate = AsyncMock(return_value=(b"", b""))
    mock_process.returncode = 0

    with patch("asyncio.create_subprocess_exec", return_value=mock_process) as mock_exec:
        asyncio.run(adapter.run(req))

    env_arg = mock_exec.call_args.kwargs.get("env", {})
    assert "AWS_SECRET_ACCESS_KEY" not in env_arg
    assert "GITHUB_TOKEN" not in env_arg
    assert env_arg.get("SAFE_VAR") == "safe"


# =====================================================================
# SubprocessSandboxAdapter - cwd
# =====================================================================


def test_adapter_passes_cwd_to_subprocess(tmp_path):
    """adapter.run 传递 cwd 给 subprocess。"""
    adapter = SubprocessSandboxAdapter()
    script = tmp_path / "test_script.py"
    script.write_text("print('test')\n", encoding="utf-8")
    work_dir = tmp_path / "work"
    work_dir.mkdir()

    req = SandboxRequest(script_path=script, cwd=work_dir)

    mock_process = AsyncMock()
    mock_process.communicate = AsyncMock(return_value=(b"", b""))
    mock_process.returncode = 0

    with patch("asyncio.create_subprocess_exec", return_value=mock_process) as mock_exec:
        asyncio.run(adapter.run(req))

    call_kwargs = mock_exec.call_args.kwargs
    assert call_kwargs.get("cwd") == work_dir


# =====================================================================
# SubprocessSandboxAdapter - 超时
# =====================================================================


def test_adapter_clamps_timeout_to_max(tmp_path):
    """adapter.run 限制 timeout 不超过 max_timeout_s (验证超时返回 SandboxResult.timed_out=True)。"""
    adapter = SubprocessSandboxAdapter(max_timeout_s=0.5)  # 极短超时确保超时触发
    script = tmp_path / "test_script.py"
    script.write_text("import time; time.sleep(10)\n", encoding="utf-8")  # sleep 10s

    req = SandboxRequest(script_path=script, timeout_s=10.0)  # 请求 10s，但 max=0.5s

    result = asyncio.run(adapter.run(req))

    # 验证超时返回 timed_out=True
    assert result.success is False
    assert result.timed_out is True
    assert "timeout" in result.error.lower()


# =====================================================================
# SubprocessSandboxAdapter - 结果处理
# =====================================================================


def test_adapter_returns_sandbox_result(tmp_path):
    """adapter.run 返回 SandboxResult。"""
    adapter = SubprocessSandboxAdapter()
    script = tmp_path / "test_script.py"
    script.write_text("print('test')\n", encoding="utf-8")

    req = SandboxRequest(script_path=script)

    mock_process = AsyncMock()
    mock_process.communicate = AsyncMock(return_value=(b"hello\n", b"warning\n"))
    mock_process.returncode = 0

    with patch("asyncio.create_subprocess_exec", return_value=mock_process):
        result = asyncio.run(adapter.run(req))

    assert isinstance(result, SandboxResult)
    assert result.success is True
    assert result.exit_code == 0
    assert result.stdout == "hello\n"
    assert result.stderr == "warning\n"
    assert result.duration_ms >= 0


def test_adapter_returns_failure_on_nonzero_exit(tmp_path):
    """adapter.run 在 exit_code != 0 时返回 success=False。"""
    adapter = SubprocessSandboxAdapter()
    script = tmp_path / "test_script.py"
    script.write_text("raise Exception('error')\n", encoding="utf-8")

    req = SandboxRequest(script_path=script)

    mock_process = AsyncMock()
    mock_process.communicate = AsyncMock(return_value=(b"", b"Traceback...\n"))
    mock_process.returncode = 1

    with patch("asyncio.create_subprocess_exec", return_value=mock_process):
        result = asyncio.run(adapter.run(req))

    assert result.success is False
    assert result.exit_code == 1


# =====================================================================
# SubprocessSandboxAdapter - 异常处理
# =====================================================================


def test_adapter_handles_subprocess_exception(tmp_path):
    """adapter.run 捕获 subprocess 异常并返回失败结果。"""
    adapter = SubprocessSandboxAdapter()
    script = tmp_path / "test_script.py"
    script.write_text("print('test')\n", encoding="utf-8")

    req = SandboxRequest(script_path=script)

    with patch("asyncio.create_subprocess_exec", side_effect=OSError("spawn failed")):
        result = asyncio.run(adapter.run(req))

    assert result.success is False
    assert "spawn failed" in result.error


# =====================================================================
# SubprocessSandboxAdapter - 真实 subprocess 集成
# =====================================================================


@pytest.mark.asyncio
async def test_adapter_real_subprocess_success(tmp_path):
    """真实 subprocess: 执行简单 print 脚本。"""
    adapter = SubprocessSandboxAdapter()
    script = tmp_path / "hello.py"
    script.write_text("print('hello world')\n", encoding="utf-8")

    req = SandboxRequest(script_path=script)
    result = await adapter.run(req)

    assert result.success is True
    assert result.exit_code == 0
    assert "hello world" in result.stdout


@pytest.mark.asyncio
async def test_adapter_real_subprocess_failure(tmp_path):
    """真实 subprocess: 执行抛异常的脚本。"""
    adapter = SubprocessSandboxAdapter()
    script = tmp_path / "error.py"
    script.write_text("import sys; sys.exit(2)\n", encoding="utf-8")

    req = SandboxRequest(script_path=script)
    result = await adapter.run(req)

    assert result.success is False
    assert result.exit_code == 2


@pytest.mark.asyncio
async def test_adapter_real_subprocess_with_args(tmp_path):
    """真实 subprocess: 传递参数。"""
    adapter = SubprocessSandboxAdapter()
    script = tmp_path / "echo_args.py"
    script.write_text(
        "import sys; print(' '.join(sys.argv[1:]))\n",
        encoding="utf-8",
    )

    req = SandboxRequest(
        script_path=script,
        args=("hello", "world"),
    )
    result = await adapter.run(req)

    assert result.success is True
    assert "hello world" in result.stdout


@pytest.mark.asyncio
async def test_adapter_real_subprocess_stdin(tmp_path):
    """真实 subprocess: 传递 stdin。"""
    adapter = SubprocessSandboxAdapter()
    script = tmp_path / "read_stdin.py"
    script.write_text(
        "import sys; data = sys.stdin.read(); print(f'got: {data}')\n",
        encoding="utf-8",
    )

    req = SandboxRequest(
        script_path=script,
        stdin_data=b"hello stdin",
    )
    result = await adapter.run(req)

    assert result.success is True
    assert "got: hello stdin" in result.stdout


@pytest.mark.asyncio
async def test_adapter_real_subprocess_env_filter(tmp_path):
    """真实 subprocess: 敏感环境变量被过滤。"""
    adapter = SubprocessSandboxAdapter()
    script = tmp_path / "check_env.py"
    script.write_text(
        "import os; print(os.environ.get('OPENAI_API_KEY', 'filtered'))\n",
        encoding="utf-8",
    )

    req = SandboxRequest(
        script_path=script,
        env={"OPENAI_API_KEY": "sk-secret", "SAFE_VAR": "safe"},
    )
    result = await adapter.run(req)

    assert result.success is True
    assert "filtered" in result.stdout  # OPENAI_API_KEY 应被过滤
    assert "sk-secret" not in result.stdout  # secret 不应泄漏
