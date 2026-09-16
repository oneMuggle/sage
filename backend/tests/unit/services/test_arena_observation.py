from __future__ import annotations

import pytest

from backend.services.arena_observation import ModelObservationService


class FakeBrowserSession:
    def __init__(self):
        self.attached = False


class FakeWorker:
    def __init__(self):
        self.calls: list = []

    def classify(self, evidence):
        self.calls.append(evidence)
        return {
            "modelId": "gpt-4o",
            "family": "openai",
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
