# ruff: noqa: UP006, UP007 — release/win7 Python 3.8 兼容
"""M4-T3 — 版本 versions/diff/rollback 路由测试。

使用真实临时库（conftest autouse ``setup_test_db``）与最小 FastAPI app，
避免主 app 的鉴权中间件干扰。覆盖：
- 创建专家自动生成 v1 快照
- PATCH 人设字段：pre + post 快照，diff 可见
- GET /versions /versions/{v} /versions/diff
- POST /rollback 恢复快照 + version+1 + reason='rollback'
- DELETE 级联清理版本快照与模拟评测记录
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api.legacy_agent_routes import router as agent_router
from backend.data.agent_repo import AgentRepository
from backend.data.agent_version_repo import AgentVersionRepository
from backend.data.database import get_database

pytestmark = pytest.mark.unit


@pytest.fixture()
def client() -> TestClient:
    app = FastAPI()
    app.include_router(agent_router)
    return TestClient(app)


def _create(client: TestClient, agent_id: str = "spec-a") -> dict:
    resp = client.post(
        "/agents",
        json={
            "id": agent_id,
            "name": "Spec A",
            "role": "specialist",
            "system_prompt": "初始提示词",
            "skills": ["writing"],
        },
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


# ---------------------------------------------------------------------------
# 创建即快照
# ---------------------------------------------------------------------------


def test_create_agent_writes_v1_snapshot(client: TestClient) -> None:
    created = _create(client)
    assert created["version"] == 1
    versions = AgentVersionRepository().list_versions("spec-a")
    assert len(versions) == 1
    assert versions[0]["version"] == 1
    assert versions[0]["reason"] == "create"


# ---------------------------------------------------------------------------
# PATCH 触发 pre/post 快照
# ---------------------------------------------------------------------------


def test_patch_writes_snapshots_and_list_route(client: TestClient) -> None:
    _create(client)
    resp = client.patch("/agents/spec-a", json={"system_prompt": "第二版提示词"})
    assert resp.status_code == 200, resp.text
    assert resp.json()["version"] == 2

    list_resp = client.get("/agents/spec-a/versions")
    assert list_resp.status_code == 200
    versions = list_resp.json()
    assert [v["version"] for v in versions] == [2, 1]
    # v1 来自 create；v2 来自 PATCH post 快照
    assert versions[0]["reason"] == "update"
    assert versions[1]["reason"] == "create"


def test_get_version_returns_full_profile(client: TestClient) -> None:
    _create(client)
    client.patch("/agents/spec-a", json={"system_prompt": "第二版提示词"})

    resp = client.get("/agents/spec-a/versions/1")
    assert resp.status_code == 200
    snap = resp.json()
    assert snap["id"] == "spec-a"
    assert snap["system_prompt"] == "初始提示词"
    assert snap["version"] == 1


def test_get_version_404_cases(client: TestClient) -> None:
    resp = client.get("/agents/ghost/versions/1")
    assert resp.status_code == 404
    assert resp.json()["detail"]["type"] == "agent_not_found"

    _create(client)
    resp = client.get("/agents/spec-a/versions/99")
    assert resp.status_code == 404
    assert resp.json()["detail"]["type"] == "version_not_found"


def test_versions_list_404_for_missing_agent(client: TestClient) -> None:
    resp = client.get("/agents/ghost/versions")
    assert resp.status_code == 404
    assert resp.json()["detail"]["type"] == "agent_not_found"


# ---------------------------------------------------------------------------
# diff
# ---------------------------------------------------------------------------


def test_diff_route_between_versions(client: TestClient) -> None:
    _create(client)
    client.patch("/agents/spec-a", json={"system_prompt": "第二版提示词"})

    resp = client.get("/agents/spec-a/versions/diff", params={"from": 1, "to": 2})
    assert resp.status_code == 200, resp.text
    changes = resp.json()
    fields = {c["field"] for c in changes}
    assert "system_prompt" in fields
    prompt = next(c for c in changes if c["field"] == "system_prompt")
    assert prompt["before"] == "初始提示词"
    assert prompt["after"] == "第二版提示词"
    # version 字段也在 diff 中（1→2）
    assert "version" in fields


def test_diff_route_404_for_missing_version(client: TestClient) -> None:
    _create(client)
    resp = client.get("/agents/spec-a/versions/diff", params={"from": 1, "to": 99})
    assert resp.status_code == 404
    assert resp.json()["detail"]["type"] == "version_not_found"


def test_diff_route_404_for_missing_agent(client: TestClient) -> None:
    resp = client.get("/agents/ghost/versions/diff", params={"from": 1, "to": 2})
    assert resp.status_code == 404
    assert resp.json()["detail"]["type"] == "agent_not_found"


# ---------------------------------------------------------------------------
# rollback
# ---------------------------------------------------------------------------


def test_rollback_restores_snapshot_and_bumps_version(client: TestClient) -> None:
    _create(client)
    client.patch("/agents/spec-a", json={"system_prompt": "第二版提示词"})

    resp = client.post("/agents/spec-a/rollback", json={"version": 1})
    assert resp.status_code == 200, resp.text
    new_profile = resp.json()
    assert new_profile["system_prompt"] == "初始提示词"
    # version = current(2) + 1 = 3（历史单调递增，不回落到 1）
    assert new_profile["version"] == 3

    versions = AgentVersionRepository().list_versions("spec-a")
    assert versions[0]["version"] == 3
    assert versions[0]["reason"] == "rollback"


def test_rollback_404_cases(client: TestClient) -> None:
    resp = client.post("/agents/ghost/rollback", json={"version": 1})
    assert resp.status_code == 404
    assert resp.json()["detail"]["type"] == "agent_not_found"

    _create(client)
    resp = client.post("/agents/spec-a/rollback", json={"version": 99})
    assert resp.status_code == 404
    assert resp.json()["detail"]["type"] == "version_not_found"


def test_rollback_rejects_invalid_body(client: TestClient) -> None:
    _create(client)
    resp = client.post("/agents/spec-a/rollback", json={"version": 0})
    assert resp.status_code == 422  # ge=1


# ---------------------------------------------------------------------------
# 删除级联
# ---------------------------------------------------------------------------


def test_delete_cascades_versions_and_eval_runs(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """删除专家时同时清理版本快照 + agent_eval_runs 记录。"""
    _create(client)
    client.patch("/agents/spec-a", json={"system_prompt": "第二版提示词"})
    assert len(AgentVersionRepository().list_versions("spec-a")) >= 2

    # 手工插入一条评测记录（M4-T4 表，先验证级联）
    conn = get_database().get_connection()
    conn.execute(
        "INSERT INTO agent_eval_runs (id, agent_id, template_id, created_at, report) "
        "VALUES (?, ?, ?, ?, ?)",
        ("run-1", "spec-a", "writing", 1730800000000, "{}"),
    )
    conn.commit()

    # 记忆级联依赖全局管理器；此处隔离掉避免真实 IO
    class _NoopMemory:
        def purge_agent_memories(self, agent_id):
            return {"episodic": 0, "semantic": 0, "vector": 0}

    monkeypatch.setattr("backend.memory.get_memory_manager", lambda: _NoopMemory())

    resp = client.delete("/agents/spec-a")
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"ok": True, "id": "spec-a"}

    assert AgentRepository().get("spec-a") is None
    assert AgentVersionRepository().list_versions("spec-a") == []
    row = conn.execute(
        "SELECT COUNT(*) FROM agent_eval_runs WHERE agent_id = ?", ("spec-a",)
    ).fetchone()
    assert int(row[0]) == 0
