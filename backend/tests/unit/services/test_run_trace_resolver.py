"""Tests for the run.trace resolver (Phase A scaffold)."""
import pytest

from backend.services.run_trace_resolver import (
    RunTraceEvidence,
    RunTraceResolver,
    extract_authorization_token,
    parse_trace_response,
    scan_sse_frame_for_run_id,
)


def test_scan_sse_frame_for_run_id_finds_run_id():
    payload = '{"event":"start","runId":"run_abc123"}'
    assert scan_sse_frame_for_run_id(payload) == "run_abc123"


def test_scan_sse_frame_for_run_id_returns_none_when_missing():
    assert scan_sse_frame_for_run_id('{"foo":"bar"}') is None


def test_extract_authorization_token_finds_token():
    payload = '{"public-access-token":"pat_xyz_123"}'
    assert extract_authorization_token(payload) == "pat_xyz_123"


def test_parse_trace_response_finds_do_stream_span():
    trace = {
        "spans": [
            {"name": "http.request", "attributes": {"model": "ignored"}},
            {
                "name": "ai.streamText.doStream",
                "attributes": {"model": "anthropic/claude-3-5-sonnet"},
            },
        ]
    }
    assert parse_trace_response(trace) == "anthropic/claude-3-5-sonnet"


def test_parse_trace_response_returns_none_when_span_missing():
    assert parse_trace_response({"spans": [{"name": "other"}]}) is None


def test_resolver_emits_evidence_on_first_observation():
    emitted = []

    def fetch(run_id, token):
        return {
            "spans": [
                {"name": "ai.streamText.doStream", "attributes": {"model": "gpt-4o"}}
            ]
        }

    def emit(ev):
        emitted.append(ev)

    resolver = RunTraceResolver(fetch_trace=fetch, emit_evidence=emit)
    resolver.observe_sse_chunk('{"runId":"r1"}')
    assert len(emitted) == 1
    assert emitted[0].model_id == "gpt-4o"
    assert emitted[0].run_id == "r1"
    assert emitted[0].weight == 1.00


def test_resolver_does_not_duplicate_same_run_id():
    emitted = []

    def fetch(run_id, token):
        return {
            "spans": [
                {"name": "ai.streamText.doStream", "attributes": {"model": "gpt-4o"}}
            ]
        }

    def emit(ev):
        emitted.append(ev)

    resolver = RunTraceResolver(fetch_trace=fetch, emit_evidence=emit)
    resolver.observe_sse_chunk('{"runId":"r1"}')
    resolver.observe_sse_chunk('{"runId":"r1"}')
    resolver.observe_sse_chunk('{"runId":"r1"}')
    assert len(emitted) == 1


def test_resolver_emits_for_distinct_run_ids():
    emitted = []

    def fetch(run_id, token):
        return {
            "spans": [
                {"name": "ai.streamText.doStream", "attributes": {"model": f"m-{run_id}"}}
            ]
        }

    def emit(ev):
        emitted.append(ev)

    resolver = RunTraceResolver(fetch_trace=fetch, emit_evidence=emit)
    resolver.observe_sse_chunk('{"runId":"r1"}')
    resolver.observe_sse_chunk('{"runId":"r2"}')
    assert len(emitted) == 2
    assert emitted[0].model_id == "m-r1"
    assert emitted[1].model_id == "m-r2"


def test_resolver_swallows_fetch_errors():
    emitted = []

    def fetch(run_id, token):
        raise RuntimeError("network error")

    def emit(ev):
        emitted.append(ev)

    resolver = RunTraceResolver(fetch_trace=fetch, emit_evidence=emit)
    resolver.observe_sse_chunk('{"runId":"r1"}')
    assert emitted == []
