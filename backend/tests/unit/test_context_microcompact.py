"""上下文微压缩单元测试 — backend/core/legacy/context_microcompact.py

覆盖:
- 白名单命中 / 未命中（非 tool 角色、白名单外工具、已清空条目均不动）
- 保留区：最近 KEEP_RECENT_TOOL_RESULTS 条工具结果原样保留
- 省量下限：预计节省 < MIN_TOKEN_SAVINGS 时不动手，两个返回值相等
- 结构不变量：条数 / 顺序 / role / tool_call_id 不变，assistant(tool_calls)
  ↔ tool 配对完整
- 阈值边界：恰好等于下限时动手
"""

from __future__ import annotations

from typing import Any, Dict, List

import pytest

from backend.core.legacy.context_microcompact import (
    CLEARED_SENTINEL,
    KEEP_RECENT_TOOL_RESULTS,
    MICROCOMPACTABLE_TOOLS,
    estimate_savings,
    micro_compact,
)

pytestmark = pytest.mark.unit

# 单条内容足够大，让任何一条都能远超 MIN_TOKEN_SAVINGS
_BULK = "文" * 2000


def _tool_msg(name: str, content: str, call_id: str) -> Dict[str, Any]:
    return {"role": "tool", "name": name, "content": content, "tool_call_id": call_id}


def _many_old_results(count: int) -> List[Dict[str, Any]]:
    """造 count 条白名单工具结果，供调用方自行追加"近期"条目验证保留区。"""
    return [_tool_msg("read_file", _BULK, f"call_{i}") for i in range(count)]


# ---- 白名单 ------------------------------------------------------------------


def test_clears_whitelisted_old_tool_result():
    messages = _many_old_results(6) + [_tool_msg("read_file", _BULK, "recent")]
    micro_compact(messages)
    assert messages[0]["content"] == CLEARED_SENTINEL


@pytest.mark.parametrize("name", sorted(MICROCOMPACTABLE_TOOLS))
def test_every_whitelisted_tool_is_compactable(name):
    messages = _many_old_results(6) + [_tool_msg(name, _BULK, "recent")]
    micro_compact(messages)
    assert messages[0]["content"] == CLEARED_SENTINEL


def test_non_whitelisted_tool_is_untouched():
    """白名单外的工具结果即使很早、很大也不清空。"""
    early = [_tool_msg("office_read", _BULK, f"office_{i}") for i in range(4)]
    messages = early + _many_old_results(6) + [_tool_msg("read_file", _BULK, "recent")]
    micro_compact(messages)
    assert all(msg["content"] == _BULK for msg in early)
    assert messages[4]["content"] == CLEARED_SENTINEL, "白名单内的旧结果仍应被清空"


def test_non_tool_roles_are_untouched():
    messages = [{"role": "user", "content": _BULK} for _ in range(7)]
    before, after = micro_compact(messages)
    assert all(msg["content"] == _BULK for msg in messages)
    assert before == after


def test_already_cleared_entry_is_not_reprocessed():
    """已清空的条目不再计入候选——窗口被填满后再压缩不得再改动任何条目。"""
    messages = _many_old_results(KEEP_RECENT_TOOL_RESULTS * 2)
    micro_compact(messages)
    snapshot = [dict(msg) for msg in messages]

    micro_compact(messages)
    assert messages == snapshot, "重复压缩不得再改动任何条目"
    assert all(msg["content"] == CLEARED_SENTINEL for msg in messages[:KEEP_RECENT_TOOL_RESULTS])


def test_missing_name_field_is_treated_as_not_whitelisted():
    """既无 name 又反查不到 tool_call_id 的 tool 消息保守跳过。"""
    messages = [{"role": "tool", "content": _BULK, "tool_call_id": f"c{i}"} for i in range(6)]
    messages.append(_tool_msg("read_file", _BULK, "recent"))
    micro_compact(messages)
    assert messages[0]["content"] == _BULK


def test_name_is_resolved_from_paired_assistant_tool_calls():
    """run_loop 写入的 tool 消息不带 name，靠 id 从 assistant.tool_calls 反查。"""

    def _pair(call_id: str, tool_name: str) -> List[Dict[str, Any]]:
        return [
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {"id": call_id, "type": "function", "function": {"name": tool_name}}
                ],
            },
            {"role": "tool", "tool_call_id": call_id, "content": _BULK},
        ]

    messages: List[Dict[str, Any]] = []
    for i in range(6):
        messages.extend(_pair(f"call_{i}", "read_file"))
    messages.extend(_pair("recent", "read_file"))

    micro_compact(messages)
    assert messages[1]["content"] == CLEARED_SENTINEL, "早期配对结果应被清空"
    assert messages[-1]["content"] == _BULK, "最近一条原样保留"


# ---- 保留区 ------------------------------------------------------------------


def test_keeps_recent_tool_results_intact():
    messages = _many_old_results(KEEP_RECENT_TOOL_RESULTS + 4)
    messages.append(_tool_msg("read_file", _BULK, "recent"))
    micro_compact(messages)

    split = len(messages) - KEEP_RECENT_TOOL_RESULTS
    assert all(msg["content"] == _BULK for msg in messages[split:]), "最近 N 条必须原样保留"
    assert all(
        msg["content"] == CLEARED_SENTINEL for msg in messages[:split]
    ), "更早的必须已清空"


def test_fewer_than_keep_recent_leaves_everything_untouched():
    messages = _many_old_results(KEEP_RECENT_TOOL_RESULTS)
    before, after = micro_compact(messages)
    assert all(msg["content"] == _BULK for msg in messages)
    assert before == after


# ---- 省量下限 ----------------------------------------------------------------


def test_small_savings_below_floor_leaves_history_untouched():
    """整体省量都不到 MIN_TOKEN_SAVINGS 时不动手。"""
    messages = [_tool_msg("read_file", "短", f"c{i}") for i in range(6)]
    before, after = micro_compact(messages)
    assert all(msg["content"] == "短" for msg in messages)
    assert before == after
    assert estimate_savings(messages) == 0


def test_zero_threshold_forces_action():
    messages = _many_old_results(6) + [_tool_msg("read_file", _BULK, "recent")]
    before, after = micro_compact(messages, min_token_savings=0)
    assert messages[0]["content"] == CLEARED_SENTINEL
    assert after < before


def test_exact_threshold_is_applied():
    """恰好等于下限：采用 >= 语义，动手。"""
    messages = _many_old_results(6) + [_tool_msg("read_file", _BULK, "recent")]
    exact = estimate_savings(messages)
    before, after = micro_compact(messages, min_token_savings=exact)
    assert after < before


def test_empty_messages_is_noop():
    assert micro_compact([]) == (0, 0)


# ---- 结构不变量 --------------------------------------------------------------


def test_structure_invariants_hold_after_compaction():
    """条数 / 顺序 / role / tool_call_id 全部不变，tool 配对不断。"""
    messages: List[Dict[str, Any]] = [
        {"role": "user", "content": "帮我看看这个文件"},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {"id": "call_0", "type": "function", "function": {"name": "read_file"}},
                {"id": "call_1", "type": "function", "function": {"name": "read_file"}},
            ],
        },
        _tool_msg("read_file", _BULK, "call_0"),
        _tool_msg("read_file", _BULK, "call_1"),
        {"role": "assistant", "content": "文件内容如上"},
        _tool_msg("read_file", _BULK, "call_2"),
    ]
    before_ids = [msg.get("tool_call_id") for msg in messages]
    before_roles = [msg["role"] for msg in messages]

    micro_compact(messages)

    assert len(messages) == 6
    assert [msg["role"] for msg in messages] == before_roles
    assert [msg.get("tool_call_id") for msg in messages] == before_ids
    assert [call["id"] for call in messages[1]["tool_calls"]] == ["call_0", "call_1"]


def test_estimate_savings_does_not_mutate():
    messages = _many_old_results(6) + [_tool_msg("read_file", _BULK, "recent")]
    snapshot = [dict(msg) for msg in messages]
    estimate_savings(messages)
    assert messages == snapshot
