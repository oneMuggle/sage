"""验证 WorkingMemory 的 SQLite 持久化功能。"""

from __future__ import annotations

import tempfile

import pytest

from backend.data.database import Database
from backend.memory.working import WorkingMemory

pytestmark = pytest.mark.unit


@pytest.fixture
def tmp_db() -> Database:
    """创建临时数据库用于测试"""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db = Database(f.name)
        db.init_db()
        yield db
        db.close()


def test_save_and_load_snapshot(tmp_db: Database) -> None:
    """保存快照后重新加载，数据应一致。"""
    wm1 = WorkingMemory(max_size=20, max_tokens=4000, db=tmp_db, session_id="test-session")
    wm1.add({"role": "user", "content": "你好"})
    wm1.add({"role": "assistant", "content": "你好！有什么可以帮你的？"})

    # 创建新实例，应从 SQLite 恢复
    wm2 = WorkingMemory(max_size=20, max_tokens=4000, db=tmp_db, session_id="test-session")

    assert len(wm2.messages) == 2
    assert wm2.messages[0]["role"] == "user"
    assert wm2.messages[0]["content"] == "你好"
    assert wm2.messages[1]["role"] == "assistant"
    assert wm2.messages[1]["content"] == "你好！有什么可以帮你的？"
    assert wm2.total_tokens == wm1.total_tokens


def test_load_empty_snapshot(tmp_db: Database) -> None:
    """空数据库加载后应为空状态。"""
    wm = WorkingMemory(max_size=20, max_tokens=4000, db=tmp_db, session_id="empty-session")
    assert len(wm.messages) == 0
    assert wm.total_tokens == 0


def test_clear_persists_empty_state(tmp_db: Database) -> None:
    """clear() 后持久化应反映空状态。"""
    wm1 = WorkingMemory(max_size=20, max_tokens=4000, db=tmp_db, session_id="clear-test")
    wm1.add({"role": "user", "content": "测试"})
    assert len(wm1.messages) == 1

    wm1.clear()

    wm2 = WorkingMemory(max_size=20, max_tokens=4000, db=tmp_db, session_id="clear-test")
    assert len(wm2.messages) == 0
    assert wm2.total_tokens == 0


def test_session_isolation(tmp_db: Database) -> None:
    """不同 session_id 的工作记忆应互相隔离。"""
    wm1 = WorkingMemory(max_size=20, max_tokens=4000, db=tmp_db, session_id="session-A")
    wm1.add({"role": "user", "content": "来自A的消息"})

    wm2 = WorkingMemory(max_size=20, max_tokens=4000, db=tmp_db, session_id="session-B")
    wm2.add({"role": "user", "content": "来自B的消息"})

    # 各自恢复时只看到自己的消息
    wm1_restored = WorkingMemory(max_size=20, max_tokens=4000, db=tmp_db, session_id="session-A")
    assert len(wm1_restored.messages) == 1
    assert wm1_restored.messages[0]["content"] == "来自A的消息"

    wm2_restored = WorkingMemory(max_size=20, max_tokens=4000, db=tmp_db, session_id="session-B")
    assert len(wm2_restored.messages) == 1
    assert wm2_restored.messages[0]["content"] == "来自B的消息"


def test_no_db_disables_persistence() -> None:
    """不传 db 参数时不启用持久化（向后兼容）。"""
    wm = WorkingMemory(max_size=20, max_tokens=4000)
    wm.add({"role": "user", "content": "测试"})
    assert len(wm.messages) == 1
    assert wm._db is None


def test_eviction_after_restore(tmp_db: Database) -> None:
    """恢复后如果超出 max_tokens 应自动淘汰。"""
    wm1 = WorkingMemory(max_size=50, max_tokens=10000, db=tmp_db, session_id="evict-test")
    for i in range(10):
        wm1.add({"role": "user", "content": f"消息{i}" * 50})

    # 用小 max_tokens 恢复
    wm2 = WorkingMemory(max_size=50, max_tokens=100, db=tmp_db, session_id="evict-test")
    assert wm2.total_tokens <= 100 or len(wm2.messages) == 1


def test_db_error_does_not_crash(tmp_db: Database) -> None:
    """数据库异常不应导致 add() 失败。"""
    wm = WorkingMemory(max_size=20, max_tokens=4000, db=tmp_db, session_id="error-test")

    # 关闭数据库连接模拟错误
    tmp_db.close()

    # add 不应抛异常
    wm.add({"role": "user", "content": "测试"})
    assert len(wm.messages) == 1
