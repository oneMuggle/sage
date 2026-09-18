"""浏览器诊断路由测试（Phase D6）。"""

from __future__ import annotations

from unittest.mock import patch

import httpx


async def test_browser_check_endpoint(client: httpx.AsyncClient):
    """GET /api/v1/diagnostic/browser-check 返回诊断结果。"""
    mock_result = {
        "platform": "linux",
        "checks": [
            {"id": "executable_chrome", "status": "pass", "detail": "found", "fix_hint": None},
        ],
        "recommended_browser": "chrome",
        "errors": [],
    }
    with patch(
        "backend.tools.browser_diagnostics.run_all_checks",
        return_value=mock_result,
    ):
        response = await client.get("/api/v1/diagnostic/browser-check")
    assert response.status_code == 200
    data = response.json()
    assert data["platform"] == "linux"
    assert data["recommended_browser"] == "chrome"
    assert len(data["checks"]) == 1
    assert data["checks"][0]["id"] == "executable_chrome"


async def test_browser_check_endpoint_errors(client: httpx.AsyncClient):
    """有错误时 errors 列表非空。"""
    mock_result = {
        "platform": "win32",
        "checks": [],
        "recommended_browser": "none",
        "errors": ["some error"],
    }
    with patch(
        "backend.tools.browser_diagnostics.run_all_checks",
        return_value=mock_result,
    ):
        response = await client.get("/api/v1/diagnostic/browser-check")
    assert response.status_code == 200
    data = response.json()
    assert data["errors"] == ["some error"]
