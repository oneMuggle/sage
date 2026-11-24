"""解析结果 SQLite 缓存：同内容 + 同引擎的解析产物直接复用。

缓存表 ``document_parse_cache`` 由 ``Database.init_db()`` 建好；本模块只做
读写。所有数据库异常一律吞掉并降级为"未命中"——缓存不可用永远不该让
解析主链路失败。
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any, Dict, Optional

from backend.data.database import Database, get_database
from backend.domain.document_parse import ParseResult

logger = logging.getLogger(__name__)


class SqliteParseCache:
    """``document_parse_cache`` 表的最小读写门面（fail-safe）。"""

    def __init__(self, db: Optional[Database] = None) -> None:
        self._db = db

    def _database(self) -> Database:
        if self._db is None:
            self._db = get_database()
        return self._db

    def get(self, content_hash: str, engine: str) -> Optional[ParseResult]:
        """命中返回 ``cached=True`` 的结果；任何异常 → None。"""
        try:
            conn = self._database().get_connection()
            row = conn.execute(
                "SELECT tier, markdown, structured_json, images_dir, meta_json "
                "FROM document_parse_cache WHERE content_hash = ? AND engine = ?",
                (content_hash, engine),
            ).fetchone()
            if row is None:
                return None
            meta: Dict[str, Any] = json.loads(row["meta_json"] or "{}")
            structured = (
                json.loads(row["structured_json"]) if row["structured_json"] else None
            )
            return ParseResult(
                text=row["markdown"] or "",
                engine_used=engine,
                structured=structured,
                tier_used=row["tier"],
                quality_score=float(meta.get("quality_score", 1.0)),
                duration_ms=int(meta.get("duration_ms", 0)),
                cached=True,
                warnings=list(meta.get("warnings") or []),
                media_url=meta.get("media_url"),
                assets=dict(meta.get("assets") or {}),
            )
        except Exception:  # noqa: BLE001 — 缓存永不阻断解析主链路
            logger.warning(
                "document parse cache get failed: engine=%s", engine, exc_info=True
            )
            return None

    def put(self, content_hash: str, engine: str, result: ParseResult) -> None:
        """写入/覆盖一条缓存；任何异常 → 静默跳过。"""
        try:
            conn = self._database().get_connection()
            meta = {
                "quality_score": result.quality_score,
                "duration_ms": result.duration_ms,
                "warnings": list(result.warnings),
                "media_url": result.media_url,
                "assets": dict(result.assets),
            }
            conn.execute(
                "INSERT OR REPLACE INTO document_parse_cache "
                "(content_hash, engine, tier, markdown, structured_json, "
                " images_dir, meta_json, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    content_hash,
                    engine,
                    result.tier_used,
                    result.text,
                    json.dumps(result.structured) if result.structured else None,
                    None,
                    json.dumps(meta),
                    int(time.time()),
                ),
            )
            conn.commit()
        except Exception:  # noqa: BLE001 — 缓存永不阻断解析主链路
            logger.warning(
                "document parse cache put failed: engine=%s", engine, exc_info=True
            )
