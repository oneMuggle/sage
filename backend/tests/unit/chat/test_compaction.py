"""
M4 会话压缩单元测试 — backend/chat/compaction.py

覆盖:
- token 估算复用 working.py 口径（dict + Message 对象两种入参）
- should_compact 阈值 + 消息数地板 + env/settings 覆盖
- prompt 结构（中文四段式）与续接消息格式
- compact_messages 的 keep_recent 边界、LLM 失败/空摘要抛 CompactionError
"""

import time

import pytest

from backend.chat.compaction import (
    CONTINUATION_PREFIX,
    DEFAULT_COMPACT_THRESHOLD_TOKENS,
    MIN_COMPACT_MESSAGE_COUNT,
    CompactionError,
    build_compaction_prompt,
    compact_messages,
    continuation_message,
    estimate_messages_tokens,
    get_compact_threshold,
    should_compact,
)
from backend.data.session_repo import Message
from backend.memory.working import WorkingMemory, estimate_tokens

pytestmark = pytest.mark.unit


def _dict_messages(n: int, content: str = "这是一条用于压缩测试的消息内容") -> list:
    return [
        {"role": "user" if i % 2 == 0 else "assistant", "content": f"{content} #{i}"}
        for i in range(n)
    ]


def _db_messages(n: int) -> list:
    base = int(time.time() * 1000)
    return [
        Message(
            id=f"m-{i}",
            session_id="s-1",
            role="user" if i % 2 == 0 else "assistant",
            content=f"消息内容 #{i}",
            created_at=base + i,
        )
        for i in range(n)
    ]


# ---- estimate_messages_tokens ------------------------------------------------


def test_estimate_messages_tokens_reuses_working_estimator():
    """估算口径必须与 WorkingMemory._estimate_tokens 完全一致（role+content）。"""
    messages = _dict_messages(4)
    wm = WorkingMemory()
    expected = sum(wm._estimate_tokens(m["role"] + m["content"]) for m in messages)
    assert estimate_messages_tokens(messages) == expected


def test_estimate_messages_tokens_matches_module_level_helper():
    """与模块级 estimate_tokens 同口径（含 role 前缀）。"""
    messages = [{"role": "user", "content": "你好世界 hello world"}]
    assert estimate_messages_tokens(messages) == estimate_tokens("user" + "你好世界 hello world")


def test_estimate_messages_tokens_supports_message_objects():
    """session_repo.Message 对象与 dict 走同一读取路径。"""
    messages = _db_messages(3)
    expected = sum(estimate_tokens(m.role + m.content) for m in messages)
    assert estimate_messages_tokens(messages) == expected


# ---- should_compact ----------------------------------------------------------


def test_should_compact_false_below_threshold(monkeypatch):
    monkeypatch.delenv("SAGE_COMPACT_THRESHOLD", raising=False)
    messages = _dict_messages(MIN_COMPACT_MESSAGE_COUNT, content="短")
    assert should_compact(messages, threshold=10**9) is False


def test_should_compact_true_above_threshold_and_floor():
    messages = _dict_messages(MIN_COMPACT_MESSAGE_COUNT, content="足够长的内容用于越过阈值" * 20)
    assert should_compact(messages, threshold=100) is True


def test_should_compact_message_floor_blocks_short_sessions():
    """消息数少于 12 时,即使 token 爆表也不压缩。"""
    messages = _dict_messages(MIN_COMPACT_MESSAGE_COUNT - 1, content="长内容" * 1000)
    assert should_compact(messages, threshold=1) is False


def test_should_compact_threshold_env_override(monkeypatch):
    """env SAGE_COMPACT_THRESHOLD 优先于 settings/default。"""
    monkeypatch.setenv("SAGE_COMPACT_THRESHOLD", "50")
    assert get_compact_threshold() == 50
    messages = _dict_messages(MIN_COMPACT_MESSAGE_COUNT, content="内容内容内容内容")
    # 不传 threshold → 走 env 阈值 50,必然超过
    assert should_compact(messages) is True


def test_should_compact_threshold_from_settings(monkeypatch):
    """settings KV compact_threshold_tokens 次优先（conftest 提供临时 DB）。"""
    monkeypatch.delenv("SAGE_COMPACT_THRESHOLD", raising=False)
    from backend.data.settings_repo import SettingsRepository

    SettingsRepository().set("compact_threshold_tokens", "42")
    assert get_compact_threshold() == 42


def test_get_compact_threshold_default_and_invalid_env(monkeypatch):
    monkeypatch.delenv("SAGE_COMPACT_THRESHOLD", raising=False)
    assert get_compact_threshold() == DEFAULT_COMPACT_THRESHOLD_TOKENS
    monkeypatch.setenv("SAGE_COMPACT_THRESHOLD", "not-a-number")
    assert get_compact_threshold() == DEFAULT_COMPACT_THRESHOLD_TOKENS


# ---- prompt / continuation ---------------------------------------------------


def test_build_compaction_prompt_structure():
    messages = [
        {"role": "user", "content": "帮我分析销售数据"},
        {"role": "assistant", "content": "好的，结论是增长 12%"},
    ]
    prompt = build_compaction_prompt(messages)
    for section in ("## 目标", "## 决策", "## 关键事实", "## 待办事项"):
        assert section in prompt
    assert "[user]: 帮我分析销售数据" in prompt
    assert "[assistant]: 好的，结论是增长 12%" in prompt


def test_continuation_message_format():
    text = continuation_message("  摘要正文  ")
    assert text == f"{CONTINUATION_PREFIX}\n摘要正文"
    assert text.startswith("[上下文已压缩] 此前对话摘要：")


# ---- compact_messages ----------------------------------------------------------


@pytest.mark.asyncio()
async def test_compact_messages_keep_recent_boundary():
    """14 条 + keep_recent=6 → 摘要 8 条,返回 1+6 条,尾部原样保留。"""
    messages = _dict_messages(14)

    async def fake_llm(prompt: str) -> str:
        return "## 目标\n测试目标"

    new_messages, removed = await compact_messages(messages, fake_llm, keep_recent=6)
    assert removed == 8
    assert len(new_messages) == 7
    summary = new_messages[0]
    assert summary["role"] == "assistant"
    assert summary["content"].startswith(CONTINUATION_PREFIX)
    assert "测试目标" in summary["content"]
    # 尾部 6 条是原对象原顺序
    assert new_messages[1:] == messages[-6:]


@pytest.mark.asyncio()
async def test_compact_messages_llm_failure_raises():
    """LLM 调用失败 → CompactionError,绝不返回半成品。"""
    messages = _dict_messages(14)

    async def broken_llm(prompt: str) -> str:
        raise RuntimeError("upstream 500")

    with pytest.raises(CompactionError, match="LLM 摘要调用失败"):
        await compact_messages(messages, broken_llm)


@pytest.mark.asyncio()
async def test_compact_messages_empty_digest_raises():
    messages = _dict_messages(14)

    async def empty_llm(prompt: str) -> str:
        return "   \n  "

    with pytest.raises(CompactionError, match="空摘要"):
        await compact_messages(messages, empty_llm)


@pytest.mark.asyncio()
async def test_compact_messages_too_few_raises():
    """消息数 <= keep_recent 时没有可压缩前缀 → 抛错。"""
    messages = _dict_messages(6)

    async def fake_llm(prompt: str) -> str:
        return "digest"

    with pytest.raises(CompactionError, match="nothing to compact"):
        await compact_messages(messages, fake_llm, keep_recent=6)
