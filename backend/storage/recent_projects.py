"""Recent wiki projects store — P8 起为 projects 注册表（SQLite）的投影。

历史：本模块原为 user data dir 下的原子 JSON 文件存储（`~/.config/sage/
recent-projects.json`，POSIX-only 安全原语）。#760 解锁平台原语、P6 完成
授权桥接后，P8 将存储迁移到 projects 注册表（backend/data/project_repo，
SQLite）——recents 成为注册表的**只读投影**（按 last_opened_at 取前
MAX_RECENT 条），单一事实源落在 SQLite。

公共 API 全部保留（load_recent / save_recent / record_recent /
most_recent_parent / RecentProject / MAX_RECENT），消费方
（wiki_routes / search_routes / mcp_server / project_authorization /
chat.entity_refs）零改动。

语义映射（见 docs/plans/2026-09-15_wiki-recents-sqlite-p8-plan.md §2）：
- ``opened_at``（秒）↔ projects.last_opened_at（毫秒）；
- ``intent``：projects.intent 可空列，record_recent 显式写入，NULL
  （侧栏登记等来源）读侧映射为 ``"open"``；
- MAX_RECENT 是 recents 投影的截断，不是注册表生命周期（表内仍保留
  最多 50 行）；
- save_recent 仅删除"上一 recents 窗口内且不在新清单"的行，绝不触碰
  窗口外的注册行（保护侧栏清单）。
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import time
from pathlib import Path
from typing import Any, Dict, List, Literal

from pydantic import BaseModel

MAX_RECENT = 10

logger = logging.getLogger(__name__)


class RecentProject(BaseModel):
    path: str
    name: str
    opened_at: float
    intent: Literal["create", "open"]  # type: ignore[valid-type]


def _validate_recent_project(raw: Any) -> RecentProject:
    """Validate a stored entry with either Pydantic major version."""
    validator = getattr(RecentProject, "model_validate", None)
    if callable(validator):
        return validator(raw)
    return RecentProject.parse_obj(raw)


def _dump_recent_project(item: RecentProject) -> Dict[str, Any]:
    """Serialize a recent entry with either Pydantic major version."""
    dumper = getattr(item, "model_dump", None)
    if callable(dumper):
        return dumper()
    return item.dict()


def user_data_dir() -> Path:
    """Return the user-writable data directory.

    Honors ``SAGE_USER_DATA_DIR``; defaults to ``~/.config/sage``.
    """
    raw = os.environ.get("SAGE_USER_DATA_DIR")
    if raw:
        return Path(raw).expanduser()
    return Path.home() / ".config" / "sage"


def recent_projects_file() -> Path:
    """P8 前的旧 JSON 存储路径；现仅作为一次性迁移的来源。"""
    d = user_data_dir()
    if not d.exists():
        d.mkdir(parents=True, exist_ok=True)
    if not d.is_dir() or d.is_symlink():
        raise OSError("recent projects 数据目录必须是实际目录")
    return d / "recent-projects.json"


def _read_legacy_raw(f: Path) -> List[Any]:
    """读旧 JSON（迁移专用）；缺失/损坏 → 空列表（损坏时改名备份）。"""
    try:
        text = f.read_text(encoding="utf-8")
    except (FileNotFoundError, OSError, UnicodeError):
        return []
    if not text.strip():
        return []
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        # Corrupted file: back it up and start fresh
        with contextlib.suppress(OSError):
            f.rename(f.with_suffix(f.suffix + ".bak"))
        return []
    if not isinstance(data, list):
        return []
    return data


def _db():
    """Lazy import 打破 storage → data 的模块环，并便于测试 monkeypatch。"""
    from backend.data.database import get_database

    return get_database().get_connection()


_emit_lock = None
_last_emit_ms = 0


def _next_ms() -> int:
    """单调毫秒时间戳：同毫秒内多次 record 保证顺序可判定。

    projects 投影按 last_opened_at 排序，POSIX JSON 版靠插入序决定同秒
    条目次序；SQLite 需要 strictly-increasing 数值才能复现该语义。
    """
    global _emit_lock, _last_emit_ms
    import threading

    if _emit_lock is None:
        _emit_lock = threading.Lock()
    with _emit_lock:
        ms = int(time.time() * 1000)
        if ms <= _last_emit_ms:
            ms = _last_emit_ms + 1
        _last_emit_ms = ms
        return ms


def _ensure_legacy_import() -> None:
    """一次性把旧 JSON 条目导入 projects 注册表，然后改名 ``.migrated``。

    幂等：JSON 不存在（或已迁移改名）即无操作。任何失败 fail-open——
    不阻塞 recents 读取，下次启动可再试。
    """
    try:
        f = recent_projects_file()
    except OSError:
        return
    if not f.exists():
        return
    try:
        conn = _db()
        now_ms = int(time.time() * 1000)
        for index, raw in enumerate(_read_legacy_raw(f)):
            try:
                item = _validate_recent_project(raw)
            except Exception:
                continue
            opened_ms = int(item.opened_at * 1000) or now_ms - index
            conn.execute(
                """
                INSERT INTO projects (id, path, name, created_at, last_opened_at, intent)
                VALUES (lower(hex(randomblob(16))), ?, ?, ?, ?, ?)
                ON CONFLICT(path) DO UPDATE SET
                    name = excluded.name,
                    intent = excluded.intent,
                    last_opened_at = MAX(projects.last_opened_at, excluded.last_opened_at)
                """,
                (item.path, item.name, now_ms, opened_ms, item.intent),
            )
        conn.commit()
        with contextlib.suppress(OSError):
            f.rename(f.with_suffix(f.suffix + ".migrated"))
    except Exception as exc:  # noqa: BLE001 — 迁移失败不阻塞 recents 读取
        logger.warning("recent projects legacy import skipped: %s", exc)


def load_recent() -> List[RecentProject]:
    """注册表投影：最近打开的前 MAX_RECENT 条（新→旧）。

    P8 迁移：先做一次性 legacy JSON 导入，再从 projects 表读取。
    任何数据库异常 → 空清单（fail-closed）。
    """
    _ensure_legacy_import()
    try:
        rows = _db().execute(
            """
            SELECT path, name, last_opened_at, intent FROM projects
            ORDER BY last_opened_at DESC, created_at DESC, id DESC
            LIMIT ?
            """,
            (MAX_RECENT,),
        ).fetchall()
    except Exception as exc:  # noqa: BLE001 — 读取失败返回空清单
        logger.warning("recent projects load failed: %s", exc)
        return []
    items: List[RecentProject] = []
    for row in rows:
        try:
            items.append(
                RecentProject(
                    path=row["path"],
                    name=row["name"],
                    opened_at=(row["last_opened_at"] or 0) / 1000.0,
                    intent=row["intent"] or "open",
                )
            )
        except Exception:
            continue
    return items


def save_recent(items: List[RecentProject]) -> None:
    """以 items 作为新的 recents 窗口（upsert 全部；越窗旧行删除）。

    越窗保护：只删除"上一次 recents 窗口内且不在新清单"的行——
    窗口外的注册行（侧栏清单第 11 位及以后）不受影响。
    """
    previous_paths = {item.path for item in load_recent()}
    new_paths = {item.path for item in items}
    stale = previous_paths - new_paths
    conn = _db()
    try:
        for path in stale:
            conn.execute("DELETE FROM projects WHERE path = ?", (path,))
        for item in items:
            opened_ms = int(item.opened_at * 1000) or _next_ms()
            conn.execute(
                """
                INSERT INTO projects (id, path, name, created_at, last_opened_at, intent)
                VALUES (lower(hex(randomblob(16))), ?, ?, ?, ?, ?)
                ON CONFLICT(path) DO UPDATE SET
                    name = excluded.name,
                    intent = excluded.intent,
                    last_opened_at = excluded.last_opened_at
                """,
                (
                    item.path,
                    item.name,
                    opened_ms,
                    opened_ms,
                    item.intent,
                ),
            )
        conn.commit()
    except Exception as exc:  # noqa: BLE001 — 写失败按原契约向上抛 OSError 语义
        raise OSError(f"recent projects 保存失败: {exc}") from exc


def record_recent(path: str, name: str, intent: Literal["create", "open"]) -> None:
    """Add or refresh an entry; dedup by path; projection truncates to MAX_RECENT."""
    if intent not in ("create", "open"):
        raise ValueError("intent must be 'create' or 'open'")
    conn = _db()
    now_ms = _next_ms()
    conn.execute(
        """
        INSERT INTO projects (id, path, name, created_at, last_opened_at, intent)
        VALUES (lower(hex(randomblob(16))), ?, ?, ?, ?, ?)
        ON CONFLICT(path) DO UPDATE SET
            name = excluded.name,
            intent = excluded.intent,
            last_opened_at = excluded.last_opened_at
        """,
        (path, name, now_ms, now_ms, intent),
    )
    conn.commit()


def most_recent_parent() -> str | None:
    """Parent directory of the most recent entry, or None if empty/missing."""
    items = load_recent()
    if not items:
        return None
    parent = Path(items[0].path).expanduser().resolve().parent
    if not parent.exists():
        return None
    return str(parent)
