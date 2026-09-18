"""Unit tests for Round 49 — 文档核心属性（core properties）。"""

from __future__ import annotations

import pytest
from docx import Document

from backend.office.models import (
    OfficeWordGenerateRequest,
    WordMetadataSpec,
    WordParagraphSpec,
    WordTableSpec,
)
from backend.office.word import generate_docx

pytestmark = pytest.mark.unit


def _gen(tmp_path, name, metadata=None):
    req = OfficeWordGenerateRequest(
        workspace_path="",
        filename=name,
        title="季度报告",
        paragraphs=[WordParagraphSpec(text="正文")],
        tables=[WordTableSpec(headers=["A"], rows=[["1"]])],
        metadata=metadata,
    )
    return generate_docx(req, output_dir=str(tmp_path))


def test_metadata_written_to_core_properties(tmp_path) -> None:
    output = _gen(
        tmp_path,
        "meta.docx",
        metadata=WordMetadataSpec(
            author="张三",
            subject="季度经营分析",
            keywords="营收；成本",
            comments="内部资料",
            category="经营报告",
        ),
    )
    core = Document(str(output)).core_properties
    assert core.title == "季度报告"
    assert core.author == "张三"
    assert core.subject == "季度经营分析"
    assert core.keywords == "营收；成本"
    assert core.comments == "内部资料"
    assert core.category == "经营报告"


def test_default_metadata_only_sets_title(tmp_path) -> None:
    """无 metadata → 只写 title（不臆造作者）。"""
    output = _gen(tmp_path, "plain.docx")
    core = Document(str(output)).core_properties
    assert core.title == "季度报告"
    # 不臆造作者：保留 python-docx 模板默认，显式 metadata.author 才覆盖
    assert core.subject in (None, "")
