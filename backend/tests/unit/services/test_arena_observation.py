from __future__ import annotations

import pytest

from backend.services.arena_observation import ModelObservationService


class FakeBrowserSession:
    def __init__(self):
        self.attached = False


class FakeWorker:
    def __init__(self, override_model=None):
        self.calls: list = []
        self._override_model = override_model

    def classify(self, evidence):
        self.calls.append(evidence)
        model_id = self._override_model or evidence.get("modelId", "gpt-4o")
        return {
            "modelId": model_id,
            "family": evidence.get("family", "openai"),
            "confidence": 0.95,
            "source": evidence["source"],
            "evidence_count": 1,
        }


def test_observation_service_stores_dependencies():
    bs = FakeBrowserSession()
    w = FakeWorker()
    svc = ModelObservationService(browser_session=bs, worker=w)
    assert svc._browser_session is bs
    assert svc._worker is w
    assert svc.get_recent_verdicts() == []


def test_observation_service_processes_request_will_be_sent():
    bs = FakeBrowserSession()
    w = FakeWorker()
    svc = ModelObservationService(browser_session=bs, worker=w)

    event = {
        "method": "Network.requestWillBeSent",
        "params": {
            "requestId": "req-1",
            "request": {
                "url": "https://arena.ai/api/agent",
                "method": "POST",
                "postData": '{"model": "gpt-4o", "messages": []}',
            },
        },
    }
    verdict = svc.process_event(event)
    assert verdict is not None
    assert verdict["modelId"] == "gpt-4o"
    assert len(w.calls) == 1
    assert w.calls[0]["source"] == "request.body.model"


def test_observation_service_ignores_unrelated_urls():
    bs = FakeBrowserSession()
    w = FakeWorker()
    svc = ModelObservationService(browser_session=bs, worker=w)

    # Static asset — should be ignored
    event = {
        "method": "Network.requestWillBeSent",
        "params": {
            "requestId": "req-2",
            "request": {"url": "https://arena.ai/static/main.js", "method": "GET"},
        },
    }
    verdict = svc.process_event(event)
    assert verdict is None
    assert len(w.calls) == 0


def test_observation_service_ignores_telemetry_hosts():
    bs = FakeBrowserSession()
    w = FakeWorker()
    svc = ModelObservationService(browser_session=bs, worker=w)

    event = {
        "method": "Network.requestWillBeSent",
        "params": {
            "requestId": "req-3",
            "request": {
                "url": "https://browser-intake-datadoghq.com/api/v2/rum",
                "method": "POST",
                "postData": '{"model": "gpt-4o"}',
            },
        },
    }
    verdict = svc.process_event(event)
    assert verdict is None


def test_observation_service_recent_verdicts_capped():
    bs = FakeBrowserSession()
    w = FakeWorker()
    svc = ModelObservationService(browser_session=bs, worker=w)
    svc._verdict_cap = 3
    for i in range(5):
        svc._record_verdict({"modelId": f"m{i}", "confidence": 0.5, "source": "x"})
    assert len(svc.get_recent_verdicts()) == 3


def test_observation_service_lifecycle():
    """Lines 73-78: start() and stop() toggle running flag."""
    bs = FakeBrowserSession()
    w = FakeWorker()
    svc = ModelObservationService(browser_session=bs, worker=w)
    assert svc._running is False
    svc.start()
    assert svc._running is True
    svc.stop()
    assert svc._running is False


def test_observation_service_rejects_non_dict_event():
    """Line 86: process_event returns None for non-dict input."""
    bs = FakeBrowserSession()
    w = FakeWorker()
    svc = ModelObservationService(browser_session=bs, worker=w)
    assert svc.process_event("not a dict") is None
    assert svc.process_event(None) is None
    assert svc.process_event([]) is None


def test_observation_service_unknown_method_returns_none():
    """Lines 96-97: unknown CDP method returns None."""
    bs = FakeBrowserSession()
    w = FakeWorker()
    svc = ModelObservationService(browser_session=bs, worker=w)
    event = {"method": "Network.unknownEvent", "params": {}}
    assert svc.process_event(event) is None
    assert len(w.calls) == 0


def test_observation_service_worker_classify_exception():
    """Lines 104-106: worker.classify exception is caught and returns None."""
    bs = FakeBrowserSession()

    class BrokenWorker:
        def classify(self, evidence):
            raise RuntimeError("boom")

    svc = ModelObservationService(browser_session=bs, worker=BrokenWorker())
    event = {
        "method": "Network.requestWillBeSent",
        "params": {
            "request": {
                "url": "https://api.openai.com/v1/chat/completions",
                "postData": '{"model": "gpt-4"}',
            },
        },
    }
    verdict = svc.process_event(event)
    assert verdict is None


def test_observation_service_verdict_without_model_id_or_family():
    """Line 111: verdict returned but without modelId/family → None (no record)."""
    bs = FakeBrowserSession()

    class EmptyVerdictWorker:
        def classify(self, evidence):
            return {"confidence": 0.1}  # no modelId, no family

    svc = ModelObservationService(browser_session=bs, worker=EmptyVerdictWorker())
    event = {
        "method": "Network.requestWillBeSent",
        "params": {
            "request": {
                "url": "https://api.openai.com/v1/chat/completions",
                "postData": '{"model": "gpt-4"}',
            },
        },
    }
    verdict = svc.process_event(event)
    assert verdict is None
    assert len(svc.get_recent_verdicts()) == 0


def test_observation_service_get_recent_verdicts_with_zero_or_negative_n():
    """Line 115: get_recent_verdicts with n<=0 returns empty list."""
    bs = FakeBrowserSession()
    w = FakeWorker()
    svc = ModelObservationService(browser_session=bs, worker=w)
    svc._record_verdict({"modelId": "x"})
    assert svc.get_recent_verdicts(0) == []
    assert svc.get_recent_verdicts(-1) == []


def test_observation_service_response_events():
    """Lines 148-158: _evidence_from_response extracts model from headers."""
    bs = FakeBrowserSession()
    w = FakeWorker()
    svc = ModelObservationService(browser_session=bs, worker=w)

    # Response with model header
    event = {
        "method": "Network.responseReceived",
        "params": {
            "response": {
                "url": "https://api.openai.com/v1/chat/completions",
                "headers": {"x-model-version": "gpt-4o-mini"},
            },
        },
    }
    verdict = svc.process_event(event)
    assert verdict is not None
    assert verdict["modelId"] == "gpt-4o-mini"

    # Response with irrelevant URL → filtered
    event2 = {
        "method": "Network.responseReceived",
        "params": {
            "response": {
                "url": "https://example.com/static/image.png",
                "headers": {"x-model-version": "gpt-4"},
            },
        },
    }
    assert svc.process_event(event2) is None

    # Response with no model header → returns None
    event3 = {
        "method": "Network.responseReceived",
        "params": {
            "response": {
                "url": "https://api.openai.com/v1/chat/completions",
                "headers": {"content-type": "application/json"},
            },
        },
    }
    assert svc.process_event(event3) is None


def test_observation_service_websocket_frame_events():
    """Lines 162-185: _evidence_from_ws_frame extracts model from SSE chunks."""
    bs = FakeBrowserSession()
    w = FakeWorker()
    svc = ModelObservationService(browser_session=bs, worker=w)

    # WebSocket frame with structured JSON payload containing model
    event = {
        "method": "Network.webSocketFrameReceived",
        "params": {
            "response": {"url": "https://api.openai.com/v1/chat/completions"},
            "payloadData": '{"model": "claude-3-opus", "messages": []}',
        },
    }
    verdict = svc.process_event(event)
    assert verdict is not None
    assert verdict["modelId"] == "claude-3-opus"

    # WebSocket frame with non-JSON payload (regex fallback)
    event2 = {
        "method": "Network.webSocketFrameReceived",
        "params": {
            "response": {"url": "https://api.openai.com/v1/chat/completions"},
            "payloadData": 'some text with "model":"gpt-4o" embedded',
        },
    }
    verdict2 = svc.process_event(event2)
    assert verdict2 is not None
    assert verdict2["modelId"] == "gpt-4o"

    # WebSocket frame with irrelevant URL → filtered
    event3 = {
        "method": "Network.webSocketFrameReceived",
        "params": {
            "response": {"url": "https://example.com/style.css"},
            "payloadData": '{"model": "gpt-4"}',
        },
    }
    assert svc.process_event(event3) is None

    # WebSocket frame with empty payload → filtered
    event4 = {
        "method": "Network.webSocketFrameReceived",
        "params": {
            "response": {"url": "https://api.openai.com/v1/chat/completions"},
            "payloadData": "",
        },
    }
    assert svc.process_event(event4) is None


def test_observation_service_request_evidence_regex_fallback():
    """Lines 136-141: non-JSON post_data uses regex scan."""
    bs = FakeBrowserSession()
    w = FakeWorker()
    svc = ModelObservationService(browser_session=bs, worker=w)

    # Non-JSON post_data with model in regex pattern
    event = {
        "method": "Network.requestWillBeSent",
        "params": {
            "request": {
                "url": "https://api.openai.com/v1/chat/completions",
                "postData": 'text with "model":"gpt-3.5-turbo" inside',
            },
        },
    }
    verdict = svc.process_event(event)
    assert verdict is not None
    assert verdict["modelId"] == "gpt-3.5-turbo"


def test_observation_service_request_no_post_data():
    """Line 132: request without post_data returns None."""
    bs = FakeBrowserSession()
    w = FakeWorker()
    svc = ModelObservationService(browser_session=bs, worker=w)

    event = {
        "method": "Network.requestWillBeSent",
        "params": {
            "request": {
                "url": "https://api.openai.com/v1/chat/completions",
                "postData": "",
            },
        },
    }
    assert svc.process_event(event) is None


def test_observation_service_is_llm_relevant_empty_url():
    """Line 44: _is_llm_relevant returns False for empty URL."""
    from backend.services.arena_observation import _is_llm_relevant

    assert _is_llm_relevant("") is False
    assert _is_llm_relevant("https://example.com/static.js") is False
    assert _is_llm_relevant("https://api.openai.com/v1/chat") is True
