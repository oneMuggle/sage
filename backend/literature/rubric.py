"""Rubric 评审：方法 / 覆盖 / 逻辑 / 写作四维确定性评分。

只读取运行目录现有产物（查询日志、文献池、证据、claims、大纲、草稿、
门禁与元数据核验结果），不调用 LLM。产物写入
``export/rubric_review.json`` 与 ``export/rubric_review.md``。
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Sequence, Tuple

from .gates import extract_citations
from .pipeline_models import Claim, ClaimVerdict, EvidenceRecord, Outline
from .run_store import (
    LiteratureRun,
    atomic_write_text,
    list_claims,
    list_evidence,
    list_papers,
    load_outline,
    read_draft,
    read_json,
    read_jsonl,
    write_json,
)

MAX_DIMENSION_SCORE = 5
MAX_TOTAL_SCORE = MAX_DIMENSION_SCORE * 4
DISCLAIMER = (
    "本评审由确定性规则自动生成，是写作自检而非同行评审；"
    "分数只反映流程完整度，不评价学术价值。"
)

_DIMENSION_TITLES = {
    "method": "方法",
    "coverage": "覆盖",
    "logic": "逻辑",
    "writing": "写作",
}


def _band(total_score: int) -> str:
    if total_score >= 16:
        return "优"
    if total_score >= 12:
        return "良"
    if total_score >= 8:
        return "及格"
    return "待改进"


def _cited_paper_keys(claims: Sequence[Claim]) -> List[str]:
    keys: List[str] = []
    seen = set()
    for claim in claims:
        for key in claim.citation_keys:
            if key not in seen:
                seen.add(key)
                keys.append(key)
    return keys


def _evidence_coverage(
    cited_keys: Sequence[str], evidence: Sequence[EvidenceRecord]
) -> float:
    if not cited_keys:
        return 0.0
    covered = {record.paper_key for record in evidence}
    return sum(1 for key in cited_keys if key in covered) / float(len(cited_keys))


def _score_method(
    queries: int,
    evidence: Sequence[EvidenceRecord],
    cited_keys: Sequence[str],
    metadata: Dict[str, Any],
) -> Tuple[int, List[str]]:
    score = 0
    issues: List[str] = []

    if queries == 0:
        issues.append("检索日志为空")
    elif queries < 3:
        score += 1
        issues.append(f"检索次数偏少（{queries} < 3）")
    else:
        score += 2

    coverage = _evidence_coverage(cited_keys, evidence)
    if not cited_keys:
        issues.append("没有任何带引用的主张")
    elif coverage >= 0.8:
        score += 2
    elif coverage >= 0.5:
        score += 1
        issues.append(f"部分被引文献缺少证据（覆盖率 {coverage:.0%}）")
    else:
        issues.append(f"被引文献证据覆盖率过低（{coverage:.0%}）")

    checked = sum(
        int(metadata.get(name, 0) or 0)
        for name in ("verified", "partial", "unverified")
    )
    if not metadata:
        issues.append("未运行外部元数据核验（verify-metadata）")
    elif checked == 0:
        issues.append("元数据核验全部跳过（文献无 DOI/arXiv）")
    else:
        verified_share = int(metadata.get("verified", 0) or 0) / float(checked)
        if verified_share >= 0.6:
            score += 1
        else:
            issues.append(f"外部元数据核验通过率偏低（{verified_share:.0%}）")
    return min(score, MAX_DIMENSION_SCORE), issues


def _score_coverage(
    papers: Sequence[Any], cited_keys: Sequence[str]
) -> Tuple[int, List[str]]:
    score = 0
    issues: List[str] = []
    total = len(papers)

    if total >= 15:
        score += 2
    elif total >= 8:
        score += 1
        issues.append(f"文献量偏少（{total} < 15）")
    else:
        issues.append(f"文献量过少（{total} < 8）")

    if total:
        cited_ratio = len(set(cited_keys)) / float(total)
        if cited_ratio >= 0.8:
            score += 2
        elif cited_ratio >= 0.5:
            score += 1
            issues.append(f"部分文献未被引用（被引比例 {cited_ratio:.0%}）")
        else:
            issues.append(f"被引比例过低（{cited_ratio:.0%}）")

    sites = {paper.source_site for paper in papers if paper.source_site}
    if len(sites) >= 3:
        score += 1
    else:
        issues.append(f"来源多样性不足（{len(sites)} 个来源站点）")
    return min(score, MAX_DIMENSION_SCORE), issues


def _score_logic(
    outline: Outline, draft: str, claims: Sequence[Claim]
) -> Tuple[int, List[str]]:
    score = 0
    issues: List[str] = []

    if outline is None:
        issues.append("缺少大纲 outline.json")
    else:
        score += 1
        missing = [
            section.title
            for section in outline.sections
            if section.title and section.title not in draft
        ]
        if missing:
            issues.append("草稿缺少大纲章节: " + "、".join(missing))
        else:
            score += 1

    blocking = [
        claim
        for claim in claims
        if claim.verdict in (ClaimVerdict.UNSUPPORTED, ClaimVerdict.UNRESOLVED)
    ]
    if blocking:
        issues.append(f"存在 {len(blocking)} 条不支持/无法核验的主张")
    elif claims:
        score += 2

    if claims:
        score += 1
    else:
        issues.append("claims 账本为空（先运行 verify-claims）")
    return min(score, MAX_DIMENSION_SCORE), issues


def _score_writing(draft: str, gate_ok: bool) -> Tuple[int, List[str]]:
    score = 0
    issues: List[str] = []

    body_chars = len("".join(draft.split()))
    if body_chars >= 3000:
        score += 2
    elif body_chars >= 1200:
        score += 1
        issues.append(f"正文偏短（{body_chars} 字）")
    else:
        issues.append("正文过短或为空")

    citations = len(extract_citations(draft))
    density = citations / (max(body_chars, 1) / 1000.0)
    if citations >= 3 and density >= 4.0:
        score += 2
    elif citations and density >= 1.5:
        score += 1
        issues.append(f"引用密度偏低（每千字 {density:.1f} 条）")
    else:
        issues.append(f"引用不足（{citations} 条）")

    if gate_ok:
        score += 1
    else:
        issues.append("门禁未通过（引用/参考文献不完整）")
    return min(score, MAX_DIMENSION_SCORE), issues


def _render_markdown(review: Dict[str, Any]) -> str:
    lines: List[str] = ["# Rubric 评审", ""]
    lines.append(f"> 生成时间：{review.get('generated_at', '')}")
    lines.append("")
    lines.append(
        f"**总分：{review['total_score']}/{review['max_score']}"
        f"（{review['band']}）**"
    )
    lines.append("")
    lines.append(f"> {review['disclaimer']}")
    lines.append("")
    lines.append("| 维度 | 得分 | 问题数 |")
    lines.append("|---|---|---|")
    for dimension in review["dimensions"]:
        lines.append(
            f"| {dimension['title']} | {dimension['score']}/{dimension['max_score']} "
            f"| {len(dimension['issues'])} |"
        )
    lines.append("")
    for dimension in review["dimensions"]:
        lines.append(
            f"## {dimension['title']}（{dimension['score']}/{dimension['max_score']}）"
        )
        lines.append("")
        if dimension["issues"]:
            for issue in dimension["issues"]:
                lines.append(f"- {issue}")
        else:
            lines.append("- 无显著问题")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def review_run(run: LiteratureRun) -> Dict[str, Any]:
    """对运行目录做四维 rubric 评审，写入 JSON 与 Markdown 产物。"""
    queries = len(read_jsonl(run.run_dir / "query_log.jsonl"))
    papers = list_papers(run)
    evidence = list_evidence(run)
    claims = list_claims(run)
    draft = read_draft(run)
    outline = load_outline(run)
    metadata = read_json(run.run_dir / "metadata_verification.json", default={}) or {}
    gate = read_json(run.run_dir / "verification.json", default={}) or {}
    cited_keys = _cited_paper_keys(claims)

    scores = {
        "method": _score_method(queries, evidence, cited_keys, metadata),
        "coverage": _score_coverage(papers, cited_keys),
        "logic": _score_logic(outline, draft, claims),
        "writing": _score_writing(draft, bool(gate.get("ok"))),
    }
    dimensions = [
        {
            "id": dimension_id,
            "title": _DIMENSION_TITLES[dimension_id],
            "score": score,
            "max_score": MAX_DIMENSION_SCORE,
            "issues": issues,
        }
        for dimension_id, (score, issues) in scores.items()
    ]
    total = sum(dimension["score"] for dimension in dimensions)
    review: Dict[str, Any] = {
        "generated_at": datetime.now(timezone.utc).isoformat(),  # noqa: UP017 — py38 兼容
        "total_score": total,
        "max_score": MAX_TOTAL_SCORE,
        "band": _band(total),
        "disclaimer": DISCLAIMER,
        "dimensions": dimensions,
    }

    export_dir = run.run_dir / "export"
    md_path = export_dir / "rubric_review.md"
    json_path = export_dir / "rubric_review.json"
    atomic_write_text(md_path, _render_markdown(review))
    write_json(json_path, review)
    review["paths"] = {"markdown": str(md_path), "json": str(json_path)}
    return review


__all__ = ["DISCLAIMER", "MAX_TOTAL_SCORE", "review_run"]
