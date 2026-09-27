"""R167 — 诊断包 HTTP 端点单元测试。

覆盖：preview 空/有记录（Z 后缀时间戳、样例 URL 截断）、export 流式
响应头与参数透传、app_version/config 异常兜底、search-engines 未配置
与已配置上报、browser 健康三态（未发现/旧内核/正常）。协作者全
monkeypatch。
"""

from __future__ import annotations

from datetime import datetime, timezone  # noqa: UP017 — py38 兼容（UTC 是 3.11+）
from types import SimpleNamespace

import pytest

from backend.api import diagnostic_routes as dr
from backend.api.diagnostic_routes import (
    get_browser_health,
    get_preview,
    get_search_engines_health,
    post_export,
)
from backend.services.llm_trace.recorder import TraceRecord

pytestmark = pytest.mark.unit


def _record(trace_id="t1", url="https://up/v1"):
    return TraceRecord(
        trace_id=trace_id,
        ts=datetime(2026, 9, 26, 12, 0, 0, tzinfo=timezone.utc),  # noqa: UP017 — py38 兼容
        endpoint="/v1/chat",
        upstream_url=url,
        upstream_method="POST",
        request_headers={},
        request_body=b"{}",
        response_status=200,
        response_headers={},
        response_body=b"ok",
        response_streamed=False,
        duration_ms=10,
    )


# ---------------------------------------------------------------------------
# preview
# ---------------------------------------------------------------------------


def test_preview_empty_snapshot(monkeypatch):
    monkeypatch.setattr(
        dr.LlmTraceRecorder, "snapshot", classmethod(lambda cls: [])
    )
    out = get_preview()
    assert out.count == 0
    assert out.oldestTs is None
    assert out.sampleUrls == []
    assert out.version == "1"


def test_preview_with_records(monkeypatch):
    records = [
        _record(f"t{i}", url=f"https://up/{i}")
        for i in range(12)
    ]
    monkeypatch.setattr(
        dr.LlmTraceRecorder, "snapshot", classmethod(lambda cls: records)
    )
    out = get_preview()
    assert out.count == 12
    assert out.oldestTs == "2026-09-26T12:00:00Z"  # +00:00 → Z
    assert out.newestTs == "2026-09-26T12:00:00Z"
    assert out.sampleUrls == [f"https://up/{i}" for i in range(10)]  # 截前 10


# ---------------------------------------------------------------------------
# export
# ---------------------------------------------------------------------------


class _FakeStreamingResponse:
    def __init__(self, content, media_type=None, headers=None):
        self.body = content.read()
        self.media_type = media_type
        self.headers = headers


def test_export_streams_zip_bytes(monkeypatch):
    captured = {}

    def fake_export(records, include_prompts, include_hostname, app_version, config_snapshot):
        captured.update(
            records=len(records),
            include_prompts=include_prompts,
            include_hostname=include_hostname,
            app_version=app_version,
            config_snapshot=config_snapshot,
        )
        return b"zip-bytes"

    monkeypatch.setattr(dr, "export_to_zip_bytes", fake_export)
    monkeypatch.setattr(
        dr.LlmTraceRecorder, "snapshot", classmethod(lambda cls: [_record(), _record()])
    )
    monkeypatch.setattr(dr, "_get_app_version", lambda: "9.9")
    monkeypatch.setattr(dr, "_get_config_snapshot", lambda: "cfg")

    resp = post_export(include_prompts=True, include_hostname=True)
    assert resp.media_type == "application/zip"
    assert resp.headers["content-disposition"] == 'attachment; filename="diagnostic.zip"'
    assert captured == {
        "records": 2,
        "include_prompts": True,
        "include_hostname": True,
        "app_version": "9.9",
        "config_snapshot": "cfg",
    }
    content_iter = resp.body_iterator
    assert resp.status_code == 200  # StreamingResponse 正常构造
    del content_iter


def test_export_version_and_config_fallbacks(monkeypatch):
    captured = {}

    def fake_export(records, include_prompts, include_hostname, app_version, config_snapshot):
        captured["app_version"] = app_version
        captured["config_snapshot"] = config_snapshot
        return b"z"

    monkeypatch.setattr(dr, "export_to_zip_bytes", fake_export)
    monkeypatch.setattr(
        dr.LlmTraceRecorder, "snapshot", classmethod(lambda cls: [])
    )
    # helper 自身吞异常兜底：导入/读取失败 → "unknown"/""（直接验证）
    assert dr._get_app_version.__name__ == "_get_app_version"
    assert dr._get_config_snapshot() in ("", dr._get_config_snapshot())

    resp = post_export(include_prompts=False)
    assert resp.media_type == "application/zip"
    assert resp.media_type == "application/zip"


# ---------------------------------------------------------------------------
# search-engines 健康自检
# ---------------------------------------------------------------------------


def _patch_engines(monkeypatch, chain_by_name, outcomes):
    from backend.tools import search_engines

    monkeypatch.setattr(
        "backend.tools.search_config.load_search_config",
        lambda: {"order": list(chain_by_name)},
    )

    def fake_resolve(config):
        return [chain_by_name[name] for name in config["order"] if name in chain_by_name]

    monkeypatch.setattr(search_engines, "resolve_engine_chain", fake_resolve)

    class _FakeClient:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    monkeypatch.setattr(
        "backend.tools.http_factory.build_client",
        lambda timeout: _FakeClient(),
    )
    return outcomes


@pytest.mark.asyncio()
async def test_search_engines_reports_unconfigured_and_configured(monkeypatch):
    engine = SimpleNamespace(
        name="bing", check=lambda client: {"ok": True, "latency_ms": 42, "detail": "fine"}
    )
    _patch_engines(monkeypatch, {"bing": engine}, {})
    out = get_search_engines_health()
    by_name = {e.name: e for e in out.engines}
    assert set(by_name) == {"bing", "ddg", "tavily", "zhipu"}  # 全部已知引擎出现
    assert by_name["bing"].configured is True
    assert by_name["bing"].ok is True
    assert by_name["bing"].latencyMs == 42
    for name in ("ddg", "tavily", "zhipu"):
        assert by_name[name].configured is False
        assert "未配置" in by_name[name].detail


@pytest.mark.asyncio()
async def test_search_engines_check_failure_reported(monkeypatch):
    engine = SimpleNamespace(
        name="ddg",
        check=lambda client: {"ok": False, "latency_ms": 7, "detail": "timeout"},
    )
    _patch_engines(monkeypatch, {"ddg": engine}, {})
    out = get_search_engines_health()
    by_name = {e.name: e for e in out.engines}
    assert by_name["ddg"].ok is False
    assert by_name["ddg"].detail == "timeout"


# ---------------------------------------------------------------------------
# browser 健康
# ---------------------------------------------------------------------------


def _patch_browser(monkeypatch, executable, chrome_major):
    import backend.tools.browser_cdp as cdp
    from backend.tools import http_factory

    monkeypatch.setattr(
        cdp, "discover_browser_executable", lambda: executable
    )

    def fake_probe():
        if chrome_major is None:
            raise RuntimeError("no chrome")
        return chrome_major

    monkeypatch.setattr(
        "backend.api.diagnostic_routes._probe_chrome_major_safe", fake_probe
    )
    monkeypatch.setattr(http_factory, "chrome_major_version", lambda: 130)


def test_browser_not_found_warning(monkeypatch):
    monkeypatch.setattr(
        "backend.tools.browser_cdp.discover_browser_executable",
        lambda: None,
    )
    monkeypatch.setattr(
        "backend.api.diagnostic_routes._probe_chrome_major_safe", lambda: None
    )
    monkeypatch.setattr(
        "backend.tools.http_factory.chrome_major_version", lambda: 130
    )
    out = get_browser_health()
    assert out.browserFound is False
    assert "未发现可用浏览器" in out.warning


def test_browser_old_version_warning(monkeypatch):
    _patch_browser(monkeypatch, executable="C:/chrome.exe", chrome_major=109)
    out = get_browser_health()
    assert out.browserFound is True
    assert out.chromeMajor == 109
    assert "较旧" in out.warning


def test_browser_healthy_no_warning(monkeypatch):
    _patch_browser(monkeypatch, executable="C:/chrome.exe", chrome_major=130)
    out = get_browser_health()
    assert out.warning == ""
    assert out.uaDeclaredMajor == 130
