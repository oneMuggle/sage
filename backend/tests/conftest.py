"""
Sage 后端测试 - 共享 fixtures
"""

import contextlib
import os
import sys
import tempfile

import pytest
import pytest_asyncio

# 确保项目根目录在 sys.path 中
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)



_SSL_BOOTSTRAP_TEST = os.path.join("backend", "tests", "unit", "test_ssl_bootstrap.py")


def _is_ssl_bootstrap_test(request):
    """Keep the AST-only SSL tests free of shared application fixtures."""
    return str(request.node.fspath).endswith(_SSL_BOOTSTRAP_TEST)


@pytest.fixture(autouse=True)
def _configure_test_http_client_auth(request, monkeypatch):
    """为直接创建的测试 HTTP 客户端注入合成本地 capability。"""
    # These tests intentionally verify that an empty Authorization header is
    # omitted when forwarding credentials to the configured LLM upstream.
    if str(request.node.fspath).endswith("backend/tests/integration/test_llm_proxy_routes.py"):
        return

    import httpx
    from starlette.testclient import TestClient

    headers = {"X-Sage-Local-Authorization": "Bearer test-local-auth-token"}
    original_test_client_init = TestClient.__init__
    original_async_client_init = httpx.AsyncClient.__init__

    def test_client_init(self, *args, **kwargs):
        kwargs.setdefault("headers", headers.copy())
        return original_test_client_init(self, *args, **kwargs)

    def async_client_init(self, *args, **kwargs):
        kwargs.setdefault("headers", headers.copy())
        return original_async_client_init(self, *args, **kwargs)

    monkeypatch.setattr(TestClient, "__init__", test_client_init)
    monkeypatch.setattr(httpx.AsyncClient, "__init__", async_client_init)


@pytest.fixture()
def tmp_db_path():
    """创建临时数据库文件，测试后自动清理"""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        yield f.name
    if os.path.exists(f.name):
        os.unlink(f.name)


@pytest.fixture(autouse=True)
def setup_test_db(request):
    """每个测试自动使用独立临时数据库。

    AST-only tests must not import the application during collection/setup.
    """
    if _is_ssl_bootstrap_test(request):
        yield None
        return

    tmp_db_path = request.getfixturevalue("tmp_db_path")
    import backend.data.database as db_mod

    # Local desktop capability: deterministic test-only token, never a production secret.
    from backend.api.local_auth import initialize_local_auth_token

    # A4: WakeStore 单例绑定全局 Database，必须随临时库一起重置，
    # 否则下一个用例拿到持有已关闭连接的旧 store。
    from backend.application.services.wake_store import reset_wake_store
    from backend.main import app
    from backend.memory.registry import reset_memory_manager

    # UserProfileStore 单例同样绑定全局 Database, 必须随临时库重置
    from backend.memory.user_profile import reset_user_profile

    # SkillLifecycleStore 单例同理（技能归档策展状态）
    from backend.skills.lifecycle import reset_lifecycle_store

    # SkillUsageStore 单例同理
    from backend.skills.usage import reset_usage_store

    monkeypatch = request.getfixturevalue("monkeypatch")
    monkeypatch.setenv("SAGE_LOCAL_AUTH_TOKEN", "test-local-auth-token")
    from backend.api import local_auth
    local_auth._local_auth_token = None
    initialize_local_auth_token()

    db_mod._db = db_mod.Database(db_path=tmp_db_path)
    db_mod._db.init_db()
    reset_wake_store()
    reset_user_profile()
    reset_usage_store()
    reset_lifecycle_store()
    # MemoryExtractionQueue 单例绑定全局事件循环，必须随测试重置
    # （取消残留 worker，避免跨测试泄漏 + "task was destroyed" 警告）
    from backend.memory.async_extractor import reset_memory_extraction_queue

    reset_memory_extraction_queue()
    # PR-3: 与生产 lifespan 保持一致, 启动时种子化 4 个默认 agent.
    # 测试不走 FastAPI lifespan, 显式调一次以模拟.
    from backend.data.agent_repo import AgentRepository

    AgentRepository().seed_defaults_if_empty()

    # 重置 MemoryManager 单例，确保每个测试使用新的数据库
    reset_memory_manager()

    # M1-M2: 修复 pre-existing 测试隔离问题 — test_chat_stream.py
    # 不使用 client fixture 也未清理 app.state.streams._entries,
    # 会在跨测试文件时泄漏. 在 autouse setup 中强制清空.

    # M1-M2 修复同上;同时确保 app.state.streams 已初始化: 测试不走 FastAPI
    # lifespan(ASGITransport 默认不触发), 直接自建 AsyncClient 的测试
    # (如 test_chat_orchestration_stream) 依赖注册表已存在。与 client fixture
    # 的兜底逻辑保持一致(conftest.py client fixture 内也做了同样 init)。
    if not hasattr(app.state, "streams") or app.state.streams is None:
        from backend.api.chat_stream_registry import StreamRegistry

        app.state.streams = StreamRegistry()

    if hasattr(app.state, "streams") and app.state.streams is not None:
        for entry in list(app.state.streams._entries.values()):
            if entry.task is not None and not entry.task.done():
                # pytest-asyncio 0.23.3 默认 function-scope event loop:
                # 上一个测试文件结束时 close loop,残留 task 的 cancel
                # 会在已关闭 loop 上触发 _check_closed → RuntimeError。
                # entry 持有的 Queue 随 Python GC 释放,跳过 cancel 不影响隔离。
                # 现象: 跨文件异步测试 ERROR 100% 触发,
                # 典型 fixture 名 setup_test_db 的 ERROR at setup。
                with contextlib.suppress(RuntimeError):
                    entry.task.cancel()
        app.state.streams._entries.clear()

    yield db_mod._db
    # test_db_path 用 importlib.reload 重建模块后 _db 会被重置为 None；
    # 守 None 防 AttributeError
    if db_mod._db is not None:
        db_mod._db.close()
    db_mod._db = None
    # 测试结束后也重置 MemoryManager
    reset_memory_manager()
    reset_wake_store()


@pytest_asyncio.fixture
async def client():
    """提供异步 HTTP 测试客户端"""
    import httpx

    from backend.main import app

    # I2: tests 不走 FastAPI lifespan(ASGITransport 默认不触发),
    # 但 app.state.streams 必须存在否则 /chat/stream/{id} 端点 500。
    # 这里兜底初始化并在测试间清空,保证隔离。
    if not hasattr(app.state, "streams") or app.state.streams is None:
        from backend.api.chat_stream_registry import StreamRegistry

        app.state.streams = StreamRegistry()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
        headers={"X-Sage-Local-Authorization": "Bearer test-local-auth-token"},
    ) as c:
        yield c
    # 清理:取消任何残留 task,清空注册表
    if hasattr(app.state, "streams") and app.state.streams is not None:
        for entry in list(app.state.streams._entries.values()):
            if entry.task is not None and not entry.task.done():
                # pytest-asyncio 0.23.3 默认 function-scope event loop:
                # 上一个测试文件结束时 close loop,残留 task 的 cancel
                # 会在已关闭 loop 上触发 _check_closed → RuntimeError。
                # entry 持有的 Queue 随 Python GC 释放,跳过 cancel 不影响隔离。
                # 现象: 跨文件异步测试 ERROR 100% 触发,
                # 典型 fixture 名 setup_test_db 的 ERROR at setup。
                with contextlib.suppress(RuntimeError):
                    entry.task.cancel()
        app.state.streams._entries.clear()


# ========== LLM Mock Fixtures (P0-T7) ==========


@pytest.fixture()
def mock_llm_ok():
    """Mock LLM 返回正常 chat completion.

    用法：
        def test_something(mock_llm_ok):
            # 在测试中，调用 LLM 的请求会被 mock
            response = await llm_client.chat(...)
            assert response == expected
    """
    import respx
    from httpx import Response

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
    import respx
    from httpx import Response

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
    import httpx
    import respx

    with respx.mock(base_url="https://api.example.com", assert_all_called=False) as mock:
        mock.post("/v1/chat/completions").mock(
            side_effect=httpx.TimeoutException("LLM request timed out")
        )
        yield mock


@pytest.fixture()
def mock_llm_server_error():
    """Mock LLM 返回 500 服务端错误"""
    import respx
    from httpx import Response

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


def ensure_session(db, session_id: str, title: str = "Test Session") -> str:
    """Idempotently create a session row in the test DB.

    Tests that insert child rows referencing ``session_id`` (messages,
    memories_episodic) used to silently succeed because ``PRAGMA
    foreign_keys=ON`` was off in the test DB. Once that pragma is enabled
    (§1.3a item c), the inserts correctly fail unless the parent session
    row exists. Call this helper from tests to satisfy the FK.

    Usage:
        def test_something(setup_test_db):
            ensure_session(setup_test_db, "sess-1")
            # ... insert child rows referencing "sess-1"
    """
    import time

    ts = int(time.time())
    conn = db.get_connection()
    conn.execute(
        "INSERT OR IGNORE INTO sessions (id, title, created_at, updated_at) "
        "VALUES (?, ?, ?, ?)",
        (session_id, title, ts, ts),
    )
    conn.commit()
    return session_id


@pytest.fixture()
def sample_session(setup_test_db):
    """Pre-create a default ``sess-1`` session row for tests that need a
    FK-referenced session but don't care about the specific session_id.

    See :func:`ensure_session` for the underlying helper that lets tests
    create other session_ids explicitly.
    """
    return ensure_session(setup_test_db, "sess-1")


@pytest.fixture()
def tmp_data_dir(tmp_path):
    """临时数据目录（避免污染真实 data/）—— 直接返回 tmp_path 便于测试中使用"""
    return tmp_path


@pytest.fixture(autouse=False)
def reset_skill_adapter():  # noqa: PT004 - 空 yield 是合法的 teardown-only fixture
    """M2b: 重置 skills 单例缓存 (enabled / usage_count)。

    单例缓存已在 ``backend.adapters.out.skill.inproc`` 模块下; 路由层只
    是 thin wrapper 委托. 测试 fixture 必须清 inproc 的模块级缓存,
    否则 ``SAGE_SKILLS_DIR`` 改动后第二次测试仍读到旧 adapter.
    """
    import backend.adapters.out.skill.inproc as inproc_mod

    inproc_mod._skill_adapter_singleton = None
    yield
    inproc_mod._skill_adapter_singleton = None
