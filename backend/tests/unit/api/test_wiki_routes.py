"""R182 — Wiki 路由单元测试（`backend/api/wiki_routes.py`，此前零覆盖）。

两层：
- 路径安全 helper 直测（`_resolve_project_file` / `_reject_symlink_components`
  / `_resolve_source_file` / `_http_exception_from_llm` / `_cleanup_temp_paths`
  / `_check_project_impl`）—— 无 IO 依赖，symlink 用例在无权限环境 skip。
- TestClient 路由测试：项目创建/打开/列表/check/recent、文件 CRUD、
  search/lint/review、citations/locate、ingest queue（真实 JSON 队列）、
  chat stream 的 selected_paths 白名单、clip、vision。

重 LLM/图集成的 `/ingest/stream`、`/research`、`/communities`、`/insights`、
`/graph` 不在本轮（mock 面过大，留给集成测试）。
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from backend.api import wiki_routes as wr

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_wiki_project(tmp_path: Path, name: str = "proj") -> Path:
    """标准 Wiki 项目：根目录 + wiki/ + schema.md + 一个内容页。

    newline="\n"：Windows 上 write_text 默认会把 \n 翻译成 \r\n，
    而 citations/locate 的 content_hash 按原始字节算，会错位。
    """
    root = tmp_path / name
    (root / "wiki" / "pages").mkdir(parents=True)
    (root / "wiki" / "schema.md").write_text(
        "---\ntitle: schema\n---\n", encoding="utf-8", newline="\n"
    )
    (root / "wiki" / "pages" / "note.md").write_text(
        "---\ntitle: Note\n---\nline1\nline2\n", encoding="utf-8", newline="\n"
    )
    return root.resolve()


@pytest.fixture()
def client():
    app = FastAPI()
    app.include_router(wr.router)
    return TestClient(app)


@pytest.fixture()
def patch_auth(monkeypatch):
    """authorize_registered_project → 返回声明路径的 canonical（免注册）。"""

    def _patch(root: Path) -> None:
        monkeypatch.setattr(wr, "authorize_registered_project", lambda p: Path(p).resolve())

    return _patch


@pytest.fixture()
def _no_side_effects(monkeypatch):
    """屏蔽写 ~/.sage 的桥接（recent/projects 注册表）。"""
    monkeypatch.setattr(wr, "record_recent", lambda *a, **k: None)
    monkeypatch.setattr(wr, "load_recent", lambda: [])
    from backend.data import project_repo

    monkeypatch.setattr(project_repo, "register_quietly", lambda *a, **k: None)


def _symlink_or_skip(link: Path, target: Path) -> None:
    try:
        os.symlink(target, link, target_is_directory=target.is_dir())
    except (OSError, NotImplementedError):
        pytest.skip("当前环境无法创建符号链接")


# ---------------------------------------------------------------------------
# _canonical_project_root / _path_is_within
# ---------------------------------------------------------------------------


def test_canonical_root_ok(tmp_path: Path) -> None:
    out = wr._canonical_project_root(str(tmp_path))
    assert out == tmp_path.resolve()


@pytest.mark.parametrize("bad", ["", "relative/path", "a\x00b"])
def test_canonical_root_invalid(bad: str) -> None:
    with pytest.raises(HTTPException) as ei:
        wr._canonical_project_root(bad)
    assert ei.value.status_code == 400


def test_path_is_within(tmp_path: Path) -> None:
    root = tmp_path.resolve()
    assert wr._path_is_within(root, root / "sub" / "f.md") is True
    assert wr._path_is_within(root, tmp_path.parent / "elsewhere.md") is False
    assert wr._path_is_within(root, tmp_path.parent / "ghost" / "x.md") is False


# ---------------------------------------------------------------------------
# _reject_symlink_components
# ---------------------------------------------------------------------------


def test_reject_symlink_components_ok(tmp_path: Path) -> None:
    (tmp_path / "sub").mkdir()
    wr._reject_symlink_components(tmp_path.resolve(), tmp_path / "sub" / "f.md")


def test_reject_symlink_components_outside(tmp_path: Path) -> None:
    with pytest.raises(HTTPException) as ei:
        wr._reject_symlink_components(tmp_path.resolve(), tmp_path.parent / "x.md")
    assert ei.value.status_code == 400


def test_reject_symlink_components_symlink(tmp_path: Path) -> None:
    root = tmp_path.resolve()
    real = tmp_path / "real"
    real.mkdir()
    link = tmp_path / "link"
    _symlink_or_skip(link, real)
    with pytest.raises(HTTPException) as ei:
        wr._reject_symlink_components(root, link / "f.md")
    assert ei.value.status_code == 400
    assert "符号链接" in str(ei.value.detail)


# ---------------------------------------------------------------------------
# _resolve_project_file
# ---------------------------------------------------------------------------


def test_resolve_project_file_ok(tmp_path: Path) -> None:
    root, resolved = wr._resolve_project_file(str(tmp_path), "a/b.md")
    assert root == tmp_path.resolve()
    assert resolved == (tmp_path / "a" / "b.md").resolve()


def test_resolve_project_file_missing_leaf_ok(tmp_path: Path) -> None:
    # strict=False：不存在的叶路径也允许（写入前解析）
    _, resolved = wr._resolve_project_file(str(tmp_path), "new.md")
    assert resolved.name == "new.md"


@pytest.mark.parametrize("bad", ["", "a\x00b"])
def test_resolve_project_file_invalid(tmp_path: Path, bad: str) -> None:
    with pytest.raises(HTTPException) as ei:
        wr._resolve_project_file(str(tmp_path), bad)
    assert ei.value.status_code == 400


def test_resolve_project_file_absolute_rejected(tmp_path: Path) -> None:
    with pytest.raises(HTTPException) as ei:
        wr._resolve_project_file(str(tmp_path), str(tmp_path / "x.md"))
    assert ei.value.status_code == 400


def test_resolve_project_file_dotdot_escape(tmp_path: Path) -> None:
    with pytest.raises(HTTPException) as ei:
        wr._resolve_project_file(str(tmp_path), "../escape.md")
    assert ei.value.status_code == 400


# ---------------------------------------------------------------------------
# _resolve_source_file
# ---------------------------------------------------------------------------


def test_resolve_source_file_relative(tmp_path: Path) -> None:
    (tmp_path / "raw").mkdir()
    _, resolved = wr._resolve_source_file(str(tmp_path), "raw/a.pdf")
    assert resolved == (tmp_path / "raw" / "a.pdf").resolve()


def test_resolve_source_file_absolute_inside(tmp_path: Path) -> None:
    target = tmp_path / "in.pdf"
    target.write_text("x", encoding="utf-8")
    _, resolved = wr._resolve_source_file(str(tmp_path), str(target))
    assert resolved == target.resolve()


def test_resolve_source_file_absolute_outside(tmp_path: Path) -> None:
    outside = tmp_path.parent / "outside.pdf"
    outside.write_text("x", encoding="utf-8")
    with pytest.raises(HTTPException) as ei:
        wr._resolve_source_file(str(tmp_path), str(outside))
    assert ei.value.status_code == 400


@pytest.mark.parametrize("bad", ["", "a\x00b"])
def test_resolve_source_file_invalid(tmp_path: Path, bad: str) -> None:
    with pytest.raises(HTTPException) as ei:
        wr._resolve_source_file(str(tmp_path), bad)
    assert ei.value.status_code == 400


# ---------------------------------------------------------------------------
# _http_exception_from_llm / _cleanup_temp_paths
# ---------------------------------------------------------------------------


def _http_status_error(status: int, with_response: bool = True) -> httpx.HTTPStatusError:
    request = httpx.Request("GET", "http://upstream")
    response = httpx.Response(status, request=request) if with_response else None
    return httpx.HTTPStatusError("boom", request=request, response=response)


def test_llm_error_maps_http_status() -> None:
    out = wr._http_exception_from_llm(_http_status_error(503), "生成失败")
    assert out.status_code == 503
    assert "upstream HTTP 503" in str(out.detail)


def test_llm_error_without_response_maps_502() -> None:
    out = wr._http_exception_from_llm(_http_status_error(503, with_response=False), "生成失败")
    assert out.status_code == 502


def test_llm_error_generic_maps_500() -> None:
    out = wr._http_exception_from_llm(RuntimeError("x"), "解析失败")
    assert out.status_code == 500
    assert out.detail == "解析失败"


def test_cleanup_temp_paths_none_ok(tmp_path: Path) -> None:
    wr._cleanup_temp_paths(None, None)


def test_cleanup_temp_paths_unlink(tmp_path: Path) -> None:
    f = tmp_path / "t.md"
    f.write_text("x", encoding="utf-8")
    wr._cleanup_temp_paths(f, f)  # 第二次 unlink 已缺失也不报错
    assert not f.exists()


def test_cleanup_temp_paths_secure_delete(tmp_path: Path) -> None:
    f = tmp_path / "t.md"
    f.write_text("x", encoding="utf-8")
    wr._cleanup_temp_paths(f, project_root=tmp_path)
    assert not f.exists()


# ---------------------------------------------------------------------------
# _check_project_impl
# ---------------------------------------------------------------------------


def test_check_open_valid(tmp_path: Path) -> None:
    root = _make_wiki_project(tmp_path)
    out = wr._check_project_impl(str(root), "open")
    assert out.is_project is True
    assert out.exists is True
    assert out.error is None


def test_check_open_missing(tmp_path: Path) -> None:
    out = wr._check_project_impl(str(tmp_path / "nope"), "open")
    assert out.exists is False
    assert out.error == "路径不存在"


def test_check_open_not_dir(tmp_path: Path) -> None:
    f = tmp_path / "afile"
    f.write_text("x", encoding="utf-8")
    out = wr._check_project_impl(str(f), "open")
    assert out.error == "不是目录"


def test_check_open_missing_wiki_dir(tmp_path: Path) -> None:
    out = wr._check_project_impl(str(tmp_path), "open")
    assert out.error is not None
    assert "wiki" in out.error


def test_check_create_existing_project(tmp_path: Path) -> None:
    root = _make_wiki_project(tmp_path)
    out = wr._check_project_impl(str(root), "create")
    assert out.error is not None
    assert "打开" in out.error


def test_check_create_existing_plain_dir_warns(tmp_path: Path) -> None:
    out = wr._check_project_impl(str(tmp_path), "create")
    assert out.warning is not None
    assert out.is_project is False


def test_check_create_new_with_writable_parent(tmp_path: Path) -> None:
    out = wr._check_project_impl(str(tmp_path / "newproj"), "create")
    assert out.exists is False
    assert out.parent_writable is True
    assert out.error is None


def test_check_create_parent_missing(tmp_path: Path) -> None:
    out = wr._check_project_impl(str(tmp_path / "ghost" / "p"), "create")
    assert out.error == "父目录不存在或不可写"


# ---------------------------------------------------------------------------
# 项目管理路由
# ---------------------------------------------------------------------------


def test_route_project_create(client, monkeypatch, tmp_path) -> None:
    _no_side_effects_ok = True  # fixture 顺序：_no_side_effects 在参数中显式列出
    assert _no_side_effects_ok
    target = tmp_path / "created"
    resp = client.post("/wiki/project/create", json={"name": "Demo", "base_path": str(target)})
    assert resp.status_code == 200
    body = resp.json()
    assert body["name"] == "Demo"
    assert (target / "wiki").is_dir()
    assert (target / "wiki" / "schema.md").exists()


@pytest.mark.usefixtures("_no_side_effects")
def test_route_project_open(client, tmp_path) -> None:
    root = _make_wiki_project(tmp_path)
    resp = client.post("/wiki/project/open", json={"path": str(root)})
    assert resp.status_code == 200
    body = resp.json()
    assert body["has_content"] is True  # pages/note.md 非默认页
    assert body["name"] == root.name


@pytest.mark.usefixtures("_no_side_effects")
def test_route_project_open_missing(client, tmp_path) -> None:
    resp = client.post("/wiki/project/open", json={"path": str(tmp_path / "nope")})
    assert resp.status_code == 404


@pytest.mark.usefixtures("_no_side_effects")
def test_route_project_open_not_wiki(client, tmp_path) -> None:
    resp = client.post("/wiki/project/open", json={"path": str(tmp_path)})
    assert resp.status_code == 400


@pytest.mark.usefixtures("_no_side_effects")
def test_route_project_list(client, tmp_path) -> None:
    root = _make_wiki_project(tmp_path, "p1")
    (tmp_path / "plain").mkdir()
    assert client.get("/wiki/project/list").json() == []
    assert client.get("/wiki/project/list", params={"base_path": "Z:/nope"}).json() == []
    rows = client.get("/wiki/project/list", params={"base_path": str(tmp_path)}).json()
    assert [r["name"] for r in rows] == [root.name]
    assert rows[0]["has_content"] is True


def test_route_project_check_open(client, tmp_path) -> None:
    root = _make_wiki_project(tmp_path)
    out = client.get("/wiki/project/check", params={"path": str(root), "intent": "open"}).json()
    assert out["is_project"] is True


def test_route_project_check_create_conflict(client, tmp_path) -> None:
    root = _make_wiki_project(tmp_path)
    out = client.get("/wiki/project/check", params={"path": str(root), "intent": "create"}).json()
    assert out["error"] is not None


def test_route_recent_projects_get(client, monkeypatch) -> None:
    from backend.storage.recent_projects import RecentProject

    monkeypatch.setattr(
        wr,
        "load_recent",
        lambda: [RecentProject(path="C:/w", name="w", opened_at=1.0, intent="open")],
    )
    rows = client.get("/wiki/recent-projects").json()
    assert rows == [{"path": "C:/w", "name": "w", "opened_at": 1.0, "intent": "open"}]


def test_route_recent_projects_record(client, monkeypatch, tmp_path) -> None:
    root = _make_wiki_project(tmp_path)
    captured: dict = {}

    def _rec(path: str, name: str, intent: str) -> None:
        captured.update(path=path, name=name, intent=intent)

    monkeypatch.setattr(wr, "record_recent", _rec)
    resp = client.post(
        "/wiki/recent-projects/record",
        json={"path": str(root), "name": "MyWiki", "intent": "open"},
    )
    assert resp.status_code == 204
    assert captured == {
        "path": str(root),
        "name": "MyWiki",
        "intent": "open",
    }


def test_route_recent_projects_record_invalid(client, monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(wr, "record_recent", lambda *a, **k: None)
    resp = client.post(
        "/wiki/recent-projects/record",
        json={"path": str(tmp_path), "name": "x", "intent": "open"},
    )
    assert resp.status_code == 404  # 缺 wiki/ 子目录


# ---------------------------------------------------------------------------
# 文件 CRUD 路由
# ---------------------------------------------------------------------------


def test_route_list_directory(client, patch_auth, tmp_path) -> None:
    root = _make_wiki_project(tmp_path)
    patch_auth(root)
    rows = client.get("/wiki/list", params={"path": "wiki", "project_path": str(root)}).json()
    assert rows[0]["path"] == "wiki"
    names = {c["name"] for c in rows[0]["children"]}
    assert names == {"pages", "schema.md"}


def test_route_list_directory_missing(client, patch_auth, tmp_path) -> None:
    root = _make_wiki_project(tmp_path)
    patch_auth(root)
    resp = client.get("/wiki/list", params={"path": "ghost", "project_path": str(root)})
    assert resp.status_code == 404


def test_route_read_write_delete(client, patch_auth, tmp_path) -> None:
    root = _make_wiki_project(tmp_path)
    patch_auth(root)

    w = client.post(
        "/wiki/write",
        params={"path": "docs/new.md", "content": "# hi", "project_path": str(root)},
    )
    assert w.json() == {"success": True}
    assert (root / "docs" / "new.md").read_text(encoding="utf-8") == "# hi"

    r = client.get("/wiki/read", params={"path": "docs/new.md", "project_path": str(root)})
    assert r.json() == "# hi"

    d = client.delete("/wiki/delete", params={"path": "docs/new.md", "project_path": str(root)})
    assert d.json() == {"success": True}
    assert not (root / "docs" / "new.md").exists()

    assert (
        client.get(
            "/wiki/read", params={"path": "docs/new.md", "project_path": str(root)}
        ).status_code
        == 404
    )


def test_route_write_absolute_rejected(client, patch_auth, tmp_path) -> None:
    root = _make_wiki_project(tmp_path)
    patch_auth(root)
    resp = client.post(
        "/wiki/write",
        params={"path": str(root / "x.md"), "content": "y", "project_path": str(root)},
    )
    assert resp.status_code == 400


def test_route_rename(client, patch_auth, tmp_path) -> None:
    root = _make_wiki_project(tmp_path)
    patch_auth(root)
    resp = client.post(
        "/wiki/rename",
        params={
            "old_path": "wiki/pages/note.md",
            "new_path": "wiki/pages/renamed.md",
            "project_path": str(root),
        },
    )
    assert resp.json() == {"success": True}
    assert (root / "wiki" / "pages" / "renamed.md").exists()

    missing = client.post(
        "/wiki/rename",
        params={
            "old_path": "wiki/pages/ghost.md",
            "new_path": "wiki/pages/x.md",
            "project_path": str(root),
        },
    )
    assert missing.status_code == 404


def test_route_delete_source(client, patch_auth, monkeypatch, tmp_path) -> None:
    root = _make_wiki_project(tmp_path)
    patch_auth(root)
    (root / "raw" / "sources").mkdir(parents=True)
    src = root / "raw" / "sources" / "a.pdf"
    src.write_bytes(b"%PDF")
    monkeypatch.setattr(
        "backend.wiki.lifecycle.cascade_delete_source",
        lambda project_root, source_path: {"wiki_pages_deleted": 2},
    )
    resp = client.delete("/wiki/source/raw/sources/a.pdf", params={"project_path": str(root)})
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    assert body["wiki_pages_deleted"] == 2
    assert not src.exists()

    gone = client.delete("/wiki/source/raw/sources/a.pdf", params={"project_path": str(root)})
    assert gone.status_code == 404


# ---------------------------------------------------------------------------
# search / lint / review
# ---------------------------------------------------------------------------


def test_route_search(client, patch_auth, monkeypatch, tmp_path) -> None:
    from backend.wiki.models import SearchResponse, SearchResult

    root = _make_wiki_project(tmp_path)
    patch_auth(root)
    monkeypatch.setattr(
        wr,
        "search_wiki",
        lambda project_root, query, limit: SearchResponse(
            results=[
                SearchResult(path="wiki/pages/note.md", title="Note", snippet="line1", score=1.0)
            ],
            total=1,
        ),
    )
    body = client.get("/wiki/search", params={"query": "line", "project_path": str(root)}).json()
    assert body["total"] == 1
    assert body["results"][0]["path"] == "wiki/pages/note.md"


def test_route_lint_and_review(client, patch_auth, tmp_path) -> None:
    root = _make_wiki_project(tmp_path)
    patch_auth(root)
    lint = client.get("/wiki/lint", params={"project_path": str(root)}).json()
    assert set(lint) >= {"total", "by_severity", "issues"}
    review = client.get("/wiki/review", params={"project_path": str(root)}).json()
    assert set(review) >= {"total", "by_type", "items"}


# ---------------------------------------------------------------------------
# citations/locate
# ---------------------------------------------------------------------------


def _locate_payload(root: Path, **overrides):
    content = (root / "wiki" / "pages" / "note.md").read_text(encoding="utf-8")
    payload = {
        "project_path": str(root),
        "path": "wiki/pages/note.md",
        "content_hash": hashlib.sha256(content.encode("utf-8")).hexdigest(),
        "line_start": 1,
        "line_end": 2,
    }
    payload.update(overrides)
    return payload


def test_route_locate_citation_ok(client, patch_auth, tmp_path) -> None:
    root = _make_wiki_project(tmp_path)
    patch_auth(root)
    body = client.post("/wiki/citations/locate", json=_locate_payload(root)).json()
    assert body["changed"] is False
    assert body["excerpt"] == "---\ntitle: Note"


def test_route_locate_citation_changed(client, patch_auth, tmp_path) -> None:
    root = _make_wiki_project(tmp_path)
    patch_auth(root)
    payload = _locate_payload(root, content_hash="0" * 64)
    assert client.post("/wiki/citations/locate", json=payload).json()["changed"] is True


def test_route_locate_citation_bad_path(client, patch_auth, tmp_path) -> None:
    root = _make_wiki_project(tmp_path)
    patch_auth(root)
    payload = _locate_payload(root, path="wiki/pages/evil.md")
    assert client.post("/wiki/citations/locate", json=payload).status_code == 403


def test_route_locate_citation_bad_range(client, patch_auth, tmp_path) -> None:
    root = _make_wiki_project(tmp_path)
    patch_auth(root)
    payload = _locate_payload(root, line_start=3, line_end=2)
    assert client.post("/wiki/citations/locate", json=payload).status_code == 422


def test_route_locate_citation_range_too_wide(client, patch_auth, tmp_path) -> None:
    root = _make_wiki_project(tmp_path)
    patch_auth(root)
    payload = _locate_payload(root, line_start=1, line_end=501)
    assert client.post("/wiki/citations/locate", json=payload).status_code == 422


def test_route_locate_citation_stale_offset(client, patch_auth, tmp_path) -> None:
    root = _make_wiki_project(tmp_path)
    patch_auth(root)
    payload = _locate_payload(root, line_start=999)
    assert client.post("/wiki/citations/locate", json=payload).status_code == 422


# ---------------------------------------------------------------------------
# ingest queue（真实 JSON 队列）
# ---------------------------------------------------------------------------


def test_route_queue_full_lifecycle(client, patch_auth, tmp_path) -> None:
    root = _make_wiki_project(tmp_path)
    patch_auth(root)

    added = client.post(
        "/wiki/ingest/queue/add",
        json={"project_path": str(root), "source_path": "raw/a.pdf"},
    ).json()
    assert added["status"] == "pending"
    task_id = added["task_id"]

    summary = client.get("/wiki/ingest/queue/status", params={"project_path": str(root)}).json()
    assert summary.get("pending") == 1

    tasks = client.get("/wiki/ingest/queue/tasks", params={"project_path": str(root)}).json()[
        "tasks"
    ]
    assert [t["task_id"] for t in tasks] == [task_id]

    bad_status = client.get(
        "/wiki/ingest/queue/tasks",
        params={"project_path": str(root), "status": "nope"},
    )
    assert bad_status.status_code == 400

    nxt = client.get("/wiki/ingest/queue/next", params={"project_path": str(root)}).json()
    assert nxt["task"]["task_id"] == task_id

    cancelled = client.post(
        f"/wiki/ingest/queue/cancel/{task_id}", params={"project_path": str(root)}
    ).json()
    assert cancelled == {"success": True}
    assert (
        client.post(
            f"/wiki/ingest/queue/cancel/{task_id}", params={"project_path": str(root)}
        ).status_code
        == 400
    )

    cleared = client.post("/wiki/ingest/queue/clear", params={"project_path": str(root)}).json()
    assert cleared == {"cleared": 1}
    nxt = client.get("/wiki/ingest/queue/next", params={"project_path": str(root)}).json()
    assert nxt == {"task": None}


def test_route_queue_retry(client, patch_auth, tmp_path) -> None:
    from backend.wiki.ingest_queue import IngestQueue, QueueStatus

    root = _make_wiki_project(tmp_path)
    patch_auth(root)
    queue = IngestQueue(root)
    task_id = queue.add("raw/b.pdf")
    queue._tasks[task_id].status = QueueStatus.FAILED  # 直写内部状态模拟失败任务
    queue._save()

    resp = client.post(f"/wiki/ingest/queue/retry/{task_id}", params={"project_path": str(root)})
    assert resp.json() == {"success": True}
    unknown = client.post("/wiki/ingest/queue/retry/ghost", params={"project_path": str(root)})
    assert unknown.status_code == 400


# ---------------------------------------------------------------------------
# chat stream 的 selected_paths 白名单
# ---------------------------------------------------------------------------


def test_route_chat_stream_selected_paths_rejected(client, patch_auth, tmp_path) -> None:
    root = _make_wiki_project(tmp_path)
    patch_auth(root)
    payload = {
        "query": "q",
        "project_path": str(root),
        "llm_base_url": "http://x",
        "llm_api_key": "k",
        "llm_model": "m",
        "embed_base_url": "http://x",
        "embed_api_key": "k",
        "embed_model": "e",
        "selected_paths": ["wiki/pages/evil.md"],
    }
    resp = client.post("/wiki/chat/stream", json=payload)
    assert resp.status_code == 403


def test_route_chat_stream_ok(client, patch_auth, monkeypatch, tmp_path) -> None:
    root = _make_wiki_project(tmp_path)
    patch_auth(root)

    async def _fake_stream(config, project_root, query, ctx):
        yield b'{"event":"chunk","data":"hi"}\n'
        yield b'{"event":"done","data":{"citations":[]}}\n'

    monkeypatch.setattr(wr, "chat_with_wiki_stream", _fake_stream)
    payload = {
        "query": "q",
        "project_path": str(root),
        "llm_base_url": "http://x",
        "llm_api_key": "k",
        "llm_model": "m",
        "embed_base_url": "http://x",
        "embed_api_key": "k",
        "embed_model": "e",
        "selected_paths": ["wiki/pages/note.md"],
    }
    with client.stream("POST", "/wiki/chat/stream", json=payload) as resp:
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("application/x-ndjson")
        body = b"".join(resp.iter_bytes())
    assert b'"event":"done"' in body


# ---------------------------------------------------------------------------
# clip / vision
# ---------------------------------------------------------------------------


def test_route_clip_saves_markdown(client, patch_auth, tmp_path) -> None:
    root = _make_wiki_project(tmp_path)
    patch_auth(root)
    resp = client.post(
        "/wiki/clip",
        json={
            "title": "Deep Learning <Guide>",
            "url": "https://example.com/a",
            "content": "# body",
            "project_path": str(root),
            "notes": "note text",
            "auto_ingest": False,
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["auto_ingested"] is False
    saved = root / body["source_path"]
    assert saved.exists()
    assert saved.name.startswith("webclip-")
    text = saved.read_text(encoding="utf-8")
    assert "# body" in text
    assert "note text" in text
    assert "<Guide>" not in saved.name  # 非法字符被清洗


def test_route_vision_invalid_base64(client, patch_auth, tmp_path) -> None:
    root = _make_wiki_project(tmp_path)
    patch_auth(root)
    resp = client.post(
        "/wiki/vision",
        json={"image_data": "!!!not-base64!!!", "project_path": str(root)},
    )
    assert resp.status_code == 400


def test_route_vision_ok(client, patch_auth, monkeypatch, tmp_path) -> None:
    import base64

    root = _make_wiki_project(tmp_path)
    patch_auth(root)

    class _Result:
        caption = "a cat"
        sha256 = "ab" * 32
        cached = False
        image_path = "wiki/assets/ab.md"

    async def _fake_caption(**kwargs):
        return _Result()

    import backend.wiki as wiki_pkg

    monkeypatch.setattr(wiki_pkg, "caption_image", _fake_caption)
    payload = {
        "image_data": base64.b64encode(b"\x89PNG fake").decode("ascii"),
        "project_path": str(root),
        "provider": "openai",
        "base_url": "http://x",
        "api_key": "k",
        "model": "gpt-4v",
    }
    body = client.post("/wiki/vision", json=payload).json()
    assert body["caption"] == "a cat"
    assert body["cached"] is False
