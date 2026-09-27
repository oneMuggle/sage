"""R148 — 上下文 Token 预算单元测试。

覆盖：ContextBudget.compute 的 70% 截断与四段分配精确值、模型上限
封顶、estimate_tokens 口径、truncate_pages 的逐页截断/单页上限/预算
耗尽丢弃。
"""

from __future__ import annotations

import pytest

from backend.wiki.context_budget import (
    DEFAULT_MAX_TOKENS,
    ContextBudget,
    estimate_tokens,
    truncate_pages,
)

pytestmark = pytest.mark.unit


def test_compute_default_allocation_exact():
    budget = ContextBudget.compute()
    total = DEFAULT_MAX_TOKENS * 7 // 10  # 8192*0.7 = 5734
    assert budget.total == total
    assert budget.pages == int(total * 0.50)
    assert budget.history == int(total * 0.30)
    assert budget.index == int(total * 0.05)
    assert budget.response_reserve == int(total * 0.15)
    assert budget.per_page_cap == total // 8


def test_compute_caps_model_max_tokens():
    budget = ContextBudget.compute(model_max_tokens=100_000)
    assert budget.total == ContextBudget.compute().total  # 封顶到默认 8192


def test_compute_scales_down_for_small_models():
    budget = ContextBudget.compute(model_max_tokens=4096)
    assert budget.total == 4096 * 7 // 10
    assert budget.pages < budget.history or budget.pages == int(budget.total * 0.5)
    assert budget.per_page_cap == budget.total // 8


def test_estimate_tokens_ceil_division():
    assert estimate_tokens("") == 0
    assert estimate_tokens("abc") == 1  # ceil(3/3)
    assert estimate_tokens("abcd") == 2  # ceil(4/3)
    assert estimate_tokens("a" * 7) == 3  # ceil(7/3)


# ---------------------------------------------------------------------------
# truncate_pages
# ---------------------------------------------------------------------------


def test_pages_within_budget_not_truncated():
    budget = ContextBudget(total=3000, pages=1500, history=900, index=150,
                           response_reserve=450, per_page_cap=500)
    chunks = truncate_pages([("a.md", "x" * 300), ("b.md", "y" * 300)], budget)
    assert [c.page_path for c in chunks] == ["a.md", "b.md"]
    assert all(not c.truncated for c in chunks)


def test_oversized_page_truncated_to_per_page_cap():
    budget = ContextBudget(total=3000, pages=1500, history=900, index=150,
                           response_reserve=450, per_page_cap=100)
    chunks = truncate_pages([("big.md", "x" * 500)], budget)
    assert len(chunks) == 1
    assert chunks[0].truncated is True
    assert len(chunks[0].content) == 100 * 3  # allowed * CHARS_PER_TOKEN


def test_budget_exhaustion_drops_later_pages():
    budget = ContextBudget(total=3000, pages=20, history=900, index=150,
                           response_reserve=450, per_page_cap=500)
    chunks = truncate_pages(
        [("a.md", "x" * 60), ("b.md", "y" * 60), ("c.md", "z" * 60)], budget
    )
    # 20 token 预算 ≈ 60 字符：第一页耗尽，后续丢弃
    assert [c.page_path for c in chunks] == ["a.md"]
    assert chunks[0].truncated is False  # 60 字符 = 20 token，恰好用满


def test_page_partially_truncated_by_remaining_budget():
    budget = ContextBudget(total=3000, pages=25, history=900, index=150,
                           response_reserve=450, per_page_cap=500)
    chunks = truncate_pages([("a.md", "x" * 30), ("b.md", "y" * 300)], budget)
    assert chunks[0].truncated is False  # 30 字符 = 10 token，单页上限内
    assert chunks[1].truncated is True  # 剩余 15 token ≈ 45 字符
    assert len(chunks[1].content) == 45
