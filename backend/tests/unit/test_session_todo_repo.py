"""SessionTodoRepository + todo 持久化（B4, 2026-09-09）单测。

- repo CRUD：upsert 整体替换 / get / 损坏 JSON 按无数据处理
- todo 单例 write-through：replace 落库；新实例（模拟重启）经 get 回填
- 匿名桶不落库；structured output 用的纯 SessionStateStore 不落库
"""

from __future__ import annotations

import pytest

from backend.data import database as db_mod
from backend.data.session_todo_repo import SessionTodoRepository
from backend.tools.todo_state import (
    ANONYMOUS_SESSION_ID,
    SessionStateStore,
    get_todo_store,
)


@pytest.fixture()
def repo(tmp_path, monkeypatch):
    """tmp DB + SAGE_DB_PATH env + 重置全局 _db 单例。"""
    db_path = tmp_path / "test.db"
    monkeypatch.setenv("SAGE_DB_PATH", str(db_path))
    monkeypatch.setattr(db_mod, "_db", None)
    db = db_mod.get_database()
    db.init_db()
    return SessionTodoRepository()


_TODOS = [
    {"content": "第一步", "status": "completed"},
    {"content": "第二步", "status": "in_progress", "activeForm": "正在执行"},
]


def test_upsert_and_get_roundtrip(repo):
    repo.upsert("s-1", _TODOS)
    assert repo.get("s-1") == _TODOS


def test_upsert_replaces_whole_list(repo):
    repo.upsert("s-1", _TODOS)
    repo.upsert("s-1", [{"content": "新清单", "status": "pending"}])
    assert repo.get("s-1") == [{"content": "新清单", "status": "pending"}]


def test_get_missing_returns_none(repo):
    assert repo.get("nope") is None


def test_corrupted_json_treated_as_missing(repo):
    repo.upsert("s-1", _TODOS)
    conn = db_mod.get_database().get_connection()
    conn.execute(
        "UPDATE session_todos SET todos_json = '{broken' WHERE session_id = 's-1'"
    )
    conn.commit()
    assert repo.get("s-1") is None


def test_todo_store_write_through(repo):
    """todo 单例 replace → DB 立即有行（write-through）。"""
    store = get_todo_store()
    store.replace("s-write", _TODOS)
    assert SessionTodoRepository().get("s-write") == _TODOS


def test_todo_store_survives_cache_loss(repo):
    """模拟 LRU 淘汰：桶被逐出后 get 从 DB 回填。

    注意不走 ``clear()`` —— B4 起 clear 语义是"处处遗忘"（连持久行一起删），
    与淘汰不同。这里直接摘桶模拟淘汰。
    """
    store = get_todo_store()
    store.replace("s-restart", _TODOS)
    store._buckets.pop("s-restart", None)
    assert store.get("s-restart") == _TODOS


def test_todo_store_new_instance_reads_persisted(repo):
    """模拟进程重启：全新 store 实例读到上一进程写入的清单。"""
    get_todo_store().replace("s-new", _TODOS)
    from backend.tools.todo_state import _NotifyingTodoStore

    fresh = _NotifyingTodoStore()
    assert fresh.get("s-new") == _TODOS


def test_anonymous_bucket_not_persisted(repo):
    get_todo_store().replace(ANONYMOUS_SESSION_ID, _TODOS)
    assert repo.get(ANONYMOUS_SESSION_ID) is None


def test_plain_session_state_store_not_persisted(repo):
    """structured output 等直接用基类的存储保持纯内存语义。"""
    plain = SessionStateStore()
    plain.replace("s-plain", _TODOS)
    assert repo.get("s-plain") is None
    plain.clear()  # 防跨测试串扰


def test_lru_evicted_bucket_falls_back_to_db(repo):
    """LRU 淘汰后 get 仍能从 DB 恢复，且返回拷贝（改返回值不影响后续读）。"""
    store = get_todo_store()
    store.replace("s-evict", _TODOS)
    store._buckets.pop("s-evict", None)
    # 二次读取走 DB 回填且返回拷贝
    first = store.get("s-evict")
    first[0]["status"] = "tampered"
    assert store.get("s-evict") == _TODOS


def test_clear_removes_persisted_row(repo):
    """clear 语义 = 处处遗忘：内存桶 + 持久行一起删（否则 get 会从 DB 复活）。"""
    store = get_todo_store()
    store.replace("s-clear", _TODOS)
    assert repo.get("s-clear") is not None
    store.clear("s-clear")
    assert repo.get("s-clear") is None
    assert store.get("s-clear") is None
