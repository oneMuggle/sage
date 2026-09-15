"""
产物版本仓储层 (Phase 2 M2)
追踪产物内容的历史版本，支持回滚到任意版本。
快照内容存文件系统（避免 SQLite 大文本性能问题），元数据存 artifact_versions 表。
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from backend.data.database import get_database

MAX_VERSIONS_PER_ARTIFACT = 100
MAX_TEXT_BYTES = 1 * 1024 * 1024  # 1 MiB text limit


def create_version(
    artifact_id: str,
    content: str,
    content_hash: str,
    snapshot_dir: str,
    note: Optional[str] = None,
) -> Dict[str, Any]:
    """创建新版本，返回版本元数据。

    快照写入 ``{snapshot_dir}/{artifact_id}_v{N}.txt``。
    单产物最多 MAX_VERSIONS_PER_ARTIFACT 个版本，超限抛 ValueError。
    """
    db = get_database()
    conn = db.get_connection()

    # 查询当前最大版本号
    cursor = conn.execute(
        "SELECT MAX(version_num) FROM artifact_versions WHERE artifact_id = ?",
        (artifact_id,),
    )
    row = cursor.fetchone()
    max_version = row[0] if row and row[0] is not None else 0
    new_version = max_version + 1

    if new_version > MAX_VERSIONS_PER_ARTIFACT:
        raise ValueError(
            f"Artifact {artifact_id} 已达最大版本数 {MAX_VERSIONS_PER_ARTIFACT}"
        )

    # 写入快照文件
    snapshot_path = Path(snapshot_dir) / f"{artifact_id}_v{new_version}.txt"
    snapshot_path.parent.mkdir(parents=True, exist_ok=True)
    snapshot_path.write_text(content, encoding="utf-8")

    # 插入版本记录
    created_at = int(time.time() * 1000)
    conn.execute(
        """
        INSERT INTO artifact_versions
            (artifact_id, version_num, content_hash, snapshot_path, created_at, note)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (artifact_id, new_version, content_hash, str(snapshot_path), created_at, note),
    )
    conn.commit()

    return {
        "artifact_id": artifact_id,
        "version_num": new_version,
        "content_hash": content_hash,
        "snapshot_path": str(snapshot_path),
        "created_at": created_at,
        "note": note,
    }


def list_versions(artifact_id: str) -> List[Dict[str, Any]]:
    """列出指定产物的所有版本，按 version_num 降序。"""
    db = get_database()
    conn = db.get_connection()
    cursor = conn.execute(
        """
        SELECT artifact_id, version_num, content_hash, snapshot_path, created_at, note
        FROM artifact_versions
        WHERE artifact_id = ?
        ORDER BY version_num DESC
        """,
        (artifact_id,),
    )
    return [
        {
            "artifact_id": row[0],
            "version_num": row[1],
            "content_hash": row[2],
            "snapshot_path": row[3],
            "created_at": row[4],
            "note": row[5],
        }
        for row in cursor.fetchall()
    ]


def get_version(artifact_id: str, version_num: int) -> Optional[Dict[str, Any]]:
    """获取指定版本，包含快照内容。不存在返回 None。"""
    db = get_database()
    conn = db.get_connection()
    cursor = conn.execute(
        """
        SELECT artifact_id, version_num, content_hash, snapshot_path, created_at, note
        FROM artifact_versions
        WHERE artifact_id = ? AND version_num = ?
        """,
        (artifact_id, version_num),
    )
    row = cursor.fetchone()
    if not row:
        return None

    snapshot_path = Path(row[3])
    content = snapshot_path.read_text(encoding="utf-8")

    return {
        "artifact_id": row[0],
        "version_num": row[1],
        "content_hash": row[2],
        "snapshot_path": row[3],
        "created_at": row[4],
        "note": row[5],
        "content": content,
    }


def get_latest_version(artifact_id: str) -> Optional[Dict[str, Any]]:
    """获取最新版本，包含快照内容。无版本返回 None。"""
    db = get_database()
    conn = db.get_connection()
    cursor = conn.execute(
        """
        SELECT artifact_id, version_num, content_hash, snapshot_path, created_at, note
        FROM artifact_versions
        WHERE artifact_id = ?
        ORDER BY version_num DESC
        LIMIT 1
        """,
        (artifact_id,),
    )
    row = cursor.fetchone()
    if not row:
        return None

    snapshot_path = Path(row[3])
    content = snapshot_path.read_text(encoding="utf-8")

    return {
        "artifact_id": row[0],
        "version_num": row[1],
        "content_hash": row[2],
        "snapshot_path": row[3],
        "created_at": row[4],
        "note": row[5],
        "content": content,
    }


# ==================== Write Serialization ====================


import asyncio


_artifact_locks: Dict[str, asyncio.Lock] = {}


def _get_lock(artifact_id: str) -> asyncio.Lock:
    """Return per-artifact asyncio.Lock (lazy init, never removed)."""
    if artifact_id not in _artifact_locks:
        _artifact_locks[artifact_id] = asyncio.Lock()
    return _artifact_locks[artifact_id]


class ConflictError(Exception):
    """base_hash 与实际文件内容不匹配，外部已修改。"""


async def apply_edit(
    artifact_id: str,
    artifact_path: str,
    base_hash: str,
    new_content: str,
    note: Optional[str] = None,
) -> Dict[str, Any]:
    """原子替换产物内容，创建新版本。

    1. 获取 per-artifact 锁（同一产物写操作串行化）
    2. 读取当前文件，计算 hash，与 base_hash 比对
    3. 不匹配 → ConflictError（外部已修改，拒绝覆盖）
    4. 新内容超 1 MiB → ValueError
    5. 创建新版本 + 写入原文件（原子替换）

    Returns: 新版本元数据。
    """
    import hashlib

    new_bytes = new_content.encode("utf-8")
    if len(new_bytes) > MAX_TEXT_BYTES:
        raise ValueError(
            f"文本内容 {len(new_bytes)} 字节超过上限 {MAX_TEXT_BYTES} (1 MiB)"
        )

    lock = _get_lock(artifact_id)
    async with lock:
        path = Path(artifact_path)
        if not path.is_file():
            raise FileNotFoundError(f"Artifact file not found: {artifact_path}")

        current_bytes = path.read_bytes()
        current_hash = hashlib.sha256(current_bytes).hexdigest()
        if current_hash != base_hash:
            raise ConflictError(
                f"base_hash 冲突：期望 {base_hash[:16]}…，实际 {current_hash[:16]}…，"
                " 文件已被外部修改"
            )

        # 写入文件（原子替换：先写临时文件再 rename）
        tmp_path = path.with_suffix(path.suffix + ".tmp")
        tmp_path.write_bytes(new_bytes)
        tmp_path.replace(path)

        # 计算新 hash 并创建版本
        new_hash = hashlib.sha256(new_bytes).hexdigest()
        snapshot_dir = str(path.parent / ".snapshots")

        return create_version(
            artifact_id=artifact_id,
            content=new_content,
            content_hash=new_hash,
            snapshot_dir=snapshot_dir,
            note=note,
        )
