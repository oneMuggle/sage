# ruff: noqa: UP006, UP007, UP035, UP045 — release/win7 Python 3.8 兼容，保留 typing 注解
"""L1 会话历史注入（backend/chat/history_context.py）单元测试。

纯函数测试，不触碰 SQLite：行对象用 session_repo.Message 构造。
"""

import os
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from backend.chat.history_context import (
    build_request_messages,
    db_rows_to_history,
    history_token_budget,
    truncate_history,
)


def _row(role, content, **kwargs):
    """构造伪 DbMessage（SimpleNamespace，避免依赖 DB 会话）。"""
    base = {
        "id": f"m-{role}-{abs(hash(content)) % 10000}",
        "session_id": "s1",
        "role": role,
        "content": content,
        "created_at": 1,
        "model": None,
        "provider": None,
        "tool_calls": None,
        "tool_call_id": None,
        "reasoning_content": None,
    }
    base.update(kwargs)
    return SimpleNamespace(**base)


# ---- db_rows_to_history ----


def test_filters_roles_and_keeps_order():
    rows = [
        _row("user", "第一句"),
        _row("assistant", "第一答"),
        _row("tool", "工具结果"),  # 非白名单角色 → 跳过
        _row("system", "内嵌 system"),  # 非白名单角色 → 跳过
        _row("user", "第二句"),
    ]
    history = db_rows_to_history(rows)
    assert history == [
        {"role": "user", "content": "第一句"},
        {"role": "assistant", "content": "第一答"},
        {"role": "user", "content": "第二句"},
    ]


def test_skips_assistant_with_tool_calls_and_empty_content():
    rows = [
        _row("assistant", "带工具调用", tool_calls='[{"id":"t1"}]'),
        _row("assistant", ""),
        _row("assistant", "   "),
        _row("assistant", None),
        _row("user", "正常"),
    ]
    assert db_rows_to_history(rows) == [{"role": "user", "content": "正常"}]


def test_drops_reasoning_content():
    rows = [_row("assistant", "答", reasoning_content="思考过程")]
    history = db_rows_to_history(rows)
    assert history == [{"role": "assistant", "content": "答"}]
    assert "reasoning" not in history[0]


# ---- truncate_history ----


def test_truncate_keeps_newest_and_counts_omitted():
    messages = [{"role": "user", "content": f"消息{i}" + "x" * 40} for i in range(10)]
    # 预算只够放最近 ~3 条（每条估算 ~11 tokens）
    kept, omitted = truncate_history(messages, budget_tokens=40)
    assert omitted > 0
    assert len(kept) < 10
    assert kept[-1] == messages[-1]  # 最新一条必须在
    assert kept[0] != messages[0]  # 最旧一条被丢


def test_truncate_noop_when_budget_fits():
    messages = [{"role": "user", "content": "短"}]
    kept, omitted = truncate_history(messages, budget_tokens=1000)
    assert kept == messages
    assert omitted == 0


def test_truncate_always_keeps_at_least_one():
    messages = [{"role": "user", "content": "很长" * 500}]
    kept, omitted = truncate_history(messages, budget_tokens=1)
    assert kept == messages  # 单条也要放行（kept_reversed 空时不丢首条）
    assert omitted == 0


# ---- history_token_budget ----


def test_budget_env_override_valid_and_invalid():
    with patch.dict(os.environ, {"SAGE_HISTORY_TOKEN_BUDGET": "12345"}):
        assert history_token_budget() == 12345
    with patch.dict(os.environ, {"SAGE_HISTORY_TOKEN_BUDGET": "not-a-number"}):
        assert history_token_budget() >= 18000
    with patch.dict(os.environ, {"SAGE_HISTORY_TOKEN_BUDGET": "-1"}):
        assert history_token_budget() >= 18000


def test_budget_floor():
    with patch.dict(os.environ, {"SAGE_HISTORY_TOKEN_BUDGET": ""}), patch(
        "backend.chat.compaction.get_compact_threshold", return_value=1
    ):
        assert history_token_budget() >= 18000


# ---- build_request_messages ----


def test_request_messages_order_and_notice():
    rows = [
        _row("user", "历史1"),
        _row("assistant", "历史2"),
        _row("user", "历史3"),
    ]
    messages, omitted = build_request_messages(
        system_content="SYS",
        user_text="新问题",
        history_rows=rows,
        attachment_block="附件内容",
    )
    assert omitted == 0
    # system + 附件 system + 3 条历史 + 本轮 user
    assert [m["role"] for m in messages] == [
        "system",
        "system",
        "user",
        "assistant",
        "user",
        "user",
    ]
    assert messages[0]["content"] == "SYS"
    assert "附件内容" in messages[1]["content"]
    assert messages[-1]["content"] == "新问题"
    assert messages[2]["content"] == "历史1"


def test_request_messages_truncation_notice_in_system():
    rows = [_row("user", "很长" * 500 + str(i)) for i in range(20)]
    messages, omitted = build_request_messages(
        system_content="SYS",
        user_text="新问题",
        history_rows=rows,
        budget_tokens=50,
    )
    assert omitted > 0
    assert "省略了最早的" in messages[0]["content"]
    # messages = [system, *kept, user] → kept 数 = len(messages) - 2
    assert omitted == 20 - (len(messages) - 2)
    # 保留的尾部历史完整：最后一条历史 == 最后一行
    assert messages[-2]["content"] == rows[-1].content


def test_request_messages_without_attachment_block():
    rows = [_row("user", "历史")]
    messages, _ = build_request_messages(
        system_content="SYS", user_text="新", history_rows=rows
    )
    assert [m["role"] for m in messages] == ["system", "user", "user"]


def test_request_messages_empty_history():
    messages, omitted = build_request_messages(
        system_content="SYS", user_text="新", history_rows=[]
    )
    assert omitted == 0
    assert messages == [
        {"role": "system", "content": "SYS"},
        {"role": "user", "content": "新"},
    ]


def test_history_load_never_raises_on_bad_rows():
    """行对象缺字段等异常输入时，过滤而非崩溃（best-effort 铁律）。"""
    messages, _ = build_request_messages(
        system_content="SYS",
        user_text="新",
        history_rows=[object()],  # 完全没有 role/content 属性
    )
    assert messages[0]["role"] == "system"
    assert messages[-1]["role"] == "user"



# ==================== L4' trailing_system (round4 批次 C) ====================


def test_request_messages_trailing_system_before_user():
    """易变上下文块作为独立 system 消息插在历史之后、末条 user 之前。"""
    rows = [_row("user", "历史")]
    messages, _ = build_request_messages(
        system_content="SYS",
        user_text="新",
        history_rows=rows,
        trailing_system="<environment>...</environment>",
    )
    assert [m["role"] for m in messages] == ["system", "user", "system", "user"]
    assert messages[-2] == {"role": "system", "content": "<environment>...</environment>"}
    assert messages[-1] == {"role": "user", "content": "新"}


def test_request_messages_trailing_system_blank_omitted():
    """空串/纯空白 trailing_system 不产生额外消息(与缺省行为一致)。"""
    whitespace_only = "   " + "\n" + "\n" + "  "
    for blank in (None, "", whitespace_only):
        messages, _ = build_request_messages(
            system_content="SYS",
            user_text="新",
            history_rows=[],
            trailing_system=blank,
        )
        assert [m["role"] for m in messages] == ["system", "user"]


if __name__ == "__main__":
    pytest.main([__file__])
