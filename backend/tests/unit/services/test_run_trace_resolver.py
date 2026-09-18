"""Tests for the run.trace resolver (Trigger.dev protocol)."""
from __future__ import annotations

import base64
import json

import pytest

from backend.services.run_trace_resolver import (
    RunTraceEvidence,
    RunTraceResolver,
    decode_jwt_payload,
    extract_models_from_trace,
    extract_public_access_token,
    extract_run_id_from_claims,
    parse_sse_frame,
)


def _make_test_jwt(claims: dict) -> str:
    """Create a test JWT (unsigned, for test fixtures only)."""
    header_b64 = base64.urlsafe_b64encode(
        json.dumps({"alg": "RS256", "typ": "JWT"}).encode()
    ).rstrip(b"=").decode()
    payload_b64 = base64.urlsafe_b64encode(
        json.dumps(claims).encode()
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

    resolver = RunTraceResolver(fetch_trace=fetch, emit_evidence=emitted.append)
    resolver.observe_sse_chunk(payload)
    assert emitted == []


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
