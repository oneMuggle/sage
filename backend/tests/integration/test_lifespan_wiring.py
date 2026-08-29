"""Minimal packaged-runtime health/lifespan contract tests."""

import os

import pytest

from backend.main import (
    _build_health_metadata,
    _shutdown_bash_sessions,
    _shutdown_repl_cleanups,
)


@pytest.mark.integration()
def test_lifespan_health_metadata_uses_runtime_ownership_envelope(monkeypatch):
    """Health metadata is derived from the process environment and is JSON-safe."""
    monkeypatch.setenv("SAGE_BUILD_ID", "test-build")
    monkeypatch.setenv("SAGE_BACKEND_GENERATION", "7")
    monkeypatch.setenv("SAGE_BACKEND_OWNERSHIP_TOKEN", "token-7")

    metadata = _build_health_metadata()

    assert metadata["buildId"] == "test-build"
    assert metadata["generation"] == 7
    assert metadata["ownershipToken"] == "token-7"
    assert metadata["pid"] == os.getpid()


def test_shutdown_bash_sessions_clears_registry(monkeypatch):
    registry = type("Registry", (), {"clear": lambda self: setattr(self, "cleared", True)})()
    monkeypatch.setattr("backend.tools.bash_session.get_registry", lambda: registry)

    _shutdown_bash_sessions()

    assert registry.cleared is True


def test_shutdown_bash_sessions_swallows_cleanup_failure(monkeypatch):
    monkeypatch.setattr(
        "backend.tools.bash_session.get_registry",
        lambda: (_ for _ in ()).throw(RuntimeError("cleanup failed")),
    )

    _shutdown_bash_sessions()


def test_shutdown_repl_cleanups_calls_pending_cleanup(monkeypatch):
    called = []
    monkeypatch.setattr(
        "backend.tools.repl_tool.shutdown_pending_cleanups",
        lambda: called.append(True),
    )

    _shutdown_repl_cleanups()

    assert called == [True]


def test_shutdown_repl_cleanups_swallows_cleanup_failure(monkeypatch):
    monkeypatch.setattr(
        "backend.tools.repl_tool.shutdown_pending_cleanups",
        lambda: (_ for _ in ()).throw(RuntimeError("cleanup failed")),
    )

    _shutdown_repl_cleanups()
