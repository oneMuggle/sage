"""
健康检查和基础路由测试
"""
import pytest

from backend.api.local_auth import ownership_health_proof

pytestmark = pytest.mark.integration


@pytest.mark.asyncio()
async def test_health_check(client):
    """健康检查端点返回 ok 状态"""
    resp = await client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert set(data) == {"status", "buildId", "pid", "generation"}


@pytest.mark.asyncio()
async def test_health_exposes_only_non_sensitive_supervisor_fields(client):
    """Health is safe for unauthenticated liveness probes and ownership checks."""
    resp = await client.get("/health")

    assert resp.status_code == 200
    assert set(resp.json()) == {"status", "buildId", "pid", "generation"}
    assert "ownershipToken" not in resp.json()


async def test_health_proof_requires_supervisor_token(client, monkeypatch):
    monkeypatch.setenv("SAGE_BACKEND_OWNERSHIP_TOKEN", "owner-token")
    public = await client.get("/health/proof")
    assert public.status_code == 404
    valid = await client.get(
        "/health/proof", headers={"X-Sage-Backend-Ownership": "owner-token"}
    )
    assert valid.status_code == 200
    data = valid.json()
    assert data["proof"] == ownership_health_proof(
        "owner-token", data["buildId"], data["generation"], data["pid"]
    )
    assert "ownershipToken" not in data


@pytest.mark.asyncio()
async def test_health_proof_rejects_stale_token(client, monkeypatch):
    monkeypatch.setenv("SAGE_BACKEND_OWNERSHIP_TOKEN", "owner-token")
    response = await client.get(
        "/health/proof", headers={"X-Sage-Backend-Ownership": "stale-token"}
    )
    assert response.status_code == 404



    """Desktop dev origin is allowed while arbitrary websites are not."""
    allowed = await client.options(
        "/health",
        headers={
            "Origin": "http://localhost:1420",
            "Access-Control-Request-Method": "GET",
        },
    )
    denied = await client.options(
        "/health",
        headers={
            "Origin": "https://evil.example",
            "Access-Control-Request-Method": "GET",
        },
    )

    assert allowed.headers["access-control-allow-origin"] == "http://localhost:1420"
    assert "access-control-allow-origin" not in denied.headers


@pytest.mark.asyncio()
async def test_sensitive_routes_require_local_bearer_token(client):
    """Application middleware protects endpoints from separately mounted routers."""
    headers = {
        "Authorization": "",
        "X-Sage-Local-Authorization": "",
    }
    sessions = await client.get("/api/v1/sessions", headers=headers)
    mcp = await client.get("/api/v1/mcp/status", headers=headers)

    assert sessions.status_code == 401
    assert mcp.status_code == 401


@pytest.mark.asyncio()
async def test_openapi_docs(client):
    """OpenAPI 文档端点可访问"""
    resp = await client.get("/openapi.json")
    assert resp.status_code == 200
    schema = resp.json()
    assert "openapi" in schema


@pytest.mark.asyncio()
async def test_docs_ui(client):
    """Swagger UI 端点可访问"""
    resp = await client.get("/docs")
    assert resp.status_code == 200
