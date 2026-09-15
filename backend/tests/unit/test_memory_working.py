"""验证 WorkingMemory 的滑动窗口与变量/实体辅助 API。"""

from __future__ import annotations

import tempfile

import pytest

from backend.data.database import Database
from backend.memory.working import WorkingMemory

pytestmark = pytest.mark.unit


@pytest.fixture()
def tmp_db() -> Database:
    """创建临时数据库用于快照持久化测试。"""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db = Database(f.name)
        db.init_db()
        yield db
        db.close()


def test_init_default_state() -> None:
    """构造后属性具备默认值。"""
    wm = WorkingMemory()
    assert wm.max_size == 20
    assert wm.max_tokens == 4000
    assert len(wm.messages) == 0
    assert wm.total_tokens == 0
    assert wm.session_summary == ""
    assert wm.active_entities == []
    assert wm.temp_variables == {}


def test_add_message_updates_state() -> None:
    wm = WorkingMemory()
    wm.add({"role": "user", "content": "hello world"})
    assert len(wm.messages) == 1
    assert wm.messages[0]["role"] == "user"
    assert wm.messages[0]["content"] == "hello world"
    assert wm.messages[0]["tokens"] >= 0
    assert wm.total_tokens >= 0


def test_evict_when_exceeding_max_tokens() -> None:
    """当总 tokens 超出阈值时，旧消息被淘汰。"""
    wm = WorkingMemory(max_size=50, max_tokens=10)
    for _ in range(8):
        wm.add({"role": "user", "content": "abcdefghij" * 5})
    assert wm.total_tokens <= wm.max_tokens or len(wm.messages) == 1


def test_get_context_with_and_without_limit() -> None:
    wm = WorkingMemory()
    for i in range(3):
        wm.add({"role": "user", "content": f"msg {i}"})
    assert len(wm.get_context()) == 3
    assert len(wm.get_context(limit=1)) == 1
    assert wm.get_context(limit=1)[0]["content"] == "msg 2"


def test_get_recent_returns_last_n() -> None:
    wm = WorkingMemory()
    for i in range(5):
        wm.add({"role": "user", "content": f"m{i}"})
    recent = wm.get_recent(limit=2)
    assert len(recent) == 2
    assert recent[-1]["content"] == "m4"


def test_clear_resets_all_state() -> None:
    wm = WorkingMemory()
    wm.add({"role": "user", "content": "x"})
    wm.add_entity("Alice")
    wm.set_variable("k", "v")
    wm.set_summary("a summary")
    wm.clear()
    assert len(wm.messages) == 0
    assert wm.total_tokens == 0
    assert wm.session_summary == ""
    assert wm.active_entities == []
    assert wm.temp_variables == {}


def test_summary_get_set_default() -> None:
    wm = WorkingMemory()
    s = wm.get_summary()
    assert "条消息" in s
    wm.set_summary("custom summary")
    assert wm.get_summary() == "custom summary"


def test_entity_dedup() -> None:
    wm = WorkingMemory()
    wm.add_entity("Bob")
    wm.add_entity("Bob")
    wm.add_entity("Alice")
    assert wm.active_entities == ["Bob", "Alice"]


def test_variable_set_get_default() -> None:
    wm = WorkingMemory()
    assert wm.get_variable("missing") is None
    assert wm.get_variable("missing", default="d") == "d"
    wm.set_variable("k", 42)
    assert wm.get_variable("k") == 42


def test_estimate_tokens_handles_chinese_and_english() -> None:
    wm = WorkingMemory()
    n_zh = wm._estimate_tokens("你好世界")
    n_en = wm._estimate_tokens("hello world")
    assert n_zh >= 4
    assert n_en >= 0


def test_unknown_role_default() -> None:
    wm = WorkingMemory()
    wm.add({"content": "no role"})
    assert wm.messages[0]["role"] == "unknown"


# ==================== Session 感知（WS-A） ====================


def test_add_with_explicit_session_id() -> None:
    """add(session_id, message) 新签名：消息携带 session_id。"""
    wm = WorkingMemory()
    wm.add("sess-A", {"role": "user", "content": "hello A"})
    assert len(wm.messages) == 1
    assert wm.messages[0]["session_id"] == "sess-A"


def test_session_isolation_get_context() -> None:
    """A 的消息不出现在 B 的 get_context 中，反之亦然。"""
    wm = WorkingMemory()
    wm.add("A", {"role": "user", "content": "a1"})
    wm.add("A", {"role": "assistant", "content": "a2"})
    wm.add("B", {"role": "user", "content": "b1"})

    assert [m["content"] for m in wm.get_context("A")] == ["a1", "a2"]
    assert [m["content"] for m in wm.get_context("B")] == ["b1"]
    # 默认会话（None）不受影响
    assert wm.get_context() == []


def test_session_isolation_total_tokens_for() -> None:
    """total_tokens_for 按 session 计数；total_tokens 属性为全局合计。"""
    wm = WorkingMemory()
    wm.add("A", {"role": "user", "content": "x" * 40})
    wm.add("B", {"role": "user", "content": "y" * 80})

    ta = wm.total_tokens_for("A")
    tb = wm.total_tokens_for("B")
    assert ta > 0
    assert tb > ta
    assert wm.total_tokens_for() == 0  # 默认会话为空
    assert wm.total_tokens == ta + tb


def test_session_isolation_clear() -> None:
    """clear(session_id) 只清空指定会话。"""
    wm = WorkingMemory()
    wm.add("A", {"role": "user", "content": "a"})
    wm.add("B", {"role": "user", "content": "b"})

    wm.clear("A")

    assert wm.get_context("A") == []
    assert wm.total_tokens_for("A") == 0
    assert [m["content"] for m in wm.get_context("B")] == ["b"]


def test_per_session_max_size_eviction() -> None:
    """max_size 按 session 各自淘汰：A 超限不影响 B。"""
    wm = WorkingMemory(max_size=3, max_tokens=1_000_000)
    for i in range(5):
        wm.add("A", {"role": "user", "content": f"a{i}"})
    for i in range(2):
        wm.add("B", {"role": "user", "content": f"b{i}"})

    ctx_a = wm.get_context("A")
    assert len(ctx_a) == 3
    assert [m["content"] for m in ctx_a] == ["a2", "a3", "a4"]  # 保留最新 3 条
    assert len(wm.get_context("B")) == 2  # B 未被 A 的淘汰波及


def test_per_session_max_tokens_eviction() -> None:
    """max_tokens 按 session 各自淘汰：A 超限不影响 B。"""
    wm = WorkingMemory(max_size=100, max_tokens=30)
    for _ in range(5):
        wm.add("A", {"role": "user", "content": "z" * 40})
    wm.add("B", {"role": "user", "content": "z" * 40})

    assert wm.total_tokens_for("A") <= 30 or len(wm.get_context("A")) == 1
    assert len(wm.get_context("B")) == 1  # B 未被 A 的淘汰波及


def test_add_returns_per_session_seq() -> None:
    """add 返回 per-session 自增序号（供上层合成 wm:<sid>:<seq> id）。"""
    wm = WorkingMemory()
    assert wm.add("A", {"role": "user", "content": "1"}) == 1
    assert wm.add("A", {"role": "user", "content": "2"}) == 2
    assert wm.add("B", {"role": "user", "content": "x"}) == 1  # B 独立计数


def test_legacy_single_dict_add_still_works() -> None:
    """旧调用 add(message_dict) 仍然有效（落入默认会话），可与新调用混用。"""
    wm = WorkingMemory()
    wm.add({"role": "user", "content": "legacy"})
    assert wm.get_context()[0]["content"] == "legacy"

    wm.add("S", {"role": "user", "content": "new"})
    assert [m["content"] for m in wm.get_context()] == ["legacy"]
    assert [m["content"] for m in wm.get_context("S")] == ["new"]


def test_get_context_positional_int_is_limit() -> None:
    """旧式 get_context(limit) 位置参数兼容：单个 int 视为 limit。"""
    wm = WorkingMemory()
    for i in range(3):
        wm.add({"role": "user", "content": f"m{i}"})
    assert len(wm.get_context(2)) == 2


def test_bound_session_instance() -> None:
    """构造时 session_id = 实例默认会话（兼容旧绑定式 API）。

    无参调用（add/get_context/clear）落在绑定会话上；
    messages 属性只展示绑定会话的消息。
    """
    wm = WorkingMemory(session_id="bound-1")
    wm.add({"role": "user", "content": "via bound"})

    assert wm.get_context()[0]["content"] == "via bound"
    assert wm.get_context("bound-1")[0]["content"] == "via bound"

    # 显式写入其他会话：messages 属性只展示绑定会话
    wm.add("other", {"role": "user", "content": "explicit other"})
    assert len(wm.messages) == 1
    assert wm.messages[0]["content"] == "via bound"


# ==================== 快照按 session 持久化（WS-A） ====================


def test_snapshot_writes_real_session_id(tmp_db: Database) -> None:
    """快照写入真实 session_id 值（不再写 NULL）。"""
    wm = WorkingMemory(db=tmp_db)
    wm.add("sess-X", {"role": "user", "content": "hello"})
    wm.add("sess-Y", {"role": "user", "content": "world"})

    conn = tmp_db.get_connection()
    rows = conn.execute("SELECT DISTINCT session_id FROM working_memory_snapshot").fetchall()
    assert {r["session_id"] for r in rows} == {"sess-X", "sess-Y"}


def test_snapshot_restore_named_sessions_unbound(tmp_db: Database) -> None:
    """重启后（新的未绑定实例）按 session 恢复具名会话。"""
    wm1 = WorkingMemory(db=tmp_db)
    wm1.add("sA", {"role": "user", "content": "alpha"})
    wm1.add("sB", {"role": "user", "content": "beta"})

    wm2 = WorkingMemory(db=tmp_db)
    assert [m["content"] for m in wm2.get_context("sA")] == ["alpha"]
    assert [m["content"] for m in wm2.get_context("sB")] == ["beta"]
    assert wm2.total_tokens_for("sA") == wm1.total_tokens_for("sA")


def test_snapshot_restore_bound_instance(tmp_db: Database) -> None:
    """绑定会话的实例重启后只恢复自己的会话。"""
    wm1 = WorkingMemory(db=tmp_db)
    wm1.add("sA", {"role": "user", "content": "alpha"})
    wm1.add("sB", {"role": "user", "content": "beta"})

    bound = WorkingMemory(db=tmp_db, session_id="sA")
    assert [m["content"] for m in bound.messages] == ["alpha"]
    assert bound.total_tokens == bound.total_tokens_for("sA")


def test_snapshot_clear_persists_per_session(tmp_db: Database) -> None:
    """clear(session) 后快照只删除该会话的行，其他会话保留。"""
    wm1 = WorkingMemory(db=tmp_db)
    wm1.add("sA", {"role": "user", "content": "alpha"})
    wm1.add("sB", {"role": "user", "content": "beta"})

    wm1.clear("sA")

    wm2 = WorkingMemory(db=tmp_db)
    assert wm2.get_context("sA") == []
    assert [m["content"] for m in wm2.get_context("sB")] == ["beta"]


def test_snapshot_default_session_not_auto_restored_unbound(tmp_db: Database) -> None:
    """未绑定实例启动时不自动恢复默认会话（保持 registry 单例"启动即空"的既有行为）。

    默认会话（legacy 无 session 调用产生）的快照仍会写入，
    但具名会话才是重启恢复的目标——与旧实现（NULL 行永远无法恢复）行为等价。
    """
    wm1 = WorkingMemory(db=tmp_db)
    wm1.add({"role": "user", "content": "default msg"})

    wm2 = WorkingMemory(db=tmp_db)
    assert wm2.get_context() == []
