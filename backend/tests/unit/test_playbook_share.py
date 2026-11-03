"""Unit tests for playbook share links (2026-11-03)."""

from __future__ import annotations

import pytest

from backend.data import database as database_module
from backend.data.database import Database
from backend.data.playbook_library_repo import PlaybookLibraryRepository
from backend.data.playbook_share_repo import PlaybookShareRepository
from backend.services.playbook_library import get_builtin
from backend.services.playbook_share import (
    PlaybookNotFoundError,
    ShareTokenExpiredError,
    ShareTokenInvalidError,
    create_share_link,
    resolve_share_token,
)


@pytest.fixture()
def db(monkeypatch: pytest.MonkeyPatch) -> Database:
    test_db = Database(":memory:")
    test_db.init_db()
    monkeypatch.setattr(database_module, "_db", test_db)
    return test_db


def _library_item():
    item, _ = PlaybookLibraryRepository().save(get_builtin("coding-project"), source="imported")
    return item


def test_create_share_link_returns_path_and_metadata(db: Database) -> None:
    item = _library_item()

    result = create_share_link(item.id)

    assert result.playbook_id == item.id
    assert result.playbook_name == item.name
    assert result.share_url == f"/share/playbook/{result.token}"
    assert result.expires_at > 0


def test_resolve_share_token_returns_spec(db: Database) -> None:
    item = _library_item()
    link = create_share_link(item.id)

    payload = resolve_share_token(link.token)

    assert payload["playbook_id"] == item.id
    assert payload["playbook_name"] == item.name
    assert payload["spec"]["id"] == item.spec["id"]
    assert payload["expires_at"] == link.expires_at


def test_resolve_unknown_token_raises(db: Database) -> None:
    with pytest.raises(ShareTokenInvalidError):
        resolve_share_token("not-a-real-token")


def test_resolve_expired_token_raises(db: Database) -> None:
    item = _library_item()
    link = create_share_link(item.id, expiry_days=0)

    with pytest.raises(ShareTokenExpiredError):
        resolve_share_token(link.token)


def test_create_share_link_for_missing_playbook_raises(db: Database) -> None:
    with pytest.raises(PlaybookNotFoundError):
        create_share_link("missing-id")


def test_resolve_after_library_entry_deleted_raises(db: Database) -> None:
    item = _library_item()
    link = create_share_link(item.id)
    PlaybookLibraryRepository().delete(item.id)

    with pytest.raises(PlaybookNotFoundError):
        resolve_share_token(link.token)


def test_share_tokens_are_unique(db: Database) -> None:
    item = _library_item()
    first = create_share_link(item.id)
    second = create_share_link(item.id)

    assert first.token != second.token
    stored = PlaybookShareRepository().get_by_token(first.token)
    assert stored is not None
    assert stored.playbook_id == item.id
