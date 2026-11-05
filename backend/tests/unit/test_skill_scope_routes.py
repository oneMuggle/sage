# mypy: disable-error-code="no-untyped-def,attr-defined"
"""M1-B — ``/skills*`` REST 入口的专家技能允许集（spec §5.1）测试。

验收标准（spec §9）::

    同一全局技能库下，写作专家看不到编码技能；非法技能名无法执行。

覆盖:

- ``GET /skills`` / ``GET /skills/commands`` — 列表入口过滤（fail-closed）
- ``POST /skills/{name}/execute`` — 越权 → 403 ``skill_not_allowed``
- ``POST /skills/command`` — 越权 → 404 ``command_not_found``（不泄漏存在性）
- ``session_id`` / ``agent_id`` 两种解析来源
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api.legacy_skills_routes import router
from backend.domain.skill_scope import resolve_skill_allowlist

pytestmark = pytest.mark.unit

ALL_NAMES = ["write-report", "code-review"]
WRITER_ROW = {"id": "writer", "enabled": True, "skills": ["write-*"]}


class _RecordingAdapter:
    """InprocSkillAdapter 的受控替身：记录传入的 allowed。"""

    def __init__(self) -> None:
        self.list_calls: list = []
        self.execute_calls: list = []
        self.command_calls: list = []

    def resolve_allowlist(self, patterns):
        return resolve_skill_allowlist(patterns, ALL_NAMES)

    def _visible(self, allowed):
        return [n for n in ALL_NAMES if allowed is None or n in allowed]

    def is_enabled(self, name: str) -> bool:
        return True

    def usage_count(self, name: str) -> int:
        return 0

    def list_skills_extended(self, allowed=None):
        self.list_calls.append(allowed)
        return [{"name": n} for n in self._visible(allowed)]

    def has_skill(self, name: str) -> bool:
        return name in ALL_NAMES

    async def execute(self, name, action, args, allowed=None):
        self.execute_calls.append((name, allowed))
        from backend.domain.skill import SkillResult

        return SkillResult(success=True, content=f"ran:{name}")

    def list_slash_commands(self, allowed=None):
        return [f"/{n}" for n in self._visible(allowed)]

    async def execute_command(self, command, args=(), allowed=None):
        from backend.domain.skill import SkillResult

        name = command.lstrip("/")
        allowed_name = allowed is None or name in allowed
        if not allowed_name or name not in ALL_NAMES:
            raise LookupError(f"slash command unavailable: {command!r}")
        self.command_calls.append((name, allowed))
        return SkillResult(success=True, content=f"cmd:{name}")


class _FakeAgentRepository:
    def get(self, agent_id):
        return WRITER_ROW if agent_id == "writer" else None


class _FakeLifecycleStore:
    def get_pinned_names(self):
        return set()


@pytest.fixture()
def adapter():
    return _RecordingAdapter()


@pytest.fixture()
def client(monkeypatch, adapter):
    import backend.api.legacy_skills_routes as routes
    import backend.chat.specialist_binding as binding
    from backend.data import agent_repo
    from backend.skills import lifecycle

    monkeypatch.setattr(routes, "_get_skill_adapter", lambda: adapter)
    monkeypatch.setattr(agent_repo, "AgentRepository", _FakeAgentRepository)
    monkeypatch.setattr(lifecycle, "get_lifecycle_store", lambda: _FakeLifecycleStore())

    def _fake_resolve(session_id, agent_id):
        if agent_id:
            return agent_id
        return "writer" if session_id == "s-writer" else binding.PRIMARY_AGENT_ID

    monkeypatch.setattr(binding, "resolve_effective_agent_id", _fake_resolve)
    monkeypatch.setattr(binding, "resolve_effective_agent_id_strict", _fake_resolve)

    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


class TestListEntrypoints:
    def test_list_restricted_by_agent_id(self, client, adapter):
        """写作专家的清单里看不到编码技能。"""
        resp = client.get("/skills", params={"agent_id": "writer"})
        assert resp.status_code == 200
        assert [s["name"] for s in resp.json()] == ["write-report"]
        assert adapter.list_calls[-1] == {"write-report"}

    def test_list_restricted_by_session_binding(self, client):
        resp = client.get("/skills", params={"session_id": "s-writer"})
        assert resp.status_code == 200
        assert [s["name"] for s in resp.json()] == ["write-report"]

    def test_list_unrestricted_without_params(self, client, adapter):
        resp = client.get("/skills")
        assert resp.status_code == 200
        assert {s["name"] for s in resp.json()} == set(ALL_NAMES)
        assert adapter.list_calls[-1] is None

    def test_list_unrestricted_for_primary(self, client):
        resp = client.get("/skills", params={"agent_id": "primary"})
        assert resp.status_code == 200
        assert {s["name"] for s in resp.json()} == set(ALL_NAMES)

    def test_slash_commands_restricted(self, client):
        resp = client.get("/skills/commands", params={"agent_id": "writer"})
        assert resp.status_code == 200
        assert resp.json() == {"commands": ["/write-report"]}

    def test_slash_commands_unrestricted_without_params(self, client):
        resp = client.get("/skills/commands")
        assert resp.status_code == 200
        assert set(resp.json()["commands"]) == {"/write-report", "/code-review"}


class TestExecuteEntrypoints:
    def test_execute_disallowed_returns_403(self, client, adapter):
        """非法技能名无法执行：越权 → 403，且不触达 adapter.execute。"""
        resp = client.post(
            "/skills/code-review/execute",
            json={"action": "", "args": {}},
            params={"agent_id": "writer"},
        )
        assert resp.status_code == 403
        assert resp.json()["detail"]["type"] == "skill_not_allowed"
        assert adapter.execute_calls == []

    def test_execute_allowed_passes_allowlist_to_adapter(self, client, adapter):
        resp = client.post(
            "/skills/write-report/execute",
            json={"action": "", "args": {}},
            params={"agent_id": "writer"},
        )
        assert resp.status_code == 200
        assert resp.json()["success"] is True
        assert adapter.execute_calls[-1] == ("write-report", {"write-report"})

    def test_execute_unrestricted_without_params(self, client, adapter):
        resp = client.post(
            "/skills/code-review/execute",
            json={"action": "", "args": {}},
        )
        assert resp.status_code == 200
        assert adapter.execute_calls[-1] == ("code-review", None)

    def test_slash_command_disallowed_returns_404(self, client):
        """越权 slash 命令与未知命令同构 → 404，不泄漏存在性。"""
        resp = client.post(
            "/skills/command",
            json={"command": "code-review", "args": []},
            params={"agent_id": "writer"},
        )
        assert resp.status_code == 404
        assert resp.json()["detail"]["type"] == "command_not_found"

    def test_slash_command_allowed_runs(self, client, adapter):
        resp = client.post(
            "/skills/command",
            json={"command": "write-report", "args": []},
            params={"agent_id": "writer"},
        )
        assert resp.status_code == 200
        assert resp.json()["success"] is True
        assert adapter.command_calls[-1] == ("write-report", {"write-report"})

    def test_execute_fails_closed_when_binding_unresolvable(
        self, monkeypatch, adapter
    ):
        """专家归属解析异常 → 403（fail-closed，安全审查 HIGH）。"""
        import backend.api.legacy_skills_routes as routes
        import backend.chat.specialist_binding as binding
        from backend.skills import lifecycle

        def _boom(_session_id, _agent_id):
            raise RuntimeError("db down")

        monkeypatch.setattr(routes, "_get_skill_adapter", lambda: adapter)
        monkeypatch.setattr(
            lifecycle, "get_lifecycle_store", lambda: _FakeLifecycleStore()
        )
        monkeypatch.setattr(
            binding, "resolve_effective_agent_id_strict", _boom
        )
        app = FastAPI()
        app.include_router(router)
        client = TestClient(app)

        resp = client.post(
            "/skills/write-report/execute",
            json={"action": "", "args": {}},
            params={"session_id": "s1"},
        )

        assert resp.status_code == 403
        assert resp.json()["detail"]["type"] == "skill_not_allowed"
        assert adapter.execute_calls == []
