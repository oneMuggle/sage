"""JournalSpec / JournalContent / JournalViolation / JournalGenerationRecord 模型测试。"""
from datetime import datetime, timezone

import pytest

from backend.api.settings_models import model_dump_compat
from backend.office.journal.errors import JournalContentShapeError
from backend.office.journal.models import (
    CitationStyle,
    FontFamily,
    HeadingSpec,
    JournalContent,
    JournalGenerationRecord,
    JournalSpec,
    JournalViolation,
    ViolationSeverity,
    parse_obj,
)


def _sample_spec() -> JournalSpec:
    return JournalSpec(
        spec_id="spec_abc123",
        template_sha256="deadbeef" * 8,
        template_filename="simple_chinese_template.docx",
        font_body=FontFamily(family="宋体", ascii_family="Times New Roman", eastasia="宋体"),
        font_heading=FontFamily(family="黑体", ascii_family="黑体", eastasia="黑体"),
        body_pt=12.0,
        heading_pt=16.0,
        line_spacing=1.5,
        margins_cm=2.54,
        headings=[
            HeadingSpec(keyword="摘要", level=1, expected_pt=16.0),
            HeadingSpec(keyword="关键词", level=1, expected_pt=16.0),
        ],
        citation_style=CitationStyle.NUMERIC,
        page_size="A4",
    )


def test_journal_spec_round_trip_dump():
    spec = _sample_spec()
    # Pydantic v1 (.dict) keeps Enum members; v2 (model_dump mode='json')
    # serialises them to strings. Force enum→str so the round-trip works
    # on both v1 (win7) and v2 (main).
    dumped = {
        k: (v.value if hasattr(v, "value") else v)
        for k, v in model_dump_compat(spec).items()
    }
    loaded = parse_obj(JournalSpec, dumped)
    assert loaded == spec


def test_journal_content_requires_abstract():
    spec = _sample_spec()
    content = JournalContent(title="研究", sections={"keywords": "关键词"})
    with pytest.raises(JournalContentShapeError):
        spec.validate_content(content)  # 缺 abstract 应抛 JournalContentShapeError


def test_journal_content_validates_required_sections():
    spec = _sample_spec()
    content = JournalContent(
        title="研究",
        abstract="摘要内容",
        sections={"keywords": "关键词；测试"},
    )
    spec.validate_content(content)  # 不抛


def test_journal_violation_severity_enum():
    v = JournalViolation(
        rule_id="body_font",
        severity=ViolationSeverity.ERROR,
        message="字体应为宋体，实际 Calibri",
        location="paragraph 3",
    )
    assert v.severity is ViolationSeverity.ERROR


def test_journal_generation_record_epoch_ms():
    rec = JournalGenerationRecord(
        gen_id="gen_xyz",
        spec_id="spec_abc123",
        output_path="/workspace/office/journal/generated/p1.docx",
        mode="structured_fill",
        created_at=1736486400000,  # 2025-01-10 12:00:00Z
    )
    dt = datetime.fromtimestamp(rec.created_at / 1000, tz=timezone.utc)  # noqa: UP017 — Python 3.10 兼容
    assert dt.year == 2025
    assert dt.month == 1
