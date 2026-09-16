"""Unit tests for backend.services.model_probe_py.classify."""

from __future__ import annotations

import pytest

from backend.services.model_probe_py.classify import (
    SOURCE_WEIGHTS, collectModelFields, protocolFingerprint,
    resolveEvidence, scanTextForModel, vendorFromUrl,
)


def test_collect_model_fields_finds_nested_model():
    payload = {
        "choices": [
            {"message": {"model": "gpt-4o", "content": "hi"}}
        ]
    }
    out = collectModelFields(payload)
    assert any(item["value"] == "gpt-4o" for item in out)


def test_collect_model_fields_respects_max_depth():
    payload = {"a": {"b": {"c": {"d": {"e": {"model": "deep"}}}}}}
    out = collectModelFields(payload, maxDepth=2)
    # depth 2 means we only descend 2 levels; 'deep' is at depth 5
    assert not any(item["value"] == "deep" for item in out)


def test_scan_text_for_model_extracts_string_values():
    text = 'data: {"model": "claude-opus-4-6", "id": "msg_123"}'
    found = scanTextForModel(text)
    assert "claude-opus-4-6" in found


def test_vendor_from_url_recognizes_known_hosts():
    assert vendorFromUrl("https://api.openai.com/v1/chat") == "openai"
    assert vendorFromUrl("https://api.anthropic.com/v1/messages") == "anthropic"
    assert vendorFromUrl("https://unknown.example.com/x") is None


def test_protocol_fingerprint_detects_anthropic():
    text = '{"type":"message_start","message":{"id":"msg_01"}}'
    assert protocolFingerprint(text) == "anthropic"


def test_protocol_fingerprint_detects_openai():
    text = '{"id":"chatcmpl-abc123","object":"chat.completion.chunk"}'
    assert protocolFingerprint(text) == "openai"


def test_resolve_evidence_aggregates_by_model_id():
    evidence = [
        {"source": "request.body.model", "modelId": "gpt-4o", "weight": 1.0},
        {"source": "response.json.model", "modelId": "gpt-4o", "weight": 0.93},
    ]
    verdict = resolveEvidence(evidence)
    assert verdict["modelId"] == "gpt-4o"
    assert verdict["confidence"] >= 0.93


def test_source_weights_have_expected_keys():
    expected = {"request.body.model", "response.header.model", "run.trace.model",
                "sse.chunk.model", "protocol.framing", "behavior.probe"}
    assert expected.issubset(SOURCE_WEIGHTS.keys())
