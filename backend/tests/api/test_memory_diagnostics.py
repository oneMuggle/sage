"""Runtime memory diagnostics route tests."""

from types import SimpleNamespace

from backend.api import legacy_routes


def test_memory_diagnostics_redacts_path_and_reports_identity(monkeypatch, tmp_path):
    db_path = tmp_path / "sage.db"
    db_path.write_bytes(b"sqlite-placeholder")
    manager = SimpleNamespace(episodic=SimpleNamespace(db=SimpleNamespace(db_path=str(db_path))))
    monkeypatch.setattr(legacy_routes, "get_memory_manager", lambda: manager)
    monkeypatch.setenv("SAGE_DB_PATH", str(db_path))
    monkeypatch.setenv("SAGE_BUILD_ID", "build-test")

    result = legacy_routes.memory_diagnostics()

    assert result["pid"] > 0
    assert result["build_id"] == "build-test"
    assert result["db"]["basename"] == "sage.db"
    assert result["db"]["exists"] is True
    assert result["db"]["size_bytes"] == len(b"sqlite-placeholder")
    assert result["db"]["source"] == "explicit_env"
    assert str(db_path) not in str(result)
    assert len(result["db"]["path_fingerprint"]) == 16
