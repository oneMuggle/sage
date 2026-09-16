"""Builtin seed data loader tests.

Tests verify:
- _parse_builtin_json parses valid JSON correctly
- _parse_builtin_json handles malformed input gracefully
"""

import json

import pytest

from backend.model_catalog.seed import _parse_builtin_json


class TestParseBuiltinJson:
    """Parse builtin.json into CandidateModel records."""

    def test_valid_json(self):
        raw = json.dumps(
            {
                "version": "1.0.0",
                "source": "builtin",
                "generated_at": "2026-09-15T00:00:00.000000Z",
                "models": [
                    {
                        "provider": "openai",
                        "model_id": "gpt-4o",
                        "native": 128000,
                        "price": {
                            "input_per_million": "2.50",
                            "output_per_million": "10.00",
                        },
                        "pricing_scope": "openai",
                    }
                ],
            }
        )
        records = _parse_builtin_json(raw)
        assert len(records) == 1
        assert records[0].model_key.provider == "openai"
        assert records[0].model_key.model_id == "gpt-4o"
        assert records[0].native == 128000
        assert records[0].source == "builtin"
        assert records[0].pricing_scope == "openai"

    def test_no_price_defaults_to_self_hosted(self):
        raw = json.dumps(
            {
                "models": [
                    {
                        "provider": "meta-llama",
                        "model_id": "llama-3.1-8b",
                        "native": 128000,
                    }
                ]
            }
        )
        records = _parse_builtin_json(raw)
        assert len(records) == 1
        assert records[0].pricing_scope == "self-hosted"
        assert records[0].price.input_per_million is None

    def test_invalid_native_ignored(self):
        raw = json.dumps(
            {
                "models": [
                    {
                        "provider": "test",
                        "model_id": "model",
                        "native": -1,
                    }
                ]
            }
        )
        records = _parse_builtin_json(raw)
        assert len(records) == 1
        assert records[0].native is None

    def test_missing_provider_skipped(self):
        raw = json.dumps(
            {"models": [{"model_id": "model", "native": 4096}]}
        )
        records = _parse_builtin_json(raw)
        assert len(records) == 0

    def test_missing_model_id_skipped(self):
        raw = json.dumps(
            {"models": [{"provider": "test", "native": 4096}]}
        )
        records = _parse_builtin_json(raw)
        assert len(records) == 0

    def test_empty_models_list(self):
        raw = json.dumps({"models": []})
        records = _parse_builtin_json(raw)
        assert len(records) == 0

    def test_no_models_key(self):
        raw = json.dumps({})
        records = _parse_builtin_json(raw)
        assert len(records) == 0

    def test_invalid_json_raises(self):
        with pytest.raises(json.JSONDecodeError):
            _parse_builtin_json("not json")

    def test_non_dict_root_raises(self):
        with pytest.raises(ValueError, match="root must be a dict"):
            _parse_builtin_json("[]")

    def test_models_not_list_raises(self):
        with pytest.raises(ValueError, match="must be a list"):
            _parse_builtin_json('{"models": "not a list"}')
