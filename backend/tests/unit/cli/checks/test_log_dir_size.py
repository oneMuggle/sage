"""Tests for backend.cli.checks.log_dir_size.LogDirSizeCheck."""
# ruff: noqa: SIM117 — nested with blocks are intentional for clarity in tests
from __future__ import annotations

import os
from unittest import mock

import pytest

from backend.cli.checks.log_dir_size import (
    CRITICAL_THRESHOLD_BYTES,
    WARN_THRESHOLD_BYTES,
    LogDirSizeCheck,
    _dir_size,
    _human_bytes,
    _resolve_log_dir,
)
from backend.cli.doctor import Severity


@pytest.fixture()
def check():
    return LogDirSizeCheck()


class TestHumanBytes:
    def test_bytes(self):
        assert _human_bytes(512) == "512.0 B"

    def test_mb(self):
        assert _human_bytes(500 * 1024 * 1024) == "500.0 MB"

    def test_gb(self):
        assert _human_bytes(3 * 1024 * 1024 * 1024) == "3.0 GB"


class TestDirSize:
    def test_empty_dir(self, tmp_path):
        assert _dir_size(tmp_path) == 0

    def test_accumulates_files(self, tmp_path):
        (tmp_path / "a.log").write_bytes(b"x" * 100)
        sub = tmp_path / "sub"
        sub.mkdir()
        (sub / "b.log").write_bytes(b"y" * 250)
        assert _dir_size(tmp_path) == 350

    def test_skips_unreadable_files(self, tmp_path):
        """模拟 stat() 抛 OSError → 跳过该文件,继续累加其它。"""
        (tmp_path / "a.log").write_bytes(b"x" * 100)
        (tmp_path / "b.log").write_bytes(b"y" * 200)

        # 用 wraps 保留原函数,只在调用次数为 1 时抛错
        from pathlib import Path

        original_stat = Path.stat
        call_count = {"n": 0}

        def selective_stat(self, *args, **kwargs):
            call_count["n"] += 1
            if call_count["n"] == 1:
                raise OSError("perm denied")
            return original_stat(self, *args, **kwargs)

        with mock.patch.object(Path, "stat", selective_stat):
            assert _dir_size(tmp_path) == 200  # a 跳过(100 字节),b 计入(200 字节)
        assert call_count["n"] == 2


class TestResolveLogDir:
    def test_env_takes_precedence(self, tmp_path):
        with mock.patch.dict(os.environ, {"SAGE_LOG_DIR": str(tmp_path)}):
            assert _resolve_log_dir() == tmp_path

    def test_default_backend_logs(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            p = _resolve_log_dir()
        # 断言是 backend/logs 下的(不依赖具体绝对路径,只校验末尾)
        assert p.name == "logs"
        assert p.parent.name == "backend"


class TestLogDirSizeCheck:
    def test_info_when_log_dir_missing(self, check, tmp_path):
        """日志目录不存在(开发模式从未跑过后端)→ INFO"""
        with mock.patch.dict(os.environ, {"SAGE_LOG_DIR": str(tmp_path / "no_such_dir")}):
            result = check.run()
        assert result.severity == Severity.INFO
        assert "不存在" in result.message

    def test_info_when_small(self, check, tmp_path):
        """< 500MB → INFO(写 10 字节,实际累加)"""
        (tmp_path / "small.log").write_bytes(b"x" * 10)
        with mock.patch.dict(os.environ, {"SAGE_LOG_DIR": str(tmp_path)}):
            result = check.run()
        assert result.severity == Severity.INFO
        assert "10" in result.message or "10.0 B" in result.message

    def test_warn_when_above_warn_threshold(self, check, tmp_path):
        """用 _dir_size mock 直接返回大值,避开真的写 500MB 文件。"""
        with mock.patch.dict(os.environ, {"SAGE_LOG_DIR": str(tmp_path)}):
            with mock.patch(
                "backend.cli.checks.log_dir_size._dir_size",
                return_value=WARN_THRESHOLD_BYTES + 1,
            ):
                result = check.run()
        assert result.severity == Severity.WARN
        assert "500.0 MB" in result.message
        assert "偏大" in result.message
        assert result.fix_hint

    def test_critical_when_above_critical_threshold(self, check, tmp_path):
        with mock.patch.dict(os.environ, {"SAGE_LOG_DIR": str(tmp_path)}):
            with mock.patch(
                "backend.cli.checks.log_dir_size._dir_size",
                return_value=CRITICAL_THRESHOLD_BYTES + 1,
            ):
                result = check.run()
        assert result.severity == Severity.CRITICAL
        assert "2.0 GB" in result.message
        assert result.fix_hint

    def test_warn_when_dir_size_raises(self, check, tmp_path):
        with mock.patch.dict(os.environ, {"SAGE_LOG_DIR": str(tmp_path)}):
            with mock.patch(
                "backend.cli.checks.log_dir_size._dir_size",
                side_effect=OSError("perm denied"),
            ):
                result = check.run()
        assert result.severity == Severity.WARN
        assert "无法读取" in result.message

    def test_threshold_boundary_warn(self, check, tmp_path):
        """exactly WARN_THRESHOLD → WARN(>= 边界触发,与 disk_space.py 一致风格)"""
        with mock.patch.dict(os.environ, {"SAGE_LOG_DIR": str(tmp_path)}):
            with mock.patch(
                "backend.cli.checks.log_dir_size._dir_size",
                return_value=WARN_THRESHOLD_BYTES,
            ):
                result = check.run()
        assert result.severity == Severity.WARN

    def test_info_below_warn_threshold(self, check, tmp_path):
        """WARN_THRESHOLD - 1 → INFO(< 边界不触发)"""
        with mock.patch.dict(os.environ, {"SAGE_LOG_DIR": str(tmp_path)}):
            with mock.patch(
                "backend.cli.checks.log_dir_size._dir_size",
                return_value=WARN_THRESHOLD_BYTES - 1,
            ):
                result = check.run()
        assert result.severity == Severity.INFO

    def test_check_attributes(self, check):
        assert check.name == "log_dir_size"
        assert isinstance(check.description, str)
        assert check.description
