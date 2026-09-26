"""R139 — MemoryContext 分层记忆上下文单元测试。

覆盖：has_memories 四层判定、format 全空空串、核心画像用户/项目分块、
工作记忆末 3 条、情景+语义按 composite_score 降序合并、summary 优先、
Token 预算逐段跳过与逐行截断、_estimate_tokens 估算口径。
"""

from __future__ import annotations

import pytest

from backend.domain.memory import MemoryContext

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# has_memories
# ---------------------------------------------------------------------------


def test_has_memories_all_empty_false():
    assert MemoryContext().has_memories is False


@pytest.mark.parametrize(
    "kwargs",
    [
        {"working": [{"role": "user", "content": "hi"}]},
        {"episodic": [{"content": "e"}]},
        {"semantic": [{"content": "s"}]},
        {"core": [{"content": "c"}]},
    ],
)
def test_has_memories_any_layer_true(kwargs):
    assert MemoryContext(**kwargs).has_memories is True


def test_format_empty_returns_empty_string():
    assert MemoryContext().format() == ""


# ---------------------------------------------------------------------------
# core：用户/项目画像分块
# ---------------------------------------------------------------------------


def test_format_core_user_block():
    ctx = MemoryContext(core=[{"content": "用户喜欢吃火锅"}])
    out = ctx.format()
    assert out.startswith("【用户画像】")
    assert "- 用户喜欢吃火锅" in out


def test_format_core_project_scope_separate_block():
    ctx = MemoryContext(
        core=[
            {"content": "用户画像条目"},
            {"content": "本项目用 pytest", "scope": "project"},
        ]
    )
    out = ctx.format()
    assert "【用户画像】\n- 用户画像条目" in out
    assert "【项目画像】\n- 本项目用 pytest" in out
    assert out.index("【用户画像】") < out.index("【项目画像】")


def test_core_content_truncated_to_150():
    ctx = MemoryContext(core=[{"content": "字" * 200}])
    out = ctx.format(budget_tokens=10_000)
    assert "字" * 150 in out
    assert "字" * 151 not in out


# ---------------------------------------------------------------------------
# working：末 3 条
# ---------------------------------------------------------------------------


def test_working_takes_last_three_with_roles():
    msgs = [{"role": f"r{i}", "content": f"m{i}"} for i in range(5)]
    ctx = MemoryContext(working=msgs)
    out = ctx.format(budget_tokens=10_000)
    assert "【当前对话】" in out
    assert "- [r4]: m4" in out
    assert "- [r3]: m3" in out
    assert "- [r2]: m2" in out
    assert "m1" not in out
    assert "m0" not in out


# ---------------------------------------------------------------------------
# episodic + semantic：合并排序与 summary 优先
# ---------------------------------------------------------------------------


def test_memory_items_sorted_by_composite_score():
    ctx = MemoryContext(
        episodic=[{"content": "低", "composite_score": 0.1}],
        semantic=[{"content": "高", "composite_score": 0.9}],
    )
    out = ctx.format(budget_tokens=10_000)
    assert out.index("高") < out.index("低")


def test_memory_sort_falls_back_to_importance():
    ctx = MemoryContext(
        episodic=[{"content": "中", "importance": 5}],
        semantic=[{"content": "高", "importance": 9}],
    )
    out = ctx.format(budget_tokens=10_000)
    assert out.index("高") < out.index("中")


def test_memory_summary_preferred_over_content():
    ctx = MemoryContext(semantic=[{"content": "原文", "summary": "摘要文本"}])
    out = ctx.format(budget_tokens=10_000)
    assert "- 摘要文本" in out
    assert "原文" not in out


# ---------------------------------------------------------------------------
# Token 预算
# ---------------------------------------------------------------------------


def test_core_skipped_entirely_when_over_budget():
    # content 先截断到 150，"-" 行 + 块头合计约 42 token；预算 10 放不下
    ctx = MemoryContext(core=[{"content": "x" * 400}])
    out = ctx.format(budget_tokens=10)
    assert "【用户画像】" not in out  # core 整块超预算 → 跳过


def test_working_skipped_when_budget_exhausted_by_core():
    ctx = MemoryContext(
        core=[{"content": "y" * 40}],  # ~10 token
        working=[{"role": "user", "content": "z" * 800}],  # ~200 token
    )
    out = ctx.format(budget_tokens=30)
    assert "【用户画像】" in out
    assert "【当前对话】" not in out  # 剩余预算不足 → 整段跳过


def test_memory_lines_stop_at_budget():
    ctx = MemoryContext(
        semantic=[
            {"content": f"记忆条目{i}" * 10, "composite_score": 1 - i * 0.1}
            for i in range(5)
        ]
    )
    out = ctx.format(budget_tokens=60)
    assert "【相关记忆】" in out
    # 预算有限：并非 5 条全部注入
    injected = [line for line in out.splitlines() if line.startswith("- ")]
    assert 0 < len(injected) < 5


def test_estimate_tokens_chinese_vs_ascii():
    assert MemoryContext._estimate_tokens("abcd") == 1  # 4 ASCII → 1 token
    chinese = "中" * 6
    assert MemoryContext._estimate_tokens(chinese) == 4  # 6/1.5 = 4
