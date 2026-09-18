"""Tests for the run.trace resolver (Trigger.dev protocol)."""
from __future__ import annotations

import base64
import json
import time

import pytest

from backend.services.run_trace_resolver import (
    RunTraceEvidence,
    RunTraceResolver,
    decode_jwt_payload,
    extract_models_from_trace,
    extract_public_access_token,
    extract_run_id_from_claims,
    parse_sse_frame,
    validate_jwt_claims,
)


#: Valid defaults for JWT claims that pass validate_jwt_claims.
#: Tests that need invalid claims (for testing rejection) override these fields.
_VALID_CLAIM_DEFAULTS = {
    "iss": "https://id.trigger.dev",
    "aud": "https://api.trigger.dev",
    "exp": 0,  # sentinel: replaced with future timestamp at construction time
    "pub": True,
}


def _make_test_jwt(claims: dict, *, valid: bool = True) -> str:
    """Create a test JWT (unsigned, for test fixtures only).

    When ``valid=True`` (default), injects iss/aud/exp/pub so the token
    passes ``validate_jwt_claims``. Tests that exercise rejection paths
    pass ``valid=False`` to skip injection, or override specific fields
    after the fact.
    """
    merged = dict(claims)
    if valid:
        for key, default in _VALID_CLAIM_DEFAULTS.items():
            merged.setdefault(key, default)
        # exp sentinel → fresh future timestamp
        if merged.get("exp") == 0:
            merged["exp"] = int(time.time()) + 3600
    header_b64 = base64.urlsafe_b64encode(
        json.dumps({"alg": "RS256", "typ": "JWT"}).encode()
    ).rstrip(b"=").decode()
    payload_b64 = base64.urlsafe_b64encode(
        json.dumps(merged).encode()
    ).rstrip(b"=").decode()
    return f"{header_b64}.{payload_b64}.FAKE_SIG"


def _make_sse_payload(token: str, *, with_prefix: bool = True) -> str:
    """Build an SSE frame payload with the token in records[].headers."""
    frame = {
        "records": [
            {
                "headers": [
                    ["public-access-token", token],
                    ["content-type", "text/event-stream"],
                ]
            }
        ]
    }
    json_str = json.dumps(frame)
    if with_prefix:
        return f"data: {json_str}"
    return json_str


def _make_trace(run_id: str, model: str, provider: str = "openai") -> dict:
    """Build a Trigger.dev trace response with one streamText event."""
    return {
        "events": [
            {
                "runId": run_id,
                "message": "ai.streamText.doStream",
                "style": {
                    "icon": f"ai-provider-{provider}",
                    "accessory": {
                        "items": [
                            {"icon": "tabler-cube", "text": model},
                            {"icon": "tabler-hash", "text": "6.6k"},
                        ]
                    },
                },
            }
        ]
    }


# --- parse_sse_frame ---

def test_parse_sse_frame_strips_data_prefix():
    payload = 'data: {"records": [{"headers": []}]}'
    frame = parse_sse_frame(payload)
    assert frame is not None
    assert "records" in frame


def test_parse_sse_frame_without_prefix():
    frame = parse_sse_frame('{"records": [{"headers": []}]}')
    assert frame is not None
    assert "records" in frame


def test_parse_sse_frame_returns_none_on_garbage():
    assert parse_sse_frame("not json") is None
    assert parse_sse_frame("") is None
    assert parse_sse_frame("   ") is None


# --- extract_public_access_token ---

def test_extract_public_access_token_from_list_headers():
    frame = {
        "records": [
            {
                "headers": [
                    ["content-type", "text/event-stream"],
                    ["public-access-token", "eyJ.test.sig"],
                ]
            }
        ]
    }
    assert extract_public_access_token(frame) == "eyJ.test.sig"


def test_extract_public_access_token_from_dict_headers():
    frame = {
        "records": [
            {
                "headers": {
                    "Public-Access-Token": "eyJ.dict.sig",
                }
            }
        ]
    }
    assert extract_public_access_token(frame) == "eyJ.dict.sig"


def test_extract_public_access_token_case_insensitive():
    frame = {
        "records": [
            {"headers": [["PUBLIC-ACCESS-TOKEN", "eyJ.upper.sig"]]}
        ]
    }
    assert extract_public_access_token(frame) == "eyJ.upper.sig"


def test_extract_public_access_token_returns_none_when_missing():
    frame = {"records": [{"headers": [["content-type", "text/plain"]]}]}
    assert extract_public_access_token(frame) is None


def test_extract_public_access_token_skips_non_string_values():
    frame = {"records": [{"headers": [["public-access-token", 12345]]}]}
    assert extract_public_access_token(frame) is None


def test_extract_public_access_token_single_record_no_list():
    """Frame without records[] wraps the frame itself as a single record."""
    frame = {"headers": [["public-access-token", "eyJ.single.sig"]]}
    assert extract_public_access_token(frame) == "eyJ.single.sig"


# --- decode_jwt_payload ---

def test_decode_jwt_payload_roundtrip():
    claims = {"pub": True, "run": "run_abc123", "type": "run"}
    token = _make_test_jwt(claims)
    decoded = decode_jwt_payload(token)
    assert decoded["pub"] is True
    assert decoded["run"] == "run_abc123"


def test_decode_jwt_payload_raises_on_malformed():
    with pytest.raises(ValueError, match="3 parts"):
        decode_jwt_payload("not.a.valid.jwt.too.many")
    with pytest.raises(ValueError, match="3 parts"):
        decode_jwt_payload("single")
    with pytest.raises(ValueError, match="must be a string"):
        decode_jwt_payload(12345)


def test_decode_jwt_payload_raises_on_bad_base64():
    # Use a payload that base64-decodes to non-JSON bytes
    bad_payload = base64.urlsafe_b64encode(b"\xff\xfe\x00\x01not json").rstrip(b"=").decode()
    bad_token = f"eyJ0eXBlIjoiUlMyNTYifQ.{bad_payload}.FAKE_SIG"
    with pytest.raises(ValueError, match="Cannot decode"):
        decode_jwt_payload(bad_token)


# --- extract_run_id_from_claims ---

def test_extract_run_id_from_claims_run_field():
    claims = {"type": "run", "run": "run_2XN4gjwt7v"}
    assert extract_run_id_from_claims(claims) == "run_2XN4gjwt7v"


def test_extract_run_id_from_claims_scopes_fallback():
    claims = {
        "scopes": [
            "read:user",
            "read:runs:run_scope456",
        ]
    }
    assert extract_run_id_from_claims(claims) == "run_scope456"


def test_extract_run_id_from_claims_prefers_run_field():
    claims = {
        "type": "run",
        "run": "run_direct",
        "scopes": ["read:runs:run_scope"],
    }
    assert extract_run_id_from_claims(claims) == "run_direct"


def test_extract_run_id_from_claims_returns_none_when_missing():
    assert extract_run_id_from_claims({"pub": True}) is None
    assert extract_run_id_from_claims({"scopes": ["read:user"]}) is None


def test_extract_run_id_from_claims_multiple_run_scopes():
    claims = {
        "scopes": [
            "read:runs:run_a",
            "read:runs:run_b",
        ]
    }
    assert extract_run_id_from_claims(claims) is None


# --- validate_jwt_claims ---

def test_validate_jwt_claims_accepts_valid_claims():
    import time
    from backend.services.run_trace_resolver import validate_jwt_claims
    claims = {
        "iss": "https://id.trigger.dev",
        "aud": "https://api.trigger.dev",
        "exp": int(time.time()) + 3600,
        "pub": True,
        "run": "run_abc",
        "type": "run",
    }
    assert validate_jwt_claims(claims) is True


def test_validate_jwt_claims_rejects_wrong_issuer():
    import time
    from backend.services.run_trace_resolver import validate_jwt_claims
    claims = {
        "iss": "https://evil.example.com",
        "aud": "https://api.trigger.dev",
        "exp": int(time.time()) + 3600,
        "pub": True,
    }
    assert validate_jwt_claims(claims) is False


def test_validate_jwt_claims_rejects_wrong_audience():
    import time
    from backend.services.run_trace_resolver import validate_jwt_claims
    claims = {
        "iss": "https://id.trigger.dev",
        "aud": "https://evil.example.com",
        "exp": int(time.time()) + 3600,
        "pub": True,
    }
    assert validate_jwt_claims(claims) is False


def test_validate_jwt_claims_rejects_expired():
    import time
    from backend.services.run_trace_resolver import validate_jwt_claims
    claims = {
        "iss": "https://id.trigger.dev",
        "aud": "https://api.trigger.dev",
        "exp": int(time.time()) - 60,  # expired 60s ago
        "pub": True,
    }
    assert validate_jwt_claims(claims) is False


def test_validate_jwt_claims_rejects_missing_pub():
    import time
    from backend.services.run_trace_resolver import validate_jwt_claims
    claims = {
        "iss": "https://id.trigger.dev",
        "aud": "https://api.trigger.dev",
        "exp": int(time.time()) + 3600,
    }
    assert validate_jwt_claims(claims) is False


def test_validate_jwt_claims_rejects_pub_false():
    import time
    from backend.services.run_trace_resolver import validate_jwt_claims
    claims = {
        "iss": "https://id.trigger.dev",
        "aud": "https://api.trigger.dev",
        "exp": int(time.time()) + 3600,
        "pub": False,
    }
    assert validate_jwt_claims(claims) is False


def test_validate_jwt_claims_rejects_missing_exp():
    from backend.services.run_trace_resolver import validate_jwt_claims
    claims = {
        "iss": "https://id.trigger.dev",
        "aud": "https://api.trigger.dev",
        "pub": True,
    }
    assert validate_jwt_claims(claims) is False


def test_resolver_rejects_expired_jwt():
    """observe_sse_chunk must silently drop tokens with expired JWTs."""
    import time
    emitted = []
    claims = {
        "iss": "https://id.trigger.dev",
        "aud": "https://api.trigger.dev",
        "exp": int(time.time()) - 60,
        "pub": True,
        "run": "run_expired",
        "type": "run",
    }
    token = _make_test_jwt(claims)
    payload = _make_sse_payload(token)

    resolver = RunTraceResolver(
        fetch_trace=lambda rid, tok: {}, emit_evidence=emitted.append
    )
    resolver.observe_sse_chunk(payload)
    assert emitted == []


def test_resolver_rejects_wrong_issuer_jwt():
    """observe_sse_chunk must silently drop tokens with wrong issuer."""
    import time
    emitted = []
    claims = {
        "iss": "https://evil.example.com",
        "aud": "https://api.trigger.dev",
        "exp": int(time.time()) + 3600,
        "pub": True,
        "run": "run_evil",
        "type": "run",
    }
    token = _make_test_jwt(claims)
    payload = _make_sse_payload(token)

    resolver = RunTraceResolver(
        fetch_trace=lambda rid, tok: {}, emit_evidence=emitted.append
    )
    resolver.observe_sse_chunk(payload)
    assert emitted == []


# --- extract_models_from_trace ---

def test_extract_models_from_trace_finds_model_and_provider():
    trace = _make_trace("run_1", "gpt-6-astra-low", "openai")
    models = extract_models_from_trace(trace, "run_1")
    assert len(models) == 1
    assert models[0]["model"] == "gpt-6-astra-low"
    assert models[0]["provider"] == "openai"


def test_extract_models_from_trace_filters_by_run_id():
    trace = _make_trace("run_1", "gpt-4o")
    assert extract_models_from_trace(trace, "run_OTHER") == []


def test_extract_models_from_trace_ignores_non_stream_events():
    trace = {
        "events": [
            {"runId": "run_1", "message": "http.request", "style": {}},
            {
                "runId": "run_1",
                "message": "ai.streamText.doStream",
                "style": {
                    "icon": "ai-provider-anthropic",
                    "accessory": {
                        "items": [{"icon": "tabler-cube", "text": "claude-fable-5.1"}]
                    },
                },
            },
        ]
    }
    models = extract_models_from_trace(trace, "run_1")
    assert len(models) == 1
    assert models[0]["model"] == "claude-fable-5.1"
    assert models[0]["provider"] == "anthropic"


def test_extract_models_from_trace_no_provider_icon():
    trace = {
        "events": [
            {
                "runId": "run_1",
                "message": "ai.streamText.doStream",
                "style": {
                    "accessory": {
                        "items": [{"icon": "tabler-cube", "text": "unknown-model"}]
                    }
                },
            }
        ]
    }
    models = extract_models_from_trace(trace, "run_1")
    assert len(models) == 1
    assert models[0]["model"] == "unknown-model"
    assert "provider" not in models[0]


def test_extract_models_from_trace_multiple_models_dedup():
    trace = {
        "events": [
            {
                "runId": "run_1",
                "message": "ai.streamText.doStream",
                "style": {
                    "icon": "ai-provider-openai",
                    "accessory": {
                        "items": [
                            {"icon": "tabler-cube", "text": "gpt-6-astra"},
                            {"icon": "tabler-cube", "text": "gpt-6-astra"},
                        ]
                    },
                },
            }
        ]
    }
    models = extract_models_from_trace(trace, "run_1")
    assert len(models) == 1


def test_extract_models_from_trace_empty_events():
    assert extract_models_from_trace({}, "run_1") == []
    assert extract_models_from_trace({"events": []}, "run_1") == []


# --- parse_token_count ---

def test_parse_token_count_k_suffix():
    from backend.services.run_trace_resolver import parse_token_count
    assert parse_token_count("6.6k") == 6600
    assert parse_token_count("1.5K") == 1500
    assert parse_token_count("10k") == 10000


def test_parse_token_count_m_suffix():
    from backend.services.run_trace_resolver import parse_token_count
    assert parse_token_count("1.2M") == 1200000
    assert parse_token_count("2m") == 2000000


def test_parse_token_count_plain_number():
    from backend.services.run_trace_resolver import parse_token_count
    assert parse_token_count("1500") == 1500
    assert parse_token_count("0") == 0


def test_parse_token_count_with_commas():
    from backend.services.run_trace_resolver import parse_token_count
    assert parse_token_count("1,500") == 1500
    assert parse_token_count("1,200,000") == 1200000


def test_parse_token_count_returns_none_on_garbage():
    from backend.services.run_trace_resolver import parse_token_count
    assert parse_token_count("") is None
    assert parse_token_count("abc") is None
    assert parse_token_count("  ") is None


# --- parse_cost_usd ---

def test_parse_cost_usd_dollar_prefix():
    from backend.services.run_trace_resolver import parse_cost_usd
    assert parse_cost_usd("$0.03") == pytest.approx(0.03)
    assert parse_cost_usd("$1.50") == pytest.approx(1.50)
    assert parse_cost_usd("$ 0.05") == pytest.approx(0.05)


def test_parse_cost_usd_no_dollar():
    from backend.services.run_trace_resolver import parse_cost_usd
    assert parse_cost_usd("0.05") == pytest.approx(0.05)
    assert parse_cost_usd("1.00") == pytest.approx(1.00)


def test_parse_cost_usd_returns_none_on_garbage():
    from backend.services.run_trace_resolver import parse_cost_usd
    assert parse_cost_usd("") is None
    assert parse_cost_usd("abc") is None
    assert parse_cost_usd("free") is None


# --- extract_models_from_trace with tokens/cost ---

def test_extract_models_from_trace_includes_tokens():
    trace = {
        "events": [
            {
                "runId": "run_1",
                "message": "ai.streamText.doStream",
                "style": {
                    "icon": "ai-provider-openai",
                    "accessory": {
                        "items": [
                            {"icon": "tabler-cube", "text": "gpt-4o"},
                            {"icon": "tabler-hash", "text": "6.6k"},
                        ]
                    },
                },
            }
        ]
    }
    models = extract_models_from_trace(trace, "run_1")
    assert len(models) == 1
    assert models[0]["tokens"] == 6600


def test_extract_models_from_trace_includes_cost():
    trace = {
        "events": [
            {
                "runId": "run_1",
                "message": "ai.streamText.doStream",
                "style": {
                    "icon": "ai-provider-anthropic",
                    "accessory": {
                        "items": [
                            {"icon": "tabler-cube", "text": "claude-sonnet"},
                            {"icon": "tabler-currency-dollar", "text": "$0.03"},
                        ]
                    },
                },
            }
        ]
    }
    models = extract_models_from_trace(trace, "run_1")
    assert len(models) == 1
    assert models[0]["cost_usd"] == pytest.approx(0.03)


def test_extract_models_from_trace_tokens_and_cost_absent():
    trace = {
        "events": [
            {
                "runId": "run_1",
                "message": "ai.streamText.doStream",
                "style": {
                    "icon": "ai-provider-openai",
                    "accessory": {
                        "items": [
                            {"icon": "tabler-cube", "text": "gpt-4o"},
                        ]
                    },
                },
            }
        ]
    }
    models = extract_models_from_trace(trace, "run_1")
    assert len(models) == 1
    assert "tokens" not in models[0]
    assert "cost_usd" not in models[0]


# --- RunTraceEvidence with tokens/cost ---

def test_run_trace_evidence_has_tokens_and_cost():
    ev = RunTraceEvidence(
        model_id="gpt-4o", run_id="run_1",
        tokens=6600, cost_usd=0.03,
    )
    assert ev.tokens == 6600
    assert ev.cost_usd == pytest.approx(0.03)


def test_run_trace_evidence_defaults_tokens_cost_to_none():
    ev = RunTraceEvidence(model_id="gpt-4o", run_id="run_1")
    assert ev.tokens is None
    assert ev.cost_usd is None


def test_resolver_emits_evidence_with_tokens_and_cost():
    emitted = []

    def fetch(rid, tok):
        return {
            "events": [
                {
                    "runId": rid,
                    "message": "ai.streamText.doStream",
                    "style": {
                        "icon": "ai-provider-openai",
                        "accessory": {
                            "items": [
                                {"icon": "tabler-cube", "text": "gpt-4o"},
                                {"icon": "tabler-hash", "text": "1.5k"},
                                {"icon": "tabler-currency-dollar", "text": "$0.05"},
                            ]
                        },
                    },
                }
            ]
        }

    resolver = RunTraceResolver(fetch_trace=fetch, emit_evidence=emitted.append)
    token = _make_test_jwt({"run": "run_tc", "type": "run"})
    resolver.observe_sse_chunk(_make_sse_payload(token))

    assert len(emitted) == 1
    assert emitted[0].tokens == 1500
    assert emitted[0].cost_usd == pytest.approx(0.05)


# --- RunTraceResolver (integration of the above) ---

def test_resolver_emits_evidence_on_first_observation():
    emitted = []
    run_id = "run_test123"
    token = _make_test_jwt({"run": run_id, "type": "run", "pub": True})
    payload = _make_sse_payload(token)

    def fetch(rid, tok):
        return _make_trace(rid, "gpt-4o")

    resolver = RunTraceResolver(fetch_trace=fetch, emit_evidence=emitted.append)
    resolver.observe_sse_chunk(payload)

    assert len(emitted) == 1
    assert emitted[0].model_id == "gpt-4o"
    assert emitted[0].run_id == run_id
    assert emitted[0].weight == 1.00
    assert emitted[0].provider == "openai"


def test_resolver_does_not_duplicate_same_run_id():
    emitted = []
    token = _make_test_jwt({"run": "run_dup", "type": "run"})
    payload = _make_sse_payload(token)

    def fetch(rid, tok):
        return _make_trace(rid, "gpt-4o")

    resolver = RunTraceResolver(fetch_trace=fetch, emit_evidence=emitted.append)
    resolver.observe_sse_chunk(payload)
    resolver.observe_sse_chunk(payload)
    resolver.observe_sse_chunk(payload)
    assert len(emitted) == 1


def test_resolver_emits_for_distinct_run_ids():
    emitted = []

    def fetch(rid, tok):
        return _make_trace(rid, f"model-{rid}")

    resolver = RunTraceResolver(fetch_trace=fetch, emit_evidence=emitted.append)

    for rid in ["run_a", "run_b"]:
        token = _make_test_jwt({"run": rid, "type": "run"})
        resolver.observe_sse_chunk(_make_sse_payload(token))

    assert len(emitted) == 2
    assert emitted[0].model_id == "model-run_a"
    assert emitted[1].model_id == "model-run_b"


def test_resolver_swallows_fetch_errors():
    emitted = []
    token = _make_test_jwt({"run": "run_err", "type": "run"})
    payload = _make_sse_payload(token)

    def fetch(rid, tok):
        raise RuntimeError("network error")

    resolver = RunTraceResolver(
        fetch_trace=fetch, emit_evidence=emitted.append,
        max_attempts=1,  # single attempt for this test (no retry)
    )
    resolver.observe_sse_chunk(payload)
    assert emitted == []


def test_resolver_retries_fetch_on_failure_then_succeeds():
    """8×3s retry: fetch fails 3 times then succeeds on attempt 4."""
    emitted = []
    token = _make_test_jwt({"run": "run_retry", "type": "run"})
    payload = _make_sse_payload(token)

    attempts = {"n": 0}

    def fetch(rid, tok):
        attempts["n"] += 1
        if attempts["n"] < 4:
            raise RuntimeError(f"transient error #{attempts['n']}")
        return _make_trace(rid, "gpt-4o")

    resolver = RunTraceResolver(
        fetch_trace=fetch, emit_evidence=emitted.append,
        max_attempts=8, base_delay=0.0,  # no sleep in test
    )
    resolver.observe_sse_chunk(payload)
    assert attempts["n"] == 4
    assert len(emitted) == 1
    assert emitted[0].model_id == "gpt-4o"


def test_resolver_retries_exhausted_returns_no_evidence():
    """All 8 attempts fail → no evidence emitted."""
    emitted = []
    token = _make_test_jwt({"run": "run_exhausted", "type": "run"})
    payload = _make_sse_payload(token)

    attempts = {"n": 0}

    def fetch(rid, tok):
        attempts["n"] += 1
        raise RuntimeError("always fails")

    resolver = RunTraceResolver(
        fetch_trace=fetch, emit_evidence=emitted.append,
        max_attempts=8, base_delay=0.0,
    )
    resolver.observe_sse_chunk(payload)
    assert attempts["n"] == 8
    assert emitted == []


def test_resolver_retry_default_is_8_attempts():
    """Default max_attempts is 8 per spec §3.5."""
    emitted = []
    token = _make_test_jwt({"run": "run_default", "type": "run"})
    payload = _make_sse_payload(token)

    attempts = {"n": 0}

    def fetch(rid, tok):
        attempts["n"] += 1
        raise RuntimeError("always fails")

    resolver = RunTraceResolver(
        fetch_trace=fetch, emit_evidence=emitted.append,
        base_delay=0.0,  # no sleep in test
    )
    resolver.observe_sse_chunk(payload)
    assert attempts["n"] == 8


def test_resolver_retry_respects_5xx_status_error():
    """ConnectionError and HTTP-style status errors are retried."""
    emitted = []
    token = _make_test_jwt({"run": "run_http_err", "type": "run"})
    payload = _make_sse_payload(token)

    attempts = {"n": 0}

    class FakeHTTPError(Exception):
        def __init__(self, status):
            super().__init__(f"HTTP {status}")
            self.status_code = status

    def fetch(rid, tok):
        attempts["n"] += 1
        if attempts["n"] < 3:
            raise FakeHTTPError(503)
        return _make_trace(rid, "claude-3-sonnet")

    resolver = RunTraceResolver(
        fetch_trace=fetch, emit_evidence=emitted.append,
        max_attempts=8, base_delay=0.0,
    )
    resolver.observe_sse_chunk(payload)
    assert attempts["n"] == 3
    assert len(emitted) == 1


def test_resolver_ignores_payload_without_token():
    emitted = []
    resolver = RunTraceResolver(
        fetch_trace=lambda rid, tok: {}, emit_evidence=emitted.append
    )
    resolver.observe_sse_chunk('data: {"no_token": true}')
    assert emitted == []


def test_resolver_ignores_invalid_jwt():
    emitted = []
    frame = {"records": [{"headers": [["public-access-token", "not.a.jwt"]]}]}
    payload = f"data: {json.dumps(frame)}"
    resolver = RunTraceResolver(
        fetch_trace=lambda rid, tok: {}, emit_evidence=emitted.append
    )
    resolver.observe_sse_chunk(payload)
    assert emitted == []


def test_resolver_ignores_garbage_payload():
    emitted = []
    resolver = RunTraceResolver(
        fetch_trace=lambda rid, tok: {}, emit_evidence=emitted.append
    )
    resolver.observe_sse_chunk("not valid json at all")
    assert emitted == []


def test_resolver_handles_scopes_format_run_id():
    emitted = []
    claims = {
        "pub": True,
        "scopes": ["read:user", "read:runs:run_scope_fallback"],
    }
    token = _make_test_jwt(claims)
    payload = _make_sse_payload(token)

    def fetch(rid, tok):
        return _make_trace(rid, "claude-3-sonnet")

    resolver = RunTraceResolver(fetch_trace=fetch, emit_evidence=emitted.append)
    resolver.observe_sse_chunk(payload)

    assert len(emitted) == 1
    assert emitted[0].run_id == "run_scope_fallback"


def test_resolver_evidence_is_frozen_dataclass():
    ev = RunTraceEvidence(model_id="m", run_id="r")
    with pytest.raises(AttributeError):
        ev.model_id = "changed"
