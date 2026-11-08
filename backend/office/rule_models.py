# ruff: noqa: UP006, UP007, UP035, UP045 — release/win7 Python 3.8 兼容
"""P3 规则管理的 pydantic 模型（规则 / 规则组 / 规则包 / 审计结果）。"""

from __future__ import annotations

import re
from typing import List, Literal, Optional

from pydantic import BaseModel, Field

# Pydantic v1/v2 compatibility (matches backend/plugins/manifest.py idiom).
try:
    # Pydantic v2
    from pydantic import field_validator
except ImportError:  # pragma: no cover — release/win7 runs v1
    # Pydantic v1 fallback
    from pydantic import validator as field_validator  # type: ignore


_MAX_PATTERN_LENGTH = 1000
# Catches patterns that nest quantifiers — e.g. ``(a+)+`` or ``(x*)*`` — which
# are the classic catastrophic-backtracking shape. We reject them at the API
# boundary rather than hoping the regex engine times out gracefully.
_NESTED_QUANTIFIER = re.compile(r"\([^()]*[+*][^()]*\)\s*[+*{]")


def _check_pattern(value: Optional[str]) -> Optional[str]:
    """Reject regex patterns that are too long or prone to catastrophic backtracking."""
    if value is None:
        return value
    if len(value) > _MAX_PATTERN_LENGTH:
        raise ValueError(f"pattern 长度超过 {_MAX_PATTERN_LENGTH} 字符")
    if _NESTED_QUANTIFIER.search(value):
        raise ValueError("正则表达式包含可能失控的回溯结构（嵌套量词）")
    return value


class Rule(BaseModel):
    id: str
    name: str
    type: Literal["format", "terminology", "citation", "structure", "custom"]
    severity: Literal["error", "warning", "info"]
    scope: Literal["full", "heading", "body", "table", "caption"]
    description: str = ""
    check_mode: Literal["regex", "ai"]
    pattern: Optional[str] = None
    ai_prompt: Optional[str] = None
    enabled: bool = True
    group_id: str

    @field_validator("pattern")
    @classmethod
    def _validate_pattern(cls, value: Optional[str]) -> Optional[str]:
        return _check_pattern(value)


class RuleGroup(BaseModel):
    id: str
    name: str
    description: str = ""
    rules: List[Rule] = Field(default_factory=list)
    priority: int = 0
    builtin: bool = False


class RulePack(BaseModel):
    name: str
    version: str
    groups: List[RuleGroup] = Field(default_factory=list)
    exported_at: str
    exported_by: str


class AuditFinding(BaseModel):
    rule_id: str
    rule_name: str
    severity: Literal["error", "warning", "info"]
    message: str
    location: str
    suggestion: str


class AuditResult(BaseModel):
    findings: List[AuditFinding] = Field(default_factory=list)
    error_count: int = 0
    warning_count: int = 0
    info_count: int = 0
