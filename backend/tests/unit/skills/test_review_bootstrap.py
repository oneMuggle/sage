"""R135 — ReviewQueue 协作对象启动期装配单元测试。

覆盖：显式注入三个协作对象、缺省参数解析全局单例（patch getter）、
queue 缺省时的部分注入、重复调用幂等不抛错。
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from backend.skills.review_bootstrap import bootstrap_review_collaborators

pytestmark = pytest.mark.unit


def _fake_queue():
    q = SimpleNamespace(injected={})

    def set_review_service(s):
        q.injected["service"] = s

    def set_draft_store(s):
        q.injected["store"] = s

    q.set_review_service = set_review_service
    q.set_draft_store = set_draft_store
    return q


def test_explicit_injection_wires_both():
    queue = _fake_queue()
    service = SimpleNamespace(name="svc")
    store = SimpleNamespace(name="store")
    bootstrap_review_collaborators(queue=queue, review_service=service, draft_store=store)
    assert queue.injected["service"] is service
    assert queue.injected["store"] is store


def test_default_params_resolve_global_singletons(monkeypatch):
    calls = {"queue": 0, "service": 0, "store": 0}
    queue = _fake_queue()

    import backend.skills.draft_store as draft_store_mod
    import backend.skills.review_queue as review_queue_mod
    import backend.skills.review_service as review_service_mod

    def fake_queue():
        calls["queue"] += 1
        return queue

    def fake_service():
        calls["service"] += 1
        return SimpleNamespace(name="svc")

    def fake_store():
        calls["store"] += 1
        return SimpleNamespace(name="store")

    monkeypatch.setattr(review_queue_mod, "get_review_queue", fake_queue)
    monkeypatch.setattr(review_service_mod, "get_review_service", fake_service)
    monkeypatch.setattr(draft_store_mod, "get_skill_draft_store", fake_store)

    bootstrap_review_collaborators()
    assert calls == {"queue": 1, "service": 1, "store": 1}  # 三个全局单例各解析一次
    assert "service" in queue.injected
    assert "store" in queue.injected


def test_queue_default_with_explicit_collaborators(monkeypatch):
    queue = _fake_queue()
    import backend.skills.review_queue as review_queue_mod

    monkeypatch.setattr(review_queue_mod, "get_review_queue", lambda: queue)
    service = SimpleNamespace()
    store = SimpleNamespace()
    bootstrap_review_collaborators(review_service=service, draft_store=store)
    assert queue.injected["service"] is service
    assert queue.injected["store"] is store


def test_repeat_call_is_idempotent(monkeypatch):
    queue = _fake_queue()
    service = SimpleNamespace()
    store = SimpleNamespace()
    bootstrap_review_collaborators(queue=queue, review_service=service, draft_store=store)
    bootstrap_review_collaborators(queue=queue, review_service=service, draft_store=store)
    assert queue.injected["service"] is service  # 不抛错、最终装配正确


def test_returns_none():
    assert bootstrap_review_collaborators(queue=_fake_queue()) is None
