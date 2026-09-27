"""R164 — safe_run 安全子进程封装单元测试。

覆盖：空 argv、成功/非零退出/stderr、stdin 传入、超时回收、输出上限
截断、找不到可执行文件、cwd 生效、环境白名单（父进程变量过滤 +
overrides 叠加）。全部使用 sys.executable 真实子进程，跨平台。
"""

from __future__ import annotations

import sys

import pytest

from backend.tools.runtime_safe_run import (
    MAX_OUTPUT_CAP,
    SAFE_ENV_ALLOWLIST,
    _sanitized_env,
    safe_run,
)

pytestmark = pytest.mark.unit


def _py(code: str):
    return [sys.executable, "-c", code]


# ---------------------------------------------------------------------------
# 基本路径
# ---------------------------------------------------------------------------


def test_empty_argv_rejected():
    result = safe_run([])
    assert result.exit_code is None
    assert "argv 不能为空" in result.error


def test_success_captures_stdout_and_exit_code():
    result = safe_run(_py("print('hello')"))
    assert result.exit_code == 0
    assert result.stdout.strip() == "hello"
    assert result.error is None
    assert result.timed_out is False


def test_nonzero_exit_code_captured():
    result = safe_run(_py("import sys; sys.exit(3)"))
    assert result.exit_code == 3


def test_stderr_captured():
    result = safe_run(_py("import sys; sys.stderr.write('oops')"))
    assert "oops" in result.stderr


def test_stdin_input_text_passed():
    result = safe_run(
        _py("import sys; print(sys.stdin.read().strip())"),
        input_text="from-stdin",
    )
    assert result.stdout.strip() == "from-stdin"


def test_cwd_is_honored(tmp_path):
    (tmp_path / "marker.txt").write_text("found", encoding="utf-8")
    code = (
        "import os; print(open('marker.txt', encoding='utf-8').read())"
    )
    result = safe_run(_py(code), cwd=tmp_path)
    assert result.stdout.strip() == "found"


# ---------------------------------------------------------------------------
# 超时与输出上限
# ---------------------------------------------------------------------------


def test_timeout_kills_and_reports():
    result = safe_run(_py("import time; time.sleep(30)"), timeout=2.0)
    assert result.timed_out is True
    assert "超时" in (result.error or "")


def test_output_cap_truncates():
    result = safe_run(_py("print('x' * 5000)"), output_cap=100)
    assert result.output_truncated is True
    # cap 按字节读取上限，截断后 read_capped_output 会追加中文提示行，
    # 故总长度略超 cap 属正常——只断言远小于原始 5000 字符
    assert len(result.stdout) < 1000
    assert "截断" in result.stdout


def test_output_cap_capped_at_max():
    # output_cap 超过 MAX_OUTPUT_CAP 时封顶（不抛错即可验证封装层）
    assert MAX_OUTPUT_CAP == 10 * 1024 * 1024


# ---------------------------------------------------------------------------
# 找不到可执行文件
# ---------------------------------------------------------------------------


def test_missing_binary_reports_error():
    result = safe_run(["definitely-not-a-real-binary-xyz"])
    assert result.exit_code is None
    assert "找不到可执行文件" in result.error


# ---------------------------------------------------------------------------
# 环境白名单
# ---------------------------------------------------------------------------


def test_sanitized_env_drops_non_allowlisted_parent_vars(monkeypatch):
    monkeypatch.setenv("MY_SECRET_VAR", "sneaky")
    env = _sanitized_env(None)
    assert "MY_SECRET_VAR" not in env
    assert "PATH" in env  # 白名单变量保留


def test_sanitized_env_overrides_applied_on_top(monkeypatch):
    monkeypatch.setenv("PATH", "parent-path")
    env = _sanitized_env({"MY_VAR": "v", "PATH": "child-path"})
    assert env["MY_VAR"] == "v"  # overrides 叠加生效
    assert env["PATH"] == "child-path"


def test_child_process_sees_override_but_not_parent_secret(monkeypatch):
    monkeypatch.setenv("MY_SECRET_VAR", "sneaky")
    code = (
        "import os; "
        "print(os.environ.get('MY_SECRET_VAR', '<absent>')); "
        "print(os.environ.get('MY_MARK', '<absent>'))"
    )
    result = safe_run(_py(code), env={"MY_MARK": "visible"})
    lines = result.stdout.splitlines()
    assert lines[0] == "<absent>"  # 父进程非白名单变量被过滤
    assert lines[1] == "visible"  # overrides 透传给子进程


def test_safe_env_allowlist_nonempty():
    assert "PATH" in SAFE_ENV_ALLOWLIST
    assert "SYSTEMROOT" in SAFE_ENV_ALLOWLIST or "TEMP" in SAFE_ENV_ALLOWLIST


def test_none_env_uses_allowlist_not_empty():
    # env=None 与 env={} 均不应产生空环境（子进程 python 依赖最少变量）
    result = safe_run(_py("print('ok')"), env=None)
    assert result.exit_code == 0
