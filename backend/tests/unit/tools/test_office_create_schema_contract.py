"""office_create 工具 schema 与 WordFormatSpec 模型的防漂移契约。

背景：R13 的 toc、R26 的 section_breaks 交付时只进了引擎模型，从未
声明进 office_create 的 LLM 工具 schema——schema 未声明即对模型不可见，
能力等于没做（R43 卫生轮发现并补齐）。本文件锁住两件事：

- 工具 schema 的 format_spec 属性集合 **全等** 于 WordFormatSpec 模型
  字段集合——今后模型加字段不带 schema 声明即红；
- 前端 types.ts 的 ``WordFormatSpec`` 接口覆盖模型全部字段——前后端
  契约不再单侧漂移。
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from backend.domain.tool_policy import ToolPolicy
from backend.office.models import WordFormatSpec, WordParagraphSpec, WordRunSpec
from backend.tools.office_create_tool import OfficeCreateTool
from backend.tools.office_lint_tool import OfficeLintWordTool

pytestmark = pytest.mark.unit

#: lint 工具的 format_spec 声明 = 有对应校验规则的可检查子集
#: （section_breaks/first_page_* 等暂无规则，有意不在列——加规则时同步）。
LINT_CHECKABLE_SPEC = {
    "page",
    "body",
    "headings",
    "title",
    "header",
    "footer",
    "numbering",
    "toc",
    "figure_index",
    "table_index",
}

_REPO_ROOT = Path(__file__).resolve().parents[4]


def test_schema_format_spec_properties_match_model_fields():
    """模型字段 ↔ schema 属性全等（防'引擎有、LLM 看不见'复发）。"""
    tool = OfficeCreateTool(policy=ToolPolicy())
    schema_props = tool.schema.parameters["properties"]["content"][
        "properties"
    ]["format_spec"]["properties"]
    assert set(schema_props) == set(WordFormatSpec.model_fields), (
        "office_create schema 的 format_spec 属性与 WordFormatSpec 模型"
        "字段不一致——模型新增/删除字段时必须同步工具 schema 声明"
    )


def test_schema_paragraph_properties_cover_model_fields():
    """schema 的 paragraphs item 属性覆盖 WordParagraphSpec 全部字段。

    M2 新增 ``style="quote"`` 与 ``runs``；未声明即 LLM 不可见。
    """
    tool = OfficeCreateTool(policy=ToolPolicy())
    item_props = tool.schema.parameters["properties"]["content"]["properties"][
        "paragraphs"
    ]["items"]["properties"]
    missing = set(WordParagraphSpec.model_fields) - set(item_props)
    assert not missing, f"schema paragraphs 缺属性: {sorted(missing)}"


def test_schema_paragraph_style_enum_matches_model():
    """style 枚举与模型 Literal 全等（防止 schema 虚报模型拒绝的值）。"""
    tool = OfficeCreateTool(policy=ToolPolicy())
    item_props = tool.schema.parameters["properties"]["content"]["properties"][
        "paragraphs"
    ]["items"]["properties"]
    assert set(item_props["style"]["enum"]) == {"bullet", "numbered", "quote"}


def test_schema_run_properties_cover_model_fields():
    """schema 的 runs item 属性覆盖 WordRunSpec 全部字段。"""
    tool = OfficeCreateTool(policy=ToolPolicy())
    run_props = tool.schema.parameters["properties"]["content"]["properties"][
        "paragraphs"
    ]["items"]["properties"]["runs"]["items"]["properties"]
    missing = set(WordRunSpec.model_fields) - set(run_props)
    assert not missing, f"schema runs 缺属性: {sorted(missing)}"


def test_types_ts_word_format_spec_covers_model_fields():
    """前端 types.ts 的 WordFormatSpec 覆盖模型全部字段。"""
    ts = (_REPO_ROOT / "src" / "shared" / "api" / "types.ts").read_text(
        encoding="utf-8"
    )
    block = ts[ts.index("export interface WordFormatSpec {"):]
    block = block[: block.index("\n}")]
    ts_keys = set(re.findall(r"^  (\w+)\??\s*:", block, re.M))
    missing = set(WordFormatSpec.model_fields) - ts_keys
    assert not missing, f"types.ts WordFormatSpec 缺字段: {sorted(missing)}"


def test_lint_schema_matches_declared_checkable_whitelist():
    """lint schema 的 format_spec 声明 = 有校验规则的可检查子集。

    与 office_create 的"全等模型"不同——lint 只暴露有规则的项；
    本测试锁住：声明既不缺规则（有 rule 无 schema），也不虚报
    （有 schema 无 rule → LLM 传了却不校验）。
    """
    tool = OfficeLintWordTool(policy=ToolPolicy())
    schema_props = tool.schema.parameters["properties"]["format_spec"][
        "properties"
    ]
    assert set(schema_props) == LINT_CHECKABLE_SPEC


def test_lint_checkable_whitelist_stays_within_model():
    """lint 可检查子集必须是模型字段的真子集（防 schema 虚报字段）。"""
    assert set(WordFormatSpec.model_fields) >= LINT_CHECKABLE_SPEC
