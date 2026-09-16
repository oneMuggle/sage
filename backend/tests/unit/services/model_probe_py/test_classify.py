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


# -- Coverage fix-ups for uncovered branches (lines 50, 62-64, 74, 88, 91-92, 94, 101, 108, 113, 127, 141-156, 182-183) --


def test_collect_model_fields_rejects_non_dict_non_list_input():
    """Line 50: invalid node type (string, int, bool) returns empty list immediately."""
    # Arrange
    invalid_nodes = ["string", 42, True, None, 3.14]
    # Act & Assert
    for node in invalid_nodes:
        out = collectModelFields(node)
        assert out == []


def test_collect_model_fields_handles_model_list_value():
    """Lines 62-64: when key=='model' and value is a list, extract each string item."""
    # Arrange
    payload = {
        "model": ["gpt-4o", "claude-3-opus", 123, None, "gpt-3.5-turbo"]
    }
    # Act
    out = collectModelFields(payload)
    # Assert: should extract 3 string values (skip int and None)
    extracted = [item["value"] for item in out]
    assert "gpt-4o" in extracted
    assert "claude-3-opus" in extracted
    assert "gpt-3.5-turbo" in extracted
    assert len(extracted) == 3


def test_scan_text_for_model_returns_empty_for_invalid_input():
    """Line 74: scanTextForModel returns empty list for non-string or empty input."""
    # Arrange & Act & Assert
    assert scanTextForModel("") == []
    assert scanTextForModel(None) == []  # type: ignore
    assert scanTextForModel(123) == []  # type: ignore
    assert scanTextForModel([]) == []  # type: ignore


def test_vendor_from_url_returns_none_for_invalid_input():
    """Line 88: vendorFromUrl returns None for non-string or empty input."""
    # Arrange & Act & Assert
    assert vendorFromUrl("") is None
    assert vendorFromUrl(None) is None  # type: ignore
    assert vendorFromUrl(123) is None  # type: ignore
    assert vendorFromUrl([]) is None  # type: ignore


def test_vendor_from_url_handles_urlparse_exception():
    """Lines 91-92: vendorFromUrl catches urlparse exceptions and returns None."""
    # Arrange: malformed URL that causes urlparse to fail
    malformed = "http://[invalid_ipv6_address"
    # Act
    result = vendorFromUrl(malformed)
    # Assert
    assert result is None


def test_vendor_from_url_returns_none_when_host_is_empty():
    """Line 94: vendorFromUrl returns None when parsed host is empty."""
    # Arrange: URL with no hostname
    no_host_urls = ["file:///path/to/file", "mailto:user@example.com", "data:text/plain,hello"]
    # Act & Assert
    for url in no_host_urls:
        result = vendorFromUrl(url)
        assert result is None


def test_vendor_from_url_uses_suffix_matching():
    """Line 101: vendorFromUrl matches via suffix (sub.api.openai.com → api.openai.com)."""
    # Arrange: subdomain of known host (not exact match but suffix match)
    url = "https://sub.api.openai.com/v1/chat/completions"
    # Act
    result = vendorFromUrl(url)
    # Assert: should match api.openai.com suffix and return "openai"
    assert result == "openai"


def test_protocol_fingerprint_returns_none_for_invalid_input():
    """Line 108: protocolFingerprint returns None for non-string or empty input."""
    # Arrange & Act & Assert
    assert protocolFingerprint("") is None
    assert protocolFingerprint(None) is None  # type: ignore
    assert protocolFingerprint(123) is None  # type: ignore
    assert protocolFingerprint([]) is None  # type: ignore


def test_protocol_fingerprint_returns_none_when_no_match():
    """Line 113: protocolFingerprint returns None when no protocol tokens match."""
    # Arrange: text with no known protocol framing
    text = "random text without any protocol tokens"
    # Act
    result = protocolFingerprint(text)
    # Assert
    assert result is None


def test_resolve_evidence_returns_empty_verdict_for_empty_list():
    """Line 127: resolveEvidence returns empty verdict when evidence list is empty."""
    # Arrange
    evidence = []
    # Act
    verdict = resolveEvidence(evidence)
    # Assert
    assert verdict["modelId"] is None
    assert verdict["family"] is None
    assert verdict["confidence"] == 0.0
    assert verdict["source"] is None
    assert verdict["evidence_count"] == 0


def test_resolve_evidence_uses_family_fallback_when_no_model_id():
    """Lines 141-156: resolveEvidence falls back to family-level grouping when no modelId present."""
    # Arrange: evidence with family but no modelId
    evidence = [
        {"source": "protocol.framing", "family": "anthropic", "weight": 0.72},
        {"source": "url.host.vendor", "family": "anthropic", "weight": 0.80},
        {"source": "protocol.framing", "family": "openai", "weight": 0.50},
    ]
    # Act
    verdict = resolveEvidence(evidence)
    # Assert: should pick anthropic (higher combined weight: 0.72+0.80=1.52 vs 0.50)
    assert verdict["modelId"] is None
    assert verdict["family"] == "anthropic"
    assert verdict["evidence_count"] == 2
    assert verdict["confidence"] == pytest.approx((0.72 + 0.80) / 2, rel=1e-3)


def test_resolve_evidence_family_fallback_returns_empty_when_no_family():
    """Lines 146-150: family fallback returns empty verdict when evidence has neither modelId nor family."""
    # Arrange: evidence with neither modelId nor family
    evidence = [
        {"source": "unknown.source", "weight": 0.5},
        {"source": "another.source", "weight": 0.3},
    ]
    # Act
    verdict = resolveEvidence(evidence)
    # Assert
    assert verdict["modelId"] is None
    assert verdict["family"] is None
    assert verdict["confidence"] == 0.0
    assert verdict["evidence_count"] == 0


def test_resolve_evidence_infers_family_from_best_items():
    """Lines 182-183: resolveEvidence infers family from first item in best_items that has family."""
    # Arrange: evidence with modelId where some items have family, some don't
    evidence = [
        {"source": "request.body.model", "modelId": "gpt-4o", "weight": 1.0},
        {"source": "response.json.model", "modelId": "gpt-4o", "weight": 0.93, "family": "openai"},
        {"source": "url.path.model", "modelId": "gpt-4o", "weight": 0.85},
    ]
    # Act
    verdict = resolveEvidence(evidence)
    # Assert: should infer family="openai" from the second item
    assert verdict["modelId"] == "gpt-4o"
    assert verdict["family"] == "openai"
    assert verdict["evidence_count"] == 3


def test_resolve_evidence_returns_none_family_when_no_item_has_family():
    """Lines 179-183: when no item in best_items has family, verdict family is None."""
    # Arrange: evidence with modelId but no family field on any item
    evidence = [
        {"source": "request.body.model", "modelId": "custom-model", "weight": 1.0},
    ]
    # Act
    verdict = resolveEvidence(evidence)
    # Assert
    assert verdict["modelId"] == "custom-model"
    assert verdict["family"] is None
    assert verdict["evidence_count"] == 1

