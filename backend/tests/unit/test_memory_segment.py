"""Task 14 (context-isolation): segment-aware WorkingMemory 隔离测试。

每个 segment 的消息彼此不可见；clear_segment 仅清目标段，其他段保留。
"""

from __future__ import annotations

from backend.memory.working import WorkingMemory


def test_working_memory_segment_isolation():
    wm = WorkingMemory()
    wm.add("s1", {"role": "user", "content": "old topic fact"}, segment_id=0)
    wm.add("s1", {"role": "user", "content": "new topic fact"}, segment_id=1)

    seg0 = wm.get_context("s1", segment_id=0)
    seg1 = wm.get_context("s1", segment_id=1)

    assert any(m["content"] == "old topic fact" for m in seg0)
    assert all(m["content"] != "new topic fact" for m in seg0)
    assert any(m["content"] == "new topic fact" for m in seg1)
    assert all(m["content"] != "old topic fact" for m in seg1)


def test_clear_segment_keeps_other_segments():
    wm = WorkingMemory()
    wm.add("s1", {"role": "user", "content": "old"}, segment_id=0)
    wm.add("s1", {"role": "user", "content": "new"}, segment_id=1)

    wm.clear_segment("s1", segment_id=0)
    assert all(m["content"] != "old" for m in wm.get_context("s1", segment_id=0))
    assert any(m["content"] == "new" for m in wm.get_context("s1", segment_id=1))