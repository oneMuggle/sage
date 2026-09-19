"""GET /api/v1/hooks/builtins 集成测试 (Phase 1)。

验证设置页"推荐 Hook"数据源: 端点返回注册表中的全部内置钩子, 且每个
条目的 matcher 能与真实工具名对齐 (回归护栏 —— matcher 写错工具名会
让内置钩子永不触发)。
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.unit

REQUIRED_FIELDS = ("id", "name", "description", "event", "matcher", "handler", "default_config")

#: 后端实际注册的写文件/执行工具名 (backend/tools/*.py ToolSchema.name)
_REAL_TOOL_NAMES = ("bash", "write_file", "edit_file", "apply_patch")


@pytest.mark.asyncio()
async def test_builtins_endpoint_returns_registry(client):
    resp = await client.get("/api/v1/hooks/builtins")
    assert resp.status_code == 200
    builtins = resp.json()["builtins"]
    assert isinstance(builtins, list)
    assert len(builtins) >= 4
    ids = {b["id"] for b in builtins}
    assert {"security_guard", "sensitive_data_guard", "audit_log", "cost_alert"} <= ids


@pytest.mark.asyncio()
async def test_builtins_entries_have_required_fields(client):
    resp = await client.get("/api/v1/hooks/builtins")
    for entry in resp.json()["builtins"]:
        for field in REQUIRED_FIELDS:
            assert field in entry, f"{entry.get('id')} missing {field}"


@pytest.mark.asyncio()
async def test_builtins_matchers_target_real_tools(client):
    """每个内置钩子的 matcher 至少命中一个真实工具名。"""
    from backend.hooks.runner import matches_tool

    resp = await client.get("/api/v1/hooks/builtins")
    for entry in resp.json()["builtins"]:
        matched = [t for t in _REAL_TOOL_NAMES if matches_tool(entry["matcher"], t)]
        # audit_log / cost_alert 的 matcher 是 "*", 命中全部
        assert matched, f"{entry['id']} matcher {entry['matcher']!r} matches no real tool"


@pytest.mark.asyncio()
async def test_builtins_handlers_are_resolvable(client):
    """暴露给前端的 handler dotted-path 必须能解析 (否则内置钩子形同虚设)。"""
    from backend.hooks.runner import _resolve_handler

    resp = await client.get("/api/v1/hooks/builtins")
    for entry in resp.json()["builtins"]:
        assert _resolve_handler(entry["handler"]) is not None, (
            f"{entry['id']} handler {entry['handler']!r} not resolvable"
        )
