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


# ==================== Phase 4: 项目信任管理 ====================


@pytest.mark.asyncio()
async def test_project_status_rejects_relative_path(client):
    resp = await client.get("/api/v1/hooks/project/status", params={"workspace": "relative/dir"})
    assert resp.status_code == 400


@pytest.mark.asyncio()
async def test_project_status_rejects_missing_dir(client, tmp_path):
    missing = tmp_path / "nope"
    resp = await client.get("/api/v1/hooks/project/status", params={"workspace": str(missing)})
    assert resp.status_code == 400


@pytest.mark.asyncio()
async def test_project_status_defaults_to_untrusted(client, tmp_path):
    resp = await client.get("/api/v1/hooks/project/status", params={"workspace": str(tmp_path)})
    assert resp.status_code == 200
    data = resp.json()
    assert data["trusted"] is False
    assert data["config_exists"] is False
    assert data["hook_count"] == 0


@pytest.mark.asyncio()
async def test_project_status_detects_config_file(client, tmp_path):
    config_dir = tmp_path / ".sage"
    config_dir.mkdir()
    (config_dir / "hooks.json").write_text(
        '{"version": 1, "hooks": []}', encoding="utf-8"
    )
    resp = await client.get("/api/v1/hooks/project/status", params={"workspace": str(tmp_path)})
    assert resp.status_code == 200
    assert resp.json()["config_exists"] is True


@pytest.mark.asyncio()
async def test_project_trust_then_status_reflects_it(client, tmp_path):
    trust_resp = await client.post(
        "/api/v1/hooks/project/trust", json={"workspace": str(tmp_path)}
    )
    assert trust_resp.status_code == 200
    assert trust_resp.json()["trusted"] is True

    status = await client.get(
        "/api/v1/hooks/project/status", params={"workspace": str(tmp_path)}
    )
    assert status.json()["trusted"] is True


@pytest.mark.asyncio()
async def test_project_untrust_reverts(client, tmp_path):
    await client.post("/api/v1/hooks/project/trust", json={"workspace": str(tmp_path)})
    resp = await client.post(
        "/api/v1/hooks/project/untrust", json={"workspace": str(tmp_path)}
    )
    assert resp.status_code == 200
    assert resp.json()["trusted"] is False

    status = await client.get(
        "/api/v1/hooks/project/status", params={"workspace": str(tmp_path)}
    )
    assert status.json()["trusted"] is False


@pytest.mark.asyncio()
async def test_project_trust_rejects_relative_path(client):
    resp = await client.post("/api/v1/hooks/project/trust", json={"workspace": "relative"})
    assert resp.status_code == 400


@pytest.mark.asyncio()
async def test_trusted_workspace_reports_hook_count(client, tmp_path):
    """信任后, status 应报告实际生效的钩子条数。"""
    config_dir = tmp_path / ".sage"
    config_dir.mkdir()
    (config_dir / "hooks.json").write_text(
        '{"version": 1, "hooks": ['
        '{"event": "pre_tool_use", "matcher": "bash", "command": "ruff"},'
        '{"event": "post_tool_use", "matcher": "*", "command": "echo done"}'
        "]}",
        encoding="utf-8",
    )
    await client.post("/api/v1/hooks/project/trust", json={"workspace": str(tmp_path)})

    status = await client.get(
        "/api/v1/hooks/project/status", params={"workspace": str(tmp_path)}
    )
    assert status.json()["hook_count"] == 2
