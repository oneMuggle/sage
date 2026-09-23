"""R17-E / R99: memory_used 流事件构造 helper 单元测试

覆盖 backend/api/legacy_routes.py::_memory_used_event_from_hits:
- 空命中 / 全空白 preview → None（不产事件）
- 正常 hits → 事件含 state/session_id/memories 结构
- 总体截断 5 条、id/memory_type 缺省回退
- R82 护栏: L13 注入块唯一性（防 merge 回潮）
"""

from __future__ import annotations

import pytest

from backend.api.legacy_routes import _memory_used_event_from_hits

pytestmark = pytest.mark.unit


def test_returns_none_without_hits():
    assert _memory_used_event_from_hits([], session_id="s1") is None
    assert _memory_used_event_from_hits(None, session_id="s1") is None


def test_builds_event_from_hits():
    hits = [
        {"id": "1", "memory_type": "episodic", "preview": "用户偏好深色主题"},
        {"id": "2", "memory_type": "semantic", "preview": "项目代号 Sage"},
        {"id": "working-0", "memory_type": "working", "preview": "[user]: 正在做记忆功能"},
    ]
    evt = _memory_used_event_from_hits(hits, session_id="s1")
    assert evt is not None
    assert evt["state"] == "memory_used"
    assert evt["session_id"] == "s1"
    assert len(evt["memories"]) == 3
    first = evt["memories"][0]
    assert first["id"] == "1"
    assert first["memory_type"] == "episodic"
    assert first["preview"] == "用户偏好深色主题"


def test_skips_blank_previews_and_defaults_memory_type():
    hits = [
        {"id": "1", "memory_type": "episodic", "preview": "   "},  # 空白 → 跳过
        {"id": "2", "preview": "无 memory_type"},  # memory_type 缺省 → memory
    ]
    evt = _memory_used_event_from_hits(hits, session_id="s1")
    assert evt is not None
    assert len(evt["memories"]) == 1
    assert evt["memories"][0]["memory_type"] == "memory"


def test_caps_memories_at_five():
    hits = [
        {"id": str(i), "memory_type": "semantic", "preview": f"记忆 {i}"}
        for i in range(8)
    ]
    evt = _memory_used_event_from_hits(hits, session_id="s1")
    assert len(evt["memories"]) == 5


def test_synthetic_ids_pass_frontend_validation():
    """前端 MEDIUM-2 校验要求每项 id 为字符串 —— 合成 id（working-N）满足。"""
    hits = [{"id": "working-0", "memory_type": "working", "preview": "正在做记忆功能"}]
    evt = _memory_used_event_from_hits(hits, session_id="s1")
    assert isinstance(evt["memories"][0]["id"], str)


# ── R82 (2026-09-19): L13 注入唯一性护栏 ────────────────────────────────


def test_l13_memory_injection_is_single():
    """源码级护栏：L13 记忆注入与召回事件在整个路由文件中各只有一个标记块。

    背景：producer 曾同时存在"对标增强批次 C"与"Task 14 段隔离"两段完全
    重复的注入，导致每次请求记忆上下文进两遍（双倍 token）且旧段工作记忆
    经无隔离版本漏进请求。此测试防止未来 merge/rebase 把重复块带回来。
    """
    from pathlib import Path

    import backend.api.legacy_routes as legacy_routes_module

    src = Path(legacy_routes_module.__file__).read_text(encoding="utf-8")
    assert src.count("L13 记忆上下文注入 BEGIN") == 1
    assert src.count("L13 记忆上下文注入 END") == 1
    assert src.count("R17-E 记忆召回展示事件 BEGIN") == 1
    assert src.count("R17-E 记忆召回展示事件 END") == 1
    # 注入文本本身也只允许出现一次
    assert src.count("以下是相关的记忆上下文：") == 1
    # R99: recall 不得再被 producer 用于记忆事件（与注入双检索）
    assert "_build_memory_used_event" not in src
