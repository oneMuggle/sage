"""TerminalTool 单元测试

使用安全的 echo / python -c 等命令，覆盖：
- 正常执行（returncode 0）
- 失败命令（returncode != 0）
- 危险命令拦截
- 超时
"""

import sys

import pytest

from backend.tools.terminal import TerminalTool

pytestmark = pytest.mark.unit


# ---------- Schema ----------


def test_terminal_schema():
    tool = TerminalTool()
    schema = tool.schema
    assert schema.name == "terminal"
    assert "command" in schema.parameters["properties"]
    assert schema.parameters["required"] == ["command"]


# ---------- 正常执行 ----------


def test_terminal_echo_success():
    """echo 命令成功执行"""
    tool = TerminalTool()
    result = tool.execute(command="echo hello")
    assert result.success is True
    assert result.content["returncode"] == 0
    assert "hello" in result.content["stdout"]


def test_terminal_runs_in_specified_cwd(tmp_path):
    """cwd 参数控制工作目录"""
    tool = TerminalTool()
    # 使用 python -c 跨平台读取 cwd
    cmd = f'{sys.executable} -c "import os; print(os.getcwd())"'
    result = tool.execute(command=cmd, cwd=str(tmp_path))
    assert result.success is True
    out = result.content["stdout"].strip()
    # resolve 处理符号链接（macOS /var → /private/var 等）
    assert str(tmp_path.resolve()) in out or str(tmp_path) in out


# ---------- 失败 ----------


def test_terminal_nonzero_exit_returns_failure():
    """命令返回非 0 退出码 → success=False"""
    tool = TerminalTool()
    cmd = f"{sys.executable} -c \"import sys; sys.stderr.write('oops'); sys.exit(1)\""
    result = tool.execute(command=cmd)
    assert result.success is False
    assert result.error is not None
    assert "oops" in result.error


def test_terminal_nonexistent_command():
    """不存在的可执行文件 → 失败"""
    tool = TerminalTool()
    result = tool.execute(command="this_definitely_does_not_exist_12345")
    assert result.success is False
    assert result.error is not None


# ---------- 危险命令拦截 ----------


def test_terminal_blocks_rm_rf_root():
    """rm -rf / 被拦截"""
    tool = TerminalTool()
    result = tool.execute(command="rm -rf /")
    assert result.success is False
    assert "危险命令" in result.error


def test_terminal_blocks_fork_bomb():
    """fork bomb 模式被拦截"""
    tool = TerminalTool()
    result = tool.execute(command=":(){ :|:& };:")
    assert result.success is False
    assert "危险命令" in result.error


def test_terminal_blocks_mkfs():
    """mkfs.ext4 等格式化命令被拦截"""
    tool = TerminalTool()
    result = tool.execute(command="mkfs.ext4 /dev/sda1")
    assert result.success is False
    assert "危险命令" in result.error


def test_terminal_is_dangerous_helper():
    """_is_dangerous 直接测试常见模式"""
    tool = TerminalTool()
    assert tool._is_dangerous("rm -rf /") is True
    assert tool._is_dangerous("RM -RF /") is True  # 大小写不敏感
    assert tool._is_dangerous("echo hello") is False


# ---------- 超时 ----------


def test_terminal_timeout():
    """超时命令返回超时错误"""
    tool = TerminalTool()
    cmd = f'{sys.executable} -c "import time; time.sleep(3)"'
    result = tool.execute(command=cmd, timeout=1)
    assert result.success is False
    assert "超时" in result.error
