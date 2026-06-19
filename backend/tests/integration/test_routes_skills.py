"""
Skills 路由集成测试 — 覆盖 PR-7 的 3 个端点:

- ``GET    /api/v1/skills``               列出所有 builtin skills
- ``POST   /api/v1/skills/{name}/toggle`` 启用/禁用 (200 / 404 / 422)
- ``POST   /api/v1/skills/{name}/execute`` 执行技能 (200 success/failure, 404)

设计取舍
--------

- skills adapter 路由层模块级 singleton, 跨测试状态会泄漏;
  用 ``reset_skill_adapter`` fixture 隔离。
- builtin skills 大多依赖 ``context.tools['web_search']`` 等,
  路由层 ``execute`` 传 ``context={}``, 大多数 builtin 会返回
  ``success=False, error="搜索工具不可用"`` 等, **不视为路由层 bug** —
  端到端跑通需在 ChatService 注入 tools, 留作未来 PR。
- ``list_skills`` 默认全 enabled, ``toggle`` 后 ``list_skills`` 反映新值。
"""

import pytest

pytestmark = pytest.mark.integration

PREFIX = "/api/v1"


# ========== list_skills ==========


@pytest.mark.asyncio()
async def test_list_skills_returns_4_builtins(client, reset_skill_adapter):
    """GET /skills 返回 4 个 builtin (search / writer / coder / travel), 默认全 enabled."""
    resp = await client.get(f"{PREFIX}/skills")
    assert resp.status_code == 200
    body = resp.json()
    assert isinstance(body, list)
    names = {s["name"] for s in body}
    assert names == {"search", "writer", "coder", "travel"}
    for s in body:
        assert s["enabled"] is True
        assert s["usage_count"] == 0
        # 字段完整性
        for field in ("name", "description", "triggers", "parameters", "examples"):
            assert field in s


# ========== toggle_skill ==========


@pytest.mark.asyncio()
async def test_toggle_skill_disable_persists_in_list(client, reset_skill_adapter):
    """POST /toggle 关闭 search → list_skills 反映 enabled=false."""
    off = await client.post(f"{PREFIX}/skills/search/toggle", json={"enabled": False})
    assert off.status_code == 200
    assert off.json()["enabled"] is False
    assert off.json()["name"] == "search"

    listed = await client.get(f"{PREFIX}/skills")
    search = next(s for s in listed.json() if s["name"] == "search")
    assert search["enabled"] is False


@pytest.mark.asyncio()
async def test_toggle_skill_enable_after_disable(client, reset_skill_adapter):
    """先关再开, 状态恢复."""
    await client.post(f"{PREFIX}/skills/coder/toggle", json={"enabled": False})
    on = await client.post(f"{PREFIX}/skills/coder/toggle", json={"enabled": True})
    assert on.status_code == 200
    assert on.json()["enabled"] is True


@pytest.mark.asyncio()
async def test_toggle_skill_not_found_returns_404(client, reset_skill_adapter):
    """不存在的 skill name → 404 + 结构化 detail."""
    resp = await client.post(
        f"{PREFIX}/skills/nonexistent-skill/toggle",
        json={"enabled": False},
    )
    assert resp.status_code == 404
    detail = resp.json()["detail"]
    assert detail["type"] == "skill_not_found"
    assert "nonexistent-skill" in detail["message"]


@pytest.mark.asyncio()
async def test_toggle_skill_missing_enabled_returns_422(client, reset_skill_adapter):
    """缺 enabled 字段 → 422 (FastAPI 自动校验)."""
    resp = await client.post(f"{PREFIX}/skills/search/toggle", json={})
    assert resp.status_code == 422


@pytest.mark.asyncio()
async def test_toggle_skill_wrong_type_returns_422(client, reset_skill_adapter):
    """enabled 类型错 (字符串) → 422."""
    resp = await client.post(f"{PREFIX}/skills/search/toggle", json={"enabled": "yes"})
    assert resp.status_code == 422


# ========== execute_skill ==========


@pytest.mark.asyncio()
async def test_execute_skill_not_found_returns_404(client, reset_skill_adapter):
    """不存在的 skill name → 404."""
    resp = await client.post(
        f"{PREFIX}/skills/nonexistent/execute",
        json={"action": "", "args": {}},
    )
    assert resp.status_code == 404
    assert resp.json()["detail"]["type"] == "skill_not_found"


@pytest.mark.asyncio()
async def test_execute_disabled_skill_returns_200_with_error(client, reset_skill_adapter):
    """disabled skill → 200 + success=False, 不抛 4xx."""
    await client.post(f"{PREFIX}/skills/search/toggle", json={"enabled": False})
    resp = await client.post(
        f"{PREFIX}/skills/search/execute",
        json={"action": "", "args": {"query": "test"}},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is False
    assert "disabled" in body["error"]


@pytest.mark.asyncio()
async def test_execute_enabled_skill_with_no_tools_returns_200_failure(client, reset_skill_adapter):
    """enabled 但 builtin 缺工具 (context={}) → 200 + success=False。

    这是 builtin 的设计行为 (search 需要 web_search tool, 路由层不注入),
    端到端跑通需在 ChatService 注入 context.tools。验证 success 字段透传
    前端能拿到结构化 error, 不视为路由 bug。
    """
    resp = await client.post(
        f"{PREFIX}/skills/search/execute",
        json={"action": "", "args": {"query": "test"}},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is False
    # builtin 返回的 error 是中文, 路由层透传
    assert body["error"]  # 任何非空错误描述


@pytest.mark.asyncio()
async def test_execute_skill_default_args_and_action(client, reset_skill_adapter):
    """execute 不传 action / args 也能走通 (defaults: action='', args={})."""
    resp = await client.post(f"{PREFIX}/skills/search/execute", json={})
    assert resp.status_code == 200
    body = resp.json()
    # 缺 web_search 工具, 仍 200 + failure
    assert body["success"] is False
    assert body["error"]


@pytest.mark.asyncio()
async def test_execute_skill_does_not_bump_usage_on_failure(client, reset_skill_adapter):
    """execute 失败时不累计 usage_count, 成功时累计 (本测试用例里只验证失败不累计)."""
    # search 默认 enabled, 但缺 web_search 工具 → 失败
    await client.post(
        f"{PREFIX}/skills/search/execute",
        json={"action": "", "args": {"query": "test"}},
    )
    listed = await client.get(f"{PREFIX}/skills")
    search = next(s for s in listed.json() if s["name"] == "search")
    assert search["usage_count"] == 0  # 失败不累计


@pytest.mark.asyncio()
async def test_execute_skill_args_wrong_type_returns_422(client, reset_skill_adapter):
    """args 类型错 (字符串而非 dict) → 422 (Pydantic 自动)."""
    resp = await client.post(
        f"{PREFIX}/skills/search/execute",
        json={"action": "", "args": "not-a-dict"},
    )
    assert resp.status_code == 422


# ========== M10: slash command 端点 ==========


@pytest.mark.asyncio()
async def test_slash_command_returns_skill_body(client, reset_skill_adapter):
    """POST /skills/command 触发 user_invocable 技能 → 返回 SKILL.md body。"""
    from pathlib import Path

    from backend.skills.skill_md.skill import DispatchMode, SkillMdDocument, SkillMdSkill

    # 注入一个 user_invocable 的 SKILL.md 技能
    adapter = _get_skill_adapter_singleton()
    skill_doc = SkillMdDocument(
        name="my-review",
        description="Review",
        body="You are a careful reviewer.",
        base_dir=Path("/tmp/skills/my-review"),
        dispatch=DispatchMode(
            user_invocable=True,
            user_invocable_name="/review",
        ),
    )
    adapter._registry.register(SkillMdSkill(skill_doc, base_dir=skill_doc.base_dir))
    # 重建 slash registry (绕开 reload)
    from backend.skills.skill_md.slash_registry import SlashCommandRegistry

    adapter._slash_registry = SlashCommandRegistry.from_registry(adapter._registry)

    resp = await client.post(
        f"{PREFIX}/skills/command",
        json={"command": "/review", "args": []},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    assert "reviewer" in body["content"]


@pytest.mark.asyncio()
async def test_slash_command_unknown_returns_404(client, reset_skill_adapter):
    """未注册的 command → 404 + command_not_found。"""
    resp = await client.post(
        f"{PREFIX}/skills/command",
        json={"command": "/unknown", "args": []},
    )
    assert resp.status_code == 404
    detail = resp.json()["detail"]
    assert detail["type"] == "command_not_found"


@pytest.mark.asyncio()
async def test_slash_command_missing_command_field_returns_422(client, reset_skill_adapter):
    """缺 command 字段 → 422 (Pydantic 自动)."""
    resp = await client.post(
        f"{PREFIX}/skills/command",
        json={"args": []},
    )
    assert resp.status_code == 422


@pytest.mark.asyncio()
async def test_list_slash_commands_returns_registered(client, reset_skill_adapter):
    """GET /skills/commands → 返回已注册的命令列表。"""
    from pathlib import Path

    from backend.skills.skill_md.skill import DispatchMode, SkillMdDocument, SkillMdSkill
    from backend.skills.skill_md.slash_registry import SlashCommandRegistry

    adapter = _get_skill_adapter_singleton()
    for cmd_name, slash_name in [("review", "/review"), ("commit", "/commit")]:
        doc = SkillMdDocument(
            name=cmd_name,
            description=cmd_name,
            body="body",
            base_dir=Path(f"/tmp/skills/{cmd_name}"),
            dispatch=DispatchMode(user_invocable=True, user_invocable_name=slash_name),
        )
        adapter._registry.register(SkillMdSkill(doc, base_dir=doc.base_dir))
    adapter._slash_registry = SlashCommandRegistry.from_registry(adapter._registry)

    resp = await client.get(f"{PREFIX}/skills/commands")
    assert resp.status_code == 200
    body = resp.json()
    assert set(body["commands"]) >= {"/review", "/commit"}


def _get_skill_adapter_singleton():
    """获取路由层持有的 InprocSkillAdapter 单例 (测试辅助).

    调用 ``_get_skill_adapter()`` 触发 lazy init — 直接读模块级变量
    在 ``reset_skill_adapter`` fixture 后会是 None。
    """
    import backend.api.legacy_routes as routes_module

    return routes_module._get_skill_adapter()
