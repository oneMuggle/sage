"""``test_research_report`` — ``research_report.py`` 单元测试（2026-10-28）。

覆盖：
- ``ResearchReport`` / ``ResearchFinding`` / ``ResearchSource`` dataclass 序列化
- ``build_report_from_research_task()`` 正常 + 降级路径
- ``_extract_findings()`` markdown 解析启发式规则
- ``_estimate_confidence()`` 信号计算
- ``_estimate_effort()`` 规则引擎
- ``to_planner_context()`` 截断 + 空报告
"""
from __future__ import annotations

from types import SimpleNamespace

from backend.orchestration.research_report import (
    ResearchFinding,
    ResearchReport,
    ResearchSource,
    build_report_from_research_task,
)

# ── Dataclass 序列化 ──────────────────────────────────────────────────────────


def test_finding_to_dict() -> None:
    f = ResearchFinding(
        title="核心发现",
        summary="测试摘要",
        relevance="high",
        sources=["https://example.com/1"],
    )
    d = f.to_dict()
    assert d == {
        "title": "核心发现",
        "summary": "测试摘要",
        "relevance": "high",
        "sources": ["https://example.com/1"],
    }


def test_source_to_dict() -> None:
    s = ResearchSource(url="https://example.com", title="Example", snippet="Hello")
    d = s.to_dict()
    assert d == {"url": "https://example.com", "title": "Example", "snippet": "Hello"}


def test_report_to_dict_round_trip() -> None:
    r = ResearchReport(
        topic="TDD",
        findings=[ResearchFinding(title="f1", summary="s1")],
        sources=[ResearchSource(url="u", title="t", snippet="sn")],
        confidence=0.75,
        estimated_effort="高",
        synthesis="综合内容",
    )
    d = r.to_dict()
    assert d["topic"] == "TDD"
    assert d["confidence"] == 0.75
    assert d["estimated_effort"] == "高"
    assert len(d["findings"]) == 1
    assert len(d["sources"]) == 1
    assert d["synthesis"] == "综合内容"


# ── _extract_findings (via build_report_from_research_task) ────────────────────


def test_extract_findings_from_headings() -> None:
    synthesis = """## 核心架构
基于事件驱动的微服务架构。

## 可选组件
消息队列可选择 Kafka 或 RabbitMQ。

## 次要考虑
日志格式可以后续优化。
"""
    report = build_report_from_research_task(topic="arch", synthesis=synthesis, web_results=[])
    titles = [f.title for f in report.findings]
    assert "核心架构" in titles
    assert "可选组件" in titles
    assert "次要考虑" in titles


def test_extract_findings_relevance_keywords() -> None:
    synthesis = """## 关键安全要求
必须使用 OAuth 2.0。

## 次要功能
可选的主题切换。
"""
    report = build_report_from_research_task(topic="sec", synthesis=synthesis, web_results=[])
    finding_map = {f.title: f.relevance for f in report.findings}
    assert finding_map["关键安全要求"] == "high"
    assert finding_map["次要功能"] == "low"


def test_extract_findings_from_bullet_list() -> None:
    synthesis = """## 技术栈
- Python 3.10
- FastAPI
- PostgreSQL
"""
    report = build_report_from_research_task(topic="stack", synthesis=synthesis, web_results=[])
    assert len(report.findings) == 1  # 单章节 → 单 finding
    assert "Python 3.10" in report.findings[0].summary
    assert "FastAPI" in report.findings[0].summary


def test_extract_findings_no_headings_fallback() -> None:
    """无 ## 标题时，文本由 flush_current 生成单条 finding（title='发现'）。"""
    synthesis = "这是一段没有标题的调研报告，包含一些关键信息。"
    report = build_report_from_research_task(topic="x", synthesis=synthesis, web_results=[])
    assert len(report.findings) == 1
    # flush_current 在 current_title 为空时用 "发现" 作为标题
    assert report.findings[0].title == "发现"
    assert "关键信息" in report.findings[0].summary


def test_extract_findings_empty_synthesis() -> None:
    report = build_report_from_research_task(topic="empty", synthesis="", web_results=[])
    assert report.findings == []


def test_extract_findings_capped_at_8() -> None:
    """防止超长报告 —— 最多 8 条 findings。"""
    sections = "\n".join(f"## Section {i}\nContent {i}" for i in range(15))
    report = build_report_from_research_task(topic="big", synthesis=sections, web_results=[])
    assert len(report.findings) <= 8


# ── _estimate_confidence ───────────────────────────────────────────────────────


def test_confidence_empty_synthesis_is_zero() -> None:
    report = build_report_from_research_task(topic="e", synthesis="", web_results=[])
    assert report.confidence == 0.0


def test_confidence_short_synthesis_few_sources() -> None:
    """短 synthesis + 无来源 → 低 confidence（仅基础分）。"""
    report = build_report_from_research_task(topic="s", synthesis="短内容", web_results=[])
    assert 0.0 < report.confidence <= 0.3


def test_confidence_long_synthesis_many_sources() -> None:
    """长 synthesis + 多来源 → 高 confidence。"""
    long_synthesis = "A" * 2500
    sources = [SimpleNamespace(url=f"u{i}", title=f"t{i}", snippet=f"s{i}") for i in range(12)]
    report = build_report_from_research_task(topic="l", synthesis=long_synthesis, web_results=sources)
    assert report.confidence >= 0.7


def test_confidence_bounded_at_1() -> None:
    """极端输入不应超过 1.0。"""
    very_long = "X" * 10000
    many_sources = [SimpleNamespace(url=f"u{i}", title=f"t{i}", snippet=f"s{i}") for i in range(50)]
    report = build_report_from_research_task(topic="huge", synthesis=very_long, web_results=many_sources)
    assert report.confidence <= 1.0


# ── _estimate_effort ───────────────────────────────────────────────────────────


def test_effort_low_for_small_report() -> None:
    """少量 findings + 少量 sources → 低工作量。"""
    report = build_report_from_research_task(
        topic="small",
        synthesis="## 小发现\n一个简单方案。",
        web_results=[SimpleNamespace(url="u", title="t", snippet="s")],
    )
    assert report.estimated_effort in ("低", "中")


def test_effort_high_for_many_findings() -> None:
    """很多 sections → 高工作量。"""
    sections = "\n".join(f"## 关键模块 {i}\n详细描述 {i}" for i in range(10))
    report = build_report_from_research_task(topic="big", synthesis=sections, web_results=[])
    assert report.estimated_effort == "高"


def test_effort_medium_for_mixed() -> None:
    """中等 findings + 有 high relevance → 中。"""
    synthesis = """## 核心架构
事件驱动设计。

## 次要考虑
可选的缓存层。
"""
    report = build_report_from_research_task(topic="mid", synthesis=synthesis, web_results=[])
    assert report.estimated_effort == "中"


# ── to_planner_context ─────────────────────────────────────────────────────────


def test_planner_context_empty_report_returns_empty() -> None:
    r = ResearchReport(topic="empty", confidence=0.0)
    assert r.to_planner_context() == ""


def test_planner_context_includes_findings_and_meta() -> None:
    r = ResearchReport(
        topic="认证系统",
        findings=[
            ResearchFinding(title="OAuth 2.0", summary="标准协议", relevance="high"),
        ],
        confidence=0.75,
        estimated_effort="高",
        synthesis="综合报告内容",
    )
    ctx = r.to_planner_context()
    assert "认证系统" in ctx
    assert "75%" in ctx
    assert "高" in ctx
    assert "OAuth 2.0" in ctx
    assert "综合报告内容" in ctx


def test_planner_context_truncates_to_max_chars() -> None:
    r = ResearchReport(
        topic="T",
        findings=[ResearchFinding(title="f", summary="x" * 5000)],
        synthesis="y" * 5000,
    )
    ctx = r.to_planner_context(max_chars=500)
    assert len(ctx) <= 500


# ── build_report_from_research_task: dict-style web_results ────────────────────


def test_build_report_accepts_dict_web_results() -> None:
    """web_results 可以是 dict（duck-typed），不必是 dataclass。"""
    results = [
        {"url": "https://a.com", "title": "A", "snippet": "Snippet A"},
        {"url": "https://b.com", "title": "B", "snippet": "Snippet B"},
    ]
    report = build_report_from_research_task(
        topic="dict", synthesis="## 发现\n内容", web_results=results
    )
    assert len(report.sources) == 2
    assert report.sources[0].url == "https://a.com"
    assert report.sources[1].title == "B"


def test_build_report_sources_capped_at_10() -> None:
    """web_results 超过 10 条时截断。"""
    results = [SimpleNamespace(url=f"u{i}", title=f"t{i}", snippet=f"s{i}") for i in range(20)]
    report = build_report_from_research_task(
        topic="cap", synthesis="## 内容\n详情", web_results=results
    )
    assert len(report.sources) == 10


def test_build_report_none_web_results() -> None:
    """web_results=None 不应崩溃。"""
    report = build_report_from_research_task(topic="none", synthesis="## 内容\n详情", web_results=None)
    assert report.sources == []
