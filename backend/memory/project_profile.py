"""ProjectProfileStore — 项目画像持久化（项目级 "MEMORY.md"，P2 scope 轴）

与 :mod:`backend.memory.user_profile`（USER.md 概念）同构，但按
``project_key``（工作区绝对路径，与 ``session_workspace_bindings`` /
``projects`` 注册表同源）分组：每个项目一份**冻结快照**，仅当会话绑定了
同一项目时注入 system prompt 的 core 层。

设计要点（继承 UserProfileStore 的语义）：

- **冻结快照**：``load()`` 时按项目计算快照；此后 ``add()`` 只更新 DB 与
  entries，不改变快照——保证同一会话内 system prompt 前缀稳定（prefix
  cache）。需要立即刷新时显式 ``invalidate(project_key)``。
- **字符上限**：每项目快照按重要性降序截断到 ``char_limit``（默认比用户
  画像更紧，项目知识应有边界感）。
- **去重**：项目内去重（完全一致 / 子串包含 / 高相似度）。
- **安全**：写入前复用 ``backend.memory.safety.get_scanner()`` 严格扫描。
"""

from __future__ import annotations

import logging
import time
import uuid
from difflib import SequenceMatcher
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

#: 项目画像注入快照的默认字符上限（每项目；比 USER.md 的 1400 更紧）
DEFAULT_CHAR_LIMIT = 1000

#: category 白名单；非白名单值降级为 convention。
VALID_CATEGORIES = ("convention", "architecture", "decision", "goal", "note")

#: 全局快照最多缓存的项目数（LRU 兜底，防长期运行内存增长）
PROJECT_CACHE_LIMIT = 64

#: 去重相似度阈值（与 user_profile 一致）
DEDUPE_RATIO = 0.95


def _now_ms() -> int:
    return int(time.time() * 1000)


class ProjectProfileStore:
    """项目画像存储 - 按 project_key 分组的冻结快照 + 限长 + 去重 + 安全扫描。

    Example:
        >>> store = ProjectProfileStore(db)
        >>> store.load()
        >>> store.add("/work/app", "接口统一用 REST", category="convention")
        'a1b2c3d4'
        >>> store.get_snapshot("/work/app")
        '## PROJECT PROFILE (/work/app)\\n- 接口统一用 REST'
        >>> store.get_snapshot("/other")
        ''
    """

    def __init__(self, db, char_limit: int = DEFAULT_CHAR_LIMIT) -> None:
        self.db = db
        self.char_limit = char_limit
        # project_key -> entries（按重要性降序的原始条目，含全量）
        self._by_project: Dict[str, List[Dict[str, Any]]] = {}
        # project_key -> 冻结快照条目（截断子集）
        self._snapshot_entries: Dict[str, List[Dict[str, Any]]] = {}
        self._snapshots: Dict[str, str] = {}
        self._access_order: List[str] = []

    # ---- 读取 / 快照 -------------------------------------------------------

    def load(self) -> None:
        """从 DB 加载全部项目画像并按项目计算冻结快照。"""
        self._by_project = {}
        for row in self._query_all():
            self._by_project.setdefault(row["project_key"], []).append(row)
        self._snapshot_entries = {}
        self._snapshots = {}
        for key in self._by_project:
            self._rebuild_snapshot(key)
        logger.debug(
            f"ProjectProfileStore 加载 {len(self._by_project)} 个项目 "
            f"共 {sum(len(v) for v in self._by_project.values())} 条画像"
        )

    def invalidate(self, project_key: str) -> None:
        """刷新指定项目的冻结快照（显式调用；写入路径默认不刷新，保 prefix cache）。"""
        self._rebuild_snapshot(project_key)

    def get_snapshot(self, project_key: Optional[str]) -> str:
        """返回指定项目的冻结快照；project_key 为空（未绑定会话）恒为 ''。"""
        if not project_key:
            return ""
        self._touch(project_key)
        if project_key not in self._snapshots and self._by_project.get(project_key):
            self._rebuild_snapshot(project_key)
        return self._snapshots.get(project_key, "")

    def get_core_items(self, project_key: Optional[str]) -> List[Dict[str, Any]]:
        """返回项目核心条目（与快照同源的冻结+截断子集），供 MemoryContext.core。

        每条附加 ``scope='project'`` / ``project_key``，供注入层区分展示归属。
        """
        if not project_key:
            return []
        self._touch(project_key)
        if project_key not in self._snapshot_entries and self._by_project.get(project_key):
            # 防御：构造后未显式 load/invalidate 时按当前 entries 生成一次
            self._rebuild_snapshot(project_key)
        return [
            {
                "content": e["content"],
                "category": e["category"],
                "importance": e.get("importance", 5),
                "scope": "project",
                "project_key": project_key,
            }
            for e in self._snapshot_entries.get(project_key, [])
        ]

    def list(self, project_key: str) -> List[Dict[str, Any]]:
        """列出指定项目的全部画像条目（按重要性降序）。"""
        if not project_key:
            return []
        items = list(self._by_project.get(project_key, []))
        items.sort(key=lambda e: e.get("importance", 5), reverse=True)
        return items

    def projects(self) -> List[str]:
        """当前有画像条目全部项目 key（供 UI 下拉）。"""
        return sorted(self._by_project)

    # ---- 写入 / 删除 -------------------------------------------------------

    def add(
        self,
        project_key: str,
        content: str,
        category: str = "convention",
        importance: int = 5,
        source: str = "manual",
    ) -> Optional[str]:
        """为指定项目添加一条画像（去重 + 限长 + 安全扫描）。

        Returns:
            新画像 ID；project_key/content 为空、重复或命中安全扫描时 None。
        """
        project_key = (project_key or "").strip()
        content = (content or "").strip()
        if not project_key or not content:
            return None

        from backend.memory.safety import get_scanner

        scan = get_scanner().scan_write(content)
        if scan.blocked:
            logger.warning(
                f"Project profile write blocked: {scan.reason} (threat={scan.threat_level})"
            )
            return None

        if category not in VALID_CATEGORIES:
            logger.debug(f"未知项目画像类别 {category!r}，降级为 convention")
            category = "convention"

        importance = max(1, min(int(importance), 10))

        entries = self._by_project.setdefault(project_key, [])
        if self._is_duplicate(entries, content):
            logger.debug(f"Project profile duplicate ignored: {content[:30]}")
            return None

        content = content[:200]
        profile_id = uuid.uuid4().hex
        now = _now_ms()
        conn = self.db.get_connection()
        conn.execute(
            "INSERT INTO project_profile "
            "(id, project_key, content, category, importance, source, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (profile_id, project_key, content, category, importance, source, now, now),
        )
        conn.commit()
        # 写入不刷新冻结快照（hermes 语义：保 prefix cache）
        entries.append(
            {
                "id": profile_id,
                "project_key": project_key,
                "content": content,
                "category": category,
                "importance": importance,
                "source": source,
                "created_at": now,
            }
        )
        logger.debug(f"Project profile saved: [{project_key}] [{category}] {content[:30]}")
        return profile_id

    def delete(self, profile_id: str) -> bool:
        """按 ID 删除画像条目（任意项目）。返回是否删除成功。"""
        conn = self.db.get_connection()
        row = conn.execute(
            "SELECT project_key FROM project_profile WHERE id = ?", (profile_id,)
        ).fetchone()
        cursor = conn.execute("DELETE FROM project_profile WHERE id = ?", (profile_id,))
        conn.commit()
        if cursor.rowcount > 0 and row is not None:
            key = row["project_key"] if not isinstance(row, dict) else row["project_key"]
            self._by_project[key] = [
                e for e in self._by_project.get(key, []) if e["id"] != profile_id
            ]
            self._rebuild_snapshot(key)
            return True
        return False

    # ---- 内部实现 ----------------------------------------------------------

    def _query_all(self) -> List[Dict[str, Any]]:
        try:
            conn = self.db.get_connection()
            rows = conn.execute(
                "SELECT id, project_key, content, category, importance, source, created_at "
                "FROM project_profile ORDER BY importance DESC, created_at ASC"
            ).fetchall()
            return [
                {
                    "id": row["id"],
                    "project_key": row["project_key"],
                    "content": row["content"],
                    "category": row["category"],
                    "importance": max(1, min(int(row["importance"] or 5), 10)),
                    "source": row["source"],
                    "created_at": row["created_at"],
                }
                for row in rows
            ]
        except Exception as exc:  # pragma: no cover - 防御性兜底
            logger.warning(f"读取项目画像失败: {exc}")
            return []

    def _rebuild_snapshot(self, project_key: str) -> None:
        """按重要性降序 + 字符上限重建指定项目的冻结快照。"""
        items = sorted(
            self._by_project.get(project_key, []),
            key=lambda e: e.get("importance", 5),
            reverse=True,
        )
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
        if kept:
            self._snapshot_entries[project_key] = kept
            self._snapshots[project_key] = (
                f"## PROJECT PROFILE ({project_key})\n" + "\n".join(lines)
            )
        else:
            self._snapshot_entries.pop(project_key, None)
            self._snapshots.pop(project_key, None)

    def _touch(self, project_key: str) -> None:
        """LRU 记账：快照缓存项目数超限时丢弃最久未用的（只丢快照，不丢数据）。"""
        if project_key in self._access_order:
            self._access_order.remove(project_key)
        self._access_order.append(project_key)
        while len(self._access_order) > PROJECT_CACHE_LIMIT:
            evicted = self._access_order.pop(0)
            self._snapshots.pop(evicted, None)
            self._snapshot_entries.pop(evicted, None)

    @staticmethod
    def _is_duplicate(entries: List[Dict[str, Any]], content: str) -> bool:
        for e in entries:
            existing = e["content"]
            if content == existing:
                return True
            if len(content) >= 5 and (content in existing or existing in content):
                return True
            if SequenceMatcher(None, content, existing).ratio() >= DEDUPE_RATIO:
                return True
        return False


# 全局单例（与 get_user_profile 同模式）
_project_profile_store: Optional[ProjectProfileStore] = None


def get_project_profile(db=None) -> ProjectProfileStore:
    """获取全局 ProjectProfileStore 单例（惰性构造 + load）。"""
    global _project_profile_store
    if _project_profile_store is None:
        from backend.data.database import get_database

        _project_profile_store = ProjectProfileStore(db or get_database())
        _project_profile_store.load()
    return _project_profile_store


def reset_project_profile() -> None:
    """重置单例（仅用于测试）。"""
    global _project_profile_store
    _project_profile_store = None
