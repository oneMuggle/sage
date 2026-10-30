"""手动归档 / 恢复归档 / 归档列表 HTTP 契约测试（legacy 路由）。

覆盖:
- PATCH /sessions/{id} 接受 ``is_archived``（归档 / 恢复）
- 归档后默认列表不可见，``GET /sessions?archived=true`` 可见
- 恢复后回到默认列表
- 不存在的会话返回 404
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.integration

PREFIX = "/api/v1"


async def _create(client, title: str) -> str:
    resp = await client.post(f"{PREFIX}/sessions", json={"title": title})
    assert resp.status_code == 200
    return resp.json()["id"]


@pytest.mark.asyncio()
async def test_patch_session_archives_and_lists_separately(client):
    sid = await _create(client, "待归档会话")

    resp = await client.patch(f"{PREFIX}/sessions/{sid}", json={"is_archived": True})
    assert resp.status_code == 200
    assert resp.json()["is_archived"] is True

    active = await client.get(f"{PREFIX}/sessions")
    assert all(s["id"] != sid for s in active.json())

    archived = await client.get(f"{PREFIX}/sessions", params={"archived": "true"})
    assert [s["id"] for s in archived.json()] == [sid]


@pytest.mark.asyncio()
async def test_patch_session_unarchives(client):
    sid = await _create(client, "恢复会话")
    await client.patch(f"{PREFIX}/sessions/{sid}", json={"is_archived": True})

    resp = await client.patch(f"{PREFIX}/sessions/{sid}", json={"is_archived": False})
    assert resp.status_code == 200
    assert resp.json()["is_archived"] is False

    active = await client.get(f"{PREFIX}/sessions")
    assert any(s["id"] == sid for s in active.json())
    archived = await client.get(f"{PREFIX}/sessions", params={"archived": "true"})
    assert all(s["id"] != sid for s in archived.json())


@pytest.mark.asyncio()
async def test_patch_archive_unknown_session_returns_404(client):
    resp = await client.patch(
        f"{PREFIX}/sessions/nonexistent-archive", json={"is_archived": True}
    )
    assert resp.status_code == 404


@pytest.mark.asyncio()
async def test_archived_list_supports_pagination(client):
    ids = [await _create(client, f"归档分页-{i}") for i in range(3)]
    for sid in ids:
        await client.patch(f"{PREFIX}/sessions/{sid}", json={"is_archived": True})

    page = await client.get(
        f"{PREFIX}/sessions", params={"archived": "true", "limit": 2, "offset": 0}
    )
    assert len(page.json()) == 2

    rest = await client.get(
        f"{PREFIX}/sessions", params={"archived": "true", "limit": 2, "offset": 2}
    )
    assert len(rest.json()) == 1
