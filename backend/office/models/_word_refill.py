"""Word 模板整块结构填充模型（P0，2026-11-26）。

供 ``POST /api/v1/office/word/template/refill`` 使用：模板没有占位符时，
按“块模板段落 + 内容块列表”克隆模板段落并替换文字。
"""

from __future__ import annotations

from typing import List, Literal

from pydantic import BaseModel, ConfigDict, Field

BlockKind = Literal["h1", "h2", "h3", "body", "bold"]


class WordTemplateBlock(BaseModel):
    """一个待写入的内容块；kind 对应模板中要克隆的段落类型。"""

    model_config = ConfigDict(extra="forbid")

    kind: BlockKind = Field(description="块类型：h1/h2/h3/body/bold")
    text: str = Field(min_length=1, max_length=10000)


class WordTemplateRefillResult(BaseModel):
    """整块结构填充结果。"""

    model_config = ConfigDict(extra="forbid")

    ok: bool
    template_path: str
    output_path: str
    filename: str
    inserted_blocks: int = Field(ge=0)
    removed_paragraphs: int = Field(ge=0)
    anchors: dict = Field(default_factory=dict)
    warnings: List[dict] = Field(default_factory=list)


__all__ = ["BlockKind", "WordTemplateBlock", "WordTemplateRefillResult"]
