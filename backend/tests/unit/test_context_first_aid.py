"""上下文急救压缩单元测试（RT2，round7） — backend/core/legacy/context_first_aid.py

覆盖:
- estimate_messages_tokens 与 working.estimate_tokens 同口径
- first_aid_compact：就地压缩不变式（条数/顺序/role/tool_call_id 不变、
  keep_recent 保护区、截断标记、配对完整）
- run_ctx_budget_tokens：env 覆盖 / 0 关闭 / 非法值回退
"""

from __future__ import annotations

import pytest

from backend.core.legacy.context_first_aid import (
    DEFAULT_RUN_CTX_BUDGET_TOKENS,
    _estimate_text_tokens,
    estimate_messages_tokens,
    first_aid_compact,
    run_ctx_budget_tokens,
)
from backend.memory.working import estimate_tokens

pytestmark = pytest.mark.unit


# ---- 估算 --------------------------------------------------------------------


def test_estimate_text_tokens_same_semantics_as_working():
    """公式与 working.estimate_tokens 逐字一致：cjk + other//4 + len//4。"""
    assert _estimate_text_tokens("") == 0
    assert _estimate_text_tokens("你好世界") == 5  # 4 cjk + 4//4
    assert _estimate_text_tokens("abcdefgh") == 4  # 8//4 + 8//4


def test_estimate_messages_tokens_counts_role_and_content():
    messages = [
        {"role": "system", "content": "abc"},
        {"role": "user", "content": "你好"},
    ]
    expected = _estimate_text_tokens("system") + _estimate_text_tokens("abc")
    expected += _estimate_text_tokens("user") + _estimate_text_tokens("你好")
    assert estimate_messages_tokens(messages) == expected


def test_estimate_matches_working_estimator_direction():
    """与 backend.memory.working.estimate_tokens 在中英混合文本上同口径。"""
    text = "重构 refactoring 上下文"
    assert _estimate_text_tokens(text) == estimate_tokens(text)


# ---- first_aid_compact -------------------------------------------------------


def _long_tool_transcript(n_pairs: int = 6, tool_chars: int = 5000) -> list:
    """构造 system + N 组 assistant(tool_calls)/tool + user 的长 transcript。"""
    messages = [{"role": "system", "content": "system prompt"}]
    for i in range(n_pairs):
        messages.append(
            {
                "role": "assistant",
                "content": "x" * 2000,
                "tool_calls": [
                    {"id": f"call_{i}", "type": "function", "function": {"name": "t", "arguments": "{}"}}
                ],
            }
        )
        messages.append({"role": "tool", "tool_call_id": f"call_{i}", "content": "y" * tool_chars})
    messages.append({"role": "user", "content": "总结一下"})
    return messages


def test_first_aid_compact_preserves_structure():
    """条数/顺序/role/tool_call_id 全部不变——API 结构校验安全的底线。"""
    messages = _long_tool_transcript()
    before_snapshot = [(m.get("role"), m.get("tool_call_id")) for m in messages]

    first_aid_compact(messages)

    assert [(m.get("role"), m.get("tool_call_id")) for m in messages] == before_snapshot
    assert len(messages) == 14


def test_first_aid_compact_truncates_early_tool_results_with_marker():
    """早期 tool 内容截到头 400 字符 + 标记；tool_call_id 原样。"""
    messages = _long_tool_transcript()
    first_aid_compact(messages)

    early_tool = messages[2]  # 第一组 tool
    assert early_tool["content"].startswith("y" * 10)
    assert early_tool["content"].endswith("[已压缩：早期工具结果]")
    assert len(early_tool["content"]) < 500
    assert early_tool["tool_call_id"] == "call_0"


def test_first_aid_compact_protects_recent_messages():
    """末尾 keep_recent 条原样保留。"""
    messages = _long_tool_transcript(n_pairs=6)
    tail_snapshot = [dict(m) for m in messages[-6:]]

    first_aid_compact(messages, keep_recent=6)

    assert messages[-6:] == tail_snapshot


def test_first_aid_compact_shrinks_token_estimate():
    """压缩后估算显著下降；短列表（≤keep_recent）是 no-op。"""
    messages = _long_tool_transcript()
    before = estimate_messages_tokens(messages)
    before_tokens, after_tokens = first_aid_compact(messages)
    assert before_tokens == before
    assert after_tokens < before_tokens * 0.75

    short = [{"role": "user", "content": "hi"}]
    b, a = first_aid_compact(short)
    assert short == [{"role": "user", "content": "hi"}]
    assert b == a


def test_first_aid_compact_never_raises_on_malformed_entries():
    """非法条目（非 dict / 缺字段）跳过不抛错。"""
    messages = _long_tool_transcript()
    messages.insert(3, "not-a-dict")  # type: ignore[list-item]
    messages.insert(5, None)  # type: ignore[list-item]
    before_snapshot = [(m.get("role") if isinstance(m, dict) else m) for m in messages]

    first_aid_compact(messages)

    assert [(m.get("role") if isinstance(m, dict) else m) for m in messages] == before_snapshot


def test_first_aid_compact_truncates_long_prose():
    """早期 assistant/user 超长文本保头尾 + 标记。"""
    messages = [
        {"role": "user", "content": "u" * 3000},
        {"role": "assistant", "content": "a" * 3000},
        {"role": "user", "content": "继续"},
    ]
    first_aid_compact(messages, keep_recent=1)

    assert messages[0]["content"].startswith("u" * 10)
    assert "[已压缩：早期内容]" in messages[0]["content"]
    assert messages[0]["content"].endswith("u")
    assert "[已压缩：早期内容]" in messages[1]["content"]
    assert messages[2]["content"] == "继续"


def test_first_aid_compact_empty_list():
    assert first_aid_compact([]) == (0, 0)


# ---- run_ctx_budget_tokens ---------------------------------------------------


def test_run_ctx_budget_default(monkeypatch):
    monkeypatch.delenv("SAGE_RUN_CTX_BUDGET_TOKENS", raising=False)
    assert run_ctx_budget_tokens() == DEFAULT_RUN_CTX_BUDGET_TOKENS


def test_run_ctx_budget_env_override(monkeypatch):
    monkeypatch.setenv("SAGE_RUN_CTX_BUDGET_TOKENS", "5000")
    assert run_ctx_budget_tokens() == 5000
    monkeypatch.setenv("SAGE_RUN_CTX_BUDGET_TOKENS", "0")
    assert run_ctx_budget_tokens() == 0


def test_run_ctx_budget_invalid_env_falls_back(monkeypatch):
    monkeypatch.setenv("SAGE_RUN_CTX_BUDGET_TOKENS", "abc")
    assert run_ctx_budget_tokens() == DEFAULT_RUN_CTX_BUDGET_TOKENS
    monkeypatch.setenv("SAGE_RUN_CTX_BUDGET_TOKENS", "-3")
    assert run_ctx_budget_tokens() == DEFAULT_RUN_CTX_BUDGET_TOKENS
