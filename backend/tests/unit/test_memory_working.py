"""验证 WorkingMemory 的滑动窗口与变量/实体辅助 API。"""

from __future__ import annotations

import pytest

from backend.memory.working import WorkingMemory

pytestmark = pytest.mark.unit


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
