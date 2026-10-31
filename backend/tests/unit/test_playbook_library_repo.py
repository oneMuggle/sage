"""Unit tests for the global playbook library repository (2026-10-31)."""

from __future__ import annotations

import pytest

from backend.data import database as database_module
from backend.data.database import Database
from backend.data.playbook_library_repo import PlaybookLibraryRepository
from backend.services.playbook_library import get_builtin


@pytest.fixture()
def db(monkeypatch: pytest.MonkeyPatch) -> Database:
    test_db = Database(":memory:")
    test_db.init_db()
    monkeypatch.setattr(database_module, "_db", test_db)
    return test_db


def test_save_dedupes_by_spec_hash(db: Database) -> None:
    repo = PlaybookLibraryRepository()
    spec = get_builtin("cn-research-grant")
    first, created = repo.save(spec, source="imported")
    assert created is True
    second, created_again = repo.save(spec, source="imported")
    assert created_again is False
    assert second.id == first.id
    assert len(repo.list()) == 1


def test_list_and_delete(db: Database) -> None:
    repo = PlaybookLibraryRepository()
    item, _ = repo.save(get_builtin("coding-project"), source="imported")
    summaries = repo.list()
    assert summaries[0].id == item.id
    assert summaries[0].summary()["stage_count"] == 5

    assert repo.delete(item.id) is True
    assert repo.list() == []
    assert repo.delete(item.id) is False
