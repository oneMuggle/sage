"""
Sage 后端测试 - 共享 fixtures
"""
import os
import sys
import tempfile

import pytest
import pytest_asyncio

# 确保项目根目录在 sys.path 中
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import httpx

from backend.main import app


@pytest.fixture()
def tmp_db_path():
    """创建临时数据库文件，测试后自动清理"""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        yield f.name
    if os.path.exists(f.name):
        os.unlink(f.name)


@pytest.fixture(autouse=True)
def setup_test_db(tmp_db_path):
    """每个测试自动使用独立临时数据库"""
    import backend.data.database as db_mod
    db_mod._db = db_mod.Database(db_path=tmp_db_path)
    db_mod._db.init_db()
    yield db_mod._db
    db_mod._db.close()
    db_mod._db = None


@pytest_asyncio.fixture
async def client():
    """提供异步 HTTP 测试客户端"""
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
        yield c


# ========== LLM Mock Fixtures (P0-T7) ==========
import respx
from httpx import Response


@pytest.fixture()
def mock_llm_ok():
    """Mock LLM 返回正常 chat completion.

    用法：
        def test_something(mock_llm_ok):
            # 在测试中，调用 LLM 的请求会被 mock
            response = await llm_client.chat(...)
            assert response == expected
    """
    with respx.mock(base_url="https://api.example.com", assert_all_called=False) as mock:
        mock.post("/v1/chat/completions").mock(
            return_value=Response(
                200,
                json={
                    "id": "test-completion",
                    "object": "chat.completion",
                    "created": 1700000000,
                    "model": "test-model",
                    "choices": [
                        {
                            "index": 0,
                            "message": {"role": "assistant", "content": "Hello from mock!"},
                            "finish_reason": "stop",
                        }
                    ],
                    "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
                },
            )
        )
        yield mock


@pytest.fixture()
def mock_llm_rate_limit():
    """Mock LLM 返回 429 限流响应"""
    with respx.mock(base_url="https://api.example.com", assert_all_called=False) as mock:
        mock.post("/v1/chat/completions").mock(
            return_value=Response(
                429,
                json={"error": {"message": "Rate limit exceeded", "type": "rate_limit_error"}},
            )
        )
        yield mock


@pytest.fixture()
def mock_llm_timeout():
    """Mock LLM 模拟超时（抛 httpx.TimeoutException）。

    使用 ``httpx.TimeoutException``（而非 builtin ``TimeoutError``）以匹配
    ``LLMClient.chat`` 中 ``except httpx.TimeoutException`` 分支，
    确保被映射为 ``LLMErrorType.TIMEOUT`` 而不是 fallback 到 UNKNOWN。
    """
    with respx.mock(base_url="https://api.example.com", assert_all_called=False) as mock:
        mock.post("/v1/chat/completions").mock(
            side_effect=httpx.TimeoutException("LLM request timed out")
        )
        yield mock


@pytest.fixture()
def mock_llm_server_error():
    """Mock LLM 返回 500 服务端错误"""
    with respx.mock(base_url="https://api.example.com", assert_all_called=False) as mock:
        mock.post("/v1/chat/completions").mock(
            return_value=Response(
                500,
                json={"error": {"message": "Internal server error"}},
            )
        )
        yield mock


@pytest.fixture()
def sample_messages():
    """测试用消息列表（标准 system + user 开头）"""
    return [
        {"role": "system", "content": "You are a helpful assistant."},
        {"role": "user", "content": "Hi"},
    ]


@pytest.fixture()
def sample_user_query():
    """测试用用户查询"""
    return "What is the capital of France?"


@pytest.fixture()
def tmp_data_dir(tmp_path):
    """临时数据目录（避免污染真实 data/）—— 直接返回 tmp_path 便于测试中使用"""
    return tmp_path
