"""文献调研流水线的中间产物模型（Python 3.8 兼容）。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from .models import PaperRecord


def _require_str(value: Any, name: str, *, required: bool = True) -> str:
    if not isinstance(value, str) or not value.strip():
        if required:
            raise ValueError(f"{name} 必填")
        return ""
    return value.strip()


def _str_tuple(value: Any, name: str) -> Tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, (list, tuple)):  # noqa: UP038 — py38 兼容
        raise ValueError(f"{name} 必须是字符串数组")
    result = []
    for item in value:
        if not isinstance(item, str) or not item.strip():
            raise ValueError(f"{name} 不能包含空值")
        result.append(item.strip())
    return tuple(result)


def paper_record_from_dict(raw: Dict[str, Any]) -> PaperRecord:
    if not isinstance(raw, dict):
        raise ValueError("paper 必须是对象")
    key = _require_str(raw.get("paper_key"), "paper_key")
    title = _require_str(raw.get("title"), "title")
    authors = _str_tuple(raw.get("authors"), "authors")
    return PaperRecord(
        paper_key=key,
        title=title,
        authors=authors,
        year=_require_str(raw.get("year"), "year", required=False) or None,
        venue=_require_str(raw.get("venue"), "venue", required=False) or None,
        abstract=_require_str(raw.get("abstract"), "abstract", required=False) or None,
        url=_require_str(raw.get("url"), "url", required=False) or None,
        doi=_require_str(raw.get("doi"), "doi", required=False) or None,
        source_site=_require_str(raw.get("source_site"), "source_site", required=False),
        source_query=_require_str(raw.get("source_query"), "source_query", required=False)
        or None,
        retrieved_at=_require_str(raw.get("retrieved_at"), "retrieved_at", required=False)
        or None,
        fulltext_path=_require_str(
            raw.get("fulltext_path"), "fulltext_path", required=False
        )
        or None,
        language=_require_str(raw.get("language"), "language", required=False) or None,
        extra=dict(raw.get("extra") or {}),
    )


@dataclass(frozen=True)
class EvidenceRecord:
    evidence_id: str
    paper_key: str
    kind: str
    text: str
    locator: Optional[str] = None
    quote: Optional[str] = None
    confidence: Optional[float] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "evidence_id": self.evidence_id,
            "paper_key": self.paper_key,
            "kind": self.kind,
            "text": self.text,
            "locator": self.locator,
            "quote": self.quote,
            "confidence": self.confidence,
        }


def evidence_from_dict(raw: Dict[str, Any]) -> EvidenceRecord:
    if not isinstance(raw, dict):
        raise ValueError("evidence 必须是对象")
    confidence = raw.get("confidence")
    if confidence is not None:
        confidence = float(confidence)
        if not 0.0 <= confidence <= 1.0:
            raise ValueError("confidence 必须在 0..1")
    return EvidenceRecord(
        evidence_id=_require_str(raw.get("evidence_id"), "evidence_id"),
        paper_key=_require_str(raw.get("paper_key"), "paper_key"),
        kind=_require_str(raw.get("kind"), "kind"),
        text=_require_str(raw.get("text"), "text"),
        locator=_require_str(raw.get("locator"), "locator", required=False) or None,
        quote=_require_str(raw.get("quote"), "quote", required=False) or None,
        confidence=confidence,
    )


@dataclass(frozen=True)
class OutlineSection:
    id: str
    title: str
    summary: str = ""
    source_keys: Tuple[str, ...] = ()


@dataclass(frozen=True)
class Outline:
    title: str
    sections: Tuple[OutlineSection, ...]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "title": self.title,
            "sections": [
                {
                    "id": section.id,
                    "title": section.title,
                    "summary": section.summary,
                    "source_keys": list(section.source_keys),
                }
                for section in self.sections
            ],
        }


def outline_from_dict(raw: Dict[str, Any]) -> Outline:
    if not isinstance(raw, dict):
        raise ValueError("outline 必须是对象")
    sections_raw = raw.get("sections")
    if not isinstance(sections_raw, list) or not sections_raw:
        raise ValueError("outline.sections 必须是非空数组")
    sections = []
    seen = set()
    for item in sections_raw:
        if not isinstance(item, dict):
            raise ValueError("outline.sections 元素必须是对象")
        section_id = _require_str(item.get("id"), "section.id")
        if section_id in seen:
            raise ValueError(f"section.id 重复: {section_id}")
        seen.add(section_id)
        sections.append(
            OutlineSection(
                id=section_id,
                title=_require_str(item.get("title"), "section.title"),
                summary=_require_str(item.get("summary"), "section.summary", required=False),
                source_keys=_str_tuple(item.get("source_keys"), "section.source_keys"),
            )
        )
    return Outline(
        title=_require_str(raw.get("title"), "outline.title"),
        sections=tuple(sections),
    )


@dataclass
class GateReport:
    ok: bool
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    citations: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ok": self.ok,
            "errors": list(self.errors),
            "warnings": list(self.warnings),
            "citations": list(self.citations),
        }


class ClaimVerdict(str):
    """Claim 核验结果。"""

    UNVERIFIED = "unverified"
    SUPPORTED = "supported"
    FLAGGED = "flagged"
    UNSUPPORTED = "unsupported"
    UNRESOLVED = "unresolved"


VALID_VERDICTS = frozenset(
    {ClaimVerdict.UNVERIFIED, ClaimVerdict.SUPPORTED, ClaimVerdict.FLAGGED,
     ClaimVerdict.UNSUPPORTED, ClaimVerdict.UNRESOLVED}
)


@dataclass(frozen=True)
class Claim:
    """一条可审计的主张：论断 + 支撑引用 + 核验结果。"""

    claim_id: str
    section: str
    text: str
    citation_keys: Tuple[str, ...]
    verdict: str = ClaimVerdict.UNVERIFIED
    notes: str = ""
    metadata_schema_ok: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "claim_id": self.claim_id,
            "section": self.section,
            "text": self.text,
            "citation_keys": list(self.citation_keys),
            "verdict": self.verdict,
            "notes": self.notes,
            "metadata_schema_ok": self.metadata_schema_ok,
        }


def claim_from_dict(raw: Dict[str, Any]) -> Claim:
    if not isinstance(raw, dict):
        raise ValueError("claim 必须是对象")
    claim_id = _require_str(raw.get("claim_id"), "claim_id")
    verdict = _require_str(raw.get("verdict"), "verdict") or ClaimVerdict.UNVERIFIED
    if verdict not in VALID_VERDICTS:
        raise ValueError(f"verdict 必须是 {sorted(VALID_VERDICTS)} 之一")
    return Claim(
        claim_id=claim_id,
        section=_require_str(raw.get("section"), "section"),
        text=_require_str(raw.get("text"), "text"),
        citation_keys=_str_tuple(raw.get("citation_keys"), "citation_keys"),
        verdict=verdict,
        notes=_require_str(raw.get("notes"), "notes", required=False),
        metadata_schema_ok=bool(raw.get("metadata_schema_ok", False)),
    )
