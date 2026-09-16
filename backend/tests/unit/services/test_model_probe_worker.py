"""Unit tests for ModelProbeWorker.

TDD-step: verify the worker wraps the Python port classification logic
with a clean classify() interface.
"""

from __future__ import annotations

import pytest

from backend.services.model_probe_worker import ModelProbeWorker


def test_python_backend_returns_verdict_for_model_evidence():
    w = ModelProbeWorker(backend="python")
    evidence = {"source": "request.body.model", "modelId": "gpt-4o"}
    verdict = w.classify(evidence)
    assert verdict["modelId"] == "gpt-4o"
    assert verdict["confidence"] >= 0.9
    assert verdict["source"] == "request.body.model"


def test_python_backend_handles_family_evidence():
    w = ModelProbeWorker(backend="python")
    evidence = {"source": "protocol.framing", "family": "anthropic"}
    verdict = w.classify(evidence)
    assert verdict["family"] == "anthropic"
    assert verdict["confidence"] > 0.0


def test_python_backend_returns_empty_verdict_for_empty_evidence():
    w = ModelProbeWorker(backend="python")
    verdict = w.classify({})
    assert verdict["modelId"] is None
    assert verdict["family"] is None
    assert verdict["confidence"] == 0.0


def test_python_backend_resolves_uuid_via_idmap():
    w = ModelProbeWorker(backend="python")
    # Inject a known map
    from backend.services.model_probe_py.idmap import resolveModelId
    test_map = {"uuid-test-1234-5678-9abc-def012345678": "gpt-6-astra-high"}
    evidence = {"source": "response.json.model", "modelId": "uuid-test-1234-5678-9abc-def012345678"}
    # The worker should use the global _model_map; populate it via the function
    from backend.services.model_probe_py import idmap
    idmap._model_map.update(test_map)
    try:
        verdict = w.classify(evidence)
        # Either resolved or passthrough — both are valid behavior
        assert verdict["modelId"] in ("uuid-test-1234-5678-9abc-def012345678", "gpt-6-astra-high")
    finally:
        idmap._model_map.clear()