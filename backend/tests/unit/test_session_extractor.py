"""session_extractor 单元测试。

覆盖:
1. 空列表 → 返回 []
2. 短于上限 → 原样保留
3. 超过上限 → 保留最后 N 条,丢弃最旧
4. 缺字段(无 tool / 无 args)→ 过滤掉
5. 类型错(tool 非 str / args 非 dict)→ 过滤掉
6. 可选字段(result_summary / timestamp_ms)缺省合法
7. 不修改输入列表
"""

from __future__ import annotations

from typing import Any, Dict, List

import pytest

from backend.skills.session_extractor import (
    MAX_SEQUENCE_LEN,
    REQUIRED_FIELDS,
    normalize_tool_sequence,
)

pytestmark = pytest.mark.unit


def _ok(tool: str = "web_fetch", args: Dict[str, Any] = None) -> Dict[str, Any]:
    return {"tool": tool, "args": args or {"url": "https://example.com"}}


# ============================================================================
# 1. 空列表
# ============================================================================


def test_normalize_empty_list_returns_empty():
    assert normalize_tool_sequence([]) == []


# ============================================================================
# 2. 短于上限 → 原样保留
# ============================================================================


def test_normalize_short_sequence_passes_through():
    seq = [_ok("web_fetch"), _ok("ask_user_question"), _ok("todo_tool")]
    result = normalize_tool_sequence(seq)
    assert result == seq


# ============================================================================
# 3. 超过上限 → 保留最后 N 条
# ============================================================================


def test_normalize_truncates_to_max_len_keeping_last():
    seq = [_ok(f"tool_{i}") for i in range(MAX_SEQUENCE_LEN + 10)]
    result = normalize_tool_sequence(seq)
    assert len(result) == MAX_SEQUENCE_LEN
    assert result[-1]["tool"] == f"tool_{MAX_SEQUENCE_LEN + 9}"
    assert result[0]["tool"] == f"tool_{10}"


# ============================================================================
# 4. 缺字段 → 过滤掉
# ============================================================================


def test_normalize_drops_records_missing_tool():
    seq = [
        _ok("web_fetch"),
        {"args": {"url": "x"}},
        _ok("ask_user_question"),
    ]
    result = normalize_tool_sequence(seq)
    assert len(result) == 2
    assert result[0]["tool"] == "web_fetch"
    assert result[1]["tool"] == "ask_user_question"


def test_normalize_drops_records_missing_args():
    seq = [
        _ok("web_fetch"),
        {"tool": "ask_user_question"},
        _ok("todo_tool"),
    ]
    result = normalize_tool_sequence(seq)
    assert len(result) == 2
    assert result[0]["tool"] == "web_fetch"
    assert result[1]["tool"] == "todo_tool"


# ============================================================================
# 5. 类型错 → 过滤掉
# ============================================================================


def test_normalize_drops_records_with_wrong_tool_type():
    seq = [
        _ok("web_fetch"),
        {"tool": 123, "args": {}},
        {"tool": None, "args": {}},
        _ok("ask_user_question"),
    ]
    result = normalize_tool_sequence(seq)
    assert len(result) == 2
    assert result[0]["tool"] == "web_fetch"
    assert result[1]["tool"] == "ask_user_question"


def test_normalize_drops_records_with_wrong_args_type():
    seq = [
        _ok("web_fetch"),
        {"tool": "ask_user_question", "args": "not-a-dict"},
        {"tool": "todo_tool", "args": None},
        _ok("plan_tool"),
    ]
    result = normalize_tool_sequence(seq)
    assert len(result) == 2
    assert result[0]["tool"] == "web_fetch"
    assert result[1]["tool"] == "plan_tool"


def test_normalize_drops_non_dict_records():
    seq = [
        _ok("web_fetch"),
        "not-a-dict",
        None,
        42,
        _ok("ask_user_question"),
    ]
    result = normalize_tool_sequence(seq)
    assert len(result) == 2
    assert result[0]["tool"] == "web_fetch"
    assert result[1]["tool"] == "ask_user_question"


# ============================================================================
# 6. 可选字段缺省合法
# ============================================================================


def test_normalize_keeps_records_with_optional_fields_missing():
    seq = [
        _ok("web_fetch"),
        {"tool": "ask_user_question", "args": {}, "result_summary": "ok"},
        {"tool": "todo_tool", "args": {}},
    ]
    result = normalize_tool_sequence(seq)
    assert len(result) == 3
    assert REQUIRED_FIELDS == ("tool", "args")


# ============================================================================
# 7. 不修改输入
# ============================================================================


def test_normalize_does_not_mutate_input():
    original = [_ok("web_fetch"), {"args": {}}, _ok("ask_user_question")]
    snapshot = list(original)
    normalize_tool_sequence(original)
    assert original == snapshot


def test_normalize_returns_new_list_object():
    original: List[Dict[str, Any]] = [_ok("web_fetch")]
    result = normalize_tool_sequence(original)
    assert result is not original
