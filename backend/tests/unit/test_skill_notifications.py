"""技能变更通知中枢 (缺口 #6a)。

- publish → wait_for 返回事件
- wait_for 超时返回空列表
- bounded buffer 丢弃最旧事件
- 线程安全: 多 producer 并发 publish 不丢事件
- iter_ndjson 每行是带换行的合法 JSON
"""

from __future__ import annotations

import threading

import pytest

from backend.skills.notifications import (
    SkillNotificationEvent,
    SkillNotificationHub,
    iter_ndjson,
)

pytestmark = pytest.mark.unit


def test_publish_and_wait_returns_event():
    hub = SkillNotificationHub(max_size=16)

    hub.publish({"kind": "skill_changed", "name": "my-skill"})
    events = hub.wait_for(after=0, timeout=0.1)

    assert len(events) == 1
    assert events[0].event["kind"] == "skill_changed"
    assert events[0].event["name"] == "my-skill"
    assert events[0].seq > 0


def test_event_shape_has_seq_event_ts():
    hub = SkillNotificationHub()
    hub.publish({"kind": "shape"})

    events = hub.wait_for(after=0, timeout=0.1)

    assert len(events) == 1
    entry = events[0]
    assert isinstance(entry, SkillNotificationEvent)
    assert isinstance(entry.seq, int)
    assert entry.event == {"kind": "shape"}
    assert isinstance(entry.ts, float)


def test_publish_copies_event_dict():
    """publish 后修改调用方 dict 不应影响已发布事件 (immutable-ish)。"""
    hub = SkillNotificationHub()
    payload = {"kind": "copy"}
    hub.publish(payload)
    payload["kind"] = "mutated"

    events = hub.wait_for(after=0, timeout=0.1)

    assert events[0].event["kind"] == "copy"


def test_wait_for_timeout_returns_empty_when_no_new_events():
    hub = SkillNotificationHub()
    hub.publish({"kind": "old"})

    # after=最新 seq → 没有新事件 → 快速返回空
    latest = hub._seq
    events = hub.wait_for(after=latest, timeout=0.05)

    assert events == []


def test_wait_for_returns_only_events_after_given_seq():
    hub = SkillNotificationHub()
    hub.publish({"kind": "e1"})
    after_e1 = hub._seq
    hub.publish({"kind": "e2"})
    hub.publish({"kind": "e3"})

    events = hub.wait_for(after=after_e1, timeout=0.1)

    kinds = [e.event["kind"] for e in events]
    assert kinds == ["e2", "e3"]


def test_bounded_buffer_drops_oldest():
    hub = SkillNotificationHub(max_size=2)

    hub.publish({"kind": "e1"})
    hub.publish({"kind": "e2"})
    hub.publish({"kind": "e3"})

    # buffer 只保留最新 2 个 (e2, e3)
    events = hub.wait_for(after=0, timeout=0.1)
    kinds = [e.event["kind"] for e in events]
    assert kinds == ["e2", "e3"]


def test_concurrent_publish_preserves_all_events():
    hub = SkillNotificationHub(max_size=100)
    errors = []

    def producer(prefix, count):
        try:
            for i in range(count):
                hub.publish({"kind": f"{prefix}-{i}"})
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=producer, args=(f"t{i}", 20)) for i in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors
    events = hub.wait_for(after=0, timeout=0.1)
    assert len(events) == 100


def test_iter_ndjson_yields_lines_with_newline():
    hub = SkillNotificationHub()
    hub.publish({"kind": "a"})
    hub.publish({"kind": "b"})

    lines = []
    gen = iter_ndjson(hub, after=0, poll_interval=0.01, max_iterations=2)
    for line in gen:
        lines.append(line)
        if len(lines) >= 2:
            break

    assert len(lines) == 2
    for line in lines:
        assert line.endswith("\n")
        # 是合法 JSON
        import json

        payload = json.loads(line)
        assert set(payload) == {"seq", "event", "ts"}
