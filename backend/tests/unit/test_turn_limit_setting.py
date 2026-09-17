"""Tests for SettingsRepository whitelist additions (context-isolation, Task 6)."""

import pytest

from backend.data import database as db_mod
from backend.data.settings_repo import SettingsRepository

pytestmark = pytest.mark.unit


@pytest.fixture
def db_setup(tmp_path, monkeypatch):
    db_path = tmp_path / "test.db"
    monkeypatch.setenv("SAGE_DB_PATH", str(db_path))
    monkeypatch.setattr(db_mod, "_db", None)
    db = db_mod.get_database()
    db.init_db()
    yield db


def test_context_turn_limit_whitelisted(db_setup):
    repo = SettingsRepository()
    repo.set("context_turn_limit", "10")
    assert repo.get("context_turn_limit") == "10"


def test_auto_topic_detection_whitelisted(db_setup):
    repo = SettingsRepository()
    repo.set("auto_topic_detection", "true")
    assert repo.get("auto_topic_detection") == "true"


def test_topic_detection_threshold_whitelisted(db_setup):
    repo = SettingsRepository()
    repo.set("topic_detection_threshold", "0.35")
    assert repo.get("topic_detection_threshold") == "0.35"


def test_unknown_key_raises(db_setup):
    repo = SettingsRepository()
    with pytest.raises(ValueError):
        repo.set("bogus_key_xyz", "x")
