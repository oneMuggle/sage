"""Pure transfer and data-source mapping tests: bundle round-trip, tampering, limits."""

from decimal import Decimal

import pytest

from backend.model_catalog.schemas import CandidateModel, ModelKey


def _candidate(**patch):
    base = {
        "model_key": {"provider": "openai", "model_id": "gpt-4o"},
        "native": 128000,
        "price": {"input_per_million": "2.5", "output_per_million": "10"},
        "source": "custom_json",
        "pricing_scope": "openrouter",
    }
    base.update(patch)
    return CandidateModel.model_validate(base)


# ---------------------------------------------------------------------------
# encode_bundle / decode_bundle round-trip
# ---------------------------------------------------------------------------


class TestBundleRoundTrip:
    def test_single_record_round_trip(self):
        from backend.model_catalog.transfer import decode_bundle, encode_bundle

        record = _candidate()
        payload = encode_bundle([record], "custom_json")
        assert decode_bundle(payload) == [record]

    def test_multiple_records_round_trip(self):
        from backend.model_catalog.transfer import decode_bundle, encode_bundle

        records = [
            _candidate(model_key={"provider": "a", "model_id": "m1"}),
            _candidate(model_key={"provider": "b", "model_id": "m2"}),
        ]
        assert decode_bundle(encode_bundle(records, "custom_json")) == records

    def test_empty_bundle_round_trip(self):
        from backend.model_catalog.transfer import decode_bundle, encode_bundle

        assert decode_bundle(encode_bundle([], "custom_json")) == []

    def test_decimal_precision_preserved(self):
        from backend.model_catalog.transfer import decode_bundle, encode_bundle

        record = _candidate(price={"input_per_million": "0.12345678901234567890"})
        result = decode_bundle(encode_bundle([record], "custom_json"))
        assert result[0].price.input_per_million == Decimal("0.12345678901234567890")

    def test_unknown_price_stays_null(self):
        from backend.model_catalog.transfer import decode_bundle, encode_bundle

        record = _candidate(price={})
        result = decode_bundle(encode_bundle([record], "custom_json"))
        assert result[0].price.input_per_million is None
        assert result[0].price.output_per_million is None


# ---------------------------------------------------------------------------
# Bundle envelope validation
# ---------------------------------------------------------------------------


class TestBundleValidation:
    def test_hash_tampering_rejected(self):
        from backend.model_catalog.transfer import (
            BundleValidationError,
            decode_bundle,
            encode_bundle,
        )

        payload = encode_bundle([_candidate()], "custom_json")
        import json

        envelope = json.loads(payload)
        envelope["sha256"] = "0" * 64
        with pytest.raises(BundleValidationError, match="sha256"):
            decode_bundle(json.dumps(envelope))

    def test_unknown_format_version_rejected(self):
        import json

        from backend.model_catalog.transfer import (
            BundleValidationError,
            _hash_payload,
            decode_bundle,
            encode_bundle,
        )

        payload = encode_bundle([_candidate()], "custom_json")
        envelope = json.loads(payload)
        envelope["formatVersion"] = 99
        envelope["sha256"] = _hash_payload(envelope["payload"])
        with pytest.raises(BundleValidationError, match="formatVersion"):
            decode_bundle(json.dumps(envelope))

    def test_too_many_records_rejected(self):
        from backend.model_catalog.transfer import BundleValidationError, encode_bundle

        huge = [
            _candidate(model_key={"provider": f"p{i}", "model_id": f"m{i}"})
            for i in range(10001)
        ]
        with pytest.raises(BundleValidationError, match="[Rr]ecord"):
            encode_bundle(huge, "custom_json")

    def test_duplicate_identity_rejected(self):
        from backend.model_catalog.transfer import BundleValidationError, encode_bundle

        records = [_candidate(), _candidate()]  # identical identity
        with pytest.raises(BundleValidationError, match="[Dd]uplicate"):
            encode_bundle(records, "custom_json")

    def test_source_must_match_records(self):
        from backend.model_catalog.transfer import BundleValidationError, encode_bundle

        records = [_candidate(source="openrouter")]
        with pytest.raises((BundleValidationError, ValueError)):
            encode_bundle(records, "custom_json")

    def test_invalid_json_rejected(self):
        from backend.model_catalog.transfer import BundleValidationError, decode_bundle

        with pytest.raises(BundleValidationError):
            decode_bundle(b"not json at all")

    def test_missing_envelope_fields_rejected(self):
        import json

        from backend.model_catalog.transfer import BundleValidationError, decode_bundle

        with pytest.raises(BundleValidationError):
            decode_bundle(json.dumps({"formatVersion": 1}))

    def test_non_bytes_input_rejected(self):
        from backend.model_catalog.transfer import BundleValidationError, decode_bundle

        with pytest.raises(BundleValidationError):
            decode_bundle(12345)

    def test_decode_rejects_oversized_input(self):
        from backend.model_catalog.transfer import (
            MAX_BUNDLE_BYTES,
            BundleValidationError,
            decode_bundle,
        )

        # Create a payload just over the limit
        huge = b"x" * (MAX_BUNDLE_BYTES + 1)
        with pytest.raises(BundleValidationError, match="[Ss]ize"):
            decode_bundle(huge)

    def test_decode_rejects_missing_payload_fields(self):
        import json

        from backend.model_catalog.transfer import (
            BundleValidationError,
            _hash_payload,
            decode_bundle,
        )

        # Missing 'source' in payload
        envelope = {
            "formatVersion": 1,
            "payload": {"generatedAt": "2026-09-15T00:00:00Z", "records": []},
            "sha256": "dummy",
        }
        envelope["sha256"] = _hash_payload(envelope["payload"])
        with pytest.raises(BundleValidationError, match="missing payload field"):
            decode_bundle(json.dumps(envelope))

    def test_decode_rejects_payload_source_mismatch(self):
        import json

        from backend.model_catalog.transfer import (
            BundleValidationError,
            _hash_payload,
            decode_bundle,
            encode_bundle,
        )

        # Create a valid bundle, then tamper with payload.source
        record = _candidate(source="openrouter")
        bundle = encode_bundle([record], "openrouter")
        envelope = json.loads(bundle)
        envelope["payload"]["source"] = "different_source"
        envelope["sha256"] = _hash_payload(envelope["payload"])
        with pytest.raises(BundleValidationError, match="source"):
            decode_bundle(json.dumps(envelope))

    def test_decode_rejects_duplicate_identity(self):
        import json

        from backend.model_catalog.transfer import (
            BundleValidationError,
            _hash_payload,
            decode_bundle,
        )

        # Craft a bundle with duplicate identities (bypassing encode validation)
        record = _candidate()
        envelope = {
            "formatVersion": 1,
            "payload": {
                "generatedAt": "2026-09-15T00:00:00Z",
                "source": "custom_json",
                "records": [record.model_dump(mode="json"), record.model_dump(mode="json")],
            },
            "sha256": "dummy",
        }
        envelope["sha256"] = _hash_payload(envelope["payload"])
        with pytest.raises(BundleValidationError, match="[Dd]uplicate"):
            decode_bundle(json.dumps(envelope))

    def test_decode_rejects_bool_format_version(self):
        import json

        from backend.model_catalog.transfer import (
            BundleValidationError,
            _hash_payload,
            decode_bundle,
            encode_bundle,
        )

        bundle = encode_bundle([_candidate()], "custom_json")
        envelope = json.loads(bundle)
        envelope["formatVersion"] = True  # bool, not int
        envelope["sha256"] = _hash_payload(envelope["payload"])
        with pytest.raises(BundleValidationError, match="formatVersion"):
            decode_bundle(json.dumps(envelope))

    def test_decode_rejects_non_string_sha256(self):
        import json

        from backend.model_catalog.transfer import (
            BundleValidationError,
            decode_bundle,
            encode_bundle,
        )

        bundle = encode_bundle([_candidate()], "custom_json")
        envelope = json.loads(bundle)
        envelope["sha256"] = 12345  # number, not string
        with pytest.raises(BundleValidationError, match="sha256"):
            decode_bundle(json.dumps(envelope))


# ---------------------------------------------------------------------------
# map_openrouter
# ---------------------------------------------------------------------------


class TestMapOpenRouter:
    @staticmethod
    def _openrouter_payload(models=None):
        return {"data": models or []}

    @staticmethod
    def _model(
        model_id="openai/gpt-4o",
        context_length=128000,
        prompt="0.0000025",
        completion="0.00001",
        architecture=None,
        created=1700000000,
    ):
        return {
            "id": model_id,
            "name": "GPT-4o",
            "context_length": context_length,
            "created": created,
            "pricing": {"prompt": prompt, "completion": completion},
            "architecture": architecture or {"modality": "text"},
        }

    def test_basic_model_mapping(self):
        from backend.model_catalog.sources import map_openrouter

        data = self._openrouter_payload([self._model()])
        result = map_openrouter(data)
        assert len(result) == 1
        record = result[0]
        assert record.model_key == ModelKey(provider="openai", model_id="gpt-4o")
        assert record.native == 128000
        assert record.source == "openrouter"
        assert record.pricing_scope == "openrouter"
        # Per-token string * 1_000_000 = per-million Decimal
        assert record.price.input_per_million == Decimal("2.5")
        assert record.price.output_per_million == Decimal("10")

    def test_missing_prices_stay_unknown(self):
        from backend.model_catalog.sources import map_openrouter

        data = self._openrouter_payload([self._model(prompt=None, completion=None)])
        result = map_openrouter(data)
        assert result[0].price.input_per_million is None
        assert result[0].price.output_per_million is None

    def test_zero_price_is_free_not_unknown(self):
        from backend.model_catalog.sources import map_openrouter

        data = self._openrouter_payload([self._model(prompt="0", completion="0")])
        result = map_openrouter(data)
        assert result[0].price.input_per_million == Decimal("0")
        assert result[0].price.output_per_million == Decimal("0")

    def test_negative_price_is_unknown_not_free(self):
        from backend.model_catalog.sources import map_openrouter

        data = self._openrouter_payload([self._model(prompt="-1", completion="0.00001")])
        result = map_openrouter(data)
        # Negative prices are rejected by Price validation; input stays null
        assert result[0].price.input_per_million is None
        assert result[0].price.output_per_million == Decimal("10")

    def test_no_slash_in_id_uses_openrouter_provider(self):
        from backend.model_catalog.sources import map_openrouter

        data = self._openrouter_payload([self._model(model_id="custom-model")])
        result = map_openrouter(data)
        assert result[0].model_key.provider == "openrouter"
        assert result[0].model_key.model_id == "custom-model"

    def test_missing_context_length_stays_unknown(self):
        from backend.model_catalog.sources import map_openrouter

        data = self._openrouter_payload([self._model(context_length=None)])
        result = map_openrouter(data)
        assert result[0].native is None

    def test_empty_data_returns_empty(self):
        from backend.model_catalog.sources import map_openrouter

        assert map_openrouter(self._openrouter_payload([])) == []
        assert map_openrouter({}) == []

    def test_invalid_input_raises(self):
        from backend.model_catalog.sources import map_openrouter

        with pytest.raises((TypeError, ValueError)):
            map_openrouter("not a dict")
        with pytest.raises((TypeError, ValueError)):
            map_openrouter(None)
