"""
进化系统 API 集成测试 — 覆盖 /evolution/logs (PR-C §5.1 后)。

§5.1 起 /evolution/trigger 与 /evolution/status 端点已下架
(改走 SchedulerService 内部 cron),故本文件只保留 logs 端点测试。
"""


import pytest

pytestmark = pytest.mark.integration

PREFIX = "/api/v1"


@pytest.mark.asyncio()
async def test_evolution_logs_empty(client):
    """空库上 /evolution/logs 返回空列表。"""
    resp = await client.get(f"{PREFIX}/evolution/logs")
    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.asyncio()
async def test_evolution_logs_returns_inserted(client):
    """插入 evolution_log 后 /evolution/logs 能查到。"""
    from backend.data.database import get_database

    db = get_database()
    now = int(1.7e12)
    db.get_connection().execute(
        """
        INSERT INTO evolution_log
        (id, evolution_type, description, trigger_type, status, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        ("ev-001", "memory_pruning", "pruned 10 memories", "manual", "completed", now),
    )
    db.get_connection().commit()

    resp = await client.get(f"{PREFIX}/evolution/logs")
    assert resp.status_code == 200
    logs = resp.json()
    assert len(logs) >= 1
    assert any(log["id"] == "ev-001" for log in logs)
