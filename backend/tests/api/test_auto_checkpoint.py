# ruff: noqa: UP006, UP007, UP035, UP045 — release/win7 Python 3.8 兼容，保留 typing 注解
"""B-2 (round5 批次 B): 发送前自动快照单元测试。

_auto_checkpoint_if_enabled 的三分支：开+绑定→快照 id；关→None；
开+未绑定→None。快照存储经 SAGE_USER_DATA_DIR 隔离到 tmp_path。
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import pytest

from backend.api.legacy_routes import _auto_checkpoint_if_enabled
from backend.data import database as database_module
from backend.data.database import Database
from backend.data.session_repo import SessionRepository
from backend.data.settings_repo import SettingsRepository
from backend.office.session_workspace import bind_session_workspace


@pytest.fixture()
def db(monkeypatch: pytest.MonkeyPatch) -> Database:
    test_db = Database(":memory:")
    test_db.init_db()
    monkeypatch.setattr(database_module, "_db", test_db)
    return test_db


@pytest.fixture(autouse=True)
def isolated_user_data(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "sage-user-data"
    monkeypatch.setenv("SAGE_USER_DATA_DIR", str(root))
    return root


def _set_pref(value: Optional[str]) -> None:
    if value is None:
        return
    SettingsRepository().set("auto_checkpoint", value)


def test_enabled_and_bound_creates_checkpoint(db: Database, tmp_path: Path) -> None:
    session = SessionRepository().create(title="快照会话")
    workspace = tmp_path / "ws"
    workspace.mkdir()
    (workspace / "a.txt").write_text("v1", encoding="utf-8")
    bind_session_workspace(db.get_connection(), session.id, str(workspace))

    _set_pref("1")
    checkpoint_id = _auto_checkpoint_if_enabled(session.id)
    assert checkpoint_id
    # 快照落盘可查（zip 存在）
    import hashlib
    import os

    key = hashlib.sha1(
        os.path.normcase(os.path.abspath(str(workspace))).encode("utf-8")
    ).hexdigest()
    checkpoint_dir = Path(os.environ["SAGE_USER_DATA_DIR"]) / "checkpoints" / key
    assert (checkpoint_dir / f"{checkpoint_id}.zip").is_file()


def test_disabled_skips(db: Database, tmp_path: Path) -> None:
    session = SessionRepository().create(title="未开启")
    workspace = tmp_path / "ws2"
    workspace.mkdir()
    bind_session_workspace(db.get_connection(), session.id, str(workspace))

    # 缺省（None）与显式 "0" 均跳过
    assert _auto_checkpoint_if_enabled(session.id) is None
    _set_pref("0")
    assert _auto_checkpoint_if_enabled(session.id) is None


def test_enabled_but_unbound_returns_none(db: Database) -> None:
    session = SessionRepository().create(title="未绑定")
    _set_pref("1")
    assert _auto_checkpoint_if_enabled(session.id) is None
