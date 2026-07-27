"""Integration tests for session workspace HTTP routes."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import AsyncIterator

import httpx
import pytest
import pytest_asyncio

from backend.data import database as database_module
from backend.data.database import Database
from backend.main import app
from backend.office.models import (
    OfficeDocStatus,
    OfficeDocType,
    OfficeDocumentMetadata,
    OfficeDocumentSummary,
)
from backend.office.session_workspace import bind_session_workspace
from backend.office.storage import save_document


@pytest.fixture()
def db(monkeypatch: pytest.MonkeyPatch) -> Database:
    test_db = Database(":memory:")
    test_db.init_db()
    monkeypatch.setattr(database_module, "_db", test_db)
    return test_db


@pytest.fixture()
def conn(db: Database) -> sqlite3.Connection:
    return db.get_connection()


@pytest.fixture()
def session_id(conn: sqlite3.Connection) -> str:
    value = "session-workspace"
    conn.execute(
        "INSERT INTO sessions (id, title, created_at, updated_at) VALUES (?, ?, ?, ?)",
        (value, "Workspace", 1, 1),
    )
    conn.commit()
    return value


@pytest.fixture()
def workspace(tmp_path: Path) -> Path:
    path = tmp_path / "workspace"
    path.mkdir()
    return path


@pytest_asyncio.fixture()
async def client(db: Database) -> AsyncIterator[httpx.AsyncClient]:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as value:
        yield value


@pytest.mark.asyncio()
async def test_get_unbound_workspace_returns_null(
    client: httpx.AsyncClient, session_id: str
) -> None:
    response = await client.get(f"/api/v1/sessions/{session_id}/workspace")
    assert response.status_code == 200
    assert response.json() == {"binding": None}


@pytest.mark.asyncio()
async def test_search_without_binding_is_forbidden(
    client: httpx.AsyncClient, session_id: str
) -> None:
    response = await client.get(
        f"/api/v1/sessions/{session_id}/workspace/files", params={"q": "report", "limit": 20}
    )
    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "workspace_not_bound"


@pytest.mark.asyncio()
async def test_search_replaced_workspace_symlink_returns_gone(
    client: httpx.AsyncClient,
    conn: sqlite3.Connection,
    session_id: str,
    workspace: Path,
    tmp_path: Path,
) -> None:
    bind_session_workspace(conn, session_id, str(workspace), now_ms=1)
    outside = tmp_path / "outside"
    outside.mkdir()
    moved_workspace = tmp_path / "moved-workspace"
    workspace.rename(moved_workspace)
    try:
        workspace.symlink_to(outside, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks are not supported")

    response = await client.get(f"/api/v1/sessions/{session_id}/workspace/files", params={"q": "x"})

    assert response.status_code == 410
    assert response.json()["detail"]["code"] == "workspace_revoked"


@pytest.mark.asyncio()
async def test_empty_search_without_binding_is_forbidden(
    client: httpx.AsyncClient, session_id: str
) -> None:
    response = await client.get(f"/api/v1/sessions/{session_id}/workspace/files", params={"q": ""})

    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "workspace_not_bound"


@pytest.mark.asyncio()
async def test_bind_get_rebind_and_revoke_workspace(
    client: httpx.AsyncClient, session_id: str, workspace: Path, tmp_path: Path
) -> None:
    first = await client.put(
        f"/api/v1/sessions/{session_id}/workspace", json={"workspace_path": str(workspace)}
    )
    assert first.status_code == 200
    assert first.json()["binding"]["generation"] == 1
    fetched = await client.get(f"/api/v1/sessions/{session_id}/workspace")
    assert fetched.json() == first.json()
    second_workspace = tmp_path / "second"
    second_workspace.mkdir()
    rebound = await client.put(
        f"/api/v1/sessions/{session_id}/workspace", json={"workspace_path": str(second_workspace)}
    )
    assert rebound.status_code == 200
    assert rebound.json()["binding"]["generation"] == 2
    revoked = await client.delete(f"/api/v1/sessions/{session_id}/workspace")
    assert revoked.status_code == 200
    assert revoked.json() == {"revoked": True, "generation": 3}
    assert (await client.get(f"/api/v1/sessions/{session_id}/workspace")).json() == {
        "binding": None
    }


@pytest.mark.asyncio()
@pytest.mark.parametrize("method", ["get", "put", "delete"])
async def test_unknown_session_returns_404(
    client: httpx.AsyncClient, method: str, workspace: Path
) -> None:
    kwargs = {"json": {"workspace_path": str(workspace)}} if method == "put" else {}
    response = await getattr(client, method)("/api/v1/sessions/missing/workspace", **kwargs)
    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "session_not_found"


@pytest.mark.asyncio()
async def test_invalid_path_returns_safe_400_without_absolute_path(
    client: httpx.AsyncClient, session_id: str, tmp_path: Path
) -> None:
    sentinel = str(tmp_path / "sensitive-does-not-exist")
    response = await client.put(
        f"/api/v1/sessions/{session_id}/workspace", json={"workspace_path": sentinel}
    )
    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "invalid_workspace_path"
    assert sentinel not in response.text


@pytest.mark.asyncio()
async def test_bind_missing_workspace_path_uses_pydantic_422(
    client: httpx.AsyncClient, session_id: str
) -> None:
    assert (
        await client.put(f"/api/v1/sessions/{session_id}/workspace", json={})
    ).status_code == 422


@pytest.mark.asyncio()
async def test_search_validates_query_and_limit_with_pydantic(
    client: httpx.AsyncClient, conn: sqlite3.Connection, session_id: str, workspace: Path
) -> None:
    bind_session_workspace(conn, session_id, str(workspace), now_ms=1)
    for params in ({"q": "界" * 201}, {"q": "report", "limit": 0}, {"q": "report", "limit": 51}):
        assert (
            await client.get(f"/api/v1/sessions/{session_id}/workspace/files", params=params)
        ).status_code == 422


@pytest.mark.asyncio()
async def test_search_response_has_typed_shape(
    client: httpx.AsyncClient, conn: sqlite3.Connection, session_id: str, workspace: Path
) -> None:
    bind_session_workspace(conn, session_id, str(workspace), now_ms=1)
    managed = workspace / "office" / "ppt" / "doc-1"
    managed.mkdir(parents=True)
    (managed / "report.pptx").write_bytes(b"ppt")
    save_document(
        conn,
        OfficeDocumentSummary(
            id="doc-1",
            workspace_path=str(workspace.resolve()),
            doc_type=OfficeDocType.PPT,
            original_filename=None,
            generated_filename="report.pptx",
            status=OfficeDocStatus.GENERATED,
            created_at=1,
            updated_at=1,
            metadata=OfficeDocumentMetadata(file_size_bytes=3),
        ),
    )
    response = await client.get(
        f"/api/v1/sessions/{session_id}/workspace/files", params={"q": "report"}
    )
    assert response.status_code == 200
    assert response.json() == {
        "results": [
            {
                "name": "report.pptx",
                "kind": "office-ppt",
                "doc_type": "ppt",
                "doc_id": "doc-1",
                "size_bytes": 3,
                "needs_import": False,
                "source_path": None,
            }
        ],
        "total": 1,
    }
