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
