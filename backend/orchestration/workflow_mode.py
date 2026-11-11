"""TDD 工作流模式解析（``"tdd"`` | ``"fast"``）。

模式优先级（设计文档 §2「用户显式指令 > 任务元数据 > 环境变量 > 默认值」）
在本模块统一实现，供 planner / executor / subagent_runner 复用：

1. ``explicit`` —— 任务元数据显式声明（lane.metadata / TaskPacket / parameters）；
2. ``user_text`` —— 用户自然语言里的意图（"跳过测试" → fast，"用 TDD" → tdd）；
3. 环境变量 ``SAGE_TDD_MODE`` —— 全局兜底；
4. 默认值 ``"tdd"``。

设计要点：
- 纯函数，无副作用（环境变量只读）；非法值一律忽略而非抛错。
- 关键词匹配大小写不敏感；fast 关键词优先于 tdd 关键词
  （"不要写测试" 命中 fast 而非被 "写测试" 误判为 tdd）。
"""

from __future__ import annotations

import os
from typing import Iterable, Optional

TDD = "tdd"
FAST = "fast"
DEFAULT_WORKFLOW_MODE = TDD
ENV_WORKFLOW_MODE = "SAGE_TDD_MODE"

VALID_WORKFLOW_MODES = (TDD, FAST)

#: 触发 fast 模式的用户表述（先于 TDD 关键词匹配，避免 "不要写测试" 被误判）。
FAST_KEYWORDS = (
    "跳过测试",
    "不要写测试",
    "别写测试",
    "免测试",
    "快速实现",
    "先出原型",
    "skip tests",
    "skip test",
    "no tests",
    "fast mode",
    "prototype first",
)

#: 触发 tdd 模式的用户表述。
TDD_KEYWORDS = (
    "tdd",
    "测试驱动",
    "先写测试",
    "test-driven",
    "test driven",
    "test first",
)


def first_valid(candidates: Iterable[Optional[str]]) -> Optional[str]:
    """返回首个合法模式值；全部非法/为空时返回 ``None``。"""
    for candidate in candidates:
        if candidate in VALID_WORKFLOW_MODES:
            return candidate
    return None


def env_workflow_mode() -> Optional[str]:
    """读取环境变量 ``SAGE_TDD_MODE``；未设置或非法返回 ``None``。"""
    return first_valid([(os.environ.get(ENV_WORKFLOW_MODE) or "").strip().lower()])


def detect_from_text(text: Optional[str]) -> Optional[str]:
    """从用户文本识别模式意图；无匹配返回 ``None``。"""
    if not text:
        return None
    lowered = text.lower()
    if any(keyword in lowered for keyword in FAST_KEYWORDS):
        return FAST
    if any(keyword in lowered for keyword in TDD_KEYWORDS):
        return TDD
    return None


def resolve_workflow_mode(
    explicit: Optional[str] = None,
    user_text: Optional[str] = None,
) -> str:
    """解析最终生效的 workflow_mode。

    优先级：``explicit`` > ``user_text`` 意图 > 环境变量 > 默认 ``"tdd"``。
    """
    resolved = first_valid(
        [
            explicit,
            detect_from_text(user_text),
            env_workflow_mode(),
        ]
    )
    return resolved or DEFAULT_WORKFLOW_MODE
