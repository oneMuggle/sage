"""Phase 5 HTTP Hook 测试 (无外网访问)。"""

from __future__ import annotations

import json

import httpx
import pytest

from backend.hooks.config import HookConfigError, validate_hooks
from backend.hooks.http_client import resolve_header_value, resolve_headers, send_http_hook
from backend.hooks.runner import DECISION_ALLOW, DECISION_NOOP, build_payload, run_hook

pytestmark = pytest.mark.unit


def test_http_hook_config_requires_valid_url():
    with pytest.raises(HookConfigError, match="url"):
        validate_hooks([{"event": "pre_tool_use", "hook_type": "http"}])
    with pytest.raises(HookConfigError, match="http/https"):
        validate_hooks(
            [{"event": "pre_tool_use", "hook_type": "http", "url": "file:///tmp/x"}]
        )


def test_http_hook_config_accepts_top_level_fields():
    hooks = validate_hooks(
        [
            {
                "event": "pre_tool_use",
                "hook_type": "http",
                "url": "https://hooks.example.test/check",
                "method": "POST",
                "headers": {"Authorization": "Bearer ${env:TOKEN}"},
            }
        ]
    )
    assert hooks[0].hook_type == "http"
    assert hooks[0].config_override["url"] == "https://hooks.example.test/check"
    assert hooks[0].config_override["headers"]["Authorization"] == "Bearer ${env:TOKEN}"


def test_http_hook_config_rejects_unsupported_method():
    with pytest.raises(HookConfigError, match="not supported"):
        validate_hooks(
            [
                {
                    "event": "pre_tool_use",
                    "hook_type": "http",
                    "url": "https://hooks.example.test/check",
                    "method": "DELETE",
                }
            ]
        )


def test_resolve_header_value_env(monkeypatch):
    monkeypatch.setenv("HOOK_TOKEN", "synthetic-secret")
    assert resolve_header_value("Bearer ${env:HOOK_TOKEN}") == "Bearer synthetic-secret"
    assert resolve_header_value("${env:MISSING}") == ""
    assert resolve_header_value("plain") == "plain"


def test_resolve_headers_filters_non_strings(monkeypatch):
    monkeypatch.setenv("TOKEN", "x")
    result = resolve_headers({"Authorization": "Bearer ${env:TOKEN}", "bad": 123})
    assert result == {"Authorization": "Bearer x"}


@pytest.mark.asyncio()
async def test_send_http_hook_success(monkeypatch):
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"decision": "allow", "additional_context": "ok"})

    transport = httpx.MockTransport(handler)
    original = httpx.AsyncClient

    def client_factory(*args, **kwargs):
        kwargs["transport"] = transport
        return original(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", client_factory)
    result = await send_http_hook(
        "https://hooks.example.test/check",
        {"hook_event_name": "post_tool_use", "tool_name": "bash"},
        headers={"X-Test": "yes"},
    )
    assert result == {"decision": "allow", "additional_context": "ok"}
    assert requests[0].headers["x-test"] == "yes"
    assert json.loads(requests[0].content)["tool_name"] == "bash"


@pytest.mark.asyncio()
async def test_send_http_hook_non_2xx_is_fail_open(monkeypatch):
    transport = httpx.MockTransport(lambda request: httpx.Response(503, text="down"))
    original = httpx.AsyncClient

    def client_factory(*args, **kwargs):
        kwargs["transport"] = transport
        return original(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", client_factory)
    assert await send_http_hook("https://hooks.example.test/check", {}) is None


@pytest.mark.asyncio()
async def test_send_http_hook_non_object_is_fail_open(monkeypatch):
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json=["bad"]))
    original = httpx.AsyncClient

    def client_factory(*args, **kwargs):
        kwargs["transport"] = transport
        return original(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", client_factory)
    assert await send_http_hook("https://hooks.example.test/check", {}) is None


@pytest.mark.asyncio()
async def test_runner_http_hook_parses_decision(monkeypatch):
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200,
            json={
                "decision": "allow",
                "additional_context": "remote lint",
                "severity": "warning",
            },
        )
    )
    original = httpx.AsyncClient

    def client_factory(*args, **kwargs):
        kwargs["transport"] = transport
        return original(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", client_factory)
    cfg = validate_hooks(
        [
            {
                "event": "post_tool_use",
                "hook_type": "http",
                "url": "https://hooks.example.test/check",
            }
        ]
    )[0]
    out = await run_hook(cfg, build_payload("post_tool_use", "bash", {}, tool_output="ok"))
    assert out.decision == DECISION_ALLOW
    assert out.additional_context == "remote lint"
    assert out.severity == "warning"


@pytest.mark.asyncio()
async def test_runner_http_failure_is_noop(monkeypatch):
    transport = httpx.MockTransport(lambda request: httpx.Response(500))
    original = httpx.AsyncClient

    def client_factory(*args, **kwargs):
        kwargs["transport"] = transport
        return original(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", client_factory)
    cfg = validate_hooks(
        [
            {
                "event": "post_tool_use",
                "hook_type": "http",
                "url": "https://hooks.example.test/check",
            }
        ]
    )[0]
    out = await run_hook(cfg, build_payload("post_tool_use", "bash", {}, tool_output="ok"))
    assert out.decision == DECISION_NOOP
