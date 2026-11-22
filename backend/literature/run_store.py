"""文献调研运行目录：meta / 查询日志 / 文献池 / 证据 / 大纲 / 草稿。"""

from __future__ import annotations

import json
import os
import re
import tempfile
from contextlib import suppress
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from .models import PaperRecord
from .pipeline_models import (
    Claim,
    EvidenceRecord,
    Outline,
    claim_from_dict,
    evidence_from_dict,
    outline_from_dict,
    paper_record_from_dict,
)

_RUN_ID_RE = re.compile(r"^[A-Za-z0-9._-]+$")


@dataclass(frozen=True)
class LiteratureRun:
    run_id: str
    run_dir: Path
    topic: str
    site_id: str
    created_at: str
    status: str = "active"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()  # noqa: UP017 — py38 兼容


def atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), prefix=".tmp-", suffix=path.suffix)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
        Path(tmp_name).replace(path)
    except BaseException:
        with suppress(OSError):
            os.unlink(tmp_name)
        raise


def write_json(path: Path, data: Any) -> None:
    atomic_write_text(path, json.dumps(data, ensure_ascii=False, indent=2) + "\n")


def read_json(path: Path, default: Any = None) -> Any:
    if not path.is_file():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def append_jsonl(path: Path, rows: Sequence[Dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def read_jsonl(path: Path) -> List[Dict[str, Any]]:
    if not path.is_file():
        return []
    rows = []
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if line:
            rows.append(json.loads(line))
    return rows


def create_run(
    root: Path, topic: str, site_id: str, run_id: Optional[str] = None
) -> LiteratureRun:
    if not topic.strip():
        raise ValueError("topic 不能为空")
    if not site_id.strip():
        raise ValueError("site_id 不能为空")
    run_id = run_id or datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")  # noqa: UP017
    if not _RUN_ID_RE.match(run_id):
        raise ValueError("run_id 只能包含字母/数字/._-")
    run_dir = Path(root) / run_id
    if run_dir.exists():
        raise ValueError(f"运行目录已存在: {run_dir}")
    run_dir.mkdir(parents=True)
    meta = {
        "run_id": run_id,
        "topic": topic.strip(),
        "site_id": site_id.strip(),
        "created_at": _now_iso(),
        "status": "active",
    }
    write_json(run_dir / "meta.json", meta)
    return LiteratureRun(run_id, run_dir, meta["topic"], meta["site_id"], meta["created_at"])


def load_run(run_dir: Path) -> LiteratureRun:
    run_dir = Path(run_dir)
    meta = read_json(run_dir / "meta.json")
    if not isinstance(meta, dict):
        raise ValueError(f"缺少 meta.json: {run_dir}")
    return LiteratureRun(
        run_id=meta["run_id"],
        run_dir=run_dir,
        topic=meta["topic"],
        site_id=meta["site_id"],
        created_at=meta["created_at"],
        status=meta.get("status", "active"),
    )


def _papers(run: LiteratureRun) -> List[PaperRecord]:
    return [paper_record_from_dict(row) for row in read_jsonl(run.run_dir / "papers.jsonl")]


def record_query(
    run: LiteratureRun,
    query: str,
    site_id: str,
    result_count: int,
    note: Optional[str] = None,
) -> None:
    append_jsonl(
        run.run_dir / "query_log.jsonl",
        [
            {
                "query": query,
                "site_id": site_id,
                "result_count": int(result_count),
                "note": note,
                "at": _now_iso(),
            }
        ],
    )


def record_papers(run: LiteratureRun, rows: Sequence[Dict[str, Any]]) -> int:
    existing = {p.paper_key for p in _papers(run)}
    new_rows = []
    for row in rows:
        record = paper_record_from_dict(row)
        if record.paper_key in existing:
            continue
        existing.add(record.paper_key)
        new_rows.append(record.to_dict())
    append_jsonl(run.run_dir / "papers.jsonl", new_rows)
    return len(new_rows)


def record_evidence(run: LiteratureRun, rows: Sequence[Dict[str, Any]]) -> int:
    known = {p.paper_key for p in _papers(run)}
    new_rows = []
    for row in rows:
        record = evidence_from_dict(row)
        if record.paper_key not in known:
            raise ValueError(f"paper_key 不在文献池中: {record.paper_key}")
        new_rows.append(record.to_dict())
    append_jsonl(run.run_dir / "evidence.jsonl", new_rows)
    return len(new_rows)


def save_claims(run: LiteratureRun, claims: Sequence[Claim]) -> Path:
    """把 claims 账本写入 claims.jsonl（覆盖写，整账本重新生成）。"""
    path = run.run_dir / "claims.jsonl"
    if path.exists():
        path.unlink()
    append_jsonl(path, [c.to_dict() for c in claims])
    return path


def load_claims(run: LiteratureRun) -> List[Claim]:
    return [claim_from_dict(row) for row in read_jsonl(run.run_dir / "claims.jsonl")]


def list_claims(run: LiteratureRun) -> List[Claim]:
    return load_claims(run)


def save_outline(run: LiteratureRun, raw: Dict[str, Any]) -> Outline:
    outline = outline_from_dict(raw)
    write_json(run.run_dir / "outline.json", outline.to_dict())
    return outline


def load_outline(run: LiteratureRun) -> Optional[Outline]:
    raw = read_json(run.run_dir / "outline.json")
    return outline_from_dict(raw) if raw else None


def save_draft(run: LiteratureRun, text: str) -> None:
    if not text.strip():
        raise ValueError("草稿不能为空")
    atomic_write_text(run.run_dir / "draft.md", text)


def read_draft(run: LiteratureRun) -> str:
    path = run.run_dir / "draft.md"
    return path.read_text(encoding="utf-8") if path.is_file() else ""


def list_papers(run: LiteratureRun) -> List[PaperRecord]:
    return _papers(run)


def list_evidence(run: LiteratureRun) -> List[EvidenceRecord]:
    return [evidence_from_dict(row) for row in read_jsonl(run.run_dir / "evidence.jsonl")]


def run_status(run: LiteratureRun) -> Dict[str, Any]:
    return {
        "run_id": run.run_id,
        "topic": run.topic,
        "site_id": run.site_id,
        "status": run.status,
        "queries": len(read_jsonl(run.run_dir / "query_log.jsonl")),
        "papers": len(_papers(run)),
        "evidence": len(read_jsonl(run.run_dir / "evidence.jsonl")),
        "claims": len(read_jsonl(run.run_dir / "claims.jsonl")),
        "has_outline": (run.run_dir / "outline.json").is_file(),
        "has_draft": (run.run_dir / "draft.md").is_file(),
        "has_verification": (run.run_dir / "verification.json").is_file(),
        "has_claims": (run.run_dir / "claims.jsonl").is_file(),
        "has_metadata_verification": (
            run.run_dir / "metadata_verification.json"
        ).is_file(),
        "has_ledger": (run.run_dir / "ledger.json").is_file(),
        "has_verification_report": (
            run.run_dir / "export" / "verification_report.md"
        ).is_file(),
    }
