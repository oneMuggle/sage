# ruff: noqa: UP006, UP007, UP035, UP045 — release/win7 Python 3.8 兼容
"""Deterministic conflict pre-filter for the Office rules workspace (P3).

Rules can only collide when they share the same ``scope`` and ``check_mode``.
Identical regex / identical AI prompt is an error; near-duplicate is a warning.
The LLM adjudication described in the design spec is deliberately out of scope.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List, Optional

from backend.office.rule_models import Rule

_MIN_PROMPT_SIMILARITY = 0.6


@dataclass
class RuleConflict:
    rule_ids: List[str] = field(default_factory=list)
    message: str = ""
    suggestion: str = ""
    severity: str = "warning"


def _normalize(value: str) -> str:
    return re.sub(r"\s+", "", value or "")


def _bigrams(text: str) -> set:
    return {text[i : i + 2] for i in range(len(text) - 1)}


def _bigram_similarity(left: str, right: str) -> float:
    left_grams = _bigrams(left)
    right_grams = _bigrams(right)
    if not left_grams or not right_grams:
        return 0.0
    overlap = len(left_grams & right_grams)
    return overlap / float(len(left_grams | right_grams))


def _describe(rule: Rule) -> str:
    return f"{rule.name}（{rule.id}）"


def _compare_regex(left: Rule, right: Rule) -> RuleConflict:
    left_pattern = _normalize(left.pattern or "")
    right_pattern = _normalize(right.pattern or "")
    if left_pattern == right_pattern:
        return RuleConflict(
            rule_ids=[left.id, right.id],
            message=f"规则 {_describe(left)} 与 {_describe(right)} 的正则表达式完全相同",
            suggestion="合并为一条规则，或在其中一条上调整 scope",
            severity="error",
        )
    return RuleConflict(
        rule_ids=[left.id, right.id],
        message=f"规则 {_describe(left)} 与 {_describe(right)} 的正则范围重叠",
        suggestion="确认两条规则的分工，必要时合并或收窄其中一条",
        severity="warning",
    )


def _compare_ai(left: Rule, right: Rule) -> RuleConflict:
    left_prompt = _normalize(left.ai_prompt or left.description or left.name)
    right_prompt = _normalize(right.ai_prompt or right.description or right.name)
    if left_prompt == right_prompt:
        severity = "error"
        message = f"规则 {_describe(left)} 与 {_describe(right)} 的 AI 提示词完全相同"
    else:
        severity = "warning"
        message = f"规则 {_describe(left)} 与 {_describe(right)} 的 AI 提示词高度相似"
    return RuleConflict(
        rule_ids=[left.id, right.id],
        message=message,
        suggestion="合并为一条规则，或改写其中一条的提示词以明确差异",
        severity=severity,
    )


def _regex_pair(left: Rule, right: Rule) -> Optional[RuleConflict]:
    left_pattern = _normalize(left.pattern or "")
    right_pattern = _normalize(right.pattern or "")
    if not left_pattern or not right_pattern:
        return None
    if left_pattern in right_pattern or right_pattern in left_pattern:
        return _compare_regex(left, right)
    return None


def _ai_pair(left: Rule, right: Rule) -> Optional[RuleConflict]:
    left_prompt = _normalize(left.ai_prompt or left.description or left.name)
    right_prompt = _normalize(right.ai_prompt or right.description or right.name)
    if not left_prompt or not right_prompt:
        return None
    if left_prompt == right_prompt:
        return _compare_ai(left, right)
    if _bigram_similarity(left_prompt, right_prompt) >= _MIN_PROMPT_SIMILARITY:
        return _compare_ai(left, right)
    return None


def _pair_conflicts(left: Rule, right: Rule) -> Optional[RuleConflict]:
    if left.scope != right.scope or left.check_mode != right.check_mode:
        return None
    if left.check_mode == "regex":
        return _regex_pair(left, right)
    if left.check_mode == "ai":
        return _ai_pair(left, right)
    return None


def detect_conflicts(rules: List[Rule]) -> List[RuleConflict]:
    """Return every conflicting pair among enabled rules (order-stable)."""
    active = [rule for rule in rules if rule.enabled]
    conflicts: List[RuleConflict] = []
    for index, left in enumerate(active):
        for right in active[index + 1 :]:
            conflict = _pair_conflicts(left, right)
            if conflict is not None:
                conflicts.append(conflict)
    return conflicts
