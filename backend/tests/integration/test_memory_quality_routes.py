"""Task 4.3 —— /memory/quality-candidates 与 /memory/batch-delete 集成测试。

覆盖:
- quality-candidates: 低分记忆入候选、高分不入、升序排序、limit 上限、
  threshold 参数生效、空库返空
- batch-delete: episodic 软删除、semantic 硬删除、id 不存在记入 failed、
  非法 memory_type 记入 failed、上限 50、空列表幂等、审计日志写入
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.integration

PREFIX = "/api/v1"


# ---------- /memory/quality-candidates ----------


@pytest.mark.asyncio()
async def test_quality_candidates_returns_low_score_items(client):
    """低 importance + 残缺内容的记忆应进入候选 (threshold=0.5)。

    注意: 刚写入的记忆 recency=1.0, 即使 importance=1 + clarity 极低,
    整体分数也在 0.4 左右 (recency 贡献 0.20)。所以用 0.5 阈值才能捕获。
    """
    # 一条高质量 (高 importance, 清晰)
    await client.post(
        f"{PREFIX}/memory/save",
        json={
            "content": "用户偏好使用 ruff 进行 Python 代码格式化",
            "memory_type": "episodic",
            "importance": 8,
        },
    )
    # 一条低质量 (低 importance, 残缺)
    await client.post(
        f"{PREFIX}/memory/save",
        json={
            "content": "嗯...",
            "memory_type": "episodic",
            "importance": 1,
        },
    )

    resp = await client.get(
        f"{PREFIX}/memory/quality-candidates", params={"threshold": 0.5}
    )
    assert resp.status_code == 200
    items = resp.json()["items"]
    # 至少低质量那条在候选里
    contents = [i["content"] for i in items]
    assert any("嗯..." in c for c in contents)


@pytest.mark.asyncio()
async def test_quality_candidates_sorted_ascending(client):
    """候选按质量分升序 (最差优先)。"""
    # 中低
    await client.post(
        f"{PREFIX}/memory/save",
        json={"content": "中低质量记忆 a", "memory_type": "episodic", "importance": 3},
    )
    # 极低
    await client.post(
        f"{PREFIX}/memory/save",
        json={"content": "嗯", "memory_type": "episodic", "importance": 1},
    )

    resp = await client.get(f"{PREFIX}/memory/quality-candidates")
    assert resp.status_code == 200
    items = resp.json()["items"]
    scores = [i["quality_score"] for i in items]
    assert scores == sorted(scores), f"候选未按升序排列: {scores}"


@pytest.mark.asyncio()
async def test_quality_candidates_threshold_parameter(client):
    """threshold 提高 → 更多候选;降低 → 更少候选。"""
    await client.post(
        f"{PREFIX}/memory/save",
        json={
            "content": "中等质量的内容测试",
            "memory_type": "episodic",
            "importance": 5,
        },
    )

    # 严格阈值 (0.1) → 几乎不入
    resp_strict = await client.get(
        f"{PREFIX}/memory/quality-candidates", params={"threshold": 0.1}
    )
    # 宽松阈值 (0.9) → 几乎全入
    resp_loose = await client.get(
        f"{PREFIX}/memory/quality-candidates", params={"threshold": 0.9}
    )
    assert resp_strict.status_code == 200
    assert resp_loose.status_code == 200
    strict_count = len(resp_strict.json()["items"])
    loose_count = len(resp_loose.json()["items"])
    assert loose_count >= strict_count


@pytest.mark.asyncio()
async def test_quality_candidates_limit_clamped(client):
    """limit 上限 200 —— 超过也不崩。"""
    resp = await client.get(
        f"{PREFIX}/memory/quality-candidates", params={"limit": 999}
    )
    assert resp.status_code == 200
    # 不应因 limit 过大而报错


@pytest.mark.asyncio()
async def test_quality_candidates_empty(client):
    """空库返空 items, 不崩。"""
    resp = await client.get(f"{PREFIX}/memory/quality-candidates")
    assert resp.status_code == 200
    assert resp.json()["items"] == []


# ---------- /memory/batch-delete ----------


@pytest.mark.asyncio()
async def test_batch_delete_episodic_soft_delete(client):
    """episodic 记忆批量删除后, list 接口不再返回 (软删除 is_valid=0)。"""
    save = await client.post(
        f"{PREFIX}/memory/save",
        json={
            "content": "待删除的 episodic 记忆",
            "memory_type": "episodic",
            "importance": 3,
        },
    )
    assert save.status_code == 200
    memory_id = save.json()["id"]

    resp = await client.post(
        f"{PREFIX}/memory/batch-delete",
        json=[{"id": memory_id, "memory_type": "episodic"}],
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["deleted"] == 1
    assert body["failed"] == []

    # 验证已不在 list 中 (软删除后 is_valid=0, get_recent 不返回)
    list_resp = await client.get(
        f"{PREFIX}/memory/list", params={"type": "episodic"}
    )
    ids = [i["id"] for i in list_resp.json()["items"]]
    assert memory_id not in ids


@pytest.mark.asyncio()
async def test_batch_delete_semantic_hard_delete(client):
    """semantic 记忆批量删除后不再出现在 list。"""
    save = await client.post(
        f"{PREFIX}/memory/save",
        json={
            "content": "待删除的 semantic 事实",
            "memory_type": "semantic",
            "importance": 7,
        },
    )
    memory_id = save.json()["id"]

    resp = await client.post(
        f"{PREFIX}/memory/batch-delete",
        json=[{"id": memory_id, "memory_type": "semantic"}],
    )
    assert resp.status_code == 200
    assert resp.json()["deleted"] == 1

    list_resp = await client.get(
        f"{PREFIX}/memory/list", params={"type": "semantic"}
    )
    ids = [i["id"] for i in list_resp.json()["items"]]
    assert memory_id not in ids


@pytest.mark.asyncio()
async def test_batch_delete_missing_id_goes_to_failed(client):
    """id 不存在 → 该条记入 failed, 其他成功的仍计 deleted。"""
    # 创建一条真实的
    save = await client.post(
        f"{PREFIX}/memory/save",
        json={
            "content": "真实的 episodic",
            "memory_type": "episodic",
            "importance": 4,
        },
    )
    real_id = save.json()["id"]

    resp = await client.post(
        f"{PREFIX}/memory/batch-delete",
        json=[
            {"id": real_id, "memory_type": "episodic"},
            {"id": "nonexistent-xyz", "memory_type": "episodic"},
        ],
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["deleted"] == 1
    assert len(body["failed"]) == 1
    assert body["failed"][0]["id"] == "nonexistent-xyz"


@pytest.mark.asyncio()
async def test_batch_delete_invalid_memory_type_goes_to_failed(client):
    """非法 memory_type → 记入 failed, 不调用 store。"""
    resp = await client.post(
        f"{PREFIX}/memory/batch-delete",
        json=[{"id": "whatever", "memory_type": "bogus_type"}],
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["deleted"] == 0
    assert len(body["failed"]) == 1
    assert "invalid memory_type" in body["failed"][0]["reason"]


@pytest.mark.asyncio()
async def test_batch_delete_empty_items(client):
    """空列表幂等。"""
    resp = await client.post(f"{PREFIX}/memory/batch-delete", json=[])
    assert resp.status_code == 200
    assert resp.json() == {"deleted": 0, "failed": []}


@pytest.mark.asyncio()
async def test_batch_delete_over_limit_returns_400(client):
    """超过 50 条 → 400。"""
    items = [
        {"id": f"id-{i}", "memory_type": "episodic"} for i in range(51)
    ]
    resp = await client.post(f"{PREFIX}/memory/batch-delete", json=items)
    assert resp.status_code == 400


@pytest.mark.asyncio()
async def test_batch_delete_writes_evolution_log(client):
    """删除后 memories_evolution_log 应有 operation='batch_delete' 记录。"""
    save = await client.post(
        f"{PREFIX}/memory/save",
        json={
            "content": "会留下审计日志的记忆",
            "memory_type": "episodic",
            "importance": 4,
        },
    )
    memory_id = save.json()["id"]

    await client.post(
        f"{PREFIX}/memory/batch-delete",
        json=[{"id": memory_id, "memory_type": "episodic"}],
    )

    # 直接查 evolution_log 表
    from backend.memory import get_memory_manager

    mm = get_memory_manager()
    conn = mm.episodic.db.get_connection()
    cursor = conn.execute(
        "SELECT operation, memory_id, reason FROM memories_evolution_log "
        "WHERE memory_id = ? ORDER BY created_at DESC LIMIT 1",
        (memory_id,),
    )
    row = cursor.fetchone()
    assert row is not None, "应写入 evolution_log"
    assert row["operation"] == "batch_delete"
    assert row["reason"] == "user:batch_delete"
