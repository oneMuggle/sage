"""Unit tests for backend.storage.recent_projects."""

import json
from pathlib import Path

import pytest

from backend.storage.recent_projects import (
    MAX_RECENT,
    RecentProject,
    load_recent,
    most_recent_parent,
    recent_projects_file,
    record_recent,
    save_recent,
    user_data_dir,
)


@pytest.fixture()
def isolated_data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Redirect user data dir to tmp_path for isolation."""
    monkeypatch.setenv("SAGE_USER_DATA_DIR", str(tmp_path))
    return tmp_path


# 1. load_recent: file missing -> empty list
def test_load_recent_returns_empty_when_file_missing(isolated_data_dir: Path):
    assert load_recent() == []


# 2. load_recent: file empty -> empty list
def test_load_recent_returns_empty_when_file_empty(isolated_data_dir: Path):
    (isolated_data_dir / "recent-projects.json").write_text("")
    assert load_recent() == []


# 3. load_recent: corrupted JSON -> backup + empty
def test_load_recent_backs_up_corrupted_file(isolated_data_dir: Path):
    p = isolated_data_dir / "recent-projects.json"
    p.write_text("{ this is not valid json")
    result = load_recent()
    assert result == []
    bak_files = list(isolated_data_dir.glob("recent-projects.json.bak"))
    assert len(bak_files) == 1


# 4. load_recent: invalid entry -> skipped
def test_load_recent_skips_invalid_entries(isolated_data_dir: Path):
    p = isolated_data_dir / "recent-projects.json"
    p.write_text(
        json.dumps(
            [
                {"path": "/a", "name": "a", "opened_at": 1.0, "intent": "create"},
                {"bogus": "entry"},
                {"path": "/b", "name": "b", "opened_at": 2.0, "intent": "open"},
            ]
        )
    )
    items = load_recent()
    assert len(items) == 2
    assert items[0].path == "/a"
    assert items[1].path == "/b"


# 5. save_recent: atomic write (no partial file on crash)
def test_save_recent_writes_atomically(isolated_data_dir: Path):
    items = [
        RecentProject(path="/x", name="x", opened_at=1.0, intent="create")
    ]
    save_recent(items)
    f = recent_projects_file()
    assert f.exists()
    # No leftover .tmp file
    assert not (f.with_suffix(f.suffix + ".tmp")).exists()
    data = json.loads(f.read_text(encoding="utf-8"))
    assert data[0]["path"] == "/x"


# 6. record_recent: new entry -> length +1
def test_record_recent_appends_new_entry(isolated_data_dir: Path):
    record_recent("/a", "a", "create")
    items = load_recent()
    assert len(items) == 1
    assert items[0].path == "/a"
    assert items[0].name == "a"
    assert items[0].intent == "create"
    assert items[0].opened_at > 0


# 7. record_recent: duplicate path -> moves to head, length unchanged
def test_record_recent_dedup_moves_to_head(isolated_data_dir: Path):
    record_recent("/a", "a", "create")
    record_recent("/b", "b", "open")
    record_recent("/a", "a", "open")
    items = load_recent()
    assert len(items) == 2
    assert items[0].path == "/a"
    assert items[0].intent == "open"
    assert items[1].path == "/b"


# 8. record_recent: exceeds MAX_RECENT -> truncated to MAX_RECENT
def test_record_recent_truncates_to_max(isolated_data_dir: Path):
    for i in range(MAX_RECENT + 5):
        record_recent(f"/p{i}", f"p{i}", "create")
    items = load_recent()
    assert len(items) == MAX_RECENT
    # Most recent should be at the head
    assert items[0].path == f"/p{MAX_RECENT + 4}"


# 9. most_recent_parent: empty list -> None
def test_most_recent_parent_returns_none_when_empty(isolated_data_dir: Path):
    assert most_recent_parent() is None


# 10. most_recent_parent: non-empty -> parent of first item
def test_most_recent_parent_returns_parent_of_head(
    isolated_data_dir: Path, tmp_path: Path
):
    target = tmp_path / "my-wiki"
    record_recent(str(target), "my-wiki", "create")
    parent = most_recent_parent()
    assert parent is not None
    assert Path(parent).resolve() == tmp_path.resolve()


# 11. most_recent_parent: parent deleted -> None (graceful)
def test_most_recent_parent_returns_none_when_parent_missing(
    isolated_data_dir: Path, tmp_path: Path
):
    ghost = tmp_path / "does-not-exist" / "wiki"
    record_recent(str(ghost), "wiki", "create")
    assert most_recent_parent() is None


# 12. user_data_dir: env var priority
def test_user_data_dir_uses_env_var_when_set(
    isolated_data_dir: Path, tmp_path: Path
):
    assert user_data_dir() == isolated_data_dir
