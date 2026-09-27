"""R152 — runtime_exec 输入校验层单元测试。

覆盖：runtime_path（空/目录/不可执行/合法 resolve）、cwd 围栏（None/
根内/工作区外/非目录）、code 字节上限、timeout 区间与缺省、
env_overrides 敏感键拒绝与合法拷贝。
"""

from __future__ import annotations

import os
import stat

import pytest

from backend.tools.runtime_validation import (
    FORBIDDEN_ENV_KEYS,
    MAX_CODE_BYTES,
    MAX_TIMEOUT_SECONDS,
    RuntimeValidationError,
    validate_code_size,
    validate_cwd,
    validate_env_overrides,
    validate_runtime_path,
    validate_timeout,
)

pytestmark = pytest.mark.unit


def _make_executable(tmp_path, name="python.exe"):
    p = tmp_path / name
    p.write_bytes(b"#!/bin/sh\n")
    p.chmod(p.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return p


# ---------------------------------------------------------------------------
# validate_runtime_path
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("bad", ["", None])
def test_runtime_path_empty_rejected(bad):
    with pytest.raises(RuntimeValidationError, match="不能为空"):
        validate_runtime_path(bad, workspace_root=None)


def test_runtime_path_not_a_file_rejected(tmp_path):
    with pytest.raises(RuntimeValidationError, match="regular file"):
        validate_runtime_path(str(tmp_path), workspace_root=None)


def test_runtime_path_not_executable_rejected(tmp_path):
    p = tmp_path / "plain.txt"
    p.write_text("x")
    p.chmod(stat.S_IREAD)
    if os.access(p, os.X_OK):
        pytest.skip("平台无法表达不可执行位")
    with pytest.raises(RuntimeValidationError, match="不可执行"):
        validate_runtime_path(str(p), workspace_root=None)


def test_runtime_path_ok_returns_resolved(tmp_path):
    p = _make_executable(tmp_path)
    resolved = validate_runtime_path(str(p), workspace_root=None)
    assert resolved == str(p.resolve())


# ---------------------------------------------------------------------------
# validate_cwd
# ---------------------------------------------------------------------------


def test_cwd_none_passes(tmp_path):
    assert validate_cwd(None, workspace_root=tmp_path) is None


def test_cwd_inside_root_resolved(tmp_path):
    sub = tmp_path / "sub"
    sub.mkdir()
    out = validate_cwd(str(sub), workspace_root=tmp_path)
    assert out == str(sub.resolve())


def test_cwd_outside_root_rejected(tmp_path):
    outside = tmp_path.parent
    with pytest.raises(RuntimeValidationError, match="workspace_root"):
        validate_cwd(str(outside), workspace_root=tmp_path)


def test_cwd_not_a_dir_rejected(tmp_path):
    file_in_root = tmp_path / "f.txt"
    file_in_root.write_text("x")
    with pytest.raises(RuntimeValidationError, match="不是目录"):
        validate_cwd(str(file_in_root), workspace_root=tmp_path)


# ---------------------------------------------------------------------------
# validate_code_size
# ---------------------------------------------------------------------------


def test_code_size_non_string_rejected():
    with pytest.raises(RuntimeValidationError, match="字符串"):
        validate_code_size(123)


def test_code_size_over_limit_rejected():
    big = "x" * (MAX_CODE_BYTES + 1)
    with pytest.raises(RuntimeValidationError, match="超过上限"):
        validate_code_size(big)


def test_code_size_returns_utf8_byte_count():
    size = validate_code_size("中" * 10)  # 每个汉字 3 字节
    assert size == 30


# ---------------------------------------------------------------------------
# validate_timeout
# ---------------------------------------------------------------------------


def test_timeout_none_defaults_60():
    assert validate_timeout(None) == 60


def test_timeout_valid_passthrough():
    assert validate_timeout(300) == 300
    assert validate_timeout(1) == 1


@pytest.mark.parametrize("bad", [0, -5, 601, "60", 1.5])
def test_timeout_invalid_rejected(bad):
    with pytest.raises(RuntimeValidationError):
        validate_timeout(bad)
    assert validate_timeout(MAX_TIMEOUT_SECONDS) == MAX_TIMEOUT_SECONDS


# ---------------------------------------------------------------------------
# validate_env_overrides
# ---------------------------------------------------------------------------


def test_env_overrides_none_and_empty():
    assert validate_env_overrides(None) == {}
    assert validate_env_overrides({}) == {}


def test_env_overrides_valid_copied():
    out = validate_env_overrides({"MY_VAR": "1"})
    assert out == {"MY_VAR": "1"}


@pytest.mark.parametrize(
    "key",
    ["SAGE_LOCAL_AUTH_TOKEN", "OPENAI_API_KEY", "GITHUB_TOKEN", "AWS_SECRET_ACCESS_KEY"],
)
def test_env_forbidden_keys_rejected(key):
    with pytest.raises(RuntimeValidationError, match="禁止覆盖"):
        validate_env_overrides({key: "x"})


def test_env_non_string_key_rejected():
    with pytest.raises(RuntimeValidationError, match="非空字符串"):
        validate_env_overrides({1: "x"})


def test_env_non_string_value_rejected():
    with pytest.raises(RuntimeValidationError, match="必须是字符串"):
        validate_env_overrides({"OK": 1})


def test_forbidden_keys_registry_nonempty():
    assert len(FORBIDDEN_ENV_KEYS) == 8


def test_validation_error_is_value_error():
    assert issubclass(RuntimeValidationError, ValueError)
