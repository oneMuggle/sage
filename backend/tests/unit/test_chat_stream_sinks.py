# ruff: noqa: UP006, UP007, UP035, UP045 — release/win7 Python 3.8 兼容，保留 typing 注解
"""StreamEventSink 单测（C2a，DSH 对标 R24）。

覆盖原内联闭包的行为契约：会话过滤、队列满静默降级、
register/unregister 四路对称、持久化 todo 初始推送。
"""

from __future__ import annotations

import asyncio

import pytest

from backend.api.chat_stream_sinks import StreamEventSink

pytestmark = pytest.mark.unit


@pytest.fixture()
def queue():
    return asyncio.Queue(maxsize=100)


@pytest.fixture()
def sink(queue):
    return StreamEventSink(queue, "sess-1")


# ---- 会话过滤 ----------------------------------------------------------------


async def test_todo_snapshot_other_session_filtered(sink, queue):
    sink.push_todo_snapshot("sess-2", [{"id": "t"}])
    assert queue.empty()


async def test_todo_snapshot_same_session_enqueued(sink, queue):
    todos = [{"id": "t1", "content": "x"}]
    sink.push_todo_snapshot("sess-1", todos)
    event = queue.get_nowait()
    assert event == {
        "state": "todo_snapshot",
        "session_id": "sess-1",
        "todos": todos,
    }


async def test_artifact_other_session_filtered(sink, queue):
    sink.push_artifact({"session_id": "sess-2", "kind": "file"})
    assert queue.empty()


async def test_artifact_same_session_passthrough(sink, queue):
    event = {"session_id": "sess-1", "kind": "file", "path": "a.txt"}
    sink.push_artifact(event)
    assert queue.get_nowait() is event  # 原样透传，不复制不包装


async def test_workspace_other_session_filtered(sink, queue):
    sink.push_workspace({"session_id": "sess-2", "path": "x"})
    assert queue.empty()


async def test_agent_bridge_no_session_filter(sink, queue):
    """agent 桥由注册表按会话寻址，sink 不再做会话过滤（与原闭包一致）。"""
    event = {"session_id": "sess-OTHER", "type": "subagent_event"}
    sink.emit_agent_bridge(event)
    assert queue.get_nowait() is event


# ---- 降级铁律：队列满/关闭静默忽略 --------------------------------------------


async def test_queue_full_degrades_silently(sink):
    tiny = asyncio.Queue(maxsize=1)
    s = StreamEventSink(tiny, "sess-1")
    s.emit_agent_bridge({"n": 1})  # 占满
    # 以下全部不应抛 QueueFull
    s.emit_agent_bridge({"n": 2})
    s.push_todo_snapshot("sess-1", [])
    s.push_artifact({"session_id": "sess-1"})
    s.push_workspace({"session_id": "sess-1"})
    assert tiny.qsize() == 1


async def test_closed_queue_degrades_silently(sink):
    class _Closed:
        def put_nowait(self, item):
            raise RuntimeError("queue closed")

    s = StreamEventSink(_Closed(), "sess-1")
    s.push_todo_snapshot("sess-1", [])  # 不应抛


# ---- register / unregister 四路对称 -------------------------------------------


@pytest.fixture()
def registries(monkeypatch):
    """fake 四路监听注册表，记录 add/remove 调用与注册的处理器。"""
    reg = {
        "bridge": {},
        "todo": {"added": [], "removed": []},
        "artifact": {"added": [], "removed": []},
        "workspace": {"added": [], "removed": []},
    }

    import backend.tools.agent_event_bridge as bridge
    from backend.data import artifact_repo, workspace_events
    from backend.tools import todo_state

    monkeypatch.setattr(
        bridge, "register_stream_emitter", lambda sid, fn: reg["bridge"].__setitem__(sid, fn)
    )
    monkeypatch.setattr(
        bridge, "unregister_stream_emitter", lambda sid: reg["bridge"].pop(sid, None)
    )
    monkeypatch.setattr(
        todo_state, "add_todo_listener", lambda fn: reg["todo"]["added"].append(fn)
    )
    monkeypatch.setattr(
        todo_state, "remove_todo_listener", lambda fn: reg["todo"]["removed"].append(fn)
    )
    monkeypatch.setattr(
        artifact_repo, "add_artifact_listener", lambda fn: reg["artifact"]["added"].append(fn)
    )
    monkeypatch.setattr(
        artifact_repo,
        "remove_artifact_listener",
        lambda fn: reg["artifact"]["removed"].append(fn),
    )
    monkeypatch.setattr(
        workspace_events,
        "add_workspace_listener",
        lambda fn: reg["workspace"]["added"].append(fn),
    )
    monkeypatch.setattr(
        workspace_events,
        "remove_workspace_listener",
        lambda fn: reg["workspace"]["removed"].append(fn),
    )
    return reg


def test_register_wires_all_four(sink, registries):
    sink.register()
    assert registries["bridge"]["sess-1"] == sink.emit_agent_bridge
    assert registries["todo"]["added"] == [sink.push_todo_snapshot]
    assert registries["artifact"]["added"] == [sink.push_artifact]
    assert registries["workspace"]["added"] == [sink.push_workspace]


def test_unregister_removes_all_four(sink, registries):
    sink.register()
    sink.unregister()
    assert "sess-1" not in registries["bridge"]
    assert registries["todo"]["removed"] == [sink.push_todo_snapshot]
    assert registries["artifact"]["removed"] == [sink.push_artifact]
    assert registries["workspace"]["removed"] == [sink.push_workspace]


def test_registered_handler_routes_through_real_sink(queue, registries):
    """注册表拿到的处理器必须真的能投递（端到端行为而非仅身份）。"""
    sink = StreamEventSink(queue, "sess-1")
    sink.register()
    registries["bridge"]["sess-1"]({"type": "subagent_event"})
    registries["todo"]["added"][0]("sess-1", ["t"])
    assert queue.qsize() == 2


# ---- B4 持久化 todo 初始推送 --------------------------------------------------


async def test_persisted_todo_pushed_on_start(sink, queue, monkeypatch):
    from backend.tools import todo_state

    class _Store:
        def get(self, sid):
            assert sid == "sess-1"
            return [{"id": "t0"}]

    monkeypatch.setattr(todo_state, "get_todo_store", lambda: _Store())
    await sink.push_persisted_todo()
    assert queue.get_nowait()["todos"] == [{"id": "t0"}]


async def test_persisted_todo_empty_is_noop(sink, queue, monkeypatch):
    from backend.tools import todo_state

    class _Store:
        def get(self, sid):
            return None

    monkeypatch.setattr(todo_state, "get_todo_store", lambda: _Store())
    await sink.push_persisted_todo()
    assert queue.empty()


async def test_persisted_todo_store_failure_degrades(sink, queue, monkeypatch):
    from backend.tools import todo_state

    def _boom():
        raise RuntimeError("db down")

    monkeypatch.setattr(todo_state, "get_todo_store", _boom)
    await sink.push_persisted_todo()  # 不应抛
    assert queue.empty()
