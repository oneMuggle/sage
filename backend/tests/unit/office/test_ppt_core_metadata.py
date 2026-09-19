"""Unit tests for Round 52 — PPT core properties（三件套对称收口）。"""

from __future__ import annotations

import pytest
from pptx import Presentation

from backend.office.models import OfficePptGenerateRequest, PptSlideSpec
from backend.office.ppt import generate_ppt, read_ppt

pytestmark = pytest.mark.unit


def _gen(tmp_path, name, metadata=None):
    req = OfficePptGenerateRequest(
        workspace_path="",
        filename=name,
        slides=[PptSlideSpec(title="标题", bullets=["点"])],
        metadata=metadata,
    )
    return generate_ppt(req, output_dir=str(tmp_path))


def test_ppt_metadata_roundtrip(tmp_path) -> None:
    output = _gen(
        tmp_path,
        "meta.pptx",
        metadata={
            "author": "张三",
            "subject": "季度汇报",
            "keywords": "Q3",
            "category": "汇报",
        },
    )
    result = read_ppt(output, workspace_path="")
    assert result.metadata is not None
    assert result.metadata.author == "张三"
    assert result.metadata.subject == "季度汇报"
    assert result.metadata.keywords == "Q3"
    assert result.metadata.category == "汇报"


def test_ppt_read_without_metadata_returns_none(tmp_path) -> None:
    output = _gen(tmp_path, "plain.pptx")
    prs = Presentation(str(output))
    prs.core_properties.author = ""
    prs.core_properties.comments = ""
    prs.save(str(output))
    result = read_ppt(output, workspace_path="")
    assert result.metadata is None
