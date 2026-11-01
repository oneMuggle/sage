"""Pydantic models for Word rule packs and deterministic audits (M2a)."""

from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

from .doc_profile_models import WordTextAnchor

RuleCategory = Literal["page", "style", "structure", "content", "table"]
RuleSeverity = Literal["error", "warning"]
IssueScope = Literal["document", "section", "style", "paragraph", "table", "cell"]
PackOrigin = Literal["builtin", "workspace"]


class WordRuleSpec(BaseModel):
    """One executable rule inside a rule pack."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, max_length=80)
    title: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=1000)
    category: RuleCategory = "content"
    severity: RuleSeverity = "error"
    kind: str = Field(
        min_length=1,
        max_length=80,
        description="Checker kind, e.g. page.margins / style.font",
    )
    params: Dict[str, Any] = Field(default_factory=dict)
    source: str = Field(default="", max_length=500)
    fixable: bool = False
    fix_hint: str = Field(default="", max_length=1000)


class WordRulePack(BaseModel):
    """A named, versioned set of Word rules."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, max_length=80)
    name: str = Field(min_length=1, max_length=200)
    version: str = Field(default="1.0", max_length=40)
    description: str = Field(default="", max_length=2000)
    source: Optional[str] = Field(default=None, max_length=500)
    rules: List[WordRuleSpec] = Field(default_factory=list)


class WordRulePackSummary(BaseModel):
    """List item for a built-in or workspace rule pack."""

    model_config = ConfigDict(extra="forbid")

    id: str
    name: str
    version: str
    description: str = ""
    source: Optional[str] = None
    origin: PackOrigin
    rule_count: int = Field(ge=0)


class WordRulePackListResult(BaseModel):
    """GET /office/word/rulepacks result."""

    model_config = ConfigDict(extra="forbid")

    ok: bool = True
    workspace_path: str = ""
    packs: List[WordRulePackSummary] = Field(default_factory=list)
    warnings: List[Dict[str, str]] = Field(default_factory=list)


class WordRulePackDetailResult(BaseModel):
    """GET /office/word/rulepacks/{id} result."""

    model_config = ConfigDict(extra="forbid")

    ok: bool = True
    workspace_path: str = ""
    origin: PackOrigin
    pack: WordRulePack


class WordAuditIssue(BaseModel):
    """One deterministic audit finding with a locator anchor."""

    model_config = ConfigDict(extra="forbid")

    rule_id: str = Field(min_length=1, max_length=80)
    rule_pack_id: str = Field(min_length=1, max_length=80)
    category: RuleCategory
    severity: RuleSeverity
    scope: IssueScope = "document"
    message: str = Field(min_length=1, max_length=1000)
    expected: Optional[str] = Field(default=None, max_length=500)
    actual: Optional[str] = Field(default=None, max_length=500)
    fix_hint: str = Field(default="", max_length=1000)
    fixable: bool = False
    source: Optional[str] = Field(default=None, max_length=500)
    anchor: Optional[WordTextAnchor] = None


class WordAuditSummary(BaseModel):
    """Counts for an audit run."""

    model_config = ConfigDict(extra="forbid")

    rules_checked: int = Field(ge=0, default=0)
    issue_count: int = Field(ge=0, default=0)
    error_count: int = Field(ge=0, default=0)
    warning_count: int = Field(ge=0, default=0)
    paragraphs: int = Field(ge=0, default=0)
    tables: int = Field(ge=0, default=0)
    sections: int = Field(ge=0, default=0)


class WordAuditResult(BaseModel):
    """POST /office/word/audit result."""

    model_config = ConfigDict(extra="forbid")

    ok: bool
    source_path: str
    rule_pack_id: str
    rule_pack_name: str
    summary: WordAuditSummary
    issues: List[WordAuditIssue] = Field(default_factory=list)
    warnings: List[Dict[str, str]] = Field(default_factory=list)


__all__ = [
    "IssueScope",
    "PackOrigin",
    "RuleCategory",
    "RuleSeverity",
    "WordAuditIssue",
    "WordAuditResult",
    "WordAuditSummary",
    "WordRulePack",
    "WordRulePackDetailResult",
    "WordRulePackListResult",
    "WordRulePackSummary",
    "WordRuleSpec",
]
