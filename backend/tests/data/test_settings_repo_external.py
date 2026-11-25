"""settings_repo 通用 spec 分发 + 服务配置合并优先级。"""

from __future__ import annotations

import json

import pytest

from backend.data.database import Database
from backend.data.settings_repo import SettingsRepository
from backend.domain.document_parse import DEFAULT_TIER
from backend.services.external_services.registry import get_service
from backend.services.external_services.settings import merge_service_settings

pytestmark = [pytest.mark.unit]


@pytest.fixture(autouse=True)
def _forced_test_scheme(monkeypatch):
    monkeypatch.setenv("SAGE_SECRET_SCHEME", "test")
    for name in (
        "SAGE_MINERU_BASE_URL",
        "SAGE_MINERU_API_KEY",
        "SAGE_MINERU_TIER",
        "SAGE_MINERU_TIMEOUT_SECONDS",
    ):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture()
def repo(tmp_path):
    db = Database(str(tmp_path / "svc.db"))
    db.init_db()
    yield SettingsRepository(db)
    db.close()


def test_settings_repo_roundtrips_mineru_secret(repo):
    repo.set("mineru_service", '{"baseUrl":"http://x","apiKey":"secret"}')
    row = (
        repo._conn()
        .execute("SELECT value FROM preferences WHERE key = ?", ("mineru_service",))
        .fetchone()
    )
    assert "secret" not in row["value"]
    got = json.loads(repo.get("mineru_service"))
    assert got["apiKey"] == "secret"
    assert got["baseUrl"] == "http://x"


def test_merge_service_settings_precedence_and_aliases():
    spec = get_service("mineru")
    merged = merge_service_settings(
        spec,
        {"base_url": "http://pref", "apiKey": "k1", "enabled": True},
        {"SAGE_MINERU_BASE_URL": "http://env"},
    )
    assert merged["baseUrl"] == "http://env"
    assert merged["apiKey"] == "k1"
    assert merged["enabled"] is True
    assert merged["defaultTier"] == DEFAULT_TIER


def test_merge_service_settings_ignores_blank_env():
    spec = get_service("mineru")
    merged = merge_service_settings(
        spec, {"baseUrl": "http://pref"}, {"SAGE_MINERU_BASE_URL": "  "}
    )
    assert merged["baseUrl"] == "http://pref"
