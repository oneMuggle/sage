from __future__ import annotations
"""Verify that the Python port of arena-model-probe produces equivalent
verdicts to what the Node.js worker would return. We can't run Node in the
test env, so we hand-code the expected verdicts for fixed inputs and assert
the Python port matches."""

import pytest

from backend.services.model_probe_py.classify import (
    collectModelFields, scanTextForModel, protocolFingerprint,
    resolveEvidence,
)


@pytest.mark.integration
def test_python_port_handles_anthropic_request_shape():
    """Anthropic-style request body with model field at top level."""
    payload = {
        "model": "claude-opus-4-6",
        "messages": [{"role": "user", "content": "hi"}],
        "max_tokens": 1024,
    }
    fields = collectModelFields(payload)
    assert any(f["value"] == "claude-opus-4-6" for f in fields)


@pytest.mark.integration
def test_python_port_handles_openai_chunks():
    """OpenAI streaming chunk with model in the chunk envelope."""
    payload = {
        "id": "chatcmpl-abc",
        "object": "chat.completion.chunk",
        "model": "gpt-4o-2024-08-06",
        "choices": [{"delta": {"content": "hello"}}],
    }
    fields = collectModelFields(payload)
    assert any("gpt-4o" in f["value"] for f in fields)


@pytest.mark.integration
def test_python_port_resolves_uuid_with_injected_map():
    from backend.services.model_probe_py import idmap
    test_map = {
        "11111111-2222-3333-4444-555555555555": "gpt-6-astra-high",
        "66666666-7777-8888-9999-aaaaaaaaaaaa": "claude-opus-4-6",
    }
    idmap._model_map.update(test_map)
    try:
        resolved = idmap.resolveModelId("11111111-2222-3333-4444-555555555555")
        assert resolved == "gpt-6-astra-high"
        # Non-UUID passthrough
        assert idmap.resolveModelId("gpt-4o") == "gpt-4o"
        # Unknown UUID passthrough
        assert idmap.resolveModelId("ffffffff-ffff-ffff-ffff-ffffffffffff") == "ffffffff-ffff-ffff-ffff-ffffffffffff"
    finally:
        idmap._model_map.clear()


@pytest.mark.integration
def test_python_port_protocol_fingerprint_matches_expected_families():
    assert protocolFingerprint('"type":"message_start"') == "anthropic"
    assert protocolFingerprint('"object":"chat.completion.chunk"') == "openai"
    assert protocolFingerprint("generateContent") == "google"
    # Unknown framing
    assert protocolFingerprint("just plain text") is None


@pytest.mark.integration
def test_python_port_verdict_aggregates_evidence_by_source_weight():
    evidence = [
        {"source": "request.body.model", "modelId": "gpt-4o", "weight": 1.0},
        {"source": "response.json.model", "modelId": "gpt-4o", "weight": 0.93},
        {"source": "sse.chunk.model", "modelId": "gpt-4o", "weight": 0.90},
    ]
    verdict = resolveEvidence(evidence)
    assert verdict["modelId"] == "gpt-4o"
    # Three corroborating sources => confidence near 1.0
    assert verdict["confidence"] >= 0.9
    assert verdict["evidence_count"] == 3
