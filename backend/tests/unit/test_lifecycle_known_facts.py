"""抽取阶段「已知事实去重」回归测试。

覆盖 Task 2.2 的四个关键行为：

1. ``lifecycle._collect_known_facts`` 通过 ``MemoryManager.recall`` 取回
   本轮相关的已知事实，并以 ``existing_facts=`` 传给提取器；
2. recall 抛异常时静默降级为空列表，且**不中断**记忆写入；
3. 只支持两参签名的旧 extractor（``test_lifecycle.py`` 的 ``BrokenExtractor``
   同款）不会因为多传 kwarg 而抛 TypeError；
4. ``extractor._select_existing_facts`` 按 token 相关性过滤 + 字符预算截断。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import pytest

from backend.memory.extractor import (
    EXISTING_FACTS_CHAR_BUDGET,
    _select_existing_facts,
)
from backend.memory.lifecycle import MemoryLifecycleManager

pytestmark = pytest.mark.unit


class _TruePrefs:
    async def get(self, key: str) -> Optional[str]:
        return "true"


class _SpyExtractor:
    """记录 ``extract`` 收到的 kwargs，用来断言 existing_facts 是否透传。"""

    def __init__(self, facts: Optional[List[Dict[str, Any]]] = None) -> None:
        self.calls: List[Dict[str, Any]] = []
        self._facts = facts if facts is not None else []

    async def extract(self, user_message: str, assistant_message: str, **kwargs: Any):
        self.calls.append(
            {
                "user_message": user_message,
                "assistant_message": assistant_message,
                "kwargs": kwargs,
            }
        )
        return list(self._facts)


class _TwoArgExtractor:
    """旧签名 extractor：只接受两个位置参数。"""

    def __init__(self) -> None:
        self.calls = 0

    async def extract(self, user_message: str, assistant_message: str):
        self.calls += 1
        return [{"content": "用户偏好使用 ruff 格式化 Python 代码", "importance": 7}]


class _FakeMemory:
    """最小 MemoryManager 替身：只有 recall + aremember_with_conflict_check。"""

    def __init__(
        self, recall_result: Any = None, recall_error: Optional[Exception] = None
    ) -> None:
        self._recall_result = recall_result
        self._recall_error = recall_error
        self.recall_calls: List[Dict[str, Any]] = []
        self.persisted: List[Dict[str, Any]] = []

    def recall(self, query: str, **kwargs: Any) -> Dict[str, List[Dict[str, Any]]]:
        self.recall_calls.append({"query": query, **kwargs})
        if self._recall_error is not None:
            raise self._recall_error
        return self._recall_result or {}

    async def aremember_with_conflict_check(self, **kwargs: Any):
        self.persisted.append(kwargs)
        return "mem-1", "add"


def _make_manager(memory: Any, extractor: Any) -> MemoryLifecycleManager:
    return MemoryLifecycleManager(
        memory_manager=memory,
        hooks=None,
        preferences_repo=_TruePrefs(),
        extractor=extractor,
    )


# ---------------------------------------------------------------------------
# 1. existing_facts 被检索出来并透传给 extractor
# ---------------------------------------------------------------------------


@pytest.mark.asyncio()
async def test_known_facts_passed_to_extractor() -> None:
    """recall 返回的事实应以 existing_facts= 传给 extractor。"""
    memory = _FakeMemory(
        recall_result={
            "episodic": [
                {"id": "e1", "content": "用户偏好用 ruff 格式化 Python 代码"},
            ],
            "semantic": [
                {"id": "s1", "content": "用户的编辑器是 VS Code"},
            ],
        }
    )
    extractor = _SpyExtractor()
    mgr = _make_manager(memory, extractor)

    await mgr.on_turn_complete(
        "session-1",
        [
            {"role": "user", "content": "帮我用 ruff 格式化一下这个项目"},
            {"role": "assistant", "content": "好的，已经配置好 ruff 格式化规则"},
        ],
    )

    assert len(extractor.calls) == 1
    kwargs = extractor.calls[0]["kwargs"]
    assert "existing_facts" in kwargs
    facts = kwargs["existing_facts"]
    assert "用户偏好用 ruff 格式化 Python 代码" in facts
    assert "用户的编辑器是 VS Code" in facts

    # recall 以本轮用户消息为查询，且限定了层与条数
    assert len(memory.recall_calls) == 1
    call = memory.recall_calls[0]
    assert "ruff" in call["query"]
    assert call["memory_types"] == ["episodic", "semantic"]
    assert call["limit"] > 0


@pytest.mark.asyncio()
async def test_known_facts_skipped_when_recall_returns_empty() -> None:
    """recall 无结果时不传 existing_facts（避免污染 extractor 签名）。"""
    memory = _FakeMemory(recall_result={})
    extractor = _SpyExtractor()
    mgr = _make_manager(memory, extractor)

    await mgr.on_turn_complete(
        "session-1",
        [
            {"role": "user", "content": "帮我用 ruff 格式化一下这个项目"},
            {"role": "assistant", "content": "好的"},
        ],
    )

    assert len(extractor.calls) == 1
    assert "existing_facts" not in extractor.calls[0]["kwargs"]


# ---------------------------------------------------------------------------
# 2. recall 失败静默降级，不中断记忆写入
# ---------------------------------------------------------------------------


@pytest.mark.asyncio()
async def test_recall_failure_does_not_block_persistence() -> None:
    """recall 抛异常时降级为空列表，事实仍然被写入。"""
    memory = _FakeMemory(recall_error=RuntimeError("sqlite locked"))
    extractor = _SpyExtractor(
        facts=[{"content": "用户偏好用 ruff 格式化 Python 代码", "importance": 7}]
    )
    mgr = _make_manager(memory, extractor)

    await mgr.on_turn_complete(
        "session-1",
        [
            {"role": "user", "content": "帮我用 ruff 格式化一下这个项目"},
            {"role": "assistant", "content": "好的"},
        ],
    )

    # 提取仍然发生（两参回退）
    assert len(extractor.calls) == 1
    assert "existing_facts" not in extractor.calls[0]["kwargs"]
    # 且事实被持久化
    assert len(memory.persisted) == 1


@pytest.mark.asyncio()
async def test_recall_failure_returns_empty_list() -> None:
    """_collect_known_facts 在 recall 抛异常时返回空列表。"""
    memory = _FakeMemory(recall_error=RuntimeError("sqlite locked"))
    mgr = _make_manager(memory, _SpyExtractor())

    assert await mgr._collect_known_facts("ruff 格式化") == []


@pytest.mark.asyncio()
async def test_collect_known_facts_without_memory_manager() -> None:
    """memory_manager 为 None 时不崩，返回空列表。"""
    mgr = MemoryLifecycleManager(
        memory_manager=None, hooks=None, preferences_repo=_TruePrefs()
    )
    assert await mgr._collect_known_facts("任意问题") == []


# ---------------------------------------------------------------------------
# 3. 旧签名 extractor 兼容
# ---------------------------------------------------------------------------


@pytest.mark.asyncio()
async def test_two_arg_extractor_not_broken_by_existing_facts() -> None:
    """只接受两参的 extractor 不会因多传 existing_facts 而 TypeError。"""
    memory = _FakeMemory(
        recall_result={
            "episodic": [{"id": "e1", "content": "用户偏好用 ruff 格式化"}],
        }
    )
    extractor = _TwoArgExtractor()
    mgr = _make_manager(memory, extractor)

    await mgr.on_turn_complete(
        "session-1",
        [
            {"role": "user", "content": "帮我用 ruff 格式化一下这个项目"},
            {"role": "assistant", "content": "好的"},
        ],
    )

    assert extractor.calls == 1
    assert len(memory.persisted) == 1


# ---------------------------------------------------------------------------
# 4. _select_existing_facts —— 相关性过滤 + 字符预算
# ---------------------------------------------------------------------------


def test_select_existing_facts_filters_irrelevant() -> None:
    """与本轮无 token 交集的事实被丢弃。"""
    query = "帮我用 ruff 格式化 Python 代码"
    facts = [
        "用户偏好用 ruff 格式化 Python 代码",
        "用户的猫叫咪咪",
        "用户喜欢用 pnpm 管理依赖",
    ]
    selected = _select_existing_facts(query, facts)
    assert "用户偏好用 ruff 格式化 Python 代码" in selected
    assert "用户的猫叫咪咪" not in selected
    assert "用户喜欢用 pnpm 管理依赖" not in selected


def test_select_existing_facts_respects_char_budget() -> None:
    """总长度不超过预算。"""
    query = "ruff 格式化"
    facts = [f"用户偏好用 ruff 格式化第 {i} 条代码风格约定" for i in range(20)]
    budget = 120
    selected = _select_existing_facts(query, facts, budget=budget)
    assert selected
    assert sum(len(s) for s in selected) <= budget


def test_select_existing_facts_truncates_oversized_single_fact() -> None:
    """单条超预算时被截断并加省略号，不突破预算。"""
    query = "ruff 格式化"
    facts = ["用户偏好用 ruff 格式化" + "很长的补充说明" * 20]
    selected = _select_existing_facts(query, facts, budget=40)
    assert len(selected) == 1
    assert len(selected[0]) <= 40
    assert selected[0].endswith("…")


def test_select_existing_facts_empty_input() -> None:
    """空 facts 返回空列表；query 无 token 时不做相关性过滤（仅按预算截断）。"""
    assert _select_existing_facts("任何查询", []) == []
    # query 为空 → 无从判断相关性，保留事实（预算仍生效）——等价于旧
    # ``existing_facts[:20]`` 的降级语义
    assert _select_existing_facts("", ["无交集的事实 abcdefg"]) == [
        "无交集的事实 abcdefg"
    ]


def test_select_existing_facts_default_budget_matches_constant() -> None:
    """默认预算来自模块常量，避免两处漂移。"""
    query = "ruff"
    facts = [f"用户偏好用 ruff 格式化第 {i} 条" for i in range(500)]
    selected = _select_existing_facts(query, facts)
    assert sum(len(s) for s in selected) <= EXISTING_FACTS_CHAR_BUDGET
