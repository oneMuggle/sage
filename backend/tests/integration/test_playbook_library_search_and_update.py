# ruff: noqa: UP006, UP007, UP035 — release/win7 Python 3.8 兼容
"""规程库搜索与元数据更新（M6，2026-11-07）。"""

from __future__ import annotations

import json
import time
from typing import AsyncIterator, List, Optional

import httpx
import pytest
import pytest_asyncio

from backend.api import playbook_routes  # noqa: F401 — 确保路由注册
from backend.data import database as database_module
from backend.data.database import Database, get_database
from backend.data.playbook_event_repo import PlaybookEventRepository
from backend.data.playbook_library_repo import PlaybookLibraryRepository
from backend.main import app


@pytest.fixture(autouse=True)
def isolated_home(tmp_path_factory, monkeypatch: pytest.MonkeyPatch):
    home = tmp_path_factory.mktemp("home")
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    return home


@pytest.fixture()
def db(monkeypatch: pytest.MonkeyPatch) -> Database:
    test_db = Database(":memory:")
    test_db.init_db()
    monkeypatch.setattr(database_module, "_db", test_db)
    return test_db


@pytest_asyncio.fixture()
async def client(db: Database) -> AsyncIterator[httpx.AsyncClient]:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as value:
        yield value


def _playbook_id(name: str) -> str:
    slug = "".join(ch if ch.isalnum() else "-" for ch in name.lower())
    return "pb-" + slug


async def _seed(
    client: httpx.AsyncClient,
    *,
    name: str = "demo",
    description: str = "",
    tags: Optional[List[str]] = None,
) -> dict:
    envelope = {
        "format": "sage.playbook",
        "playbook": {
            "schema_version": "1.0",
            "id": _playbook_id(name),
            "name": name,
            "description": description,
            "stages": [{"id": "s1", "label": "阶段一"}],
            "directory_layout": [],
            "meta": {"tags": list(tags or [])},
        },
    }
    response = await client.post(
        "/api/v1/playbooks/library", json={"envelope": envelope, "source": "test"}
    )
    assert response.status_code == 200, response.text
    return response.json()["item"]


def _insert_library_row(library_id: str, name: str, spec: dict) -> None:
    """Insert a library row directly to simulate legacy / hand-edited data."""
    conn = get_database().get_connection()
    conn.execute(
        "INSERT INTO playbook_library "
        "(id, name, source, spec_json, spec_hash, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (
            library_id,
            name,
            "test",
            json.dumps(spec, ensure_ascii=False),
            "legacy-" + library_id,
            int(time.time() * 1000),
        ),
    )
    conn.commit()


async def test_list_returns_description_and_tags(client: httpx.AsyncClient):
    item = await _seed(client, description="团队通用", tags=["coding", "fast"])

    response = await client.get("/api/v1/playbooks/library")

    assert response.status_code == 200
    returned = response.json()["items"][0]
    assert returned["id"] == item["id"]
    assert returned["description"] == "团队通用"
    assert returned["tags"] == ["coding", "fast"]


async def test_list_filter_by_name_substring_case_insensitive(
    client: httpx.AsyncClient,
):
    await _seed(client, name="Alpha Standard")
    await _seed(client, name="Beta Standard")
    await _seed(client, name="Gamma Guide")

    response = await client.get("/api/v1/playbooks/library?q=STANDARD")

    assert response.status_code == 200
    names = {item["name"] for item in response.json()["items"]}
    assert names == {"Alpha Standard", "Beta Standard"}


async def test_list_filter_by_description(client: httpx.AsyncClient):
    await _seed(client, name="One", description="团队协作")
    await _seed(client, name="Two", description="个人工具")

    response = await client.get("/api/v1/playbooks/library?q=协作")

    body = response.json()
    assert len(body["items"]) == 1
    assert body["items"][0]["name"] == "One"


async def test_list_filter_by_tag(client: httpx.AsyncClient):
    await _seed(client, name="One", tags=["python"])
    await _seed(client, name="Two", tags=["typescript"])

    response = await client.get("/api/v1/playbooks/library?q=python")

    body = response.json()
    assert len(body["items"]) == 1
    assert body["items"][0]["name"] == "One"


async def test_list_multi_word_query_requires_all_tokens(
    client: httpx.AsyncClient,
):
    await _seed(client, name="Alpha Standard", description="team coding")
    await _seed(client, name="Beta Standard", description="personal tools")

    matched = await client.get("/api/v1/playbooks/library?q=alpha%20coding")
    names = {item["name"] for item in matched.json()["items"]}
    assert names == {"Alpha Standard"}

    missed = await client.get("/api/v1/playbooks/library?q=alpha%20missing")
    assert missed.json()["items"] == []


async def test_update_description_and_tags_persists(client: httpx.AsyncClient):
    item = await _seed(client)

    patch = await client.patch(
        f"/api/v1/playbooks/library/{item['id']}",
        json={"description": "新描述", "tags": ["audit", "v1"]},
    )

    assert patch.status_code == 200, patch.text
    updated = patch.json()["item"]
    assert updated["description"] == "新描述"
    assert updated["tags"] == ["audit", "v1"]
    # 二次拉取验证持久化
    refetch = await client.get("/api/v1/playbooks/library")
    match = next(i for i in refetch.json()["items"] if i["id"] == item["id"])
    assert match["description"] == "新描述"
    assert match["tags"] == ["audit", "v1"]
    # 直接读原始行，确认存储位置（R46(b)）
    row = (
        get_database()
        .get_connection()
        .execute(
            "SELECT spec_json FROM playbook_library WHERE id = ?", (item["id"],)
        )
        .fetchone()
    )
    spec = json.loads(row["spec_json"])
    assert spec["description"] == "新描述"
    assert spec["meta"]["tags"] == ["audit", "v1"]
    assert "metadata" not in spec


async def test_update_name(client: httpx.AsyncClient):
    item = await _seed(client, name="Old Name")

    patch = await client.patch(
        f"/api/v1/playbooks/library/{item['id']}",
        json={"name": "New Name"},
    )

    assert patch.status_code == 200
    assert patch.json()["item"]["name"] == "New Name"


async def test_update_unknown_id_returns_404(client: httpx.AsyncClient):
    response = await client.patch(
        "/api/v1/playbooks/library/does-not-exist",
        json={"description": "x"},
    )

    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "playbook_not_found"


async def test_update_records_activity_event(client: httpx.AsyncClient):
    item = await _seed(client)

    patch = await client.patch(
        f"/api/v1/playbooks/library/{item['id']}",
        json={"description": "audit"},
    )
    assert patch.status_code == 200, patch.text

    events = PlaybookEventRepository().list_recent("library:" + item["id"])
    assert any(event.event == "library_update" for event in events)
    recorded = next(event for event in events if event.event == "library_update")
    assert recorded.payload["changed"] == ["description"]


async def test_update_empty_name_returns_422(client: httpx.AsyncClient):
    item = await _seed(client)

    response = await client.patch(
        f"/api/v1/playbooks/library/{item['id']}",
        json={"name": "   "},
    )

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "invalid_name"


async def test_update_description_too_long_returns_422(
    client: httpx.AsyncClient,
):
    item = await _seed(client)

    response = await client.patch(
        f"/api/v1/playbooks/library/{item['id']}",
        json={"description": "x" * 4001},
    )

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "invalid_description"


async def test_update_invalid_tags_returns_422(client: httpx.AsyncClient):
    item = await _seed(client)

    too_many = await client.patch(
        f"/api/v1/playbooks/library/{item['id']}",
        json={"tags": [f"t{index}" for index in range(33)]},
    )
    assert too_many.status_code == 422
    assert too_many.json()["detail"]["code"] == "invalid_tags"

    too_long = await client.patch(
        f"/api/v1/playbooks/library/{item['id']}",
        json={"tags": ["x" * 65]},
    )
    assert too_long.status_code == 422
    assert too_long.json()["detail"]["code"] == "invalid_tags"


async def test_update_name_too_long_returns_422(client: httpx.AsyncClient):
    item = await _seed(client)

    response = await client.patch(
        f"/api/v1/playbooks/library/{item['id']}",
        json={"name": "x" * 201},
    )

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "invalid_name"


async def test_update_does_not_recompute_spec_hash(client: httpx.AsyncClient):
    item = await _seed(client, name="Hash Stable", description="before")
    before = PlaybookLibraryRepository().get(item["id"]).spec_hash

    response = await client.patch(
        f"/api/v1/playbooks/library/{item['id']}",
        json={"description": "after"},
    )

    assert response.status_code == 200
    after = PlaybookLibraryRepository().get(item["id"]).spec_hash
    assert after == before
    assert after == item["spec_hash"]


async def test_update_noop_does_not_record_event(client: httpx.AsyncClient):
    item = await _seed(client, name="Noop Stable", description="keep")

    response = await client.patch(
        f"/api/v1/playbooks/library/{item['id']}",
        json={},
    )

    assert response.status_code == 200
    returned = response.json()["item"]
    assert returned["name"] == "Noop Stable"
    assert returned["description"] == "keep"
    events = PlaybookEventRepository().list_recent("library:" + item["id"])
    assert all(event.event != "library_update" for event in events)


async def test_non_list_legacy_tags_do_not_break_list(client: httpx.AsyncClient):
    legacy_spec = {
        "schema_version": "1.0",
        "id": "legacy-tags",
        "name": "Legacy Tags",
        "description": "",
        "applies_to": {"project_types": [], "sub_types": []},
        "directory_layout": [],
        "stages": [{"id": "s1", "label": "阶段一"}],
        "global_rules": [],
        "todos": [],
        "ai_guidance": {},
        "meta": {"tags": "python"},
    }
    _insert_library_row("legacy-tags", "Legacy Tags", legacy_spec)

    listed = await client.get("/api/v1/playbooks/library")
    assert listed.status_code == 200
    item = next(i for i in listed.json()["items"] if i["id"] == "legacy-tags")
    assert item["tags"] == []

    searched = await client.get("/api/v1/playbooks/library?q=python")
    assert searched.status_code == 200
