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
