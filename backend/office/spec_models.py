# ruff: noqa: UP006, UP007, UP035 — release/win7 Python 3.8 兼容，保留 typing 注解
"""Pydantic models for the M2.5 spec library (格式规范书库).

A spec document is metadata around a ``word_rulepacks`` file: the rules
themselves stay in ``<workspace>/.sage/word-rulepacks/<rulepack_id>.json``
and are edited through the existing rule pack endpoints. These models only
describe the library row + binding fields.
"""

from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, Field

from backend.compat.win7.pydantic_compat import ConfigDict

from .word_rulepack_models import WordRulePack


class OfficeSpecDocument(BaseModel):
    """One row from ``office_spec_documents``."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, max_length=80)
    workspace_path: str = ""
    name: str = Field(min_length=1, max_length=200)
    source_file_path: Optional[str] = Field(default=None, max_length=2000)
    source_content_hash: Optional[str] = Field(default=None, max_length=200)
    rulepack_id: str = Field(min_length=1, max_length=80)
    is_default: bool = False
    created_at: int = 0
    updated_at: int = 0


class OfficeSpecListResult(BaseModel):
    """GET /office/specs result."""

    model_config = ConfigDict(extra="forbid")

    ok: bool = True
    workspace_path: str = ""
    specs: List[OfficeSpecDocument] = Field(default_factory=list)


class OfficeSpecDetailResult(BaseModel):
    """GET /office/specs/{id} result — metadata plus the live rule pack."""

    model_config = ConfigDict(extra="forbid")

    ok: bool = True
    spec: OfficeSpecDocument
    rulepack: Optional[WordRulePack] = None


class OfficeSpecSaveResult(BaseModel):
    """POST/PATCH /office/specs* result."""

    model_config = ConfigDict(extra="forbid")

    ok: bool = True
    spec: OfficeSpecDocument
    rulepack: Optional[WordRulePack] = None


class OfficeSpecBindingResult(BaseModel):
    """POST /office/doc/{doc_id}/spec result."""

    model_config = ConfigDict(extra="forbid")

    ok: bool = True
    doc_id: str
    spec_id: Optional[str] = None
    #: 解析后的生效规范书（文档绑定 → 工作区默认），便于前端即时刷新徽章。
    effective_spec: Optional[OfficeSpecDocument] = None


__all__ = [
    "OfficeSpecBindingResult",
    "OfficeSpecDetailResult",
    "OfficeSpecDocument",
    "OfficeSpecListResult",
    "OfficeSpecSaveResult",
]
