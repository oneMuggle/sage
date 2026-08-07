"""Tests for backend.cli.checks.sqlite_writable.SqliteWritableCheck."""
from __future__ import annotations

import os
from pathlib import Path
from unittest import mock

import pytest

from backend.cli.checks.sqlite_writable import (
    SqliteWritableCheck,
    _resolve_user_data_dir,
)
from backend.cli.doctor import Severity


@pytest.fixture()
def check():
    return SqliteWritableCheck()


class TestResolveUserDataDir:
    def test_uses_env_when_set(self, tmp_path):
        with mock.patch.dict(os.environ, {"SAGE_USER_DATA_DIR": str(tmp_path)}):
            result = _resolve_user_data_dir()
        assert result == Path(str(tmp_path))

    def test_falls_back_to_home_sage(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("SAGE_USER_DATA_DIR", None)
            result = _resolve_user_data_dir()
        assert result == Path.home() / ".sage"


class TestSqliteWritableCheck:
    def test_info_when_dir_writable(self, check, tmp_path):
        with mock.patch.dict(os.environ, {"SAGE_USER_DATA_DIR": str(tmp_path)}):
            result = check.run()
        assert result.severity == Severity.INFO
        assert "可写" in result.message
        assert check.name == "sqlite_writable"

    def test_critical_when_dir_missing(self, check, tmp_path):
        nonexistent = tmp_path / "does_not_exist"
        with mock.patch.dict(os.environ, {"SAGE_USER_DATA_DIR": str(nonexistent)}):
            result = check.run()
        assert result.severity == Severity.CRITICAL
        assert "不存在" in result.message
        assert result.fix_hint is not None
        assert "mkdir" in result.fix_hint

    def test_critical_when_path_is_file_not_dir(self, check, tmp_path):
        file_path = tmp_path / "not_a_dir"
        file_path.write_text("x")
        with mock.patch.dict(os.environ, {"SAGE_USER_DATA_DIR": str(file_path)}):
            result = check.run()
        assert result.severity == Severity.CRITICAL
        assert "不是目录" in result.message

    def test_critical_when_dir_not_writable(self, check, tmp_path):
        if os.geteuid() == 0:
            pytest.skip("root can write to read-only dirs; skip chmod test")
        ro_dir = tmp_path / "readonly"
        ro_dir.mkdir()
        os.chmod(ro_dir, 0o555)
        try:
            with mock.patch.dict(os.environ, {"SAGE_USER_DATA_DIR": str(ro_dir)}):
                result = check.run()
            assert result.severity == Severity.CRITICAL
            assert "不可写" in result.message or "写入失败" in result.message
        finally:
            os.chmod(ro_dir, 0o755)

    def test_check_attributes(self, check):
        assert check.name == "sqlite_writable"
        assert isinstance(check.description, str)
        assert check.description
