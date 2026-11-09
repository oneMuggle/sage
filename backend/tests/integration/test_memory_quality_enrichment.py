<<<<<<< HEAD
"""Task 4.4 —— /memory/list 的 quality_score 集成测试。
=======
"""Task 4.4 ---- /memory/list 的 quality_score 集成测试。
>>>>>>> origin/main

验证每个层视图在 list 响应里是否带 quality_score:
- episodic / semantic: 带(0-1 浮点数)
- working / session_summary: 不带(无 importance/recency 语义)
- 'all' 合并视图: episodic + semantic 带, working/summary 不带

scorer 在请求内构建, 语料范围是当前查询命中的 episodic+semantic
<<<<<<< HEAD
行 —— 不泄漏到其他层, 也不会因空库报错。
=======
行 -- 不泄漏到其他层, 也不会因空库报错。
>>>>>>> origin/main
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.integration

PREFIX = "/api/v1"


# ---------- episodic / semantic ----------


@pytest.mark.asyncio()
async def test_episodic_list_returns_quality_score(client):
    """episodic 列表每条记录带 0-1 之间的 quality_score。"""
    await client.post(
        f"{PREFIX}/memory/save",
        json={
            "content": "用户偏好简洁回答",
            "memory_type": "episodic",
            "importance": 7,
        },
    )
    await client.post(
        f"{PREFIX}/memory/save",
        json={
            "content": "嗯...",
            "memory_type": "episodic",
            "importance": 1,
        },
    )

    resp = await client.get(f"{PREFIX}/memory/list", params={"type": "episodic"})
    assert resp.status_code == 200
    items = resp.json()["items"]
    assert len(items) >= 2
    for item in items:
        assert "quality_score" in item, f"缺少 quality_score: {item}"
        score = item["quality_score"]
        assert score is None or 0.0 <= score <= 1.0
    # 重要且清晰的那条分数应高于残缺语气词
    high = next(i for i in items if "简洁回答" in i["content"])
    low = next(i for i in items if i["content"].strip() == "嗯...")
    assert high["quality_score"] > low["quality_score"]


@pytest.mark.asyncio()
async def test_semantic_list_returns_quality_score(client):
    """semantic 列表每条记录带 quality_score。"""
    await client.post(
        f"{PREFIX}/memory/save",
        json={
            "content": "用户的职业是软件工程师",
            "memory_type": "semantic",
            "importance": 8,
        },
    )

    resp = await client.get(f"{PREFIX}/memory/list", params={"type": "semantic"})
    assert resp.status_code == 200
    items = resp.json()["items"]
    assert len(items) >= 1
    assert 0.0 <= items[0]["quality_score"] <= 1.0


# ---------- working / session_summary ----------


@pytest.mark.asyncio()
async def test_working_list_has_no_quality_score(client):
<<<<<<< HEAD
    """工作记忆没有 importance/recency 语义 —— 不打分。"""
=======
    """工作记忆没有 importance/recency 语义 -- 不打分。"""
>>>>>>> origin/main
    # 直接写入工作记忆(走 manager)绕过 HTTP 路由
    from backend.memory import get_memory_manager

    mm = get_memory_manager()
    mm.working.add(
        session_id="working-quality-test",
        message={"role": "user", "content": "临时问题"},
    )

    resp = await client.get(
        f"{PREFIX}/memory/list",
        params={"type": "working", "session_id": "working-quality-test"},
    )
    assert resp.status_code == 200
    items = resp.json()["items"]
    assert items, "应该有至少一条工作记忆"
    for item in items:
        assert "quality_score" not in item or item["quality_score"] is None


# ---------- 'all' 合并视图 ----------


@pytest.mark.asyncio()
async def test_all_mode_mixed_quality_score(client):
    """'all' 视图: episodic/semantic 带分, working/summary 不带。"""
    # 至少一条 episodic
    await client.post(
        f"{PREFIX}/memory/save",
        json={
            "content": "用户偏好使用 ruff 格式化 Python 代码",
            "memory_type": "episodic",
            "importance": 6,
        },
    )

    resp = await client.get(f"{PREFIX}/memory/list")
    assert resp.status_code == 200
    body = resp.json()
    assert body["layer"] == "all"
    for item in body["items"]:
        layer = item.get("layer")
        score = item.get("quality_score")
        if layer in ("episodic", "semantic"):
            assert score is not None, f"layer={layer} 应有 quality_score"
            assert 0.0 <= score <= 1.0, f"layer={layer} score={score} 越界"
        elif layer in ("working", "session_summary"):
            assert score is None, f"layer={layer} 不应有 quality_score"


# ---------- 语料范围 ----------


@pytest.mark.asyncio()
async def test_quality_scorer_corpus_is_per_request(client):
<<<<<<< HEAD
    """scorer 基于当前查询构建 —— 第二次查询不会因为上次语料污染。"""
=======
    """scorer 基于当前查询构建 -- 第二次查询不会因为上次语料污染。"""
>>>>>>> origin/main
    # 第一轮: episodic 一条独特内容
    await client.post(
        f"{PREFIX}/memory/save",
        json={
            "content": "第一轮独特内容 alpha",
            "memory_type": "episodic",
            "importance": 6,
        },
    )
    resp1 = await client.get(f"{PREFIX}/memory/list", params={"type": "episodic"})
    score1 = resp1.json()["items"][0]["quality_score"]

    # 第二轮新增一条高度重复的内容
    await client.post(
        f"{PREFIX}/memory/save",
        json={
            "content": "第一轮独特内容 alpha",
            "memory_type": "episodic",
            "importance": 6,
        },
    )
    resp2 = await client.get(f"{PREFIX}/memory/list", params={"type": "episodic"})
    # 重复内容的 uniqueness 应该被扣分(独特性 < 1.0)
    duplicates = [i for i in resp2.json()["items"] if "alpha" in i["content"]]
    assert len(duplicates) >= 2
    for dup in duplicates:
<<<<<<< HEAD
        # 重复内容的独特性维度 ≤ 0.0 → 整体分数受影响
=======
        # 重复内容的独特性维度 <= 0.0 -> 整体分数受影响
>>>>>>> origin/main
        assert dup["quality_score"] < score1 + 0.05, (
            f"重复内容不应仍得高分: {dup['quality_score']} vs baseline {score1}"
        )


# ---------- 空库 ----------


@pytest.mark.asyncio()
async def test_empty_list_returns_quality_score_schema(client):
<<<<<<< HEAD
    """空库里 list 返回空 items —— 不崩。"""
=======
    """空库里 list 返回空 items -- 不崩。"""
>>>>>>> origin/main
    resp = await client.get(f"{PREFIX}/memory/list", params={"type": "episodic"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["items"] == []
    assert body["total"] == 0
