"""R133 — BibTeX 解析工具单元测试。

覆盖：schema 契约（READ/无工具上下文）、text 缺失三态 → text_required、
合法 .bib 文本解析出 count + references 全字段、解析异常 parse_failed
前缀、全噪声文本 OfficeParseError 透传。
"""

from __future__ import annotations

import pytest

from backend.domain.risk import RiskClass
from backend.tools.office_bibtex_tool import OfficeBibTexTool

pytestmark = pytest.mark.unit

_BIB = """@article{einstein1905,
  title = {Zur Elektrodynamik bewegter Koerper},
  author = {Einstein, Albert},
  year = {1905},
}

@book{knuth1984,
  title = {The TeXbook},
  author = {Knuth, Donald E.},
}
"""


def test_schema_contract():
    tool = OfficeBibTexTool()
    schema = tool.schema
    assert schema.name == "office_parse_bibtex"
    assert schema.parameters["required"] == ["text"]
    assert tool.requires_tool_context is False


def test_risk_is_read():
    assert OfficeBibTexTool.risk == RiskClass.READ


@pytest.mark.parametrize("bad", [None, "", "   ", 123])
def test_text_missing_or_blank_rejected(bad):
    out = OfficeBibTexTool().execute(text=bad)
    assert out.success is False
    assert out.error == "text_required"


def test_parse_success_returns_references():
    out = OfficeBibTexTool().execute(text=_BIB)
    assert out.success is True
    assert out.content["count"] == 2
    refs = out.content["references"]
    assert refs[0]["key"] == "einstein1905"
    assert refs[1]["key"] == "knuth1984"
    assert refs[0]["authors"]
    assert refs[0]["title"]


def test_parse_exception_maps_to_parse_failed(monkeypatch):
    from backend.office import bibtex as bibtex_mod

    def boom(_text):
        raise RuntimeError("bad internals")

    monkeypatch.setattr(bibtex_mod, "parse_bibtex", boom)
    out = OfficeBibTexTool().execute(text="@x{y, title={t}}")
    assert out.success is False
    assert out.error.startswith("parse_failed:")


def test_all_noise_text_maps_to_parse_failed():
    out = OfficeBibTexTool().execute(text="这不是 BibTeX，只是普通中文文本。")
    assert out.success is False
    assert out.error.startswith("parse_failed:")
