import re
import pytest

from backend.services.model_probe_py import registry


def test_model_patterns_is_non_empty_dict():
    assert isinstance(registry.MODEL_PATTERNS, dict)
    assert len(registry.MODEL_PATTERNS) >= 4  # at minimum: gpt, claude, gemini, llama


def test_model_key_re_matches_expected_keys():
    assert registry.MODEL_KEY_RE.search('"model"')
    assert registry.MODEL_KEY_RE.search('"model_id"')
    assert registry.MODEL_KEY_RE.search('"upstream_model"')
    assert not registry.MODEL_KEY_RE.search('"unrelated"')


def test_host_vendor_maps_known_hosts():
    assert registry.HOST_VENDOR.get("api.openai.com") == "openai"
    assert registry.HOST_VENDOR.get("api.anthropic.com") == "anthropic"


def test_is_frontier_returns_true_for_known_models():
    assert registry.isFrontier("gpt-4o")
    assert registry.isFrontier("claude-opus-4-6")