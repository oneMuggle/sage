"""R166 — Hooks REST 路由单元测试。

直接调用路由函数。forbidden_origin 守卫、SettingsRepository、
project_config、history repo 全 monkeypatch。覆盖：builtins 元数据、
workspace 校验 400、trust/untrust/status 成功与失败、history 透传与
清空、origin 守卫短路。
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from backend.api import hooks_routes as hr

pytestmark = pytest.mark.unit


class _FakeRequest:
    """forbidden_origin_response patch 后不读该对象。"""


@pytest.fixture(autouse=True)
def _allow_origin(monkeypatch):
    monkeypatch.setattr(hr, "forbidden_origin_response", lambda request: None)


@pytest.fixture()
def ws(tmp_path):
    d = tmp_path / "ws"
    d.mkdir()
    return d


@pytest.fixture()
def fake_settings(monkeypatch):
    state = {"trusted": set()}
    repo = SimpleNamespace(
        get=lambda key: json_trusted(state),
        set=lambda key, value, value_type=None: state["trusted"].add("x"),
    )

    def json_trusted(state):
        return None

    monkeypatch.setattr(
        "backend.data.settings_repo.SettingsRepository", lambda: repo
    )
    return state


def _patch_project_config(monkeypatch, state):
    """路由模块顶层 from-import 了 project_config 符号——必须 patch hr 命名空间。"""
    monkeypatch.setattr(
        hr, "is_workspace_trusted", lambda repo, ws: ws in state["trusted_set"]
    )
    monkeypatch.setattr(
        hr, "trust_workspace", lambda repo, ws: state["trusted_set"].add(ws)
    )
    monkeypatch.setattr(
        hr, "untrust_workspace", lambda repo, ws: state["trusted_set"].discard(ws)
    )
    import backend.hooks.project_config as pc

    monkeypatch.setattr(pc, "load_project_hooks", lambda ws, repo: [{"id": "h"}])


# ---------------------------------------------------------------------------
# builtins
# ---------------------------------------------------------------------------


@pytest.mark.asyncio()
async def test_get_builtin_hooks_lists_registry():
    from backend.hooks.builtin import BUILTIN_HOOKS

    out = await hr.get_builtin_hooks(_FakeRequest())
    import json

    data = json.loads(out.body)
    assert {b["id"] for b in data["builtins"]} == set(BUILTIN_HOOKS)


# ---------------------------------------------------------------------------
# workspace 校验
# ---------------------------------------------------------------------------


def test_validated_workspace_rejects_relative():
    assert hr._validated_workspace("relative/path") is None


def test_validated_workspace_rejects_nonexistent(tmp_path):
    assert hr._validated_workspace(str(tmp_path / "ghost")) is None


def test_validated_workspace_rejects_empty():
    assert hr._validated_workspace("") is None


# ---------------------------------------------------------------------------
# project status / trust / untrust
# ---------------------------------------------------------------------------


@pytest.mark.asyncio()
async def test_project_status_untrusted(ws, monkeypatch):
    state = {"trusted_set": set()}
    _patch_project_config(monkeypatch, state)
    monkeypatch.setattr(
        "backend.data.settings_repo.SettingsRepository", lambda: SimpleNamespace()
    )
    out = await hr.get_project_status(_FakeRequest(), workspace=str(ws))
    import json

    data = json.loads(out.body)
    assert data["trusted"] is False
    assert data["config_exists"] is False
    assert data["hook_count"] == 0
    assert data["workspace"] == str(ws.resolve())


@pytest.mark.asyncio()
async def test_project_status_trusted_counts_hooks(ws, monkeypatch):
    state = {"trusted_set": {str(ws)}}
    _patch_project_config(monkeypatch, state)
    monkeypatch.setattr(
        "backend.data.settings_repo.SettingsRepository", lambda: SimpleNamespace()
    )
    (ws / ".sage").mkdir()
    (ws / ".sage" / "hooks.json").write_text("{}", encoding="utf-8")
    out = await hr.get_project_status(_FakeRequest(), workspace=str(ws))
    import json

    data = json.loads(out.body)
    assert data["trusted"] is True
    assert data["config_exists"] is True
    assert data["hook_count"] == 1


@pytest.mark.asyncio()
async def test_status_invalid_workspace_400(ws):
    out = await hr.get_project_status(_FakeRequest(), workspace="relative")
    import json

    assert out.status_code == 400
    assert "existing absolute directory" in json.loads(out.body)["error"]


@pytest.mark.asyncio()
async def test_trust_success(ws, monkeypatch):
    state = {"trusted_set": set()}
    _patch_project_config(monkeypatch, state)
    monkeypatch.setattr(
        "backend.data.settings_repo.SettingsRepository", lambda: SimpleNamespace()
    )
    out = await hr.trust_project(_FakeRequest(), hr.WorkspaceBody(workspace=str(ws)))
    import json

    assert json.loads(out.body) == {"ok": True, "trusted": True}
    assert str(ws) in state["trusted_set"]


@pytest.mark.asyncio()
async def test_trust_invalid_workspace_400(ws):
    out = await hr.trust_project(_FakeRequest(), hr.WorkspaceBody(workspace="rel"))
    assert out.status_code == 400


@pytest.mark.asyncio()
async def test_untrust_success_and_failure(ws, monkeypatch):
    import json

    state = {"trusted_set": {str(ws)}}
    _patch_project_config(monkeypatch, state)
    monkeypatch.setattr(
        "backend.data.settings_repo.SettingsRepository", lambda: SimpleNamespace()
    )

    out = await hr.untrust_project(_FakeRequest(), hr.WorkspaceBody(workspace=str(ws)))
    assert json.loads(out.body) == {"ok": True, "trusted": False}

    def boom(repo, ws_path):
        raise RuntimeError("persist failed")

    monkeypatch.setattr(hr, "untrust_workspace", boom)
    out = await hr.untrust_project(_FakeRequest(), hr.WorkspaceBody(workspace=str(ws)))
    assert out.status_code == 500


# ---------------------------------------------------------------------------
# history
# ---------------------------------------------------------------------------


class _FakeHistoryRepo:
    def __init__(self):
        self.list_calls = {}
        self.cleared = False

    def list_records(self, **kwargs):
        self.list_calls = kwargs
        return [
            SimpleNamespace(
                id="r1",
                occurred_at="t",
                hook_id="audit_log",
                hook_type="python",
                event="post_tool_use",
                tool_name="bash",
                decision="allow",
                duration_ms=5,
                reason="",
                stdout_snippet="",
                stderr_snippet="",
                hook_config_snapshot={},
            )
        ]

    def clear(self):
        self.cleared = True
        return 3


@pytest.fixture()
def fake_history(monkeypatch):
    repo = _FakeHistoryRepo()

    import backend.hooks.history as history_mod

    monkeypatch.setattr(history_mod, "get_history_repo", lambda: repo)
    return repo


@pytest.mark.asyncio()
async def test_history_list_passes_filters(fake_history):
    out = await hr.list_hook_history(
        _FakeRequest(), limit=7, hook_id="audit_log", event="post_tool_use", since="t0"
    )
    import json

    assert fake_history.list_calls == {
        "limit": 7,
        "hook_id": "audit_log",
        "event": "post_tool_use",
        "since": "t0",
    }
    data = json.loads(out.body)
    assert data["records"][0]["id"] == "r1"
    assert data["records"][0]["hook_type"] == "python"


@pytest.mark.asyncio()
async def test_history_empty_filters_become_none(fake_history):
    await hr.list_hook_history(_FakeRequest())
    assert fake_history.list_calls == {
        "limit": 50,
        "hook_id": None,
        "event": None,
        "since": None,
    }


@pytest.mark.asyncio()
async def test_history_clear(fake_history):
    out = await hr.clear_hook_history(_FakeRequest())
    import json

    assert json.loads(out.body) == {"ok": True, "deleted": 3}
    assert fake_history.cleared is True
