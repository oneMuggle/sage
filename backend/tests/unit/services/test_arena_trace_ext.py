"""Unit tests for backend/services/arena_trace_ext.py (pure parsers)."""

from backend.services.arena_trace_ext import (
    extract_internal_names,
    extract_usage,
    model_matches,
    parse_models,
    parse_tier,
    setting_hints,
    span_ids,
)


def _stream_event(model="Claude Sonnet 4.5", provider="anthropic", run_id="run_x"):
    return {
        "runId": run_id,
        "message": "ai.streamText.doStream",
        "spanId": "span-1",
        "style": {
            "icon": f"ai-provider-{provider}",
            "accessory": {
                "items": [
                    {"icon": "tabler-cube", "text": model},
                    {"icon": "tabler-hash", "text": "6.6k"},
                    {"icon": "tabler-currency-dollar", "text": "$0.03"},
                ]
            },
        },
    }


def test_extract_internal_names_sorted_and_deduped():
    events = {
        "events": [
            {"payload": {"modelName": "gpt-6-astra-low"}},
            {"other": {"nested": {"modelName": "claude-sonnet-4.5-high"}}},
            {"again": {"modelName": "gpt-6-astra-low"}},
        ]
    }
    assert extract_internal_names(events) == ["claude-sonnet-4.5-high", "gpt-6-astra-low"]
    assert extract_internal_names({}) == []
    assert extract_internal_names({"events": []}) == []


def test_parse_tier():
    assert parse_tier("gpt-6-astra-low") == ("gpt-6-astra", "low")
    assert parse_tier("gpt-6-astra-low-20260101") == ("gpt-6-astra", "low")
    assert parse_tier("claude-opus-4.6.max") == ("claude-opus-4.6", "max")
    assert parse_tier("claude-sonnet-4.5") == ("", "")  # no tier suffix
    assert parse_tier("") == ("", "")


def test_model_matches():
    assert model_matches("anything", "", "") is True  # empty keeps all
    assert model_matches("GPT-6 Astra", "", "gpt-6") is True  # case-insensitive
    assert model_matches("Claude Sonnet 4.5", "", "^gpt") is False
    assert model_matches("", "gpt-6-astra-low", "astra") is True  # internal hit
    # invalid regex degrades to literal match, never raises
    assert model_matches("x(gpt)", "", "x(") is True
    assert model_matches("plain", "", "x(") is False


def test_extract_usage_from_usage_span():
    detail = {
        "properties": {
            "modelName": "gpt-6-astra-low",
            "provider": "openai",
            "inputTokens": 120,
            "outputTokens": 80.0,
            "reasoningTokens": "4096",
            "usageSource": "tokens",
        }
    }
    usage = extract_usage(detail, "usage")
    assert usage["modelName"] == "gpt-6-astra-low"
    assert usage["inputTokens"] == 120
    assert usage["outputTokens"] == 80
    assert usage["reasoningTokens"] == "4096"  # strings kept when not numeric


def test_extract_usage_from_stream_span_dotted_paths():
    detail = {
        "properties": {
            "ai": {"usage": {"reasoningTokens": 9, "outputTokens": 10}},
            "gen_ai": {"request": {"model": "gpt-6-astra"}},
        }
    }
    usage = extract_usage(detail, "stream")
    assert usage["reasoningTokens"] == 9
    assert usage["outputTokens"] == 10
    assert usage["requestModel"] == "gpt-6-astra"


def test_extract_usage_empty_and_garbage():
    assert extract_usage({}, "usage") == {}
    assert extract_usage({"properties": "not-a-dict"}, "stream") == {}
    assert extract_usage({"properties": {}}, "cost") == {}


def test_setting_hints():
    detail = {"properties": {"ai": {"settings": {"thinking": {"type": "enabled"}}}}}
    assert setting_hints(detail) == ["ai.settings.thinking"]
    assert setting_hints({"properties": {}}) == []


def test_span_ids_filter_and_cap():
    events = {
        "events": [
            {"message": "ai.streamText.doStream", "spanId": "s1"},
            {"message": "token.usage.recorded", "spanId": "s2"},
            {"message": "other.message", "spanId": "s3"},  # not a span kind
            {"message": "spend.recorded", "spanId": "s4"},
        ]
    }
    assert span_ids(events) == ["s1", "s2", "s4"]
    assert span_ids(events, kinds=("usage",)) == ["s2"]
    assert span_ids(events, max_n=2) == ["s2", "s4"]


def test_parse_models_attaches_internal_and_tokens():
    events = {
        "events": [
            _stream_event(model="GPT-6 Astra", provider="openai"),
            {"payload": {"modelName": "gpt-6-astra-low"}},
        ]
    }
    models = parse_models(events)
    assert len(models) == 1
    entry = models[0]
    assert entry["model"] == "GPT-6 Astra"
    assert entry["provider"] == "openai"
    assert entry["internal"] == "gpt-6-astra-low"
    assert entry["tokens"] == 6600  # "6.6k" parsed by run_trace_resolver
    assert entry["cost_usd"] == 0.03


def test_parse_models_empty_events():
    assert parse_models({}) == []
    assert parse_models({"events": [{"message": "unrelated"}]}) == []
