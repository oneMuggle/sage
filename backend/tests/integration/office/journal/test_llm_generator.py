"""journal generator (LLM generate_article) 集成测试。

覆盖：
- 单轮通过：LLM 返回合法 content → 1 次 LLM 调用；
- 两轮自纠：round 0 content 缺 keywords → round 1 修正 → 2 次 LLM 调用。
"""
from pathlib import Path

import pytest

from backend.office.journal.generator import generate_article
from backend.office.journal.parser import parse_journal_spec

FIXTURE_DIR = (
    Path(__file__).resolve().parent.parent.parent.parent
    / "fixtures"
    / "journal"
)


class MockLLMProxy:
    """返回结构化 content JSON 的 mock LLM proxy。"""

    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []

    async def generate(self, *, system_prompt, user_prompt, output_schema=None, **kwargs):
        self.calls.append({"system": system_prompt, "user": user_prompt})
        return self._responses.pop(0)


@pytest.fixture()
def workspace(tmp_path: Path) -> Path:
    (tmp_path / "office" / "journal" / "specs").mkdir(parents=True)
    (tmp_path / "office" / "journal" / "cache").mkdir(parents=True)
    (tmp_path / "office" / "journal" / "generated").mkdir(parents=True)
    return tmp_path


@pytest.mark.asyncio()
async def test_generate_article_one_round_passes(workspace):
    spec = parse_journal_spec(FIXTURE_DIR / "simple_chinese_template.docx")
    content_round1 = {
        "title": "测试论文",
        "abstract": "测试摘要内容。",
        "sections": {"keywords": "测试；关键词"},
        "references": [],
        "citations": [],
    }
    mock = MockLLMProxy([content_round1])
    rec = await generate_article(
        spec,
        user_request="写一个测试论文",
        llm_proxy=mock,
        workspace=workspace,
        output_filename="llm.docx",
        max_rounds=2,
    )
    assert rec.mode == "llm_generate"
    assert len(mock.calls) == 1
    assert Path(rec.output_path).exists()


@pytest.mark.asyncio()
async def test_generate_article_two_rounds_with_self_correction(workspace):
    """Round 1 缺 '关键词' → validator 报 warning；Round 2 补全。"""
    spec = parse_journal_spec(FIXTURE_DIR / "simple_chinese_template.docx")
    content_round1 = {
        "title": "论文",
        "abstract": "摘要。",
        "sections": {"keywords": ""},  # 空 → validator 报 warning
        "references": [],
        "citations": [],
    }
    content_round2 = {
        "title": "论文",
        "abstract": "摘要。",
        "sections": {"keywords": "已修正"},
        "references": [],
        "citations": [],
    }
    mock = MockLLMProxy([content_round1, content_round2])
    rec = await generate_article(
        spec,
        user_request="论文",
        llm_proxy=mock,
        workspace=workspace,
        output_filename="llm.docx",
        max_rounds=2,
    )
    assert rec.mode == "llm_generate"
    assert len(mock.calls) == 2  # 跑了两轮
