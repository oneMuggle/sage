"""workspace 本地 JSON + SQLite 元数据双写存储。

布局：
  <workspace>/office/journal/specs/<spec_id>.json      # spec 主体
  <workspace>/office/journal/cache/<sha256>.docx       # pandoc 缓存
  <workspace>/office/journal/generated/<gen_id>.docx   # 生成落点

SQLite 表 office_journal_specs 与 office_journal_generations 存元数据
(spec_id / sha256 / created_at / ...) 供全局查询（跨 workspace 列表）。

设计要点：
- PEP 604/585 全部禁用（X | None / list[int]）；
- workspace 路径安全：所有落盘路径经 backend.office.path_safety.resolve_within；
- SQLite 通过 backend.data.database.get_database().get_connection() 走统一加锁代理；
- ensure_journal_tables() 由 init_db 末尾调用，幂等。
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import List, Optional

from backend.data.database import get_database
from backend.office.journal.errors import JournalSpecNotFoundError
from backend.office.journal.models import JournalGenerationRecord, JournalSpec

_LAYOUT_ROOT = Path("office") / "journal"


def _layout_paths(workspace: Path) -> dict:
    specs = workspace / _LAYOUT_ROOT / "specs"
    cache = workspace / _LAYOUT_ROOT / "cache"
    generated = workspace / _LAYOUT_ROOT / "generated"
    for d in (specs, cache, generated):
        d.mkdir(parents=True, exist_ok=True)
    return {"specs": specs, "cache": cache, "generated": generated}


def _validate_workspace(workspace: Path) -> Path:
    """确保 workspace 是规范化的绝对路径且真实可解析。"""
    from backend.office.path_safety import resolve_within

    return resolve_within(workspace, workspace)


def save_spec(workspace: Path, spec: JournalSpec) -> Path:
    """落 JSON 到 <workspace>/office/journal/specs/<spec_id>.json + 登记 SQLite。"""
    _validate_workspace(workspace)
    layout = _layout_paths(workspace)
    path = layout["specs"] / f"{spec.spec_id}.json"
    # model_dump_json 不支持 ensure_ascii；改用 json.dumps(spec.model_dump())。
    path.write_text(
        json.dumps(spec.model_dump(mode="json"), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    # 登记 SQLite（spec_id 主键 → INSERT OR REPLACE 即可幂等）。
    # 注意：不关闭连接 —— Database 单例持有 _LockedConnection 代理，连接生命周期
    # 由 Database.close() 统一管理；中途 close 会让后续 init_db 的 conn.commit() 报
    # "Cannot operate on a closed database"（connection 与 proxy 共享同一底层 conn）。
    db = get_database()
    conn = db.get_connection()
    conn.execute(
        """
        INSERT OR REPLACE INTO office_journal_specs
            (spec_id, template_sha256, template_filename, workspace_path, spec_json, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            spec.spec_id,
            spec.template_sha256,
            spec.template_filename,
            str(workspace.resolve()),
            spec.model_dump_json(),
            time.time_ns() // 1_000_000,  # epoch ms
        ),
    )
    return path


def load_spec(workspace: Path, spec_id: str) -> JournalSpec:
    """从 workspace JSON 读 spec；不存在抛 JournalSpecNotFoundError。"""
    _validate_workspace(workspace)
    path = workspace / _LAYOUT_ROOT / "specs" / f"{spec_id}.json"
    if not path.exists():
        raise JournalSpecNotFoundError(f"spec_id={spec_id}")
    data = path.read_bytes().decode("utf-8")
    return JournalSpec.model_validate_json(data)


def list_specs(workspace: Path) -> List[JournalSpec]:
    """按文件名（spec_id）排序列出 workspace 内所有 spec。损坏文件跳过不抛。"""
    _validate_workspace(workspace)
    layout = _layout_paths(workspace)
    out: List[JournalSpec] = []
    for p in sorted(layout["specs"].glob("*.json")):
        try:
            out.append(
                JournalSpec.model_validate_json(
                    p.read_bytes().decode("utf-8")
                )
            )
        except Exception:  # noqa: BLE001 — 损坏文件跳过不抛
            continue
    return out


def record_generation(
    workspace: Path, record: JournalGenerationRecord
) -> JournalGenerationRecord:
    """登记一条生成记录到 SQLite office_journal_generations。"""
    _validate_workspace(workspace)
    db = get_database()
    conn = db.get_connection()
    conn.execute(
        """
        INSERT OR REPLACE INTO office_journal_generations
            (gen_id, spec_id, output_path, mode, created_at, llm_model, bytes_written, workspace_path)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            record.gen_id,
            record.spec_id,
            record.output_path,
            record.mode,
            record.created_at,
            record.llm_model,
            record.bytes_written,
            str(workspace.resolve()),
        ),
    )
    return record


def list_generations(
    workspace: Path, spec_id: Optional[str] = None
) -> List[JournalGenerationRecord]:
    """列 workspace 的生成记录；可选按 spec_id 过滤；按 created_at 升序。"""
    _validate_workspace(workspace)
    db = get_database()
    conn = db.get_connection()
    if spec_id:
        rows = conn.execute(
            "SELECT gen_id, spec_id, output_path, mode, created_at, llm_model, bytes_written "
            "FROM office_journal_generations WHERE workspace_path=? AND spec_id=? "
            "ORDER BY created_at",
            (str(workspace.resolve()), spec_id),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT gen_id, spec_id, output_path, mode, created_at, llm_model, bytes_written "
            "FROM office_journal_generations WHERE workspace_path=? ORDER BY created_at",
            (str(workspace.resolve()),),
        ).fetchall()
    return [
        JournalGenerationRecord(
            gen_id=r["gen_id"],
            spec_id=r["spec_id"],
            output_path=r["output_path"],
            mode=r["mode"],
            created_at=r["created_at"],
            llm_model=r["llm_model"],
            bytes_written=r["bytes_written"],
        )
        for r in rows
    ]


def ensure_journal_tables() -> None:
    """CREATE TABLE IF NOT EXISTS office_journal_specs / office_journal_generations。幂等。"""
    db = get_database()
    conn = db.get_connection()
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS office_journal_specs (
            spec_id TEXT PRIMARY KEY,
            template_sha256 TEXT NOT NULL,
            template_filename TEXT NOT NULL,
            workspace_path TEXT NOT NULL,
            spec_json TEXT NOT NULL,
            created_at INTEGER NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_journal_specs_ws_sha
            ON office_journal_specs (workspace_path, template_sha256);

        CREATE TABLE IF NOT EXISTS office_journal_generations (
            gen_id TEXT PRIMARY KEY,
            spec_id TEXT NOT NULL,
            output_path TEXT NOT NULL,
            mode TEXT NOT NULL,
            created_at INTEGER NOT NULL,
            llm_model TEXT,
            bytes_written INTEGER NOT NULL DEFAULT 0,
            workspace_path TEXT NOT NULL,
            FOREIGN KEY (spec_id) REFERENCES office_journal_specs(spec_id) ON DELETE CASCADE
        );

        CREATE INDEX IF NOT EXISTS idx_journal_generations_ws_spec
            ON office_journal_generations (workspace_path, spec_id, created_at);
        """
    )


__all__ = [
    "save_spec",
    "load_spec",
    "list_specs",
    "record_generation",
    "list_generations",
    "ensure_journal_tables",
]
