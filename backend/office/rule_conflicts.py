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
_MAX_SIMILARITY_CHARS = 2000


@dataclass
class RuleConflict:
    rule_ids: List[str] = field(default_factory=list)
    message: str = ""
    suggestion: str = ""
    severity: str = "warning"


@dataclass
class _PreparedRule:
    """A rule normalized once, with its capped bigram set precomputed."""

    rule: Rule
    key: str
    grams: set


def _normalize(value: str) -> str:
    return re.sub(r"\s+", "", value or "")


def _bigram_set(text: str) -> set:
    return {text[i : i + 2] for i in range(len(text) - 1)}


def _bigram_similarity(left_grams: set, right_grams: set) -> float:
    if not left_grams or not right_grams:
        return 0.0
    overlap = len(left_grams & right_grams)
    return overlap / float(len(left_grams | right_grams))


def _prepare(rule: Rule) -> _PreparedRule:
    if rule.check_mode == "regex":
        key = _normalize(rule.pattern or "")
    else:
        key = _normalize(rule.ai_prompt or rule.description or rule.name)
    return _PreparedRule(rule=rule, key=key, grams=_bigram_set(key[:_MAX_SIMILARITY_CHARS]))


def _describe(rule: Rule) -> str:
    return f"{rule.name}（{rule.id}）"


def _compare_regex(left: _PreparedRule, right: _PreparedRule) -> RuleConflict:
    if left.key == right.key:
        return RuleConflict(
            rule_ids=[left.rule.id, right.rule.id],
            message=f"规则 {_describe(left.rule)} 与 {_describe(right.rule)} 的正则表达式完全相同",
            suggestion="合并为一条规则，或在其中一条上调整 scope",
            severity="error",
        )
    return RuleConflict(
        rule_ids=[left.rule.id, right.rule.id],
        message=f"规则 {_describe(left.rule)} 与 {_describe(right.rule)} 的正则范围重叠",
        suggestion="确认两条规则的分工，必要时合并或收窄其中一条",
        severity="warning",
    )


def _compare_ai(left: _PreparedRule, right: _PreparedRule) -> RuleConflict:
    if left.key == right.key:
        severity = "error"
        message = f"规则 {_describe(left.rule)} 与 {_describe(right.rule)} 的 AI 提示词完全相同"
    else:
        severity = "warning"
        message = f"规则 {_describe(left.rule)} 与 {_describe(right.rule)} 的 AI 提示词高度相似"
    return RuleConflict(
        rule_ids=[left.rule.id, right.rule.id],
        message=message,
        suggestion="合并为一条规则，或改写其中一条的提示词以明确差异",
        severity=severity,
    )


def _regex_pair(left: _PreparedRule, right: _PreparedRule) -> Optional[RuleConflict]:
    if not left.key or not right.key:
        return None
    if left.key in right.key or right.key in left.key:
        return _compare_regex(left, right)
    return None


def _ai_pair(left: _PreparedRule, right: _PreparedRule) -> Optional[RuleConflict]:
    if not left.key or not right.key:
        return None
    if left.key == right.key:
        return _compare_ai(left, right)
    if _bigram_similarity(left.grams, right.grams) >= _MIN_PROMPT_SIMILARITY:
        return _compare_ai(left, right)
    return None


def _pair_conflicts(left: _PreparedRule, right: _PreparedRule) -> Optional[RuleConflict]:
    left_rule = left.rule
    right_rule = right.rule
    if left_rule.scope != right_rule.scope or left_rule.check_mode != right_rule.check_mode:
        return None
    if left_rule.check_mode == "regex":
        return _regex_pair(left, right)
    if left_rule.check_mode == "ai":
        return _ai_pair(left, right)
    return None


def detect_conflicts(rules: List[Rule]) -> List[RuleConflict]:
    """Return every conflicting pair among enabled rules (order-stable)."""
    prepared = [_prepare(rule) for rule in rules if rule.enabled]
    conflicts: List[RuleConflict] = []
    for index, left in enumerate(prepared):
        for right in prepared[index + 1 :]:
            conflict = _pair_conflicts(left, right)
            if conflict is not None:
                conflicts.append(conflict)
    return conflicts
