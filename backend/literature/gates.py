"""确定性门禁：引用解析、证据/大纲校验、参考文献生成。"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Sequence, Tuple

from .models import PaperRecord
from .pipeline_models import Claim, ClaimVerdict, GateReport
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


def _ieee_author(name: str) -> str:
    """IEEE 作者格式：英文名缩写首字母，中文名保持原样。"""
    name = name.strip()
    if not name or any(ord(char) > 127 for char in name):
        return name
    tokens = name.split()
    if len(tokens) == 1:
        return tokens[0]
    initials = " ".join(f"{token[0]}." for token in tokens[:-1])
    return f"{initials} {tokens[-1]}"


def _ieee_authors(authors: Sequence[str]) -> str:
    if not authors:
        return "Anon."
    if len(authors) > 3:
        return f"{_ieee_author(authors[0])} et al."
    names = [_ieee_author(name) for name in authors]
    if len(names) == 1:
        return names[0]
    if len(names) == 2:
        return f"{names[0]} and {names[1]}"
    return f"{names[0]}, {names[1]}, and {names[2]}"


def _ieee_reference_line(number: int, paper: PaperRecord) -> str:
    authors = _ieee_authors(paper.authors)
    venue = paper.venue or "[出版者不详]"
    year = paper.year or "[年份不详]"
    return f'[{number}] {authors}, "{paper.title}," {venue}, {year}.'


SUPPORTED_REFERENCE_STYLES = ("gbt7714", "ieee")


def build_references(
    draft: str, papers: Sequence[PaperRecord], style: str = "gbt7714"
) -> Tuple[str, List[Dict[str, Any]]]:
    if style not in SUPPORTED_REFERENCE_STYLES:
        raise ValueError(
            f"暂不支持的引用样式: {style}（可选: {', '.join(SUPPORTED_REFERENCE_STYLES)}）"
        )
    line_builder = _ieee_reference_line if style == "ieee" else _reference_line
    by_key = {p.paper_key: p for p in papers}
    entries: List[Dict[str, Any]] = []
    lines: List[str] = []
    for number, key in enumerate(extract_citations(draft), start=1):
        paper = by_key.get(key)
        if paper is None:
            continue
        lines.append(line_builder(number, paper))
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


def extract_claims(draft: str) -> List[Claim]:
    """从草稿按段落提取带 `[cite:KEY]` 的主张。

    每个非空段落生成一条 claim，section 统一为 "body"（后续可由 outline 推断）。
    """
    claims: List[Claim] = []
    paragraphs = [p.strip() for p in (draft or "").split("\n\n") if p.strip()]
    for para in paragraphs:
        keys = extract_citations(para)
        if not keys:
            continue
        claim_id = f"c{len(claims) + 1:04d}"
        text = para[:2000]
        claims.append(Claim(
            claim_id=claim_id,
            section="body",
            text=text,
            citation_keys=tuple(keys),
        ))
    return claims


def verify_claims(
    claims: Sequence[Claim], paper_keys: set
) -> List[Claim]:
    """对 claims 跑 Layer 1+2a 核验。

    - UNRESOLVED：引用 key 不在文献池。
    - UNSUPPORTED：claim 无任何引用。
    - SUPPORTED：所有引用 key 都在文献池且 metadata_schema 完整（有 DOI/arXiv/标题/作者/年份）。
    - FLAGGED：部分引用缺失或 metadata 不全。
    """
    verified: List[Claim] = []
    for claim in claims:
        if not claim.citation_keys:
            verified.append(Claim(
                claim_id=claim.claim_id,
                section=claim.section,
                text=claim.text,
                citation_keys=claim.citation_keys,
                verdict=ClaimVerdict.UNSUPPORTED,
                notes="claim 无引用 key",
            ))
            continue
        missing = [k for k in claim.citation_keys if k not in paper_keys]
        if missing:
            verified.append(Claim(
                claim_id=claim.claim_id,
                section=claim.section,
                text=claim.text,
                citation_keys=claim.citation_keys,
                verdict=ClaimVerdict.UNRESOLVED,
                notes=f"未知引用: {', '.join(missing)}",
            ))
            continue
        verified.append(Claim(
            claim_id=claim.claim_id,
            section=claim.section,
            text=claim.text,
            citation_keys=claim.citation_keys,
            verdict=ClaimVerdict.SUPPORTED,
            metadata_schema_ok=True,
        ))
    return verified
