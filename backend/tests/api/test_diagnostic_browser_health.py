"""Round 14 浏览器健康自检 — /api/v1/diagnostic/browser 契约测试。

浏览器发现 / 版本探测全部 monkeypatch —— 不依赖本机真实浏览器安装。
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.unit  # ASGITransport 直连 app, 属快测


def _patch_browser(monkeypatch, executable, chrome_major):
    monkeypatch.setattr(
        "backend.tools.browser_cdp.discover_browser_executable",
        lambda: executable,
    )
    monkeypatch.setattr(
        "backend.tools.http_factory._probe_chrome_major",
        lambda: chrome_major,
    )
    monkeypatch.setattr(
        "backend.tools.http_factory.chrome_major_version",
        lambda refresh=False: chrome_major or 126,
    )


async def test_browser_health_found_recent(client, monkeypatch):
    _patch_browser(monkeypatch, "C:/chrome/chrome.exe", 138)
    resp = await client.get("/api/v1/diagnostic/browser")
    assert resp.status_code == 200
    data = resp.json()
    assert data["browserFound"] is True
    assert data["chromeMajor"] == 138
    assert data["uaDeclaredMajor"] == 138
    assert data["warning"] == ""


async def test_browser_health_old_version_warns(client, monkeypatch):
    """win7 Chrome 109 场景：有浏览器但版本过旧 → 警告带升级指引。"""
    _patch_browser(monkeypatch, "C:/chrome/chrome.exe", 109)
    resp = await client.get("/api/v1/diagnostic/browser")
    assert resp.status_code == 200
    data = resp.json()
    assert data["browserFound"] is True
    assert data["chromeMajor"] == 109
    assert "较旧" in data["warning"]
    assert "SAGE_BROWSER_PATH" in data["warning"]


async def test_browser_health_not_found(client, monkeypatch):
    _patch_browser(monkeypatch, None, None)
    resp = await client.get("/api/v1/diagnostic/browser")
    assert resp.status_code == 200
    data = resp.json()
    assert data["browserFound"] is False
    assert "未发现" in data["warning"]
