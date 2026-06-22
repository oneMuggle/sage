"""settings_repo 单元测试"""

import json
from unittest.mock import MagicMock

import pytest

from backend.data.settings_repo import SettingsRepository


@pytest.fixture()
def mock_db():
    db = MagicMock()
    conn = MagicMock()
    db.get_connection.return_value = conn
    return db, conn


def test_keys_whitelist():
    repo = SettingsRepository()  # noqa: F841  构造校验：实例化不应抛异常
    assert "app_settings" in SettingsRepository.KEYS
    assert "theme_mode" in SettingsRepository.KEYS
    assert "current_session_id" in SettingsRepository.KEYS


def test_get_returns_value(mock_db):
    db, conn = mock_db
    conn.execute.return_value.fetchone.return_value = {"value": "light"}
    repo = SettingsRepository(db=db)
    assert repo.get("theme_mode") == "light"


def test_get_returns_none_when_missing(mock_db):
    db, conn = mock_db
    conn.execute.return_value.fetchone.return_value = None
    repo = SettingsRepository(db=db)
    assert repo.get("theme_mode") is None


def test_get_json_parses_value(mock_db):
    db, conn = mock_db
    conn.execute.return_value.fetchone.return_value = {"value": '{"k": 1}'}
    repo = SettingsRepository(db=db)
    assert repo.get_json("app_settings") == {"k": 1}


def test_get_json_returns_none_on_invalid_json(mock_db):
    db, conn = mock_db
    conn.execute.return_value.fetchone.return_value = {"value": "not json"}
    repo = SettingsRepository(db=db)
    assert repo.get_json("app_settings") is None


def test_set_inserts_new_row(mock_db):
    db, conn = mock_db
    # fetchone 返回 None → 走 INSERT 分支
    conn.execute.return_value.fetchone.return_value = None
    repo = SettingsRepository(db=db)
    repo.set("theme_mode", "dark", value_type="string", category="ui")
    # 验证调用序列：SELECT 存在性检查 + INSERT
    assert conn.execute.call_count == 2
    # First call is SELECT existence check
    select_call = conn.execute.call_args_list[0]
    assert "SELECT" in str(select_call)
    assert "theme_mode" in str(select_call)
    # Second call is INSERT
    insert_call = conn.execute.call_args_list[1]
    assert "INSERT" in str(insert_call)
    assert "theme_mode" in str(insert_call)
    assert "dark" in str(insert_call)
    assert "string" in str(insert_call)
    assert "ui" in str(insert_call)
    conn.commit.assert_called()


def test_set_updates_existing_row(mock_db):
    db, conn = mock_db
    # fetchone 返回已有行 → 走 UPDATE 分支
    conn.execute.return_value.fetchone.return_value = {"key": "theme_mode"}
    repo = SettingsRepository(db=db)
    repo.set("theme_mode", "dark")
    # 验证调用序列：SELECT 存在性检查 + UPDATE
    assert conn.execute.call_count == 2
    # First call is SELECT existence check
    select_call = conn.execute.call_args_list[0]
    assert "SELECT" in str(select_call)
    # Second call is UPDATE
    update_call = conn.execute.call_args_list[1]
    assert "UPDATE" in str(update_call)
    assert "theme_mode" in str(update_call)
    assert "dark" in str(update_call)
    conn.commit.assert_called()


def test_set_json_serializes(mock_db):
    db, conn = mock_db
    conn.execute.return_value.fetchone.return_value = None
    repo = SettingsRepository(db=db)
    repo.set_json("app_settings", {"x": 1}, category="general")
    # call_args_list[0] = SELECT 存在性检查
    # call_args_list[1] = INSERT（JSON 字符串在这里）
    args = conn.execute.call_args_list[1]
    assert json.dumps({"x": 1}) in str(args)


def test_delete_removes_row(mock_db):
    db, conn = mock_db
    repo = SettingsRepository(db=db)
    repo.delete("theme_mode")
    conn.execute.assert_called()
    conn.commit.assert_called()


def test_list_by_category(mock_db):
    db, conn = mock_db
    # mock 模拟 SQL 已按 category 过滤后的结果（实现里 SQL 含 WHERE category = ?）
    conn.execute.return_value.fetchall.return_value = [
        {"key": "theme_mode", "value": "dark"},
    ]
    repo = SettingsRepository(db=db)
    result = repo.list_by_category("ui")
    assert result == {"theme_mode": "dark"}
