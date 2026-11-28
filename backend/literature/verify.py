"""引用核验 M2b：外部元数据 2-of-3 共识 + 证据级 claim 支持。

- ``MetadataLookup``：Crossref / OpenAlex / Semantic Scholar 的窄接口。
- ``verify_paper_metadata``：至少两家命中标题/年份/作者才算 ``verified``。
- ``verify_run_metadata``：对运行目录全部文献跑核验，写
  ``metadata_verification.json``。
- ``apply_evidence_support``：确定性 Layer 3a——claim 引用的论文若没有
  任何 evidence 记录，标记 ``flagged``（语义支持留 LLM 核验）。
"""

from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Protocol, Sequence, Tuple

from .models import PaperRecord, SiteProfile
from .pipeline_models import Claim, ClaimVerdict
from .run_store import LiteratureRun, list_papers, write_json

_USER_AGENT = "SageLiterature/1.0 (local research assistant)"
_TIMEOUT_S = 8.0
_UNPAYWALL_MIN_INTERVAL_S = 1.0

ACCESS_STATUSES: Tuple[str, ...] = ("subscription", "oa", "closed", "unknown")
_ACCESS_PRIORITY = {"subscription": 3, "oa": 2, "closed": 1, "unknown": 0}


class MetadataLookup(Protocol):
    name: str

    def lookup(self, paper: PaperRecord) -> Optional[Dict[str, Any]]: ...


def _get_json(url: str) -> Optional[Dict[str, Any]]:
    request = urllib.request.Request(
        url,
        headers={"User-Agent": _USER_AGENT, "Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=_TIMEOUT_S) as response:
            data = json.loads(response.read().decode("utf-8", "replace"))
    except (urllib.error.URLError, OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _doi_of(paper: PaperRecord) -> Optional[str]:
    doi = (paper.doi or "").strip()
    if not doi and paper.paper_key.lower().startswith("doi:"):
        doi = paper.paper_key[4:].strip()
    if not doi:
        return None
    for prefix in ("https://doi.org/", "http://doi.org/", "doi:"):
        if doi.startswith(prefix):
            doi = doi[len(prefix):]
    return doi.strip() or None


def _arxiv_of(paper: PaperRecord) -> Optional[str]:
    key = paper.paper_key.strip()
    if key.lower().startswith("arxiv:"):
        return key[6:].strip() or None
    match = re.search(r"arxiv\.org/(?:abs|pdf)/([^/?#]+)", paper.url or "")
    return match.group(1) if match else None


class CrossrefLookup:
    name = "crossref"

    def lookup(self, paper: PaperRecord) -> Optional[Dict[str, Any]]:
        doi = _doi_of(paper)
        if not doi:
            return None
        data = _get_json("https://api.crossref.org/works/" + urllib.parse.quote(doi, safe=""))
        if not data:
            return None
        message = data.get("message") or {}
        authors = [
            f"{a.get('given', '')} {a.get('family', '')}".strip()
            for a in message.get("author") or []
        ]
        year = None
        parts = (message.get("issued") or {}).get("date-parts") or []
        if parts and parts[0]:
            year = str(parts[0][0])
        return {
            "source": self.name,
            "title": ((message.get("title") or [""])[0] or "").strip(),
            "year": year,
            "authors": authors,
            "doi": message.get("DOI"),
        }


class OpenAlexLookup:
    name = "openalex"

    def lookup(self, paper: PaperRecord) -> Optional[Dict[str, Any]]:
        doi = _doi_of(paper)
        arxiv = _arxiv_of(paper)
        if doi:
            ident = "doi:" + urllib.parse.quote(doi, safe="")
        elif arxiv:
            ident = "arxiv:" + urllib.parse.quote(arxiv, safe="")
        else:
            return None
        data = _get_json("https://api.openalex.org/works/" + ident)
        if not data:
            return None
        authors = [
            (a.get("author") or {}).get("display_name", "")
            for a in data.get("authorships") or []
        ]
        return {
            "source": self.name,
            "title": (data.get("title") or "").strip(),
            "year": str(data["publication_year"]) if data.get("publication_year") else None,
            "authors": [a for a in authors if a],
            "doi": data.get("doi"),
        }


class SemanticScholarLookup:
    name = "semantic_scholar"

    def lookup(self, paper: PaperRecord) -> Optional[Dict[str, Any]]:
        doi = _doi_of(paper)
        arxiv = _arxiv_of(paper)
        if doi:
            ident = "DOI:" + doi
        elif arxiv:
            ident = "arXiv:" + arxiv
        else:
            return None
        data = _get_json(
            "https://api.semanticscholar.org/graph/v1/paper/"
            + urllib.parse.quote(ident, safe=":")
            + "?fields=title,year,authors,externalIds"
        )
        if not data:
            return None
        return {
            "source": self.name,
            "title": (data.get("title") or "").strip(),
            "year": str(data["year"]) if data.get("year") else None,
            "authors": [a.get("name", "") for a in data.get("authors") or []],
            "doi": (data.get("externalIds") or {}).get("DOI"),
        }


def default_lookups() -> List[MetadataLookup]:
    return [CrossrefLookup(), OpenAlexLookup(), SemanticScholarLookup()]


def merge_access_status(*statuses: str) -> str:
    """按优先级合并可得性：subscription > oa > closed > unknown。"""
    if not statuses:
        return "unknown"
    return max(statuses, key=lambda status: _ACCESS_PRIORITY.get(status, 0))


class UnpaywallLookup:
    """Unpaywall OA 可得性查询（spec §7.3）；无 email 时不可用。

    与元数据轴分开装配——混入 ``default_lookups()`` 会污染核验报告。
    """

    name = "unpaywall"

    def __init__(
        self,
        contact_email: str,
        min_interval_s: float = _UNPAYWALL_MIN_INTERVAL_S,
    ) -> None:
        self.contact_email = (contact_email or "").strip()
        self.min_interval_s = min_interval_s
        self._last_call_at = 0.0

    @property
    def available(self) -> bool:
        return bool(self.contact_email)

    def lookup(self, paper: PaperRecord) -> Optional[Dict[str, Any]]:
        if not self.available:
            return None
        doi = _doi_of(paper)
        if not doi:
            return None
        now = time.monotonic()
        if now - self._last_call_at < self.min_interval_s:
            return None
        self._last_call_at = now
        url = (
            "https://api.unpaywall.org/v2/"
            + urllib.parse.quote(doi, safe="")
            + "?email="
            + urllib.parse.quote(self.contact_email, safe="")
        )
        data = _get_json(url)
        if not data:
            return None
        is_oa = bool(data.get("is_oa"))
        best = data.get("best_oa_location") or {}
        return {
            "source": self.name,
            "is_oa": is_oa,
            "oa_status": (data.get("oa_status") or "").strip() or None,
            "best_oa_url": best.get("url_for_pdf") or best.get("url"),
            "access_status": "oa" if is_oa else "closed",
        }


def build_oa_lookups(profile: Optional[SiteProfile]) -> List[UnpaywallLookup]:
    """按站点合规配置装配 OA 轴；缺 email 时返回空列表（不阻断主链路）。"""
    if profile is None:
        return []
    email = (profile.compliance.contact_email or "").strip()
    if not email:
        return []
    return [UnpaywallLookup(contact_email=email)]


def verify_run_access(
    run: LiteratureRun,
    lookups: Optional[Sequence[UnpaywallLookup]] = None,
    profile: Optional[SiteProfile] = None,
) -> Dict[str, Any]:
    """对运行目录全部文献跑 OA 可得性判定，写 ``access_verification.json``。"""
    if lookups is None:
        lookups = build_oa_lookups(profile)
    items: List[Dict[str, Any]] = []
    for paper in list_papers(run):
        status = "unknown"
        best_oa_url = None
        source = None
        for lookup in lookups:
            candidate = lookup.lookup(paper)
            if candidate is None:
                continue
            status = merge_access_status(status, candidate.get("access_status") or "unknown")
            best_oa_url = candidate.get("best_oa_url") or best_oa_url
            source = candidate.get("source")
        items.append(
            {
                "paper_key": paper.paper_key,
                "access_status": status,
                "best_oa_url": best_oa_url,
                "source": source,
            }
        )
    report = {
        "items": items,
        "oa": sum(1 for item in items if item["access_status"] == "oa"),
        "subscription": sum(1 for item in items if item["access_status"] == "subscription"),
        "closed": sum(1 for item in items if item["access_status"] == "closed"),
        "unknown": sum(1 for item in items if item["access_status"] == "unknown"),
    }
    write_json(run.run_dir / "access_verification.json", report)
    return report


def _normalize(text: str) -> str:
    return re.sub(r"[\s\W_]+", "", (text or "").lower())


def _author_overlap(left: Sequence[str], right: Sequence[str]) -> bool:
    if not left or not right:
        return True
    left_names = {_normalize(name) for name in left if name.strip()}
    right_names = {_normalize(name) for name in right if name.strip()}
    return bool(left_names & right_names)


def metadata_matches(paper: PaperRecord, candidate: Dict[str, Any]) -> bool:
    if not candidate.get("title"):
        return False
    expected = _normalize(paper.title)
    actual = _normalize(str(candidate.get("title") or ""))
    if not expected or not actual or expected != actual:
        return False
    if paper.year and candidate.get("year") and str(paper.year) != str(candidate["year"]):
        return False
    if not _author_overlap(paper.authors, candidate.get("authors") or []):
        return False
    return True


@dataclass
class PaperMetadataVerdict:
    paper_key: str
    status: str  # verified | partial | unverified | skipped
    matched: int = 0
    checks: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "paper_key": self.paper_key,
            "status": self.status,
            "matched": self.matched,
            "checks": list(self.checks),
        }


def verify_paper_metadata(
    paper: PaperRecord,
    lookups: Sequence[MetadataLookup],
    min_consensus: int = 2,
) -> PaperMetadataVerdict:
    if not (_doi_of(paper) or _arxiv_of(paper)):
        return PaperMetadataVerdict(paper.paper_key, "skipped")
    checks: List[Dict[str, Any]] = []
    matched = 0
    for lookup in lookups:
        candidate = lookup.lookup(paper)
        if candidate is None:
            checks.append({"lookup": lookup.name, "ok": False, "reason": "no_data"})
            continue
        ok = metadata_matches(paper, candidate)
        matched += 1 if ok else 0
        checks.append(
            {
                "lookup": lookup.name,
                "ok": ok,
                "title": candidate.get("title"),
                "year": candidate.get("year"),
            }
        )
    if matched >= min_consensus:
        status = "verified"
    elif matched >= 1:
        status = "partial"
    else:
        status = "unverified"
    return PaperMetadataVerdict(paper.paper_key, status, matched, checks)


def verify_run_metadata(
    run: LiteratureRun,
    lookups: Optional[Sequence[MetadataLookup]] = None,
    min_consensus: int = 2,
) -> Dict[str, Any]:
    lookups = list(lookups) if lookups is not None else default_lookups()
    verdicts = [
        verify_paper_metadata(paper, lookups, min_consensus)
        for paper in list_papers(run)
    ]
    report = {
        "min_consensus": min_consensus,
        "items": [verdict.to_dict() for verdict in verdicts],
        "verified": sum(1 for v in verdicts if v.status == "verified"),
        "partial": sum(1 for v in verdicts if v.status == "partial"),
        "unverified": sum(1 for v in verdicts if v.status == "unverified"),
        "skipped": sum(1 for v in verdicts if v.status == "skipped"),
    }
    write_json(run.run_dir / "metadata_verification.json", report)
    return report


def apply_evidence_support(
    claims: Sequence[Claim],
    evidence: Sequence[Any],
) -> List[Claim]:
    """Layer 3a：claim 的引用论文若没有任何 evidence，标记 flagged。"""
    evidence_keys = {record.paper_key for record in evidence}
    result: List[Claim] = []
    for claim in claims:
        if claim.verdict in (ClaimVerdict.UNRESOLVED, ClaimVerdict.UNSUPPORTED):
            result.append(claim)
            continue
        missing = [key for key in claim.citation_keys if key not in evidence_keys]
        if missing:
            result.append(
                Claim(
                    claim_id=claim.claim_id,
                    section=claim.section,
                    text=claim.text,
                    citation_keys=claim.citation_keys,
                    verdict=ClaimVerdict.FLAGGED,
                    notes=(
                        f"引用文献未抽取证据: {', '.join(missing)}；"
                        "语义支持待人工/LLM 核验"
                    ),
                    metadata_schema_ok=claim.metadata_schema_ok,
                )
            )
        else:
            result.append(claim)
    return result
