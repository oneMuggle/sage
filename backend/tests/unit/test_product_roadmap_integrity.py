"""Product integrity regressions; all database writes use setup_test_db."""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from backend.api.legacy_models import ChatRequest
from backend.data.project_material_repo import ProjectMaterialRepository
from backend.data.project_repo import ProjectRepository


def test_new_inline_material_is_immediately_usable(tmp_path, setup_test_db):
    folder = tmp_path / "project"
    folder.mkdir()
    project = ProjectRepository().register(str(folder))
    repo = ProjectMaterialRepository()
    material = repo.add(project.id, "A reference the user explicitly added")
    assert material.status == "ready"
    assert [row.id for row in repo.get_active_materials_for_project(project.id)] == [material.id]


@pytest.mark.parametrize("mode", ["paused", "OFF", "false"])
def test_unknown_memory_modes_are_not_silently_treated_as_on(mode):
    with pytest.raises(ValidationError):
        ChatRequest(session_id="test-session", message="hello", memory_mode=mode)


@pytest.mark.parametrize("mode", ["on", "off", None])
def test_legacy_memory_modes_remain_compatible(mode):
    request = ChatRequest(session_id="test-session", message="hello", memory_mode=mode)
    assert request.memory_mode == mode


def test_legacy_repair_is_scoped_and_preserves_index_jobs_and_errors(tmp_path, setup_test_db):
    a = tmp_path / "a"
    b = tmp_path / "b"
    a.mkdir()
    b.mkdir()
    first = ProjectRepository().register(str(a))
    second = ProjectRepository().register(str(b))
    repo = ProjectMaterialRepository()
    legacy = repo.add(first.id, "legacy")
    indexed = repo.add(first.id, "index job")
    failed = repo.add(first.id, "failed")
    other = repo.add(second.id, "other project")
    conn = repo.db.get_connection()
    for item in (legacy, indexed, other):
        conn.execute("UPDATE project_materials SET status='pending_index' WHERE id=?", (item.id,))
    conn.execute("UPDATE project_materials SET wiki_page_path='/wiki/pending.md' WHERE id=?", (indexed.id,))
    repo.mark_failed(failed.id, "retain this error")
    conn.commit()
    assert [row.id for row in repo.get_active_materials_for_project(first.id)] == [legacy.id]
    assert repo.get(indexed.id).status == "pending_index"
    assert repo.get(failed.id).error_message == "retain this error"
    assert repo.get(other.id).status == "pending_index"
    assert repo.add(first.id, "legacy").id == legacy.id
