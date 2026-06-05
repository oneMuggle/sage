"""
健康检查和基础路由测试
"""
import pytest


@pytest.mark.asyncio()
async def test_health_check(client):
    """健康检查端点返回 ok 状态"""
    resp = await client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert "version" in data


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
