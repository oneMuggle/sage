"""确定性门禁：引用解析、证据/大纲校验、参考文献生成。"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Sequence, Tuple

from .models import PaperRecord
from .pipeline_models import GateReport
from .run_store import (
    LiteratureRun,
    list_evidence,
    list_papers,
    load_outline,
    read_draft,
    read_jsonl,
    write_json,
)

_CITE_RE = re.compile(r"\[cite:([^\]]+)\]")


def extract_citations(text: str) -> List[str]:
    ordered: List[str] = []
    seen = set()
    for match in _CITE_RE.finditer(text or ""):
        for raw_key in match.group(1).split(","):
            key = raw_key.strip()
            if key and key not in seen:
                seen.add(key)
                ordered.append(key)
    return ordered


def _author_text(authors: Sequence[str]) -> str:
    if not authors:
        return "佚名"
    if len(authors) <= 3:
        return ", ".join(authors)
    return ", ".join(authors[:3]) + ", 等"


def _reference_line(number: int, paper: PaperRecord) -> str:
    authors = _author_text(paper.authors)
    venue = paper.venue or "[出版者不详]"
    year = paper.year or "[年份不详]"
    return f"[{number}] {authors}. {paper.title}[J]. {venue}, {year}."


def build_references(
    draft: str, papers: Sequence[PaperRecord], style: str = "gbt7714"
) -> Tuple[str, List[Dict[str, Any]]]:
    if style != "gbt7714":
        raise ValueError(f"暂不支持的引用样式: {style}")
    by_key = {p.paper_key: p for p in papers}
    entries: List[Dict[str, Any]] = []
    lines: List[str] = []
    for number, key in enumerate(extract_citations(draft), start=1):
        paper = by_key.get(key)
        if paper is None:
            continue
        lines.append(_reference_line(number, paper))
        entries.append({"key": key, "number": number, "paper": paper.to_dict()})
    return "\n".join(lines), entries


def run_gates(run: LiteratureRun) -> GateReport:
    errors: List[str] = []
    warnings: List[str] = []
    papers = list_papers(run)
    paper_keys = {p.paper_key for p in papers}
    draft = read_draft(run)

    if not read_jsonl(run.run_dir / "query_log.jsonl"):
        errors.append("检索日志为空：至少记录一次 query_log")
    if not papers:
        errors.append("文献池为空：没有可引用的文献")

    for evidence in list_evidence(run):
        if evidence.paper_key not in paper_keys:
            errors.append(f"证据 {evidence.evidence_id} 指向未知文献 {evidence.paper_key}")

    outline = load_outline(run)
    if outline is None:
        errors.append("缺少大纲 outline.json")
    else:
        for section in outline.sections:
            for key in section.source_keys:
                if key not in paper_keys:
                    errors.append(f"大纲章节 {section.id} 引用未知文献 {key}")

    if not draft.strip():
        errors.append("缺少草稿 draft.md")

    citations = extract_citations(draft)
    for key in citations:
        if key not in paper_keys:
            errors.append(f"草稿引用未知文献: {key}")
    for key in sorted(paper_keys - set(citations)):
        warnings.append(f"文献未被正文引用: {key}")

    report = GateReport(
        ok=not errors, errors=errors, warnings=warnings, citations=citations
    )
    write_json(run.run_dir / "verification.json", report.to_dict())
    return report
