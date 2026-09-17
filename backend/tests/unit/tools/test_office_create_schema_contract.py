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
from backend.office.models import WordFormatSpec
from backend.tools.office_create_tool import OfficeCreateTool

pytestmark = pytest.mark.unit

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
