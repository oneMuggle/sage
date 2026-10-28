"""``research_report`` — scout_deep 输出 schema（2026-10-28）。

将 WikiResearch 的 ``ResearchTask`` 结果转换为结构化 ``ResearchReport``，
供前端 ``ResearchSummaryCard`` 渲染、planner 读取上下文。

降级纪律：scout_deep 失败时返回空报告（confidence=0），绝不阻塞编排。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Literal, Optional

RelevanceLevel = Literal["high", "medium", "low"]


@dataclass
class ResearchFinding:
    """单条调研发现。"""

    title: str
    summary: str
    relevance: RelevanceLevel = "medium"
    sources: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "title": self.title,
            "summary": self.summary,
            "relevance": self.relevance,
            "sources": self.sources,
        }


@dataclass
class ResearchSource:
    """调研来源。"""

    url: str
    title: str
    snippet: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "url": self.url,
            "title": self.title,
            "snippet": self.snippet,
        }


@dataclass
class ResearchReport:
    """scout_deep 输出的结构化调研报告。

    字段含义：
    - ``topic``: 调研主题
    - ``findings``: 分点发现（带相关性标注）
    - ``sources``: 来源列表（URL + 摘要）
    - ``confidence``: 调研充分度（0-1）
    - ``estimated_effort``: 预估实施工作量（"低" | "中" | "高"）
    - ``synthesis``: LLM 综合报告原文（完整 markdown）
    """

    topic: str
    findings: List[ResearchFinding] = field(default_factory=list)
    sources: List[ResearchSource] = field(default_factory=list)
    confidence: float = 0.0
    estimated_effort: str = "中"
    synthesis: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "topic": self.topic,
            "findings": [f.to_dict() for f in self.findings],
            "sources": [s.to_dict() for s in self.sources],
            "confidence": self.confidence,
            "estimated_effort": self.estimated_effort,
            "synthesis": self.synthesis,
        }

    def to_planner_context(self, max_chars: int = 4000) -> str:
        """将报告序列化为 planner context 注入文本。

        截断至 ``max_chars`` 字符（默认 4000，与 SCOUT_FACTS_MAX_CHARS 一致）。
        空报告返回空字符串。
        """
        if not self.findings and not self.synthesis:
            return ""

        lines = [f"## 调研报告: {self.topic}"]
        lines.append(f"调研充分度: {self.confidence:.0%} | 预估工作量: {self.estimated_effort}")
        lines.append("")

        if self.findings:
            lines.append("### 关键发现")
            for f in self.findings:
                relevance_marker = {"high": "🔴", "medium": "🟡", "low": "🟢"}.get(
                    f.relevance, "⚪"
                )
                sources_str = ", ".join(f.sources[:3]) if f.sources else "无来源"
                lines.append(f"- {relevance_marker} **{f.title}**: {f.summary} [来源: {sources_str}]")
            lines.append("")

        if self.synthesis:
            lines.append("### 综合报告")
            lines.append(self.synthesis[:2000])

        result = "\n".join(lines)
        return result[:max_chars]


def build_report_from_research_task(
    topic: str,
    synthesis: str,
    web_results: List[Any],
    queries: Optional[List[str]] = None,
) -> ResearchReport:
    """将 WikiResearch ``ResearchTask`` 结果转换为 ``ResearchReport``。

    ``web_results`` 是 ``WebSearchResult`` dataclass 列表（有 title/url/snippet/score）。
    本函数接受 dict 或 dataclass（duck-typed），便于测试注入。

    降级纪律：synthesis 为空时 confidence=0；web_results 为空时 sources 为空列表。
    """
    sources = [
        ResearchSource(
            url=str(getattr(r, "url", None) if not isinstance(r, dict) else r.get("url", "")),
            title=str(getattr(r, "title", None) if not isinstance(r, dict) else r.get("title", "")),
            snippet=str(getattr(r, "snippet", None) if not isinstance(r, dict) else r.get("snippet", "")),
        )
        for r in (web_results or [])[:10]
    ]

    # 从 synthesis 提取 findings（简单分点解析 —— LLM 综合报告通常用 ## 或 - 分节）
    findings = _extract_findings(synthesis, sources)

    # confidence 基于来源数量和 synthesis 长度估算
    confidence = _estimate_confidence(synthesis, web_results)

    # estimated_effort 基于 findings 数量 + 来源数量
    estimated_effort = _estimate_effort(findings, sources)

    return ResearchReport(
        topic=topic,
        findings=findings,
        sources=sources,
        confidence=confidence,
        estimated_effort=estimated_effort,
        synthesis=synthesis,
    )


def _extract_findings(
    synthesis: str, sources: List[ResearchSource]
) -> List[ResearchFinding]:
    """从 synthesis markdown 中提取分点发现。

    启发式规则：
    - 以 "## " 或 "### " 开头的行 → 标题
    - 以 "- " 或 "* " 或 "1. " 开头的行 → 要点
    - 其余视为摘要

    最多提取 8 条（防止过长）。
    """
    if not synthesis.strip():
        return []

    findings: List[ResearchFinding] = []
    current_title = ""
    current_summary_lines: List[str] = []

    def flush_current() -> None:
        if current_title or current_summary_lines:
            summary = " ".join(current_summary_lines).strip()
            if summary:
                # 根据标题关键词推断相关性
                relevance: RelevanceLevel = "medium"
                title_lower = current_title.lower()
                if any(kw in title_lower for kw in ("核心", "关键", "重要", "必须", "critical", "key")):
                    relevance = "high"
                elif any(kw in title_lower for kw in ("可选", "次要", "optional", "minor")):
                    relevance = "low"

                findings.append(
                    ResearchFinding(
                        title=current_title or "发现",
                        summary=summary[:300],
                        relevance=relevance,
                        sources=[s.url for s in sources[:2]],
                    )
                )

    for line in synthesis.splitlines():
        stripped = line.strip()
        if stripped.startswith("## ") or stripped.startswith("### "):
            flush_current()
            current_title = stripped.lstrip("#").strip()
            current_summary_lines = []
        elif stripped.startswith(("- ", "* ")) or (
            len(stripped) > 2 and stripped[0].isdigit() and stripped[1] == "."
        ):
            # 列表项 → 作为当前章节的摘要
            point = stripped.lstrip("-*").strip()
            if point and point[0].isdigit():
                point = point.split(".", 1)[-1].strip()
            current_summary_lines.append(point)
        elif stripped:
            current_summary_lines.append(stripped)

    flush_current()

    # 如果没有提取到结构化发现，用 synthesis 前 200 字作为单条发现
    if not findings and synthesis.strip():
        findings.append(
            ResearchFinding(
                title="调研摘要",
                summary=synthesis.strip()[:300],
                relevance="medium",
                sources=[s.url for s in sources[:2]],
            )
        )

    return findings[:8]


def _estimate_confidence(synthesis: str, web_results: Optional[List[Any]]) -> float:
    """估算调研充分度（0-1）。

    信号：
    - synthesis 长度（> 1000 字 → +0.3）
    - web_results 数量（> 5 → +0.3, > 10 → +0.5）
    - 综合：base = min(len/2000 * 0.4 + sources * 0.05, 1.0)
    """
    if not synthesis.strip():
        return 0.0

    length_score = min(len(synthesis) / 2000, 1.0) * 0.4
    source_count = len(web_results) if web_results else 0
    source_score = min(source_count / 10, 1.0) * 0.5
    base = min(length_score + source_score + 0.1, 1.0)  # +0.1 基础分（有合成结果）

    return round(base, 2)


def _estimate_effort(
    findings: List[ResearchFinding], sources: List[ResearchSource]
) -> str:
    """估算实施工作量。

    信号：
    - findings 数量（> 5 → 高）
    - sources 数量（> 8 → 高）
    - 有 high relevance findings → 至少中
    """
    high_count = sum(1 for f in findings if f.relevance == "high")

    if len(findings) > 5 or len(sources) > 8 or high_count >= 3:
        return "高"
    elif len(findings) >= 3 or len(sources) >= 4 or high_count >= 1:
        return "中"
    else:
        return "低"


__all__ = [
    "ResearchReport",
    "ResearchFinding",
    "ResearchSource",
    "build_report_from_research_task",
]
