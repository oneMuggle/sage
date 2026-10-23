# ruff: noqa: UP006, UP007, UP035
"""R82：插件 manifest 持久化、事件日志与旧 DB 迁移单测。"""

from __future__ import annotations

import copy
import sqlite3
from pathlib import Path

import pytest

from backend.plugins import PluginEvent
from backend.plugins.lifecycle import PluginLifecycleManager
from backend.plugins.manifest import EXAMPLE_MANIFEST, PluginManifest


@pytest.fixture()
def manager(tmp_path: Path):
    instance = PluginLifecycleManager(db_path=tmp_path / "plugins.db")
    yield instance
    instance.close()


@pytest.fixture()
def manifest() -> PluginManifest:
    return PluginManifest.model_validate(copy.deepcopy(EXAMPLE_MANIFEST))


def _manifest_named(name: str) -> PluginManifest:
    data = copy.deepcopy(EXAMPLE_MANIFEST)
    data["name"] = name
    return PluginManifest.model_validate(data)


def test_install_persists_manifest_and_records_event(manager, manifest) -> None:
    record = manager.install(manifest, "/plugins/example")

    assert record.manifest["name"] == "example-plugin"
    assert record.manifest["capabilities"][0]["permissions"] == ["file:read"]
    assert manager.get_plugin("example-plugin").manifest == record.manifest

    events = manager.list_events("example-plugin")
    assert len(events) == 1
    assert isinstance(events[0], PluginEvent)
    assert events[0].event == "installed"
    assert events[0].detail == "v1.0.0"


def test_lifecycle_events_are_recorded_in_order(manager, manifest) -> None:
    manager.install(manifest, "/plugins/example")
    manager.enable("example-plugin")
    manager.update_config("example-plugin", {"api_key": "secret"})
    manager.disable("example-plugin")
    manager.uninstall("example-plugin")
    manager.restore("example-plugin")

    events = manager.list_events("example-plugin")

    assert [event.event for event in reversed(events)] == [
        "installed",
        "enabled",
        "config_updated",
        "disabled",
        "uninstalled",
        "restored",
    ]
    assert events[0].event == "restored"
    assert all(event.created_at > 0 for event in events)


def test_list_events_filters_by_plugin_and_limits_results(manager) -> None:
    manager.install(_manifest_named("alpha-plugin"), "/plugins/alpha")
    manager.install(_manifest_named("beta-plugin"), "/plugins/beta")
    manager.enable("alpha-plugin")

    alpha_events = manager.list_events("alpha-plugin")
    all_events = manager.list_events(limit=2)

    assert [event.event for event in reversed(alpha_events)] == ["installed", "enabled"]
    assert len(all_events) == 2
    assert all_events[0].plugin_name == "alpha-plugin"
    assert all_events[0].event == "enabled"
    assert manager.list_events(limit=0)[0].event == "enabled"


def test_old_database_without_manifest_column_is_migrated(tmp_path: Path) -> None:
    db_path = tmp_path / "legacy-plugins.db"
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        """
        CREATE TABLE plugins (
            name TEXT PRIMARY KEY,
            version TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'installed',
            plugin_type TEXT NOT NULL DEFAULT 'personal',
            install_path TEXT NOT NULL,
            installed_at REAL NOT NULL,
            enabled_at REAL,
            disabled_at REAL,
            uninstalled_at REAL,
            config TEXT DEFAULT '{}'
        )
        """
    )
    conn.execute(
        """
        INSERT INTO plugins (
            name, version, status, plugin_type, install_path, installed_at, config
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        ("legacy-plugin", "0.9.0", "installed", "personal", "/old", 123.0, "{}"),
    )
    conn.commit()
    conn.close()

    manager = PluginLifecycleManager(db_path=db_path)
    try:
        record = manager.get_plugin("legacy-plugin")
        columns = {
            row[1]
            for row in manager._get_connection().execute("PRAGMA table_info(plugins)")
        }
        tables = {
            row[0]
            for row in manager._get_connection().execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }

        assert record.manifest == {}
        assert "manifest" in columns
        assert "plugin_events" in tables
        assert manager.list_events("legacy-plugin") == []
    finally:
        manager.close()


def test_malformed_stored_manifest_falls_back_to_empty(tmp_path: Path, manifest) -> None:
    db_path = tmp_path / "plugins.db"
    manager = PluginLifecycleManager(db_path=db_path)
    manager.install(manifest, "/plugins/example")
    manager.close()

    conn = sqlite3.connect(str(db_path))
    conn.execute(
        "UPDATE plugins SET manifest = ? WHERE name = ?",
        ("not-json", "example-plugin"),
    )
    conn.commit()
    conn.close()

    reopened = PluginLifecycleManager(db_path=db_path)
    try:
        assert reopened.get_plugin("example-plugin").manifest == {}
    finally:
        reopened.close()
