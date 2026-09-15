"""Unit tests for MemoryWriteLedger（对标 S2：记忆写入台账）。"""

import pytest

from backend.memory.write_ledger import (
    KIND_MEMORY,
    KIND_PROFILE,
    MemoryWriteLedger,
    get_write_ledger,
    reset_write_ledger,
)

pytestmark = pytest.mark.unit


@pytest.fixture
def ledger():
    return MemoryWriteLedger(per_session_limit=3, session_limit=2)


class TestRecord:
    def test_record_and_list_since(self, ledger):
        r1 = ledger.record(memory_id="m1", kind=KIND_MEMORY, content="用户喜欢火锅", session_id="s1")
        r2 = ledger.record(memory_id="p1", kind=KIND_PROFILE, content="偏好简洁", session_id="s1")
        assert r1 is not None
        assert r2 is not None
        assert r2.seq > r1.seq
        items = ledger.list_since("s1")
        assert [i.id for i in items] == ["m1", "p1"]
        assert ledger.list_since("s1", after_seq=r1.seq) == [r2]
        assert ledger.latest_seq("s1") == r2.seq

    def test_invalid_inputs_ignored(self, ledger):
        assert ledger.record(memory_id="", kind=KIND_MEMORY, content="x", session_id="s") is None
        assert ledger.record(memory_id="m", kind=KIND_MEMORY, content="x", session_id=None) is None
        assert ledger.record(memory_id="m", kind="bogus", content="x", session_id="s") is None
        assert ledger.list_since("s") == []
        assert ledger.latest_seq("s") == 0

    def test_per_session_bound(self, ledger):
        for i in range(5):
            ledger.record(memory_id=f"m{i}", kind=KIND_MEMORY, content="c", session_id="s1")
        ids = [r.id for r in ledger.list_since("s1")]
        assert ids == ["m2", "m3", "m4"]

    def test_session_lru_bound(self, ledger):
        ledger.record(memory_id="a", kind=KIND_MEMORY, content="c", session_id="s1")
        ledger.record(memory_id="b", kind=KIND_MEMORY, content="c", session_id="s2")
        ledger.record(memory_id="c", kind=KIND_MEMORY, content="c", session_id="s3")
        assert ledger.list_since("s1") == []
        assert ledger.list_since("s3")[0].id == "c"

    def test_content_truncated(self, ledger):
        r = ledger.record(memory_id="m", kind=KIND_MEMORY, content="x" * 500, session_id="s")
        assert len(r.content) == 200

    def test_profile_default_memory_type(self, ledger):
        r = ledger.record(memory_id="p", kind=KIND_PROFILE, content="c", session_id="s")
        assert r.memory_type == "profile"


class TestForget:
    def test_find_and_forget(self, ledger):
        ledger.record(memory_id="m1", kind=KIND_MEMORY, content="c", session_id="s1")
        ledger.record(memory_id="m2", kind=KIND_MEMORY, content="c", session_id="s1")
        assert ledger.find("s1", "m1").id == "m1"
        assert ledger.forget("s1", "m1") is True
        assert ledger.forget("s1", "m1") is False
        assert [r.id for r in ledger.list_since("s1")] == ["m2"]
        assert ledger.find("s1", "m1") is None

    def test_clear(self, ledger):
        ledger.record(memory_id="m1", kind=KIND_MEMORY, content="c", session_id="s1")
        ledger.clear("s1")
        assert ledger.list_since("s1") == []


class TestSingleton:
    def test_singleton_reset(self):
        reset_write_ledger()
        a = get_write_ledger()
        assert get_write_ledger() is a
        reset_write_ledger()
        assert get_write_ledger() is not a
