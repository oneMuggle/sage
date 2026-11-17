"""
M4 会话分叉路由 API 测试 — POST /api/v1/sessions/{id}/fork

真实临时 DB：
- 前缀复制在分叉点处的精确性（含 at_message_id 本身，之后的不复制）
- 缺省全量复制
- fork_root / forked_at_message_id 持久化 + list_sessions 序列化
- 标题覆盖 / 默认 "Fork: <原标题>"
- 未知会话 / 未知消息 404
"""


import pytest

from backend.data.session_repo import (
    Message as DbMessage,
    MessageRepository,
    SessionRepository,
    fork_session,
)

pytestmark = pytest.mark.integration

PREFIX = "/api/v1"


def _seed_messages(session_id: str, n: int = 6):
    repo = MessageRepository()
    base = 1_750_000_000_000  # 固定基准便于断言时间戳原样保留
    ids = []
    for i in range(n):
        msg_id = f"fork-seed-{i}"
        ids.append(msg_id)
        repo.save(
            DbMessage(
                id=msg_id,
                session_id=session_id,
                role="user" if i % 2 == 0 else "assistant",
                content=f"分叉测试消息 #{i}",
                created_at=base + i * 100,
            )
        )
    return ids


@pytest.mark.asyncio()
async def test_fork_unknown_session_returns_404(client):
    resp = await client.post(f"{PREFIX}/sessions/nonexistent-id/fork", json={})
    assert resp.status_code == 404
    assert resp.json()["detail"]["type"] == "session_not_found"


@pytest.mark.asyncio()
async def test_fork_unknown_message_returns_404(client):
    create = await client.post(f"{PREFIX}/sessions", json={"title": "源会话"})
    session_id = create.json()["id"]
    _seed_messages(session_id)

    resp = await client.post(
        f"{PREFIX}/sessions/{session_id}/fork", json={"at_message_id": "no-such-msg"}
    )
    assert resp.status_code == 404
    assert resp.json()["detail"]["type"] == "message_not_found"


@pytest.mark.asyncio()
async def test_fork_prefix_copy_exactness_at_boundary(client):
    """at_message_id=fork-seed-2 → 复制 0..2（含）共 3 条，3..5 不复制。"""
    create = await client.post(f"{PREFIX}/sessions", json={"title": "边界分叉"})
    source_id = create.json()["id"]
    ids = _seed_messages(source_id)

    resp = await client.post(
        f"{PREFIX}/sessions/{source_id}/fork", json={"at_message_id": ids[2]}
    )
    assert resp.status_code == 200, resp.text
    forked = resp.json()

    assert forked["id"] != source_id
    assert forked["fork_root"] == source_id
    assert forked["forked_at_message_id"] == ids[2]
    assert forked["message_count"] == 3

    rows = MessageRepository().get_by_session(forked["id"])
    assert len(rows) == 3
    # 内容 / 顺序 / 角色 / 时间戳原样保留
    assert [r.content for r in rows] == [f"分叉测试消息 #{i}" for i in range(3)]
    assert [r.role for r in rows] == ["user", "assistant", "user"]
    assert [r.created_at for r in rows] == [1_750_000_000_000 + i * 100 for i in range(3)]
    # 新 id（不与源消息冲突）
    source_ids = {ids[0], ids[1], ids[2]}
    assert all(r.id not in source_ids for r in rows)
    # 分叉点之后的消息没有泄漏到新会话
    assert all("分叉测试消息 #3" not in r.content for r in rows)


@pytest.mark.asyncio()
async def test_fork_all_copy_default(client):
    """省略 at_message_id → 复制全部; forked_at_message_id 为 None。"""
    create = await client.post(f"{PREFIX}/sessions", json={"title": "全量分叉"})
    source_id = create.json()["id"]
    _seed_messages(source_id, n=5)

    resp = await client.post(f"{PREFIX}/sessions/{source_id}/fork", json={})
    assert resp.status_code == 200
    forked = resp.json()

    assert forked["fork_root"] == source_id
    assert forked["forked_at_message_id"] is None
    rows = MessageRepository().get_by_session(forked["id"])
    assert len(rows) == 5
    assert [r.content for r in rows] == [f"分叉测试消息 #{i}" for i in range(5)]


@pytest.mark.asyncio()
async def test_fork_title_override_and_default(client):
    """显式 title 覆盖; 缺省 title 为 "Fork: <原标题>"。"""
    create = await client.post(f"{PREFIX}/sessions", json={"title": "原始标题"})
    source_id = create.json()["id"]
    _seed_messages(source_id, n=2)

    default_fork = await client.post(f"{PREFIX}/sessions/{source_id}/fork", json={})
    assert default_fork.json()["title"] == "Fork: 原始标题"

    custom_fork = await client.post(
        f"{PREFIX}/sessions/{source_id}/fork", json={"title": "我的分支"}
    )
    assert custom_fork.json()["title"] == "我的分支"


@pytest.mark.asyncio()
async def test_list_sessions_serializes_fork_fields(client):
    """list_sessions / get_session 序列化必须带上 fork_root（侧栏徽标依赖）。"""
    create = await client.post(f"{PREFIX}/sessions", json={"title": "序列化检查"})
    source_id = create.json()["id"]
    _seed_messages(source_id, n=2)

    forked = (await client.post(f"{PREFIX}/sessions/{source_id}/fork", json={})).json()

    listing = (await client.get(f"{PREFIX}/sessions")).json()
    forked_row = next(s for s in listing if s["id"] == forked["id"])
    source_row = next(s for s in listing if s["id"] == source_id)
    assert forked_row["fork_root"] == source_id
    assert source_row["fork_root"] is None

    got = (await client.get(f"{PREFIX}/sessions/{forked['id']}")).json()
    assert got["fork_root"] == source_id
    assert "forked_at_message_id" in got


@pytest.mark.asyncio()
async def test_fork_does_not_touch_source_session(client):
    """分叉是非破坏性的：源会话消息不变。"""
    create = await client.post(f"{PREFIX}/sessions", json={"title": "源不动"})
    source_id = create.json()["id"]
    ids = _seed_messages(source_id, n=4)

    resp = await client.post(
        f"{PREFIX}/sessions/{source_id}/fork", json={"at_message_id": ids[1]}
    )
    assert resp.status_code == 200

    source_rows = MessageRepository().get_by_session(source_id)
    assert [r.id for r in source_rows] == ids
    source = SessionRepository().get(source_id)
    assert source.fork_root is None


@pytest.mark.asyncio()
async def test_fork_inherits_active_workspace_binding(client, tmp_path):
    """B1 (对标增强第五轮批次 A): fork 复制源会话的活跃工作区绑定。

    workspace_path 原样带走;generation 是 per-session 陈旧检测序号,
    新会话从 1 起算;revoked_at 为 NULL(活跃)。
    """
    create = await client.post(f"{PREFIX}/sessions", json={"title": "绑定继承"})
    source_id = create.json()["id"]
    _seed_messages(source_id, n=2)

    workspace = tmp_path / "ws"
    workspace.mkdir()
    bound = await client.put(
        f"{PREFIX}/sessions/{source_id}/workspace",
        json={"workspace_path": str(workspace)},
    )
    assert bound.status_code == 200
    # 建会话时已自动绑定默认工作区(generation=1),本次 PUT 是重绑 → 2。
    source_generation = bound.json()["binding"]["generation"]
    assert source_generation == 2

    forked = (
        await client.post(
            f"{PREFIX}/sessions/{source_id}/fork", json={"at_message_id": "fork-seed-0"}
        )
    ).json()

    got = await client.get(f"{PREFIX}/sessions/{forked['id']}/workspace")
    assert got.status_code == 200
    binding = got.json()["binding"]
    assert binding is not None
    assert binding["workspace_path"] == str(workspace.resolve())
    assert binding["generation"] == 1
    assert binding["revoked_at"] is None

    # 源会话绑定不动(仍为活跃且 generation 不变)
    source_got = await client.get(f"{PREFIX}/sessions/{source_id}/workspace")
    source_binding = source_got.json()["binding"]
    assert source_binding["session_id"] == source_id
    assert source_binding["generation"] == source_generation


def _record_source_artifacts(session_id: str, tmp_path, n: int = 2):
    """在源会话登记 n 个产物（返回 artifact id 列表）。"""
    from backend.data import artifact_repo

    ids = []
    for i in range(n):
        path = tmp_path / f"产物{i}.md"
        path.write_text(f"# content {i}\n", encoding="utf-8")
        ids.append(
            artifact_repo.record_artifact(
                session_id, str(path), path.name, "markdown", path.stat().st_size
            )
        )
    return ids


@pytest.mark.asyncio()
async def test_fork_copies_artifacts(client, tmp_path):
    """F1: fork 继承源会话的产物 —— 历史消息里的产物链接与面板应延续。

    产物 id 是全局主键且 content 端点按 session 校验，复制必须分配新 id；
    源会话的产物行不受影响。
    """
    create = await client.post(f"{PREFIX}/sessions", json={"title": "产物继承"})
    source_id = create.json()["id"]
    _seed_messages(source_id, n=2)
    source_artifact_ids = _record_source_artifacts(source_id, tmp_path)

    forked = (await client.post(f"{PREFIX}/sessions/{source_id}/fork", json={})).json()

    items = (
        await client.get(f"{PREFIX}/sessions/{forked['id']}/artifacts")
    ).json()["artifacts"]
    assert {i["name"] for i in items} == {"产物0.md", "产物1.md"}
    assert all(i["id"] not in source_artifact_ids for i in items)

    # 源会话产物原样保留；fork 复制行共享源产物路径（同一工作区文件）
    source_items = (
        await client.get(f"{PREFIX}/sessions/{source_id}/artifacts")
    ).json()["artifacts"]
    assert {i["id"] for i in source_items} == set(source_artifact_ids)
    source_paths = {i["name"]: i["path"] for i in source_items}
    forked_paths = {i["name"]: i["path"] for i in items}
    assert forked_paths == source_paths

    # fork 的产物可按新 id 正常读取内容
    target = next(i for i in items if i["name"] == "产物0.md")
    content = (
        await client.get(
            f"{PREFIX}/sessions/{forked['id']}/artifacts/{target['id']}/content"
        )
    ).json()
    assert content["ok"] is True
    assert content["content"] == "# content 0\n"


@pytest.mark.asyncio()
async def test_fork_copies_artifact_versions(client, tmp_path):
    """F1: fork 复制产物的版本历史（重映射到新 artifact id）。"""
    import hashlib

    from backend.data import artifact_version_repo

    create = await client.post(f"{PREFIX}/sessions", json={"title": "版本继承"})
    source_id = create.json()["id"]
    _seed_messages(source_id, n=2)
    (artifact_id,) = _record_source_artifacts(source_id, tmp_path, n=1)

    content = "# content 0\n"
    artifact_version_repo.create_version(
        artifact_id=artifact_id,
        content=content,
        content_hash=hashlib.sha256(content.encode("utf-8")).hexdigest(),
        snapshot_dir=str(tmp_path / ".snapshots"),
        note="v1",
    )

    forked = (await client.post(f"{PREFIX}/sessions/{source_id}/fork", json={})).json()
    items = (
        await client.get(f"{PREFIX}/sessions/{forked['id']}/artifacts")
    ).json()["artifacts"]
    assert len(items) == 1
    versions = (
        await client.get(
            f"{PREFIX}/sessions/{forked['id']}/artifacts/{items[0]['id']}/versions"
        )
    ).json()["versions"]
    assert [v["note"] for v in versions] == ["v1"]


@pytest.mark.asyncio()
async def test_fork_cuts_artifacts_at_fork_point(client, tmp_path):
    """显式分叉点只复制分叉点之前的产物，被丢弃未来的产物不进入新分支。"""
    from backend.data import artifact_repo
    from backend.data.database import get_database

    create = await client.post(f"{PREFIX}/sessions", json={"title": "截断"})
    source_id = create.json()["id"]
    ids = _seed_messages(source_id, n=4)  # created_at = base + i*100（base 固定）

    old = tmp_path / "旧产物.md"
    old.write_text("old", encoding="utf-8")
    old_id = artifact_repo.record_artifact(
        source_id, str(old), old.name, "markdown", 3
    )
    new = tmp_path / "新产物.md"
    new.write_text("new", encoding="utf-8")
    new_id = artifact_repo.record_artifact(
        source_id, str(new), new.name, "markdown", 3
    )
    base = 1_750_000_000_000
    conn = get_database().get_connection()
    conn.execute("UPDATE artifacts SET created_at = ? WHERE id = ?", (base + 50, old_id))
    conn.execute(
        "UPDATE artifacts SET created_at = ? WHERE id = ?", (base + 2500, new_id)
    )
    conn.commit()

    # 分叉点 ids[2]（created_at=base+200）→ 只带 base+50 的旧产物
    forked = (
        await client.post(
            f"{PREFIX}/sessions/{source_id}/fork",
            json={"at_message_id": ids[2], "before_message": True},
        )
    ).json()
    items = (
        await client.get(f"{PREFIX}/sessions/{forked['id']}/artifacts")
    ).json()["artifacts"]
    assert [i["name"] for i in items] == ["旧产物.md"]


@pytest.mark.asyncio()
async def test_fork_without_binding_leaves_fork_unbound(client):
    """B1 边界: 源会话无活跃绑定 → fork 会话同样无绑定(binding 为 null)。

    建会话会自动绑定默认工作区,这里先显式撤销,构造"无绑定"前置状态。
    """
    create = await client.post(f"{PREFIX}/sessions", json={"title": "无绑定"})
    source_id = create.json()["id"]
    _seed_messages(source_id, n=2)

    revoked = await client.delete(f"{PREFIX}/sessions/{source_id}/workspace")
    assert revoked.status_code == 200
    source_binding = (await client.get(f"{PREFIX}/sessions/{source_id}/workspace")).json()
    assert source_binding["binding"] is None

    forked = (await client.post(f"{PREFIX}/sessions/{source_id}/fork", json={})).json()
    got = await client.get(f"{PREFIX}/sessions/{forked['id']}/workspace")
    assert got.status_code == 200
    assert got.json()["binding"] is None


@pytest.mark.asyncio()
async def test_fork_before_message_exclusive_cut(client):
    """U5' before_message=True → 开区间截断：复制分叉点之前（不含本身）。

    U5' 编辑重发依赖此语义——编辑某条消息 = 分叉其前缀后重发改写内容。
    首条消息场景得到空前缀会话（0 条消息，合法）。
    """
    create = await client.post(f"{PREFIX}/sessions", json={"title": "开区间分叉"})
    source_id = create.json()["id"]
    ids = _seed_messages(source_id, n=4)

    # 截到 fork-seed-2 之前 → 保留 0..1 共 2 条
    resp = await client.post(
        f"{PREFIX}/sessions/{source_id}/fork",
        json={"at_message_id": ids[2], "before_message": True},
    )
    assert resp.status_code == 200
    forked = resp.json()
    rows = MessageRepository().get_by_session(forked["id"])
    assert [r.content for r in rows] == ["分叉测试消息 #0", "分叉测试消息 #1"]
    assert forked["forked_at_message_id"] == ids[2]

    # 首条消息开区间 → 空前缀会话
    resp_first = await client.post(
        f"{PREFIX}/sessions/{source_id}/fork",
        json={"at_message_id": ids[0], "before_message": True},
    )
    assert resp_first.status_code == 200
    first_fork = resp_first.json()
    assert first_fork["message_count"] == 0
    assert MessageRepository().get_by_session(first_fork["id"]) == []

    # 不传 before_message → 默认闭区间（回归保护）
    resp_default = await client.post(
        f"{PREFIX}/sessions/{source_id}/fork", json={"at_message_id": ids[2]}
    )
    assert resp_default.status_code == 200
    assert resp_default.json()["message_count"] == 3


def test_fork_mid_copy_failure_leaves_no_orphan(monkeypatch):
    """MEDIUM-2: 复制到一半失败 → 整个事务回滚，不留孤儿会话/消息行。

    旧逐条提交流程会在第 3 条失败后留下"有会话行 + 2 条消息"的半成品；
    单事务修复后 sessions / messages 两表都回到 fork 前状态。
    """
    source = SessionRepository().create(title="fork 原子性")
    _seed_messages(source.id, n=5)

    import backend.data.session_repo as repo_mod

    calls = {"n": 0}
    original = repo_mod._insert_forked_message_row

    def flaky_copy(cursor, session_id, src_msg):
        calls["n"] += 1
        if calls["n"] == 3:  # 5 条中的第 3 条失败（前 2 条已插入到事务内）
            raise RuntimeError("simulated disk failure")
        return original(cursor, session_id, src_msg)

    monkeypatch.setattr(repo_mod, "_insert_forked_message_row", flaky_copy)

    with pytest.raises(RuntimeError, match="simulated disk failure"):
        fork_session(SessionRepository(), MessageRepository(), source.id)

    # 无孤儿会话行：sessions 表仍只有源会话
    assert [s.id for s in SessionRepository().list()] == [source.id]
    # 零孤儿消息行：DB 中所有消息仍属于源会话
    conn = SessionRepository().db.get_connection()
    rows = conn.execute("SELECT DISTINCT session_id FROM messages").fetchall()
    assert {r["session_id"] for r in rows} == {source.id}
    # 源会话消息未被触碰
    assert len(MessageRepository().get_by_session(source.id)) == 5
