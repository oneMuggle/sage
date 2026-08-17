"""WS-C P0-2: legacy /chat/stream 统一记忆写入路径集成测试

回归缺陷：legacy /chat/stream producer 持久化 user/assistant 消息后
**不触发** MemoryExtractor，只有 hex ChatService.run_turn 写记忆，
导致一半对话数据不进记忆系统。

win7 修复路径（与 main 的差异）：
- main 用 ``chat_service.extract_and_store_memory`` 模块级函数（#271 异步
  队列版本走 ``async_extractor``）；win7 在 Task 4 / Gap A 起统一走
  ``MemoryLifecycleManager.on_turn_complete``（见 ``backend/main.py``
  lifespan 装配 + ``legacy_routes.py`` producer），事实经
  ``aremember`` 持久化到 ``memories_episodic``（带 memory_category），
  而非 main 的 user_profile 分类路由。本文件按 win7 生产路径断言。

覆盖：
1. mock LLM 走完 /chat/stream 端到端 → memories_episodic 出现提取条目
   （接线不变性：assistant 落盘成功后才触发提取）
2. autoMemory=false（preferences.auto_memory）→ 不写入
3. 提取过程抛错 → 流照常完成, 不写记忆（best-effort 不破坏流式响应）
4. assistant 落盘失败 → 不触发提取（不产生无对应消息的脏记忆）

测试装配说明：win7 测试不走 FastAPI lifespan（ASGITransport 默认不
触发），而 producer 只在 ``request.app.state.lifecycle`` 存在时驱动提取。
每个测试经 ``wired_lifecycle`` fixture 按生产 wiring 补上（用 per-test 已
重置的 MemoryManager 单例 + SettingsRepository-backed prefs + 真实
MemoryExtractor——其 ``extract`` 类方法被各测试 patch），用后清回 None。
"""

import asyncio
import contextlib
import uuid
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio

from backend.core.legacy.agent_state import AgentEvent, AgentState
from backend.data.database import get_database
from backend.main import app

pytestmark = pytest.mark.integration

CHAT_STREAM_PATH = "/api/v1/chat/stream"

# 提取器 mock 固定返回的事实（绕过真实 LLM 提取）
_FIXED_FACTS = [
    {
        "content": "用户喜欢吃火锅",
        "importance": 7,
        "category": "preference",
        "tags": ["preference"],
    }
]


@pytest_asyncio.fixture()
async def wired_lifecycle():
    """Test 不走 FastAPI lifespan → app.state.lifecycle 缺失, producer 的
    ``lifecycle.on_turn_complete`` 永不触发。按生产装配补上:

    - memory_manager: per-test 已重置的 MemoryManager 单例（setup_test_db
      autouse 先于本 fixture 执行）
    - preferences_repo: SettingsRepository-backed async adapter —
      lifecycle 读 ``auto_memory`` pref（默认 True, 测试 2 置 false）
    - extractor: 真实 ``MemoryExtractor``（llm_client=None 即可——
      每个用例对 ``MemoryExtractor.extract`` 的类方法 patch 会覆盖行为）

    用后清回 ``app.state.lifecycle = None``, 防跨文件泄漏。
    """
    from backend.data.settings_repo import SettingsRepository
    from backend.memory import get_memory_manager
    from backend.memory.extractor import MemoryExtractor
    from backend.memory.hooks import HookRegistry
    from backend.memory.lifecycle import MemoryLifecycleManager

    class _AsyncPrefs:
        """thin async wrapper — lifecycle awaits prefs.get()."""

        def __init__(self, repo: SettingsRepository) -> None:
            self._repo = repo

        async def get(self, key: str):
            return self._repo.get(key)

    lifecycle = MemoryLifecycleManager(
        memory_manager=get_memory_manager(),
        hooks=HookRegistry(),
        preferences_repo=_AsyncPrefs(SettingsRepository()),
        extractor=MemoryExtractor(llm_client=None),
    )
    app.state.lifecycle = lifecycle
    yield lifecycle
    app.state.lifecycle = None


async def _run_chat_stream(client, session_id: str, message: str) -> str:
    """POST /chat/stream + attach 消费 + 等 producer 跑完，返回 attach 响应文本。"""

    # mock SageAgent.run_loop 直接 DONE（不调真实 LLM）
    async def mock_run_loop(messages, max_iterations=5, **kwargs):
        yield AgentEvent(state=AgentState.THINKING, iteration=0)
        yield AgentEvent(
            state=AgentState.DONE,
            iteration=0,
            content="好的,我记住了,您喜欢吃火锅。成都的火锅店确实很多,我可以给您推荐几家口碑不错的。",
        )

    with patch("backend.api.legacy_routes.SageAgent") as MockAgent:
        MockAgent.return_value.run_loop = mock_run_loop

        create_stream = await client.post(
            CHAT_STREAM_PATH,
            json={"session_id": session_id, "message": message},
        )
        assert create_stream.status_code == 200, create_stream.text
        stream_id = create_stream.json()["streamId"]

        attach = await client.get(f"{CHAT_STREAM_PATH}/{stream_id}")
        assert attach.status_code == 200

        # 等 producer 后台 task 完整跑完（落盘 + 记忆提取都在 producer 内）
        entry = app.state.streams.get(stream_id)
        if entry and entry.task:
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await entry.task

    return attach.text


def _episodic_rows() -> list:
    conn = get_database().get_connection()
    return conn.execute(
        "SELECT content, session_id, memory_category "
        "FROM memories_episodic WHERE is_valid = 1"
    ).fetchall()


def _ensure_session(session_id: str) -> None:
    """§1.3a: PRAGMA foreign_keys=ON — messages.session_id FKs 到 sessions.id。
    user/assistant 消息落盘需要父 session 行；提取链路（assistant 落盘成功
    后才触发）同样需要它。"""
    from backend.tests.conftest import ensure_session

    ensure_session(get_database(), session_id)


@pytest.mark.asyncio()
async def test_legacy_chat_stream_extracts_memory_after_assistant_persisted(
    client, wired_lifecycle
):
    """一次成功 chat 后提取条目落库（autoMemory 缺省 True）。

    win7 lifecycle 路径把提取事实经 ``aremember`` 持久化到
    ``memories_episodic``（带 ``memory_category``），而非 main 的
    ``user_profile`` 分类路由。
    """
    session_id = str(uuid.uuid4())
    _ensure_session(session_id)
    user_message = "我特别喜欢吃火锅,尤其是四川麻辣口味的,以后请多给我推荐火锅店"

    # mock 掉 MemoryExtractor.extract（类方法级 patch）：
    # helper 在调用点才 from backend.memory.extractor import MemoryExtractor,
    # patch 类属性后实例化拿到的就是 mock 版 extract, 其余链路
    # （MemoryLifecycleManager._persist_fact → MemoryManager.aremember）
    # 全部走真实实现。
    with patch(
        "backend.memory.extractor.MemoryExtractor.extract",
        new=AsyncMock(return_value=_FIXED_FACTS),
    ) as mock_extract:
        attach_text = await _run_chat_stream(client, session_id, user_message)

    # 流正常完成
    assert '"state": "done"' in attach_text or '"state":"done"' in attach_text

    # 提取被触发, 且传入的就是本轮 user / assistant 文本
    # （lifecycle 用位置参数调 extract(user_msg, assistant_msg)）
    mock_extract.assert_awaited()
    call_args = mock_extract.await_args
    assert call_args.args[0] == user_message
    assert "火锅" in call_args.args[1]

    # 事实落库到 memories_episodic（session 关联 + preference 分类标记）
    rows = _episodic_rows()
    matched = [r for r in rows if "用户喜欢吃火锅" in r["content"]]
    assert matched, f"memories_episodic 未出现提取事实: {[dict(r) for r in rows]}"
    assert matched[0]["session_id"] == session_id
    assert matched[0]["memory_category"] == "preference"


@pytest.mark.asyncio()
async def test_legacy_chat_stream_skips_extraction_when_auto_memory_disabled(
    client, wired_lifecycle
):
    """preferences.auto_memory=false 时不写记忆。

    lifecycle gate 读的是 ``preferences.auto_memory``（snake_case, Task 2 /
    Gap B 新增的顶层 key）而非 legacy ``app_settings.autoMemory`` ——
    win7 生产路径（MemoryLifecycleManager）统一走前者。
    """
    from backend.data.settings_repo import SettingsRepository

    SettingsRepository().set("auto_memory", "false")

    session_id = str(uuid.uuid4())
    _ensure_session(session_id)
    with patch(
        "backend.memory.extractor.MemoryExtractor.extract",
        new=AsyncMock(return_value=_FIXED_FACTS),
    ) as mock_extract:
        attach_text = await _run_chat_stream(client, session_id, "我喜欢吃火锅, 请记住这一点")

    assert '"state": "done"' in attach_text or '"state":"done"' in attach_text
    mock_extract.assert_not_awaited()
    assert _episodic_rows() == []


@pytest.mark.asyncio()
async def test_legacy_chat_stream_extraction_failure_does_not_break_stream(
    client, wired_lifecycle
):
    """提取过程抛错只 warning：流照常完成, 不写记忆, 不 500。"""
    session_id = str(uuid.uuid4())
    _ensure_session(session_id)
    with patch(
        "backend.memory.extractor.MemoryExtractor.extract",
        new=AsyncMock(side_effect=RuntimeError("extractor boom")),
    ):
        attach_text = await _run_chat_stream(client, session_id, "我喜欢吃火锅, 请记住这一点")

    # 流未被记忆提取错误打断
    assert '"state": "done"' in attach_text or '"state":"done"' in attach_text
    assert "RuntimeError" not in attach_text
    assert _episodic_rows() == []


@pytest.mark.asyncio()
async def test_legacy_chat_stream_assistant_persist_failure_skips_extraction(
    client, wired_lifecycle
):
    """assistant 落盘失败时不触发提取（不产生无对应消息的脏记忆）。

    producer 的 lifecycle 调用以 ``assistant_message_id is not None`` 为门：
    落盘失败 → id 为 None → 不驱动 on_turn_complete（#269 契约）。
    """
    session_id = str(uuid.uuid4())
    _ensure_session(session_id)

    with patch(
        "backend.memory.extractor.MemoryExtractor.extract",
        new=AsyncMock(return_value=_FIXED_FACTS),
    ) as mock_extract, patch(
        "backend.api.legacy_routes.MessageRepository"
    ) as MockMsgRepo:
        # 第一次 save(user) 成功, 第二次 save(assistant) 抛错
        MockMsgRepo.return_value.save.side_effect = [None, RuntimeError("simulated db down")]
        attach_text = await _run_chat_stream(client, session_id, "我喜欢吃火锅, 请记住这一点")

    # 流仍正常完成（持久化失败只 warning）
    assert '"state": "done"' in attach_text or '"state":"done"' in attach_text
    # assistant 未落盘 → 提取不应触发
    mock_extract.assert_not_awaited()
    assert _episodic_rows() == []
