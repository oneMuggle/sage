"""站点专属事实不得写进通用代码与技能正文（spec §3.3）。

站点差异只允许落在 profile（notes / backends / pdf.* / search.*）与
skill 的 references/ 里。通用代码与技能正文出现具体站点主机即视为回归。
"""

from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

#: 站点专属字面量（小写主机片段 + 具体站点 id）
_SITE_LITERALS = (
    "xueshu789",
    "cnki.net",
    "oversea.cnki",
    "kns.cnki",
    "xueshu789.cc",
)

_LITERATURE_DIR = Path(__file__).resolve().parents[2] / "literature"
_LITERATURE_SKILL_MD = (
    Path(__file__).resolve().parents[2]
    / "skills"
    / "skill_md"
    / "shipped"
    / "literature-research"
    / "SKILL.md"
)


def _literature_sources():
    for path in sorted(_LITERATURE_DIR.glob("*.py")):
        yield path, path.read_text(encoding="utf-8")
    yield _LITERATURE_SKILL_MD, _LITERATURE_SKILL_MD.read_text(encoding="utf-8")


def test_no_site_specific_literals_in_literature_code_or_skill_body() -> None:
    offenders = []
    for path, text in _literature_sources():
        lowered = text.lower()
        for literal in _SITE_LITERALS:
            if literal in lowered:
                offenders.append(f"{path.name}: {literal}")
    assert not offenders, (
        "站点专属事实不得出现在通用代码/技能正文（应下沉到 profile）："
        + ", ".join(offenders)
    )


def test_pipeline_reference_stays_free_of_site_facts() -> None:
    """references/pipeline.md 是纯流程契约 —— 站点事实不许进。"""
    pipeline = (
        _LITERATURE_SKILL_MD.parent / "references" / "pipeline.md"
    ).read_text(encoding="utf-8").lower()
    for literal in _SITE_LITERALS:
        assert literal not in pipeline, f"pipeline.md 不该出现站点事实: {literal}"
