"""Minimal packaged-runtime health/lifespan contract tests."""

import os

import pytest

from backend.main import _build_health_metadata


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
    assert metadata["pythonVersion"]
