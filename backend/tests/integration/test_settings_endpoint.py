"""GET/PUT /settings 端点集成测试"""

import os
from unittest.mock import MagicMock

import pytest
from httpx import ASGITransport, AsyncClient

from backend.api.hex_routes import get_chat_service
from backend.main import app

_API_MODE = os.environ.get("API_MODE", "legacy").lower()
_HEX_ONLY = pytest.mark.skipif(
    _API_MODE != "hex",
    reason=f"本文件测 hex 端点 /settings；当前 API_MODE={_API_MODE!r}（需 hex）",
)


# PG3.2: brief 的 PUT 端点依赖 svc.events.emit，需 DI 注入 ChatService。
# 现有项目测试惯例：conftest 不触发 FastAPI lifespan，需手动 override DI。
# 装配最简 ChatService mock（含 events.emit 占位）让端到端跑通。
@pytest.fixture(autouse=True)
def _hex_di_override():
    from sage_core import Message, Role

    from backend.adapters.out.llm.mock_adapter import MockLLMAdapter
    from backend.adapters.out.metric.noop_adapter import NoopMetricAdapter
    from backend.adapters.out.storage.memory_adapter import MemoryStorageAdapter
    from backend.adapters.out.tool.inproc_adapter import InprocToolAdapter
    from backend.application.services.chat_service import ChatService

    mock_tool = MagicMock()
    mock_tool.execute.return_value = MagicMock(success=True, output="ok", error=None)
    mock_registry = MagicMock()
    mock_registry.list.return_value = []
    mock_registry.get.return_value = mock_tool

    fake_svc = ChatService(
        llm=MockLLMAdapter(responses=[Message(role=Role.ASSISTANT, content="ok")]),
        tools=InprocToolAdapter(registry=mock_registry),
        skills=MagicMock(),
        storage=MemoryStorageAdapter(),
        metrics=NoopMetricAdapter(),
        events=MagicMock(),  # emit 接受任意 dict
    )
    saved = app.dependency_overrides.get(get_chat_service)
    app.dependency_overrides[get_chat_service] = lambda: fake_svc
    yield
    if saved is not None:
        app.dependency_overrides[get_chat_service] = saved
    else:
        app.dependency_overrides.pop(get_chat_service, None)


@pytest.mark.asyncio()
@_HEX_ONLY
async def test_get_settings_returns_null_when_no_data():
    async with AsyncClient(
        transport=ASGITransport(app=app),  # type: ignore[arg-type]
        base_url="http://test",
    ) as ac:
        resp = await ac.get("/api/v1/settings")
    assert resp.status_code == 200
    assert resp.json() is None


@pytest.mark.asyncio()
@_HEX_ONLY
async def test_put_settings_persists_and_get_returns():
    async with AsyncClient(
        transport=ASGITransport(app=app),  # type: ignore[arg-type]
        base_url="http://test",
    ) as ac:
        payload = {
            "version": "3.0.0",
            "endpoints": [],
            "modelSelections": {
                "chatModel": {"endpointId": None, "modelId": None},
                "visionModel": {"endpointId": None, "modelId": None},
                "embeddingModel": {"endpointId": None, "modelId": None},
            },
            "streaming": True,
            "autoMemory": True,
            "confirmDelete": True,
            "compactMode": False,
            "maxContext": 4096,
            "temperature": 0.7,
            "proxyMode": "system",
            "proxyUrl": "",
            "tlsVersion": "1.2",
        }
        put_resp = await ac.put("/api/v1/settings", json=payload)
        assert put_resp.status_code == 200
        assert put_resp.json()["status"] == "ok"

        get_resp = await ac.get("/api/v1/settings")
        assert get_resp.status_code == 200
        data = get_resp.json()
        assert data["maxContext"] == 4096
        assert data["version"] == "3.0.0"
