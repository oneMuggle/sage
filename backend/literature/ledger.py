"""统一证据账本（EvidenceLedger）。

把运行目录中的文献、证据、claims 以及外部引用（附件 / Wiki / 专家知识 /
Word / Zotero）收敛成统一的 ``ledger.json``：每条记录表达
"文献 paper_key ↔ 出处 locator/quote ↔ 论断 claim_id"。

外部来源通过 ``ingest_external`` 以 dict 形式接入，保持本模块不依赖
具体子系统。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from .run_store import (
    LiteratureRun,
    list_claims,
    list_evidence,
    list_papers,
    read_json,
    write_json,
)


@dataclass(frozen=True)
class LedgerEntry:
    entry_id: str
    paper_key: str
    source_type: str  # evidence | claim | attachment | wiki | specialist | word | zotero | external
    source_id: Optional[str] = None
    claim_id: Optional[str] = None
    locator: Optional[str] = None
    quote: Optional[str] = None
    text: str = ""

    def dedupe_key(self) -> Tuple[Any, ...]:
        return (
            self.paper_key,
            self.source_type,
            self.source_id,
            self.claim_id,
            self.locator,
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "entry_id": self.entry_id,
            "paper_key": self.paper_key,
            "source_type": self.source_type,
            "source_id": self.source_id,
            "claim_id": self.claim_id,
            "locator": self.locator,
            "quote": self.quote,
            "text": self.text,
        }


def entry_from_dict(raw: Dict[str, Any]) -> LedgerEntry:
    if not isinstance(raw, dict):
        raise ValueError("ledger entry 必须是对象")
    paper_key = str(raw.get("paper_key") or "").strip()
    if not paper_key:
        raise ValueError("ledger entry 缺少 paper_key")
    source_type = str(raw.get("source_type") or "external").strip()
    source_id = str(raw.get("source_id") or "").strip() or None
    claim_id = str(raw.get("claim_id") or "").strip() or None
    entry_id = str(raw.get("entry_id") or "").strip() or (
        f"{source_type}:{source_id or claim_id or paper_key}"
    )
    return LedgerEntry(
        entry_id=entry_id,
        paper_key=paper_key,
        source_type=source_type,
        source_id=source_id,
        claim_id=claim_id,
        locator=str(raw.get("locator") or "").strip() or None,
        quote=str(raw.get("quote") or "").strip() or None,
        text=str(raw.get("text") or "").strip(),
    )


@dataclass
class EvidenceLedger:
    entries: List[LedgerEntry] = field(default_factory=list)
    _keys: set = field(default_factory=set, repr=False)

    def add(self, entry: LedgerEntry) -> bool:
        key = entry.dedupe_key()
        if key in self._keys:
            return False
        self._keys.add(key)
        self.entries.append(entry)
        return True

    def merge(self, entries: Iterable[LedgerEntry]) -> int:
        added = 0
        for entry in entries:
            added += 1 if self.add(entry) else 0
        return added

    def ingest_external(self, rows: Sequence[Dict[str, Any]]) -> int:
        return self.merge(entry_from_dict(row) for row in rows)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "count": len(self.entries),
            "entries": [entry.to_dict() for entry in self.entries],
        }

    @classmethod
    def from_dict(cls, raw: Dict[str, Any]) -> EvidenceLedger:
        ledger = cls()
        for row in raw.get("entries") or []:
            ledger.add(entry_from_dict(row))
        return ledger


def build_ledger(
    run: LiteratureRun,
    external_entries: Optional[Sequence[Dict[str, Any]]] = None,
) -> EvidenceLedger:
    """从运行目录构建账本，并覆盖写入 ``ledger.json``。"""
    paper_keys = {paper.paper_key for paper in list_papers(run)}
    evidence_entries = [
        LedgerEntry(
            entry_id=f"evidence:{record.evidence_id}",
            paper_key=record.paper_key,
            source_type="evidence",
            source_id=record.evidence_id,
            locator=record.locator,
            quote=record.quote,
            text=record.text,
        )
        for record in list_evidence(run)
        if record.paper_key in paper_keys
    ]
    claim_entries = [
        LedgerEntry(
            entry_id=f"claim:{claim.claim_id}:{key}",
            paper_key=key,
            source_type="claim",
            source_id=claim.claim_id,
            claim_id=claim.claim_id,
            text=claim.text,
        )
        for claim in list_claims(run)
        for key in claim.citation_keys
        if key in paper_keys
    ]
    ledger = EvidenceLedger()
    ledger.merge(evidence_entries + claim_entries)
    if external_entries:
        ledger.ingest_external(external_entries)
    write_json(run.run_dir / "ledger.json", ledger.to_dict())
    return ledger


def load_ledger(run: LiteratureRun) -> EvidenceLedger:
    raw = read_json(run.run_dir / "ledger.json")
    return EvidenceLedger.from_dict(raw) if raw else EvidenceLedger()


def ledger_stats(ledger: EvidenceLedger) -> Dict[str, int]:
    stats: Dict[str, int] = {}
    for entry in ledger.entries:
        stats[entry.source_type] = stats.get(entry.source_type, 0) + 1
    return stats


__all__ = [
    "EvidenceLedger",
    "LedgerEntry",
    "build_ledger",
    "entry_from_dict",
    "ledger_stats",
    "load_ledger",
]
