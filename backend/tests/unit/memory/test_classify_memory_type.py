"""R146 — 记忆分类规则 classify_memory_type 单元测试。

规则（单一事实来源，MemoryManager 与 MemoryAdapter 共用）：
- 显式指定的非 auto 类型原样透传；
- auto：importance >= 8 → semantic；
- auto：短内容（<200 字符）且 importance < 5 → working；
- 其余 → episodic。
"""

from __future__ import annotations

import pytest

from backend.memory.manager import classify_memory_type

pytestmark = pytest.mark.unit


@pytest.mark.parametrize("explicit", ["working", "episodic", "semantic", "custom_bucket"])
def test_explicit_type_passthrough(explicit):
    # 显式类型无条件透传——即使与 importance 规则矛盾
    assert classify_memory_type(explicit, importance=10, content="x" * 500) == explicit


def test_auto_high_importance_goes_semantic():
    assert classify_memory_type("auto", importance=8, content="") == "semantic"
    assert classify_memory_type("auto", importance=10, content="x" * 500) == "semantic"


def test_auto_importance_seven_not_semantic():
    result = classify_memory_type("auto", importance=7, content="x" * 500)
    assert result != "semantic"


def test_auto_short_low_importance_goes_working():
    assert classify_memory_type("auto", importance=4, content="x" * 199) == "working"
    assert classify_memory_type("auto", importance=1, content="hi") == "working"


def test_boundary_199_chars_is_working_200_is_not():
    assert classify_memory_type("auto", importance=4, content="x" * 199) == "working"
    assert classify_memory_type("auto", importance=4, content="x" * 200) == "episodic"


def test_boundary_importance_five_not_working():
    assert classify_memory_type("auto", importance=5, content="x" * 100) == "episodic"
    assert classify_memory_type("auto", importance=5, content="x" * 500) == "episodic"


def test_default_long_content_goes_episodic():
    assert classify_memory_type("auto", importance=5, content="x" * 500) == "episodic"


def test_empty_type_treated_as_auto():
    assert classify_memory_type("", importance=9, content="") == "semantic"
    assert classify_memory_type("", importance=3, content="short") == "working"
    assert classify_memory_type("", importance=5, content="x" * 300) == "episodic"
