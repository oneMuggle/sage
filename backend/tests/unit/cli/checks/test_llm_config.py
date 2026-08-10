"""Tests for backend.cli.checks.llm_config.LlmConfigCheck."""
# ruff: noqa: SIM117 — nested with blocks are intentional for clarity in tests
from __future__ import annotations

import json
import os
import sqlite3
from unittest import mock

import pytest

from backend.cli.checks.llm_config import (
    LlmConfigCheck,
    _load_app_settings_json,
)
from backend.cli.doctor import Severity


@pytest.fixture()
def check():
    return LlmConfigCheck()


def _write_app_settings(db_path, payload):
    """Insert a row into the preferences table for app_settings."""
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS preferences (key TEXT PRIMARY KEY, value TEXT)"
        )
        conn.execute(
            "INSERT INTO preferences(key, value) VALUES (?, ?)",
            ("app_settings", json.dumps(payload)),
        )
        conn.commit()
    finally:
        conn.close()


class TestLlmConfigCheck:
    def test_info_when_db_missing(self, check, tmp_path):
        """未初始化:DB 不存在 → INFO(首次安装或冷启动早期)"""
        with mock.patch.dict(os.environ, {"SAGE_USER_DATA_DIR": str(tmp_path)}):
            result = check.run()
        assert result.severity == Severity.INFO
        assert "尚未配置" in result.message

    def test_info_when_no_app_settings_row(self, check, tmp_path):
        """DB 存在但无 app_settings 行 → INFO(用户从未打开过设置页)"""
        db = tmp_path / "sage.db"
        conn = sqlite3.connect(str(db))
        try:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS preferences (key TEXT PRIMARY KEY, value TEXT)"
            )
            conn.commit()
        finally:
            conn.close()
        with mock.patch.dict(os.environ, {"SAGE_USER_DATA_DIR": str(tmp_path)}):
            result = check.run()
        assert result.severity == Severity.INFO

    def test_warn_when_no_endpoints_list(self, check, tmp_path):
        """app_settings 存在但无 endpoints 列表 → WARN(用户开了设置但没配)"""
        db = tmp_path / "sage.db"
        _write_app_settings(db, {"theme_mode": "dark"})
        with mock.patch.dict(os.environ, {"SAGE_USER_DATA_DIR": str(tmp_path)}):
            result = check.run()
        assert result.severity == Severity.WARN
        assert "endpoints" in result.message

    def test_warn_when_all_endpoints_missing_key(self, check, tmp_path):
        """所有 endpoint 都没 apiKey → WARN(最常见的报障场景)"""
        db = tmp_path / "sage.db"
        _write_app_settings(
            db,
            {
                "llm": {
                    "endpoints": [
                        {"name": "e1", "apiKey": ""},
                        {"name": "e2", "apiKey": "   "},
                    ]
                }
            },
        )
        with mock.patch.dict(os.environ, {"SAGE_USER_DATA_DIR": str(tmp_path)}):
            result = check.run()
        assert result.severity == Severity.WARN
        assert "2 个 endpoint 全部未配置" in result.message
        assert result.fix_hint

    def test_info_when_some_endpoints_have_key(self, check, tmp_path):
        """部分 endpoint 有 key → INFO(可用,只是不完整)"""
        db = tmp_path / "sage.db"
        _write_app_settings(
            db,
            {
                "llm": {
                    "endpoints": [
                        {"name": "e1", "apiKey": ""},
                        {"name": "e2", "apiKey": "sk-test"},
                    ]
                }
            },
        )
        with mock.patch.dict(os.environ, {"SAGE_USER_DATA_DIR": str(tmp_path)}):
            result = check.run()
        assert result.severity == Severity.INFO
        assert "1/2" in result.message

    def test_info_when_all_endpoints_have_key(self, check, tmp_path):
        """所有 endpoint 都有 key → INFO(完整可用)"""
        db = tmp_path / "sage.db"
        _write_app_settings(
            db,
            {
                "llm": {
                    "endpoints": [
                        {"name": "e1", "apiKey": "sk-1"},
                        {"name": "e2", "apiKey": "sk-2"},
                    ]
                }
            },
        )
        with mock.patch.dict(os.environ, {"SAGE_USER_DATA_DIR": str(tmp_path)}):
            result = check.run()
        assert result.severity == Severity.INFO
        assert "2 个 endpoint 全部已配置" in result.message

    def test_info_when_bad_json_in_db(self, check, tmp_path):
        """app_settings 行的 JSON 损坏 → INFO(不阻塞 doctor)"""
        db = tmp_path / "sage.db"
        conn = sqlite3.connect(str(db))
        try:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS preferences (key TEXT PRIMARY KEY, value TEXT)"
            )
            conn.execute(
                "INSERT INTO preferences(key, value) VALUES (?, ?)",
                ("app_settings", "not-json{"),
            )
            conn.commit()
        finally:
            conn.close()
        with mock.patch.dict(os.environ, {"SAGE_USER_DATA_DIR": str(tmp_path)}):
            result = check.run()
        assert result.severity == Severity.INFO

    def test_check_attributes(self, check):
        assert check.name == "llm_config"
        assert isinstance(check.description, str)
        assert check.description


class TestLoadAppSettingsJson:
    """_load_app_settings_json 是 fail-open 关键函数,所有异常路径都要降级。"""

    def test_returns_none_when_path_missing(self, tmp_path):
        assert _load_app_settings_json(tmp_path / "missing.db") is None

    def test_returns_none_when_preferences_table_missing(self, tmp_path):
        db = tmp_path / "sage.db"
        sqlite3.connect(str(db)).close()  # 创建空 db,无表
        assert _load_app_settings_json(db) is None

    def test_returns_none_when_app_settings_row_missing(self, tmp_path):
        db = tmp_path / "sage.db"
        conn = sqlite3.connect(str(db))
        try:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS preferences (key TEXT PRIMARY KEY, value TEXT)"
            )
            conn.commit()
        finally:
            conn.close()
        assert _load_app_settings_json(db) is None
