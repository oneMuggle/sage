# ruff: noqa: UP006, UP007, UP035 — release/win7 Python 3.8 兼容，保留 typing 注解
"""F12 (round5 批次 B): 消息全文搜索端点测试（GET /api/v1/search/messages）。"""

from __future__ import annotations

import pytest

from backend.data.session_repo import Message as DbMessage, MessageRepository, SessionRepository

PREFIX = "/api/v1"

pytestmark = pytest.mark.integration


async def _seed(client, title: str, messages) -> str:
    session_id = (await client.post(f"{PREFIX}/sessions", json={"title": title})).json()["id"]
    repo = MessageRepository()
    base = 1_750_000_000_000
    for i, (role, content) in enumerate(messages):
        repo.save(
            DbMessage(
                id=f"msg-{session_id[:6]}-{i}",
                session_id=session_id,
                role=role,
                content=content,
                created_at=base + i * 100,
            )
        )
    return session_id


async def test_cross_session_search_orders_and_snippets(client):
    s1 = await _seed(client, "登录页", [("user", "帮我修复登录页的样式"), ("assistant", "已修复登录页")])
    s2 = await _seed(client, "设置页", [("user", "设置页也要改"), ("assistant", "好的")])

    resp = await client.get(f"{PREFIX}/search/messages", params={"q": "登录页"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["has_more"] is False
    assert [r["session_id"] for r in body["results"]] == [s1, s1]  # 新→旧: assistant 先
    first = body["results"][0]
    assert first["session_title"] == "登录页"
    assert first["role"] == "assistant"
    assert "登录页" in first["snippet"]
    # 不含设置页会话的消息
    assert all(r["session_id"] != s2 for r in body["results"])


async def test_role_filter_excludes_tool_and_system(client):
    await _seed(
        client,
        "角色过滤",
        [
            ("user", "运行诊断命令"),
            ("tool", "诊断命令输出 diagnostics..."),
            ("system", "系统提示 diagnostics"),
            ("assistant", "诊断完成"),
        ],
    )
    body = (await client.get(f"{PREFIX}/search/messages", params={"q": "诊断"})).json()
    assert {r["role"] for r in body["results"]} == {"user", "assistant"}


async def test_session_id_filter(client):
    await _seed(client, "会话A", [("user", "关键词在A")])
    s2 = await _seed(client, "会话B", [("user", "关键词在B")])

    body = (
        await client.get(f"{PREFIX}/search/messages", params={"q": "关键词", "session_id": s2})
    ).json()
    assert len(body["results"]) == 1
    assert body["results"][0]["session_id"] == s2


async def test_like_wildcards_are_escaped(client):
    session = SessionRepository().create(title="通配符")
    repo = MessageRepository()
    repo.save(
        DbMessage(
            id="msg-wild-0",
            session_id=session.id,
            role="user",
            content="覆盖率 100_percent 完成",
            created_at=1_750_000_000_000,
        )
    )

    # 字面下划线不应被当作 LIKE 单字符通配符
    body = (await client.get(f"{PREFIX}/search/messages", params={"q": "100_percent"})).json()
    assert len(body["results"]) == 1
    # % 同理：搜 "100%" 不应命中（内容里没有百分号字面量）
    body = (await client.get(f"{PREFIX}/search/messages", params={"q": "100p%rcent"})).json()
    assert body["results"] == []


async def test_limit_and_has_more(client):
    session = SessionRepository().create(title="翻页")
    repo = MessageRepository()
    for i in range(5):
        repo.save(
            DbMessage(
                id=f"msg-page-{i}",
                session_id=session.id,
                role="user",
                content=f"翻页命中 {i}",
                created_at=1_750_000_000_000 + i * 100,
            )
        )

    body = (await client.get(f"{PREFIX}/search/messages", params={"q": "翻页", "limit": 3})).json()
    assert len(body["results"]) == 3
    assert body["has_more"] is True
    # 最新优先
    assert body["results"][0]["message_id"] == "msg-page-4"

    body = (await client.get(f"{PREFIX}/search/messages", params={"q": "翻页", "limit": 5})).json()
    assert len(body["results"]) == 5
    assert body["has_more"] is False


async def test_short_query_rejected(client):
    resp = await client.get(f"{PREFIX}/search/messages", params={"q": "a"})
    assert resp.status_code == 422


async def test_no_match_empty(client):
    await _seed(client, "空结果", [("user", "普通消息")])
    body = (await client.get(f"{PREFIX}/search/messages", params={"q": "不存在的词"})).json()
    assert body == {"results": [], "has_more": False}
