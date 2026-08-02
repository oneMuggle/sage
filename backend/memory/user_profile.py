"""UserProfileStore - 用户画像持久化存储（USER.md 概念）

借鉴 hermes-agent ``tools/memory_tool.py`` 的 ``MemoryStore`` frozen snapshot
模式：把"关于用户的知识"（偏好 / 沟通风格 / 工作习惯 / 身份）与通用记忆分离，
以**冻结快照**方式始终注入 system prompt。

设计要点
--------

- **冻结快照**：``load()`` 时从 DB 读取并计算快照；此后 ``add()`` 只更新 DB，
  不改变快照 —— 保证同一会话内 system prompt 前缀稳定，提升 prefix cache
  命中率（hermes 语义：中途写入不改 system prompt，下次会话启动才刷新）。
  需要立即刷新时显式调 ``invalidate()``。
- **字符上限**：快照按重要性降序截断到 ``char_limit``，避免画像膨胀挤占
  context。
- **去重**：写入前检查相似内容（完全一致 / 子串包含 / 高相似度），避免重复
  画像刷屏。
- **安全**：写入前复用 ``backend.memory.safety.get_scanner()`` 严格扫描，
  命中威胁模式时拒绝写入并记 warning。
"""

from __future__ import annotations

import logging
import time
import uuid
from difflib import SequenceMatcher
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

#: 用户画像注入快照的默认字符上限（hermes USER.md 默认 1375 chars 同量级）
DEFAULT_CHAR_LIMIT = 1400

#: category 白名单（写入时校验，防脏数据）。
#: 含 extractor 已产出的 ``goal``（用户目标属画像类知识）。
VALID_CATEGORIES = ("preference", "communication_style", "workflow_habit", "identity", "goal")

#: 去重判定：新内容与存量内容的最相似度阈值（> 视为重复）
DEDUPE_RATIO = 0.95


def _now_ms() -> int:
    """当前时间（ms epoch，与 sessions/messages 表一致）。"""
    return int(time.time() * 1000)


class UserProfileStore:
    """用户画像存储 - 冻结快照 + 字符上限 + 去重 + 安全扫描。

    Example:
        >>> store = UserProfileStore(db)
        >>> store.load()
        >>> store.add("用户偏好简洁回答", category="preference", importance=8)
        'a1b2c3d4'
        >>> store.get_snapshot()
        '## USER PROFILE\\n- 用户偏好简洁回答'
        >>> store.get_core_items()
        [{"content": "用户偏好简洁回答", "category": "preference", "importance": 8}]
    """

    def __init__(self, db, char_limit: int = DEFAULT_CHAR_LIMIT) -> None:
        """初始化用户画像存储。

        Args:
            db: Database 实例（提供 ``get_connection()``）。
            char_limit: 快照字符上限，默认 1400。
        """
        self.db = db
        self.char_limit = char_limit
        self._entries: List[Dict[str, Any]] = []
        #: 冻结快照条目（load/invalidate 时按重要性 + 字符上限截断的子集）。
        #: 供 ``get_snapshot()`` 与 ``get_core_items()`` 共用，保证 hex / legacy
        #: 两条注入路径都拿到同一份"冻结 + 截断"的画像。
        self._snapshot_entries: List[Dict[str, Any]] = []
        self._snapshot: str = ""

    # ---- 读取 / 快照 -------------------------------------------------------

    def load(self) -> None:
        """从 DB 加载全部画像并计算冻结快照（会话启动时调用）。"""
        self._entries = self._query_all()
        self._rebuild_snapshot()
        logger.debug(f"UserProfileStore 加载 {len(self._entries)} 条画像")

    def invalidate(self) -> None:
        """刷新冻结快照（显式调用；写入路径默认不刷新，保 prefix cache）。"""
        self._rebuild_snapshot()

    def get_snapshot(self) -> str:
        """返回冻结快照（字符受限），用于注入 system prompt 静态段。"""
        if not self._snapshot and self._entries:
            # 防御：构造后未显式 load 时按当前 entries 生成一次
            self._rebuild_snapshot()
        return self._snapshot

    def get_core_items(self) -> List[Dict[str, Any]]:
        """返回核心画像条目，供 ``MemoryContext.core`` 注入。

        基于冻结快照条目（与 ``get_snapshot()`` 同源），保证 hex 路径也遵循
        字符上限截断与"中途写入不改快照"语义。

        Returns:
            按重要性降序的 ``[{"content", "category", "importance"}]`` 列表。
        """
        items = [
            {
                "content": e["content"],
                "category": e["category"],
                "importance": e.get("importance", 5),
            }
            for e in self._snapshot_entries
        ]
        items.sort(key=lambda i: i["importance"], reverse=True)
        return items

    def list(self) -> List[Dict[str, Any]]:
        """列出全部画像条目（按重要性降序）。"""
        items = list(self._entries)
        items.sort(key=lambda e: e.get("importance", 5), reverse=True)
        return items

    # ---- 写入 / 删除 -------------------------------------------------------

    def add(
        self,
        content: str,
        category: str = "preference",
        importance: int = 5,
    ) -> Optional[str]:
        """添加一条用户画像（去重 + 限长 + 安全扫描）。

        Args:
            content: 画像内容（一句话，如 "用户偏好简洁回答"）。
            category: 类别，白名单 ``preference / communication_style /
                workflow_habit / identity``；非白名单值降级为 preference。
            importance: 重要性 1-10。

        Returns:
            新画像 ID；内容为空 / 与存量重复 / 命中安全扫描时返回 None。
        """
        content = (content or "").strip()
        if not content:
            return None

        # 安全扫描（Hermes 风格，与 MemoryAdapter.store 一致）
        from backend.memory.safety import get_scanner

        scan = get_scanner().scan_write(content)
        if scan.blocked:
            logger.warning(
                f"User profile write blocked: {scan.reason} (threat={scan.threat_level})"
            )
            return None

        # 类别白名单校验
        if category not in VALID_CATEGORIES:
            logger.debug(f"未知画像类别 {category!r}，降级为 preference")
            category = "preference"

        # importance 钳制到 1-10（DB CHECK 约束防越界写入抛 IntegrityError）
        importance = max(1, min(int(importance), 10))

        # 去重：完全一致 / 子串包含 / 高相似度
        if self._is_duplicate(content):
            logger.debug(f"User profile duplicate ignored: {content[:30]}")
            return None

        # 限长：单条画像内容截断到 200 字（防脏数据刷屏）
        content = content[:200]
        profile_id = uuid.uuid4().hex
        now = _now_ms()
        conn = self.db.get_connection()
        conn.execute(
            "INSERT INTO user_profile (id, content, category, importance, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (profile_id, content, category, importance, now, now),
        )
        conn.commit()
        # 写入路径不刷新冻结快照（hermes 语义：保 prefix cache）
        self._entries.append(
            {
                "id": profile_id,
                "content": content,
                "category": category,
                "importance": importance,
            }
        )
        logger.debug(f"User profile saved: [{category}] {content[:30]}")
        return profile_id

    def delete(self, profile_id: str) -> bool:
        """按 ID 删除画像条目。返回是否删除成功。"""
        conn = self.db.get_connection()
        cursor = conn.execute("DELETE FROM user_profile WHERE id = ?", (profile_id,))
        conn.commit()
        if cursor.rowcount > 0:
            self._entries = [e for e in self._entries if e["id"] != profile_id]
            self._rebuild_snapshot()
            return True
        return False

    # ---- 内部实现 ----------------------------------------------------------

    def _query_all(self) -> List[Dict[str, Any]]:
        """从 DB 读取全部画像条目。"""
        try:
            conn = self.db.get_connection()
            rows = conn.execute(
                "SELECT id, content, category, importance, created_at "
                "FROM user_profile ORDER BY importance DESC, created_at ASC"
            ).fetchall()
            return [
                {
                    "id": row["id"],
                    "content": row["content"],
                    "category": row["category"],
                    "importance": max(1, min(int(row["importance"] or 5), 10)),
                    "created_at": row["created_at"],
                }
                for row in rows
            ]
        except Exception as exc:  # pragma: no cover - 防御性兜底
            logger.warning(f"读取用户画像失败: {exc}")
            return []

    def _rebuild_snapshot(self) -> None:
        """按重要性降序 + 字符上限重建冻结快照条目与文本。

        ``_snapshot_entries`` 与 ``_snapshot`` 同源,保证 hex（get_core_items）
        与 legacy（get_snapshot）注入同一份"冻结 + 截断"画像。
        """
        items = sorted(self._entries, key=lambda e: e.get("importance", 5), reverse=True)
        lines: List[str] = []
        kept: List[Dict[str, Any]] = []
        used = 0
        for e in items:
            line = f"- {e['content']}"
            if used + len(line) + 1 > self.char_limit:
                break
            lines.append(line)
            used += len(line) + 1
            kept.append(e)
        self._snapshot_entries = kept
        self._snapshot = "## USER PROFILE\n" + "\n".join(lines) if kept else ""

    def _is_duplicate(self, content: str) -> bool:
        """判断内容是否与存量画像重复（完全一致 / 子串包含 / 高相似度）。"""
        for e in self._entries:
            existing = e["content"]
            if content == existing:
                return True
            if len(content) >= 5 and (content in existing or existing in content):
                return True
            ratio = SequenceMatcher(None, content, existing).ratio()
            if ratio >= DEDUPE_RATIO:
                return True
        return False


# 全局单例（与 get_memory_manager 同模式）
_profile_store: Optional[UserProfileStore] = None


def get_user_profile(db=None) -> UserProfileStore:
    """获取全局 UserProfileStore 单例（惰性构造 + load）。

    Args:
        db: 可选 Database 实例；缺省用 ``get_database()``。

    Returns:
        全局共享的用户画像存储实例。
    """
    global _profile_store
    if _profile_store is None:
        from backend.data.database import get_database

        _profile_store = UserProfileStore(db or get_database())
        _profile_store.load()
    return _profile_store


def reset_user_profile() -> None:
    """重置 UserProfileStore 单例（仅用于测试）。"""
    global _profile_store
    _profile_store = None
