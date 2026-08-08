"""Tests for backend.cli.checks.disk_space.DiskSpaceCheck."""
# ruff: noqa: SIM117 — nested with blocks are intentional for clarity in tests
from __future__ import annotations

import os
from unittest import mock

import pytest

from backend.cli.checks.disk_space import (
    WARN_THRESHOLD_BYTES,
    DiskSpaceCheck,
    _human_bytes,
)
from backend.cli.doctor import Severity


@pytest.fixture()
def check():
    return DiskSpaceCheck()


class TestHumanBytes:
    def test_bytes(self):
        assert _human_bytes(512) == "512.0 B"

    def test_kb(self):
        assert _human_bytes(2048) == "2.0 KB"

    def test_mb(self):
        result = _human_bytes(5 * 1024 * 1024)
        assert result == "5.0 MB"

    def test_gb(self):
        result = _human_bytes(2 * 1024 * 1024 * 1024)
        assert result == "2.0 GB"

    def test_tb(self):
        result = _human_bytes(3 * 1024 * 1024 * 1024 * 1024)
        assert result == "3.0 TB"

    def test_zero(self):
        assert _human_bytes(0) == "0.0 B"


class TestDiskSpaceCheck:
    def test_info_when_space_sufficient(self, check, tmp_path):
        fake_usage = mock.Mock(free=10 * 1024 * 1024 * 1024)  # 10 GB
        with mock.patch.dict(os.environ, {"SAGE_USER_DATA_DIR": str(tmp_path)}):
            with mock.patch("shutil.disk_usage", return_value=fake_usage):
                result = check.run()
        assert result.severity == Severity.INFO
        assert "剩余空间" in result.message
        assert check.name == "disk_space"

    def test_warn_when_space_low(self, check, tmp_path):
        fake_usage = mock.Mock(free=100 * 1024 * 1024)  # 100 MB < 500 MB
        with mock.patch.dict(os.environ, {"SAGE_USER_DATA_DIR": str(tmp_path)}):
            with mock.patch("shutil.disk_usage", return_value=fake_usage):
                result = check.run()
        assert result.severity == Severity.WARN
        assert "不足" in result.message
        assert "500" in result.message
        assert result.fix_hint is not None

    def test_info_at_threshold_boundary(self, check, tmp_path):
        # Exactly at threshold -> not strictly less than -> INFO
        fake_usage = mock.Mock(free=WARN_THRESHOLD_BYTES)
        with mock.patch.dict(os.environ, {"SAGE_USER_DATA_DIR": str(tmp_path)}):
            with mock.patch("shutil.disk_usage", return_value=fake_usage):
                result = check.run()
        assert result.severity == Severity.INFO

    def test_warn_when_disk_usage_raises(self, check, tmp_path):
        with mock.patch.dict(os.environ, {"SAGE_USER_DATA_DIR": str(tmp_path)}):
            with mock.patch("shutil.disk_usage", side_effect=OSError("no such fs")):
                result = check.run()
        assert result.severity == Severity.WARN
        assert "无法读取" in result.message
        assert result.fix_hint is not None

    def test_falls_back_to_parent_when_dir_missing(self, check, tmp_path):
        """If user data dir doesn't exist, check the parent instead."""
        nonexistent = tmp_path / "missing"
        fake_usage = mock.Mock(free=20 * 1024 * 1024 * 1024)
        with mock.patch.dict(os.environ, {"SAGE_USER_DATA_DIR": str(nonexistent)}):
            with mock.patch("shutil.disk_usage", return_value=fake_usage) as m:
                result = check.run()
        assert result.severity == Severity.INFO
        assert m.called

    def test_check_attributes(self, check):
        assert check.name == "disk_space"
        assert isinstance(check.description, str)
        assert check.description
