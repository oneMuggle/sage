# ruff: noqa: UP006, UP007, UP035, UP045 — release/win7 Python 3.8 兼容
"""P3 规则管理的 pydantic 模型（规则 / 规则组 / 规则包 / 审计结果）。"""

from __future__ import annotations

from typing import List, Literal, Optional

from pydantic import BaseModel, Field


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
