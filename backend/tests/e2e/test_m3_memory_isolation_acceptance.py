"""M3 验收 E2E —— 专家记忆隔离三条验收线。

覆盖 spec §M3 的验收条件（真库 + 真单例 + 真 HTTP 路由，不打桩）：

1. 两个专家的私有记忆互不可见（读路径 = 私有 ∪ 共享）；
2. 共享层偏好对两个专家都可见；
3. 删除专家时级联清空其私有记忆，且不动共享层与其它专家；
4. 私有记忆经 ``POST /memory/{id}/promote`` 提升后对所有专家可见
   （提升是"私有 → 共享"的唯一合法出口，需同样纳入验收）。

本文件不使用 ``manager.memorize`` 之外的存储替身：写入经全局
``MemoryManager`` 单例（与聊天路径同一实例），删除经真实
``DELETE /api/v1/agents/{id}`` 路由（含级联清理）。
"""

from __future__ import annotations

import pytest

from backend.memory import get_memory_manager

pytestmark = pytest.mark.e2e

AGENT_WRITER = "specialist-writer"
AGENT_CODER = "specialist-coder"

# 与 test_memory_agent_isolation / test_m3_promote_and_purge 共用同一检索
# token，确保 FTS5 与 LIKE 两条路径都能命中。
QUERY = "阈值配置"


async def _create_agent(client, agent_id: str, name: str) -> None:
    resp = await client.post(
        "/api/v1/agents",
        json={"id": agent_id, "name": name, "role": "general"},
    )
    assert resp.status_code == 200, resp.text


def _recalled_ids(manager, agent_id: str) -> set[str]:
    """该专家通过读路径（私有 ∪ 共享）能看到的情景/语义记忆 ID 集合。"""
    result = manager.recall(
        QUERY, limit=20, memory_types=["episodic", "semantic"], agent_id=agent_id
    )
    ids: set[str] = set()
    for kind in ("episodic", "semantic"):
        for row in result.get(kind) or []:
            ids.add(row["id"])
    return ids


def _seed_private_and_shared(manager) -> dict[str, str]:
    """写入两个专家的私有记忆 + 一条共享偏好，返回 id 索引。"""
    return {
        "writer_episodic": manager.memorize(
            "写作私有记忆 阈值配置 蓝色标题优先",
            memory_type="episodic",
            agent_id=AGENT_WRITER,
        ),
        "writer_semantic": manager.memorize(
            "写作私有知识 阈值配置 模板固定用蓝色",
            memory_type="semantic",
            agent_id=AGENT_WRITER,
        ),
        "coder_episodic": manager.memorize(
            "编码私有记忆 阈值配置 提交前跑 ruff",
            memory_type="episodic",
            agent_id=AGENT_CODER,
        ),
        "coder_semantic": manager.memorize(
            "编码私有知识 阈值配置 缩进四空格",
            memory_type="semantic",
            agent_id=AGENT_CODER,
        ),
        "shared": manager.memorize(
            "共享用户偏好 阈值配置 回答使用中文",
            memory_type="episodic",
            agent_id=None,
        ),
    }


@pytest.mark.asyncio()
async def test_two_specialists_private_memories_are_mutually_invisible(client):
    """验收线 1：专家 A 的私有记忆对专家 B 不可见，反之亦然。"""
    await _create_agent(client, AGENT_WRITER, "写作专家")
    await _create_agent(client, AGENT_CODER, "编码专家")

    manager = get_memory_manager()
    ids = _seed_private_and_shared(manager)

    writer_sees = _recalled_ids(manager, AGENT_WRITER)
    assert ids["writer_episodic"] in writer_sees
    assert ids["writer_semantic"] in writer_sees
    assert ids["coder_episodic"] not in writer_sees
    assert ids["coder_semantic"] not in writer_sees

    coder_sees = _recalled_ids(manager, AGENT_CODER)
    assert ids["coder_episodic"] in coder_sees
    assert ids["coder_semantic"] in coder_sees
    assert ids["writer_episodic"] not in coder_sees
    assert ids["writer_semantic"] not in coder_sees


@pytest.mark.asyncio()
async def test_shared_preference_visible_to_every_specialist(client):
    """验收线 2：共享层（agent_id IS NULL）对两个专家都可见。"""
    await _create_agent(client, AGENT_WRITER, "写作专家")
    await _create_agent(client, AGENT_CODER, "编码专家")

    manager = get_memory_manager()
    ids = _seed_private_and_shared(manager)

    assert ids["shared"] in _recalled_ids(manager, AGENT_WRITER)
    assert ids["shared"] in _recalled_ids(manager, AGENT_CODER)


@pytest.mark.asyncio()
async def test_deleting_specialist_purges_only_its_private_memory(client):
    """验收线 3：删专家级联清私有记忆，共享层与另一专家不受影响。"""
    await _create_agent(client, AGENT_WRITER, "写作专家")
    await _create_agent(client, AGENT_CODER, "编码专家")

    manager = get_memory_manager()
    ids = _seed_private_and_shared(manager)

    resp = await client.delete(f"/api/v1/agents/{AGENT_WRITER}")
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"ok": True, "id": AGENT_WRITER}

    # 专家本体已删除
    assert (await client.get(f"/api/v1/agents/{AGENT_WRITER}")).status_code == 404

    # 写作专家的私有记忆不可再被读到（本人视图也不应残留）
    writer_sees = _recalled_ids(manager, AGENT_WRITER)
    assert ids["writer_episodic"] not in writer_sees
    assert ids["writer_semantic"] not in writer_sees

    # 共享层与编码专家不受级联影响
    coder_sees = _recalled_ids(manager, AGENT_CODER)
    assert ids["shared"] in coder_sees
    assert ids["coder_episodic"] in coder_sees
    assert ids["coder_semantic"] in coder_sees

    # 存储层语义：情景层软删（行在、is_valid=0），语义层硬删 + FTS 同步
    conn = manager.episodic.db.get_connection()
    row = conn.execute(
        "SELECT is_valid FROM memories_episodic WHERE id = ?",
        (ids["writer_episodic"],),
    ).fetchone()
    assert row is not None
    assert row["is_valid"] == 0
    assert (
        conn.execute(
            "SELECT COUNT(*) AS n FROM memories_semantic WHERE id = ?",
            (ids["writer_semantic"],),
        ).fetchone()["n"]
        == 0
    )
    # 未删除的行走正常路径，未被误伤
    assert (
        conn.execute(
            "SELECT is_valid FROM memories_episodic WHERE id = ?",
            (ids["coder_episodic"],),
        ).fetchone()["is_valid"]
        == 1
    )


@pytest.mark.asyncio()
async def test_promoted_memory_becomes_visible_to_other_specialist(client):
    """验收线 4：私有记忆提升为共享后，另一专家立即可读（且留审计行）。"""
    await _create_agent(client, AGENT_WRITER, "写作专家")
    await _create_agent(client, AGENT_CODER, "编码专家")

    manager = get_memory_manager()
    ids = _seed_private_and_shared(manager)

    # 提升前：编码专家看不到写作专家的私有记忆
    assert ids["writer_episodic"] not in _recalled_ids(manager, AGENT_CODER)

    resp = await client.post(f"/api/v1/memory/{ids['writer_episodic']}/promote")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "promoted"
    assert body["previous_agent_id"] == AGENT_WRITER
    assert body["memory_type"] == "episodic"

    # 提升后：编码专家可读
    assert ids["writer_episodic"] in _recalled_ids(manager, AGENT_CODER)

    conn = manager.episodic.db.get_connection()
    audit = conn.execute(
        "SELECT operation, memory_id FROM memories_evolution_log "
        "WHERE memory_id = ? ORDER BY created_at",
        (ids["writer_episodic"],),
    ).fetchall()
    assert [(r["operation"], r["memory_id"]) for r in audit] == [
        ("promote", ids["writer_episodic"])
    ]
