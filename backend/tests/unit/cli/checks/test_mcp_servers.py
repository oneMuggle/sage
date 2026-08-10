"""Tests for backend.cli.checks.mcp_servers.McpServersCheck."""
# ruff: noqa: SIM117 — nested with blocks are intentional for clarity in tests
from __future__ import annotations

import json
import os
from unittest import mock

import pytest

from backend.cli.checks.mcp_servers import (
    McpServersCheck,
    _command_resolvable,
    _resolve_mcp_config_path,
)
from backend.cli.doctor import Severity


@pytest.fixture()
def check():
    return McpServersCheck()


def _write_mcp_config(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        json.dump(payload, fh)


class TestResolveMcpConfigPath:
    def test_env_takes_precedence(self, tmp_path):
        with mock.patch.dict(os.environ, {"SAGE_USER_DATA_DIR": str(tmp_path)}):
            p = _resolve_mcp_config_path()
        assert p == tmp_path / "mcp_servers.json"

    def test_fallback_to_backend_data(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            p = _resolve_mcp_config_path()
        # 不依赖具体 project 路径,只断言文件名
        assert p.name == "mcp_servers.json"
        assert "data" in str(p)


class TestCommandResolvable:
    def test_empty_command(self):
        ok, reason = _command_resolvable("")
        assert ok is False
        assert "为空" in reason

    @pytest.mark.skipif(os.name == "nt", reason="POSIX-only path test")
    def test_absolute_path_executable(self):
        # /bin/sh 在所有 POSIX 都有
        ok, _reason = _command_resolvable("/bin/sh")
        assert ok is True

    def test_absolute_path_missing(self):
        ok, reason = _command_resolvable("/nonexistent/path/foo.sh")
        assert ok is False
        assert "不存在" in reason

    def test_path_lookup_via_which(self):
        # python3 一定在 PATH
        ok, _ = _command_resolvable("python3")
        assert ok is True

    def test_path_lookup_missing_command(self):
        ok, reason = _command_resolvable("definitely-not-a-real-cmd-12345")
        assert ok is False
        assert "PATH" in reason


class TestMcpServersCheck:
    def test_info_when_config_missing(self, check, tmp_path):
        with mock.patch.dict(os.environ, {"SAGE_USER_DATA_DIR": str(tmp_path)}):
            result = check.run()
        assert result.severity == Severity.INFO
        assert "未配置" in result.message

    def test_warn_when_bad_json(self, check, tmp_path):
        cfg = tmp_path / "mcp_servers.json"
        cfg.write_text("{not-json", encoding="utf-8")
        with mock.patch.dict(os.environ, {"SAGE_USER_DATA_DIR": str(tmp_path)}):
            result = check.run()
        assert result.severity == Severity.WARN
        assert "解析失败" in result.message

    def test_info_when_empty_servers(self, check, tmp_path):
        _write_mcp_config(tmp_path / "mcp_servers.json", {"servers": []})
        with mock.patch.dict(os.environ, {"SAGE_USER_DATA_DIR": str(tmp_path)}):
            result = check.run()
        assert result.severity == Severity.INFO

    @pytest.mark.skipif(os.name == "nt", reason="POSIX-only path test")
    def test_warn_when_command_unresolvable(self, check, tmp_path):
        _write_mcp_config(
            tmp_path / "mcp_servers.json",
            {
                "servers": [
                    {"name": "broken", "command": "/nonexistent/foo.sh"},
                ]
            },
        )
        with mock.patch.dict(os.environ, {"SAGE_USER_DATA_DIR": str(tmp_path)}):
            result = check.run()
        assert result.severity == Severity.WARN
        assert "broken" in result.message
        assert "1/1" in result.message

    @pytest.mark.skipif(os.name == "nt", reason="POSIX-only path test")
    def test_info_when_command_resolvable(self, check, tmp_path):
        _write_mcp_config(
            tmp_path / "mcp_servers.json",
            {
                "servers": [
                    {"name": "ok1", "command": "/bin/sh"},
                    {"name": "ok2", "command": "python3"},
                ]
            },
        )
        with mock.patch.dict(os.environ, {"SAGE_USER_DATA_DIR": str(tmp_path)}):
            result = check.run()
        assert result.severity == Severity.INFO
        assert "2 个 MCP server 全部可解析" in result.message

    def test_disabled_server_skipped(self, check, tmp_path):
        """enabled=False 的 server 不参与 command 校验。"""
        _write_mcp_config(
            tmp_path / "mcp_servers.json",
            {
                "servers": [
                    {"name": "disabled", "command": "/nonexistent", "enabled": False},
                    {"name": "ok", "command": "python3"},
                ]
            },
        )
        with mock.patch.dict(os.environ, {"SAGE_USER_DATA_DIR": str(tmp_path)}):
            result = check.run()
        assert result.severity == Severity.INFO

    def test_mixed_valid_and_invalid(self, check, tmp_path):
        """部分 server 不可解析 → WARN,提示修正。"""
        _write_mcp_config(
            tmp_path / "mcp_servers.json",
            {
                "servers": [
                    {"name": "ok", "command": "python3"},
                    {"name": "broken", "command": "/no/such/path"},
                ]
            },
        )
        with mock.patch.dict(os.environ, {"SAGE_USER_DATA_DIR": str(tmp_path)}):
            result = check.run()
        assert result.severity == Severity.WARN
        assert "1/2" in result.message

    def test_check_attributes(self, check):
        assert check.name == "mcp_servers"
        assert isinstance(check.description, str)
        assert check.description
