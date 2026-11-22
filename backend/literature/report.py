"""四态核验报告 artifact：supported / flagged / unsupported / unclear。

读取运行目录的 claims / metadata_verification / ledger，生成
``export/verification_report.md`` 与 ``.json``，供 artifact 面板展示。
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List

from .ledger import ledger_stats, load_ledger
from .pipeline_models import ClaimVerdict
from .run_store import (
    LiteratureRun,
    atomic_write_text,
    list_claims,
    read_json,
    write_json,
)

_VERDICT_ORDER = (
    ClaimVerdict.SUPPORTED,
    ClaimVerdict.FLAGGED,
    ClaimVerdict.UNSUPPORTED,
    ClaimVerdict.UNCLEAR,
    ClaimVerdict.UNRESOLVED,
    ClaimVerdict.UNVERIFIED,
)


def _render_markdown(report: Dict[str, Any]) -> str:
    lines: List[str] = ["# 文献核验报告", ""]
    lines.append(f"> 生成时间：{report.get('generated_at', '')}")
    lines.append("")
    lines.append("## 摘要")
    lines.append("")
    for verdict in _VERDICT_ORDER:
        lines.append(f"- {verdict}: {report['summary'].get(verdict, 0)}")
    metadata = report.get("metadata") or {}
    lines.append(
        "- 元数据：verified {verified} / partial {partial} / "
        "unverified {unverified} / skipped {skipped}".format(
            verified=metadata.get("verified", 0),
            partial=metadata.get("partial", 0),
            unverified=metadata.get("unverified", 0),
            skipped=metadata.get("skipped", 0),
        )
    )
    ledger = report.get("ledger") or {}
    lines.append(
        f"- EvidenceLedger：{ledger.get('count', 0)} 条 "
        f"({ledger.get('by_source') or {}})"
    )
    lines.append("")

    for verdict in _VERDICT_ORDER:
        items = report["groups"].get(verdict) or []
        if not items:
            continue
        lines.append(f"## {verdict} ({len(items)})")
        lines.append("")
        for item in items:
            text = str(item.get("text") or "").replace("\n", " ").strip()
            lines.append(f"- **{item.get('claim_id')}** {text[:300]}")
            notes = str(item.get("notes") or "").strip()
            if notes:
                lines.append(f"  - 备注：{notes}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def build_verification_report(run: LiteratureRun) -> Dict[str, Any]:
    claims = list_claims(run)
    groups: Dict[str, List[Dict[str, Any]]] = {
        verdict: [] for verdict in _VERDICT_ORDER
    }
    for claim in claims:
        groups.setdefault(claim.verdict, []).append(claim.to_dict())
    summary = {verdict: len(groups.get(verdict) or []) for verdict in _VERDICT_ORDER}

    metadata = read_json(run.run_dir / "metadata_verification.json", default={}) or {}
    ledger = load_ledger(run)
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),  # noqa: UP017 — py38 兼容
        "summary": summary,
        "groups": groups,
        "metadata": metadata,
        "ledger": {
            "count": len(ledger.entries),
            "by_source": ledger_stats(ledger),
        },
    }

    export_dir = run.run_dir / "export"
    md_path = export_dir / "verification_report.md"
    json_path = export_dir / "verification_report.json"
    atomic_write_text(md_path, _render_markdown(report))
    write_json(json_path, report)
    report["paths"] = {"markdown": str(md_path), "json": str(json_path)}
    return report


__all__ = ["build_verification_report"]
