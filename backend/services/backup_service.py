"""SQLite 自动备份服务（R19-A）。

本地优先应用的数据库安全底线：会话与记忆全部落在单个 SQLite 文件里，
损坏/误删即不可恢复。本服务提供：

- ``create_backup(reason)``: 用 sqlite3 在线 backup API（WAL 安全）把
  主库复制到 ``<db 目录>/backups/sage-backup-<时间戳>.db``，保留最近
  7 份轮转；独立只读源连接，不经过全局 _SQLITE_LOCK 代理，不阻塞
  聊天主流程。
- ``list_backups()``: 现有备份清单（文件名/大小/创建时间/触发来源）。

所有失败路径 fail-safe：备份失败只记日志，绝不影响应用运行。
"""

from __future__ import annotations

import logging
import re
import sqlite3
import time
from pathlib import Path
from typing import Any, Dict, List

from backend.data.database import Database

logger = logging.getLogger(__name__)

#: 备份保留份数（超出后按 mtime 从旧到新清理）
RETENTION_COUNT = 7

#: 备份文件名模式（用于列表识别与轮转）
_BACKUP_RE = re.compile(r"^sage-backup-\d{8}-\d{6}(?:-\d+)?\.db$")

_VALID_REASONS = ("startup", "daily", "manual")


def get_backup_dir(db_path: str | None = None) -> Path:
    """备份目录：跟随主库所在目录（packaged 与 dev 都成立）。"""
    if db_path is None:
        db_path = Database().db_path
    return Path(db_path).parent / "backups"


def list_backups(db_path: str | None = None) -> List[Dict[str, Any]]:
    """列出备份文件（新→旧），供列表端点与 UI 展示。"""
    backup_dir = get_backup_dir(db_path)
    if not backup_dir.is_dir():
        return []
    entries: List[Dict[str, Any]] = []
    try:
        for f in backup_dir.iterdir():
            if not _BACKUP_RE.match(f.name):
                continue
            try:
                st = f.stat()
            except OSError:
                continue
            entries.append(
                {
                    "name": f.name,
                    "size_bytes": st.st_size,
                    "created_at": int(st.st_mtime * 1000),
                }
            )
    except OSError as exc:
        logger.warning("list_backups failed: %s", exc)
        return []
    entries.sort(key=lambda e: e["created_at"], reverse=True)
    return entries


def _rotate(backup_dir: Path, keep: int = RETENTION_COUNT) -> int:
    """超出保留份数时清理最旧的备份，返回删除数。"""
    backups: List[tuple[float, Path]] = []
    for f in backup_dir.iterdir():
        if _BACKUP_RE.match(f.name):
            try:
                backups.append((f.stat().st_mtime, f))
            except OSError:
                continue
    backups.sort()
    removed = 0
    for _, f in backups[: max(0, len(backups) - keep)]:
        try:
            f.unlink()
            removed += 1
        except OSError as exc:
            logger.warning("backup rotation unlink failed (%s): %s", f.name, exc)
    return removed


def create_backup(reason: str = "manual", db_path: str | None = None) -> Dict[str, Any] | None:
    """在线备份主库，返回备份条目；失败返回 None（fail-safe）。

    使用独立源连接 + sqlite3 backup API —— 对 WAL 主库安全，备份期间
    主连接可继续读写。先写 ``.tmp`` 再原子 rename，避免半成品备份被
    当成有效文件。
    """
    if reason not in _VALID_REASONS:
        reason = "manual"
    try:
        if db_path is None:
            db_path = Database().db_path
        src = sqlite3.connect(db_path)
        try:
            backup_dir = get_backup_dir(db_path)
            backup_dir.mkdir(parents=True, exist_ok=True)
            stamp = time.strftime("%Y%m%d-%H%M%S")
            # 同秒多次备份（测试/手动连点）→ 追加序号保证文件名唯一
            final = backup_dir / f"sage-backup-{stamp}.db"
            seq = 2
            while final.exists():
                final = backup_dir / f"sage-backup-{stamp}-{seq}.db"
                seq += 1
            tmp = backup_dir / f".tmp-{stamp}.db"
            dst = sqlite3.connect(str(tmp))
            try:
                src.backup(dst)
            finally:
                dst.close()
            tmp.replace(final)
        finally:
            src.close()
        _rotate(backup_dir)
        st = final.stat()
        logger.info("backup created (%s): %s (%d bytes)", reason, final.name, st.st_size)
        return {
            "name": final.name,
            "size_bytes": st.st_size,
            "created_at": int(st.st_mtime * 1000),
            "reason": reason,
        }
    except Exception:
        logger.exception("create_backup failed (reason=%s)", reason)
        return None


# ==================== 恢复（R21-A） ====================

#: 恢复标记文件名（位于 backups 目录旁，记录待应用的备份）
RESTORE_MARKER = "restore-marker.json"


def restore_backup(name: str, db_path: str | None = None) -> Dict[str, Any] | None:
    """安排恢复指定备份（下次启动生效）。

    桌面单进程无法在运行中安全换库 —— 采用"标记 + 启动应用"两段式：

    1. 先做一次 ``pre-restore`` 安全备份（恢复失败时现有数据可回退）；
    2. 把备份复制为 ``<db_path>.restore-pending``；
    3. 写 restore-marker.json（备份名/时间）；下次启动
       :func:`apply_pending_restore` 原子替换主库文件。

    Returns:
        {'ok': True, 'applied_at_startup': True, 'backup': name}；失败 None。
    """
    try:
        if not _BACKUP_RE.match(name or ""):
            logger.warning("restore_backup rejected invalid name: %r", name)
            return None
        if db_path is None:
            db_path = Database().db_path
        backup_dir = get_backup_dir(db_path)
        src = backup_dir / name
        if not src.is_file():
            logger.warning("restore_backup: backup not found: %s", name)
            return None

        # 恢复前安全备份（fail-safe：失败不阻断恢复安排，但记日志）
        safety = create_backup("manual", db_path=db_path)
        if safety is None:
            logger.error("pre-restore safety backup failed; aborting restore")
            return None

        pending = Path(str(db_path) + ".restore-pending")
        tmp = backup_dir / f".restore-tmp-{name}"
        data = src.read_bytes()
        tmp.write_bytes(data)
        tmp.replace(pending)

        import json as _json

        marker = backup_dir / RESTORE_MARKER
        marker.write_text(
            _json.dumps(
                {
                    "backup": name,
                    "scheduled_at": int(time.time() * 1000),
                    "safety_backup": safety["name"],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        logger.info("restore scheduled from %s (applies at next startup)", name)
        return {"ok": True, "applied_at_startup": True, "backup": name}
    except Exception:
        logger.exception("restore_backup failed")
        return None


def apply_pending_restore(db_path: str | None = None) -> bool:
    """启动早期应用待恢复备份（原子替换主库文件）。

    由 main.lifespan 在 init_db 之前调用。任何失败都只记日志并清理
    标记 —— 绝不阻塞启动。
    """
    try:
        if db_path is None:
            db_path = Database().db_path
        backup_dir = get_backup_dir(db_path)
        marker = backup_dir / RESTORE_MARKER
        pending = Path(str(db_path) + ".restore-pending")
        if not marker.is_file():
            return False
        import json as _json

        info: Dict[str, Any] = {}
        try:
            info = _json.loads(marker.read_text(encoding="utf-8"))
        except Exception:
            logger.exception("restore marker unreadable; cleaning up")
        if not pending.is_file():
            # 半成品（复制失败过）—— 清理标记即可
            marker.unlink(missing_ok=True)
            return False
        db = Path(db_path)
        # 主库旁路文件（-wal/-shm）一并清理，避免旧 WAL 污染新库
        for suffix in ("-wal", "-shm"):
            side = Path(str(db_path) + suffix)
            if side.exists():
                side.unlink()
        pending.replace(db)
        marker.unlink(missing_ok=True)
        logger.info("restore applied from %s (info=%s)", db.name, info)
        return True
    except Exception:
        logger.exception("apply_pending_restore failed (ignored)")
        return False
