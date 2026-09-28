"""R178 — MemoryManager（三层记忆协调层）单元测试。

用 SimpleNamespace fake 三层记忆（working/episodic/semantic）验证协调层
的委托方向、返回值透传与分类分派逻辑。
"""

from __future__ import annotations

import pytest

from backend.memory.manager import MemoryManager

pytestmark = pytest.mark.unit


class _FakeWorking:
    def __init__(self):
        self.added = []
        self.cleared = []
        self._seq = 0
        self.messages = []
        self.total_tokens = 0

    def session_ids(self):
        return set()

    def delete_message(self, session_id, seq):
        return True

    def add(self, session_id, msg, segment_id=0):
        self._seq += 1
        self.added.append((session_id, msg, segment_id))
        return self._seq

    def resolve_session_id(self, session_id):
        return session_id or "default"

    def get_context(self, session_id=None, segment_id=None):
        return [{"role": "user", "content": "hello"}]

    def get_summary(self, session_id=None):
        return "对话摘要"

    def clear(self, session_id=None):
        self.cleared.append(session_id)

    def clear_segment(self, session_id, segment_id):
        self.cleared.append((session_id, segment_id))


class _FakeEpisodic:
    def __init__(self):
        self.saved = []

    def save(self, content, **kwargs):
        self.saved.append({"content": content, **kwargs})
        return f"ep-{len(self.saved)}"

    def search(self, query, limit=5, session_id=None):
        return [{"content": f"match: {query}"}]


class _FakeSemantic:
    def __init__(self):
        self.saved = []

    def save(self, content, **kwargs):
        self.saved.append({"content": content, **kwargs})
        return f"sem-{len(self.saved)}"

    def search(self, query, limit=5, session_id=None):
        return [{"content": f"sem: {query}"}]


@pytest.fixture()
def layers():
    return {
        "working": _FakeWorking(),
        "episodic": _FakeEpisodic(),
        "semantic": _FakeSemantic(),
    }


@pytest.fixture()
def manager(layers):
    return MemoryManager(
        working=layers["working"],
        episodic=layers["episodic"],
        semantic=layers["semantic"],
    )


# ---------------------------------------------------------------------------
# remember → episodic
# ---------------------------------------------------------------------------


def test_remember_delegates_to_episodic(manager, layers):
    mid = manager.remember("用户偏好", metadata={"session_id": "s1"})
    assert mid.startswith("ep-")
    assert layers["episodic"].saved[0]["content"] == "用户偏好"
    assert layers["episodic"].saved[0]["session_id"] == "s1"


def test_remember_default_importance(manager, layers):
    manager.remember("content")
    assert layers["episodic"].saved[0]["importance"] == 5


# ---------------------------------------------------------------------------
# memorize 分派
# ---------------------------------------------------------------------------


def test_memorize_low_importance_short_to_working(manager, layers):
    mid = manager.memorize("hi", importance=3)
    assert mid.startswith("wm:")
    assert len(layers["working"].added) == 1
    assert layers["working"].added[0][1]["content"] == "hi"


def test_memorize_high_importance_to_semantic(manager, layers):
    mid = manager.memorize("关键事实", importance=9)
    assert mid.startswith("sem-")
    assert layers["semantic"].saved[0]["content"] == "关键事实"


def test_memorize_default_to_episodic(manager, layers):
    mid = manager.memorize("x" * 300, importance=5)
    assert mid.startswith("ep-")
    assert layers["episodic"].saved[0]["content"] == "x" * 300


def test_memorize_tags_injected_into_episodic_metadata(manager, layers):
    manager.memorize("content", memory_type="episodic", tags=["a", "b"])
    assert layers["episodic"].saved[0]["metadata"]["tags"] == ["a", "b"]


def test_memorize_explicit_type_bypasses_auto(manager, layers):
    manager.memorize("关键", memory_type="working", importance=9)
    assert len(layers["working"].added) == 1  # 显式 working 覆盖 importance 规则


# ---------------------------------------------------------------------------
# delete_memory
# ---------------------------------------------------------------------------


def test_delete_memory_delegates_to_episodic_and_semantic(manager, layers):
    layers["episodic"].delete = lambda mid: mid == "ep-1"
    layers["semantic"].delete = lambda mid: False
    assert manager.delete_memory("ep-1", "episodic") is True
    assert manager.delete_memory("ghost", "episodic") is False


def test_delete_memory_semantic_type(manager, layers):
    layers["semantic"].delete = lambda mid: True
    assert manager.delete_memory("sem-1", "semantic") is True


def test_delete_memory_working_delegates(manager, layers):
    # wm:s1:1 → session="s1", seq=1 → 委托 working.delete_message("s1", 1)
    assert manager.delete_memory("wm:s1:1", "working") is True
    # 格式非法 → False
    assert manager.delete_memory("not-wm", "working") is False


# ---------------------------------------------------------------------------
# get_stats
# ---------------------------------------------------------------------------


def test_get_stats_aggregates_three_layers(manager, layers):
    layers["episodic"].count = lambda: 10
    layers["semantic"].count = lambda: 3
    stats = manager.get_stats()
    assert stats["working"]["message_count"] == 0  # fake messages 空
    assert stats["episodic"]["total"] == 10
    assert stats["semantic"]["total"] == 3


# ---------------------------------------------------------------------------
# add_to_working / compress
# ---------------------------------------------------------------------------


def test_add_to_working_delegates(manager, layers):
    manager.add_to_working("user", "hello", session_id="s1")
    assert layers["working"].added == [("s1", {"role": "user", "content": "hello"}, 0)]


def test_compress_delegates_to_working_and_episodic(manager, layers):
    manager.compress(session_id="s1")
    # working.clear 被调用
    assert "s1" in layers["working"].cleared
    # 摘要写入 episodic
    assert any("对话摘要" in s["content"] for s in layers["episodic"].saved)


def test_compress_empty_working_noop(manager, layers):
    layers["working"].get_context = lambda session_id=None, segment_id=None: []
    manager.compress(session_id="s1")
    assert layers["episodic"].saved == []
