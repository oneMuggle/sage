"""HTTP contract tests for the recent-projects record endpoint."""

import pytest
from httpx import ASGITransport, AsyncClient

from backend.main import app

pytestmark = pytest.mark.integration


@pytest.mark.asyncio()
async def test_record_recent_project_returns_empty_204(monkeypatch, tmp_path):
    """Recording a project keeps 204 semantics and sends no response body."""
    from backend.api import wiki_routes

    recorded = []
    monkeypatch.setattr(
        wiki_routes,
        "record_recent",
        lambda path, name, intent: recorded.append((path, name, intent)),
    )

    project = tmp_path / "project"
    (project / "wiki").mkdir(parents=True)
    payload = {"path": str(project), "name": "", "intent": "create"}
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post("/api/v1/wiki/recent-projects/record", json=payload)

    assert response.status_code == 204
    assert response.content == b""
    assert recorded == [(str(project.resolve()), "project", "create")]
