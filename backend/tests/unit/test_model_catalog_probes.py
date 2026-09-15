"""Service probe adapter tests: parse_probe for each supported service.

Tests verify:
- Ollama /api/show: llama.context_length → native (not service)
- OpenAI-compatible: no metadata → empty ProbeValues
- Unknown service → empty ProbeValues
- Malformed responses → graceful handling
- Quantization and architecture extraction from Ollama details
"""

import pytest

from backend.model_catalog.probes import (
    ProbeResult,
    ProbeValues,
    detect_service,
    parse_probe,
)


# ---------------------------------------------------------------------------
# parse_probe: Ollama adapter
# ---------------------------------------------------------------------------


class TestOllamaParseProbe:
    """Ollama /api/show response parsing."""

    def test_file_metadata_is_not_runtime_limit(self):
        """GGUF llama.context_length is file metadata → native, not service."""
        result = parse_probe(
            "ollama", {"model_info": {"llama.context_length": 32768}}
        )
        assert result.native == 32768
        assert result.service is None

    def test_ollama_full_response(self):
        """Full Ollama /api/show response with model_info + details."""
        response = {
            "model_info": {
                "llama.context_length": 4096,
                "llama.embedding_length": 4096,
                "general.architecture": "llama",
            },
            "details": {
                "family": "llama",
                "parameter_size": "7B",
                "quantization_level": "Q4_0",
            },
        }
        result = parse_probe("ollama", response)
        assert result.native == 4096
        assert result.service is None
        assert result.architecture == "llama"
        assert result.quantization == "Q4_0"

    def test_ollama_no_model_info(self):
        """Missing model_info → all None."""
        result = parse_probe("ollama", {"details": {"family": "llama"}})
        assert result.native is None
        assert result.service is None
        assert result.architecture == "llama"

    def test_ollama_empty_response(self):
        """Empty dict → empty ProbeValues."""
        result = parse_probe("ollama", {})
        assert result.native is None
        assert result.service is None

    def test_ollama_invalid_context_length_zero(self):
        """context_length=0 is not a valid positive integer → None."""
        result = parse_probe(
            "ollama", {"model_info": {"llama.context_length": 0}}
        )
        assert result.native is None

    def test_ollama_invalid_context_length_negative(self):
        """Negative context_length → None."""
        result = parse_probe(
            "ollama", {"model_info": {"llama.context_length": -1}}
        )
        assert result.native is None

    def test_ollama_invalid_context_length_string(self):
        """String context_length → None (not coerced)."""
        result = parse_probe(
            "ollama", {"model_info": {"llama.context_length": "4096"}}
        )
        assert result.native is None

    def test_ollama_invalid_context_length_float(self):
        """Float context_length → None (strict int check)."""
        result = parse_probe(
            "ollama", {"model_info": {"llama.context_length": 4096.0}}
        )
        assert result.native is None

    def test_ollama_model_info_not_dict(self):
        """model_info as non-dict → graceful fallback."""
        result = parse_probe("ollama", {"model_info": "not a dict"})
        assert result.native is None

    def test_ollama_details_not_dict(self):
        """details as non-dict → architecture/quantization None."""
        result = parse_probe(
            "ollama",
            {"model_info": {"llama.context_length": 4096}, "details": "bad"},
        )
        assert result.native == 4096
        assert result.architecture is None
        assert result.quantization is None

    def test_ollama_non_dict_response(self):
        """Non-dict response → empty ProbeValues."""
        result = parse_probe("ollama", "not a dict")  # type: ignore[arg-type]
        assert result.native is None
        assert result.service is None

    def test_ollama_quantization_only(self):
        """Only quantization_level, no family → architecture None."""
        result = parse_probe(
            "ollama",
            {"details": {"quantization_level": "Q8_0"}},
        )
        assert result.quantization == "Q8_0"
        assert result.architecture is None


# ---------------------------------------------------------------------------
# parse_probe: OpenAI-compatible adapters
# ---------------------------------------------------------------------------


class TestOpenAICompatibleParseProbe:
    """OpenAI-compatible services don't expose model metadata via /v1/models."""

    @pytest.mark.parametrize(
        "service",
        ["openai-compatible", "lmstudio", "vllm", "xinference", "localai"],
    )
    def test_openai_compatible_returns_empty(self, service):
        """All OpenAI-compatible variants return empty ProbeValues."""
        result = parse_probe(service, {"data": [{"id": "model"}]})
        assert result.native is None
        assert result.service is None
        assert result.architecture is None
        assert result.quantization is None

    def test_xinference_with_max_tokens_ignored(self):
        """Xinference /v1/models doesn't reliably expose max_tokens → ignore."""
        result = parse_probe(
            "xinference",
            {"data": [{"id": "model", "max_tokens": 8192}]},
        )
        assert result.native is None
        assert result.service is None


# ---------------------------------------------------------------------------
# parse_probe: Unknown service
# ---------------------------------------------------------------------------


class TestUnknownServiceParseProbe:
    """Unknown service → empty ProbeValues."""

    def test_unknown_service(self):
        result = parse_probe("custom-unknown", {"some": "data"})
        assert result.native is None
        assert result.service is None

    def test_empty_service_name(self):
        result = parse_probe("", {"some": "data"})
        assert result.native is None


# ---------------------------------------------------------------------------
# detect_service
# ---------------------------------------------------------------------------


class TestDetectService:
    """Protocol → service identifier mapping."""

    def test_ollama_protocol(self):
        assert detect_service("ollama", "http://localhost:11434") == "ollama"

    def test_openai_compatible_protocol(self):
        assert (
            detect_service("openai-compatible", "http://localhost:1234/v1")
            == "openai-compatible"
        )

    def test_anthropic_protocol(self):
        assert (
            detect_service("anthropic", "https://api.anthropic.com")
            == "openai-compatible"
        )

    def test_gemini_protocol(self):
        assert (
            detect_service(
                "gemini", "https://generativelanguage.googleapis.com"
            )
            == "openai-compatible"
        )


# ---------------------------------------------------------------------------
# ProbeResult model
# ---------------------------------------------------------------------------


class TestProbeResultModel:
    """ProbeResult validation."""

    def test_success_result(self):
        result = ProbeResult(
            status="success",
            adapter="ollama",
            data={"native": 4096},
        )
        assert result.status == "success"
        assert result.error is None

    def test_unsupported_result(self):
        result = ProbeResult(
            status="unsupported",
            adapter="openai-compatible",
            error="no metadata endpoint",
        )
        assert result.status == "unsupported"
        assert result.data is None

    def test_error_result(self):
        result = ProbeResult(
            status="error",
            adapter="ollama",
            error="connection refused",
        )
        assert result.status == "error"

    @pytest.mark.parametrize("bad_status", ["failed", "unknown", "", None])
    def test_invalid_status_rejected(self, bad_status):
        with pytest.raises(Exception):
            ProbeResult(status=bad_status, adapter="test")  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# ProbeValues model
# ---------------------------------------------------------------------------


class TestProbeValuesModel:
    """ProbeValues validation."""

    def test_all_none(self):
        values = ProbeValues()
        assert values.native is None
        assert values.service is None
        assert values.architecture is None
        assert values.quantization is None

    def test_with_values(self):
        values = ProbeValues(
            native=4096, architecture="llama", quantization="Q4_0"
        )
        assert values.native == 4096
        assert values.service is None

    def test_dict_roundtrip(self):
        values = ProbeValues(native=32768, architecture="mistral")
        data = values.model_dump()
        restored = ProbeValues.model_validate(data)
        assert restored == values
