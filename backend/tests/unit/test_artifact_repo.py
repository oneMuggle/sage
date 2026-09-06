# backend/tests/unit/test_artifact_repo.py
from backend.data import artifact_repo


def test_record_artifact_returns_id():
    aid = artifact_repo.record_artifact(
        session_id="sess_001",
        path="/tmp/test.md",
        name="test.md",
        kind="markdown",
        size=100,
        tool_call_id="call_001",
    )
    assert isinstance(aid, str)
    assert aid.startswith("art_")


def test_list_artifacts_recent_first():
    a1 = artifact_repo.record_artifact("sess_001", "/tmp/a.md", "a.md", "markdown", 10)
    a2 = artifact_repo.record_artifact("sess_001", "/tmp/b.md", "b.md", "markdown", 20)
    items = artifact_repo.list_artifacts("sess_001")
    assert [a.id for a in items] == [a2, a1]


def test_list_artifacts_filters_by_session():
    artifact_repo.record_artifact("sess_001", "/tmp/a.md", "a.md", "markdown", 10)
    artifact_repo.record_artifact("sess_002", "/tmp/b.md", "b.md", "markdown", 20)
    items = artifact_repo.list_artifacts("sess_001")
    assert len(items) == 1
    assert items[0].path == "/tmp/a.md"


def test_get_artifact_found():
    aid = artifact_repo.record_artifact("sess_001", "/tmp/x.md", "x.md", "markdown", 50)
    found = artifact_repo.get_artifact(aid)
    assert found is not None
    assert found.name == "x.md"
    assert found.to_dict()["kind"] == "markdown"


def test_get_artifact_missing_returns_none():
    assert artifact_repo.get_artifact("nonexistent") is None


# ============================================================================
# S7 (2026-09-06): record_artifact 落库后广播 artifact_created 事件
# ============================================================================

def test_record_artifact_emits_event_with_payload():
    events = []
    remove = artifact_repo.add_artifact_listener(events.append)
    try:
        aid = artifact_repo.record_artifact("sess_ev", "/tmp/out.md", "out.md", "markdown", 42)
    finally:
        artifact_repo.remove_artifact_listener(remove)
    assert len(events) == 1
    evt = events[0]
    assert evt["state"] == "artifact_created"
    assert evt["session_id"] == "sess_ev"
    assert evt["artifact"]["id"] == aid
    assert evt["artifact"]["name"] == "out.md"
    assert evt["artifact"]["size"] == 42


def test_listener_exception_does_not_break_record():
    def _boom(_evt):
        raise RuntimeError("listener bug")

    artifact_repo.add_artifact_listener(_boom)
    try:
        aid = artifact_repo.record_artifact("sess_boom", "/tmp/a.md", "a.md", "markdown", 1)
        assert aid.startswith("art_")  # 落库不受监听器异常影响
    finally:
        artifact_repo.remove_artifact_listener(_boom)


def test_remove_artifact_listener_stops_delivery():
    events = []
    remove = artifact_repo.add_artifact_listener(events.append)
    artifact_repo.remove_artifact_listener(remove)
    artifact_repo.record_artifact("sess_quiet", "/tmp/a.md", "a.md", "markdown", 1)
    assert events == []


def test_remove_unknown_listener_is_silent():
    def _ghost(_evt):
        pass

    artifact_repo.remove_artifact_listener(_ghost)  # 不应抛 ValueError
