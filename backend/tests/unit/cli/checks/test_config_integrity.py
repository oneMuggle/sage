"""Tests for backend.cli.checks.config_integrity.ConfigIntegrityCheck."""
from __future__ import annotations

import json
import os
from unittest import mock

import pytest

from backend.cli.checks.config_integrity import ConfigIntegrityCheck
from backend.cli.doctor import Severity


@pytest.fixture()
def check():
    return ConfigIntegrityCheck()


class TestConfigIntegrityCheck:
    def test_info_when_no_config_dir(self, check, tmp_path):
        """No config/ dir -> INFO 'first install'."""
        with mock.patch.dict(os.environ, {"SAGE_USER_DATA_DIR": str(tmp_path)}):
            result = check.run()
        assert result.severity == Severity.INFO
        assert "首次安装" in result.message
        assert check.name == "config_integrity"

    def test_info_when_config_dir_empty(self, check, tmp_path):
        """config/ exists but no .json files -> INFO 'first install'."""
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        with mock.patch.dict(os.environ, {"SAGE_USER_DATA_DIR": str(tmp_path)}):
            result = check.run()
        assert result.severity == Severity.INFO
        assert "首次安装" in result.message

    def test_info_when_all_configs_valid(self, check, tmp_path):
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        (config_dir / "settings.json").write_text(
            json.dumps({"version": "1", "key": "value"})
        )
        (config_dir / "users.json").write_text(
            json.dumps({"version": "1", "items": []})
        )
        with mock.patch.dict(os.environ, {"SAGE_USER_DATA_DIR": str(tmp_path)}):
            result = check.run()
        assert result.severity == Severity.INFO
        assert "2 个配置文件" in result.message

    def test_warn_when_config_broken_json(self, check, tmp_path):
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        (config_dir / "broken.json").write_text("{ this is not json")
        with mock.patch.dict(os.environ, {"SAGE_USER_DATA_DIR": str(tmp_path)}):
            result = check.run()
        assert result.severity == Severity.WARN
        assert "损坏" in result.message or "缺失" in result.message
        assert result.fix_hint is not None

    def test_warn_when_missing_required_field(self, check, tmp_path):
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        (config_dir / "no_version.json").write_text(json.dumps({"key": "value"}))
        with mock.patch.dict(os.environ, {"SAGE_USER_DATA_DIR": str(tmp_path)}):
            result = check.run()
        assert result.severity == Severity.WARN
        assert "version" in result.message
        assert "缺少" in result.message

    def test_warn_aggregates_multiple_problems(self, check, tmp_path):
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        (config_dir / "broken.json").write_text("not json at all")
        (config_dir / "missing.json").write_text(json.dumps({"key": "no version"}))
        with mock.patch.dict(os.environ, {"SAGE_USER_DATA_DIR": str(tmp_path)}):
            result = check.run()
        assert result.severity == Severity.WARN
        assert "broken.json" in result.message
        assert "missing.json" in result.message

    def test_check_attributes(self, check):
        assert check.name == "config_integrity"
        assert isinstance(check.description, str)
        assert check.description
