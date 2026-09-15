# backend/tests/api/test_search_routes.py
"""P1-3.7 全局搜索路由测试（/api/v1/search/global）。

覆盖：参数校验 / 三类聚合 / types 过滤 / 会话命中 / 无匹配。
memory 与 knowledge 源在测试环境通常为空，且 helper 内部已 try/except 降级，
因此断言聚焦于结构而非具体条数（会话源可直接造数据验证）。
"""
import pytest

from backend.data.session_repo import SessionRepository


@pytest.mark.asyncio
async def test_global_search_missing_q_returns_422(client):
    resp = await client.get("/api/v1/search/global")
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_global_search_empty_q_returns_422(client):
    # q 的 min_length=1，空串应被 FastAPI 校验拒绝
    resp = await client.get("/api/v1/search/global", params={"q": ""})
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_global_search_returns_all_four_keys(client):
    resp = await client.get("/api/v1/search/global", params={"q": "never-match-xyz"})
    assert resp.status_code == 200
    body = resp.json()
    # P7: 项目模块接入全局搜索，默认含 projects 组
    assert set(body.keys()) == {"sessions", "memories", "knowledge", "projects"}
    assert body["sessions"] == []
    assert isinstance(body["memories"], list)
    assert isinstance(body["knowledge"], list)
    assert isinstance(body["projects"], list)


@pytest.mark.asyncio
async def test_global_search_types_filter_limits_keys(client):
    resp = await client.get("/api/v1/search/global", params={"q": "abc", "types": "session"})
    assert resp.status_code == 200
    assert set(resp.json().keys()) == {"sessions"}


@pytest.mark.asyncio
async def test_global_search_finds_session_by_title(client):
    repo = SessionRepository()
    repo.create(title="项目计划评审")
    repo.create(title="无关会话")

    resp = await client.get("/api/v1/search/global", params={"q": "项目计划"})
    assert resp.status_code == 200
    sessions = resp.json()["sessions"]
    assert len(sessions) == 1
    assert sessions[0]["title"] == "项目计划评审"
    assert "message_count" in sessions[0]
    assert "updated_at" in sessions[0]


@pytest.mark.asyncio
async def test_global_search_respects_limit(client):
    repo = SessionRepository()
    for i in range(5):
        repo.create(title=f"限制测试-{i}")

    resp = await client.get("/api/v1/search/global", params={"q": "限制测试", "limit": 2})
    assert resp.status_code == 200
    assert len(resp.json()["sessions"]) == 2


# ===== P7: 项目模块接入全局搜索 =====


@pytest.mark.asyncio
async def test_global_search_finds_registered_project(client, tmp_path):

    from backend.data.project_repo import ProjectRepository

    project_dir = tmp_path / "alpha-web"
    project_dir.mkdir()
    other_dir = tmp_path / "beta-cli"
    other_dir.mkdir()
    repo = ProjectRepository()
    repo.register(str(project_dir), now_ms=5_000)
    repo.register(str(other_dir), now_ms=4_000)

    resp = await client.get("/api/v1/search/global", params={"q": "alpha"})
    assert resp.status_code == 200
    projects = resp.json()["projects"]
    assert len(projects) == 1
    assert projects[0]["name"] == "alpha-web"
    assert projects[0]["path"] == str(project_dir.resolve())
    assert projects[0]["session_count"] == 0
    assert "id" in projects[0]


@pytest.mark.asyncio
async def test_global_search_project_types_filter(client, tmp_path):
    from backend.data.project_repo import ProjectRepository

    project_dir = tmp_path / "solo"
    project_dir.mkdir()
    ProjectRepository().register(str(project_dir))

    resp = await client.get(
        "/api/v1/search/global", params={"q": "solo", "types": "project"}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert set(body.keys()) == {"projects"}
    assert len(body["projects"]) == 1


# ===== P9: 知识搜索范围配置化（knowledge_project）=====


def _seed_wiki_project(root, token: str) -> None:
    """创建含唯一词页面的 wiki 项目并登记进 recents。"""
    wiki = root / "wiki"
    wiki.mkdir(parents=True)
    content = f"# {token}\n\nunique-token-{token} 的正文内容。"
    (wiki / f"note-{token}.md").write_text(content, encoding="utf-8")
    from backend.storage.recent_projects import record_recent

    record_recent(str(root), root.name, "open")


@pytest.mark.asyncio
async def test_knowledge_project_scope_limits_results(client, tmp_path):
    """显式范围=A 时，只命中 A 内的页面（即使 B 更新）。"""
    project_a = tmp_path / "project-a"
    project_b = tmp_path / "project-b"
    _seed_wiki_project(project_a, "aaaa")
    _seed_wiki_project(project_b, "bbbb")
    # 让 B 成为"最近打开"（默认域），A 才是被范围指定的
    record_b = await client.post(
        "/api/v1/wiki/recent-projects/record",
        json={"path": str(project_b), "name": "b", "intent": "open"},
    )
    assert record_b.status_code == 204

    resp = await client.get(
        "/api/v1/search/global",
        params={"q": "unique-token-aaaa", "knowledge_project": str(project_a)},
    )
    assert resp.status_code == 200
    knowledge = resp.json()["knowledge"]
    assert knowledge, "范围内命中不应为空"
    assert all("note-aaaa" in item["path"] for item in knowledge)


@pytest.mark.asyncio
async def test_knowledge_project_unauthorized_returns_403(client, tmp_path):
    """范围目录未登记/未打开 → 403（与 wiki 域授权契约一致）。"""
    rogue = tmp_path / "rogue"
    (rogue / "wiki").mkdir(parents=True)
    resp = await client.get(
        "/api/v1/search/global",
        params={"q": "anything", "knowledge_project": str(rogue)},
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_knowledge_project_without_wiki_dir_returns_404(client, tmp_path):
    """范围目录存在但不是 wiki 项目（缺 wiki/）→ 404。"""
    plain = tmp_path / "plain"
    plain.mkdir()
    from backend.storage.recent_projects import record_recent

    record_recent(str(plain), "plain", "open")

    resp = await client.get(
        "/api/v1/search/global",
        params={"q": "anything", "knowledge_project": str(plain)},
    )
    assert resp.status_code == 404
