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


def test_material_status_is_explicit_and_scoped_per_project(tmp_path, setup_test_db):
    """状态只由显式调用改变：默认 ready，pending/failed 不会被静默改写。"""
    a = tmp_path / "a"
    b = tmp_path / "b"
    a.mkdir()
    b.mkdir()
    first = ProjectRepository().register(str(a))
    second = ProjectRepository().register(str(b))
    repo = ProjectMaterialRepository()

    ready = repo.add(first.id, "usable immediately")
    pending = repo.add(first.id, "awaiting async index", status="pending_index")
    failed = repo.add(first.id, "index blew up")
    repo.mark_failed(failed.id, "retain this error")
    elsewhere = repo.add(second.id, "other project", status="pending_index")

    assert ready.status == "ready"
    assert [row.id for row in repo.get_active_materials_for_project(first.id)] == [ready.id]
    assert repo.get(pending.id).status == "pending_index"
    assert repo.get(failed.id).error_message == "retain this error"
    assert repo.get(elsewhere.id).status == "pending_index"

    with pytest.raises(ValueError, match="Invalid material status"):
        repo.add(first.id, "invalid status", status="ready?")

    revived = repo.add(first.id, "index blew up")
    assert revived.id == failed.id
    assert revived.status == "ready"
    assert revived.error_message is None
