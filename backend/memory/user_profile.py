"""UserProfileStore - 用户画像持久化存储（USER.md 概念）

借鉴 hermes-agent ``tools/memory_tool.py`` 的 ``MemoryStore`` frozen snapshot
模式：把"关于用户的知识"（偏好 / 沟通风格 / 工作习惯 / 身份）与通用记忆分离，
以**冻结快照**方式始终注入 system prompt。

设计要点（v2 治理，2026-11-18 fix/user-profile-memory-governance）
------------------------------------------------------------------

- **冻结快照**：``load()`` 时从 DB 读取并计算快照；此后写入只更新 DB，
  不改变快照 —— 保证同一会话内 system prompt 前缀稳定，提升 prefix cache
  命中率（hermes 语义：中途写入不改 system prompt，下次会话启动才刷新）。
- **会话级快照缓存**：``preload_for_session(session_id)`` /
  ``get_snapshot_for(session_id)`` 为每个会话维护独立的冻结快照实例，
  新会话开始时立即看到最新画像，无需重启进程。
- **字符上限**：快照按重要性降序截断到 ``char_limit``，超长条目跳过但
  不阻断后续短条目的填充（``continue`` 而非 ``break``）。
- **Upsert 语义**：``upsert()`` 按结构化维度（``dimension``）或相似度覆盖
  旧行，旧行 ``invalidated_at`` 被标记，新行通过 ``supersedes_id`` 链接；
  完全相等的内容只 bump ``last_confirmed_at``，不新增。
- **来源与溯源**：每条写入记录 ``source``（per_turn / evolution / manual）
  与 ``evidence_session_id``，便于审计。
- **注入过滤**：``_query_all`` 与 ``list`` 仅返回未失效条目
  （``invalidated_at = 0 OR IS NULL``）。
- **安全**：写入前复用 ``backend.memory.safety.get_scanner()`` 严格扫描，
  命中威胁模式时拒绝写入并记 warning。
"""

from __future__ import annotations

import logging
import time
import uuid
from collections import OrderedDict
from difflib import SequenceMatcher
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

#: 用户画像注入快照的默认字符上限（hermes USER.md 默认 1375 chars 同量级）
DEFAULT_CHAR_LIMIT = 1400

#: category 白名单（写入时校验，防脏数据）
VALID_CATEGORIES = (
    "preference",
    "communication_style",
    "workflow_habit",
    "identity",
    "goal",
    "environment",
)

#: environment 类画像最多保留条数（超出删最旧）：环境事实重要但同机数量应少，
#: 防止反复试错把 1400 字符的快照预算挤爆。
ENVIRONMENT_MAX_ENTRIES = 3

#: 去重判定：新内容与存量内容的最相似度阈值（>= 视为相似，走 supersedes）
DEDUPE_RATIO = 0.95

#: session 级快照缓存最大容量（LRU 淘汰）
_SESSION_CACHE_MAX = 64


def _now_ms() -> int:
    """当前时间（ms epoch，与 sessions/messages 表一致）。"""
    return int(time.time() * 1000)


class UserProfileStore:
    """用户画像存储 - 冻结快照 + 字符上限 + upsert + 安全扫描。

    Example:
        >>> store = UserProfileStore(db)
        >>> store.load()
        >>> store.upsert("用户偏好简洁回答", category="preference",
        ...              importance=8, dimension="response_length")
        'a1b2c3d4'
        >>> store.get_snapshot()
        '## USER PROFILE\\n- 用户偏好简洁回答'
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
        #: 会话级冻结快照缓存（LRU）：新会话首次预热点，得到该会话启动时刻
        #: 的画像切面；已开会话保持冻结，不因其他会话写入而变（保 prefix cache）。
        self._session_snapshots: OrderedDict[str, UserProfileStore] = OrderedDict()

    # ---- 读取 / 快照 -------------------------------------------------------

    def load(self) -> None:
        """从 DB 加载全部（未失效）画像并计算冻结快照。"""
        self._entries = self._query_all()
        self._rebuild_snapshot()
        logger.debug(f"UserProfileStore 加载 {len(self._entries)} 条画像")

    def invalidate(self) -> None:
        """刷新冻结快照（显式调用；写入路径默认不刷新，保 prefix cache）。"""
        self._rebuild_snapshot()

    def get_snapshot(self) -> str:
        """返回冻结快照（字符受限），用于注入 system prompt 静态段。"""
        if not self._snapshot and self._entries:
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
        """列出全部（未失效）画像条目（按重要性降序）。"""
        items = list(self._entries)
        items.sort(key=lambda e: e.get("importance", 5), reverse=True)
        return items

    # ---- 写入 / 删除 -------------------------------------------------------

    def upsert(
        self,
        content: str,
        category: str = "preference",
        importance: int = 5,
        source: str = "manual",
        evidence_session_id: Optional[str] = None,
        dimension: Optional[str] = None,
    ) -> Optional[str]:
        """写入一条画像；同维度覆盖旧行，相似度高时走 supersedes。

        行为：
        - 结构化维度（``dimension`` 非空）：查 ``category + dimension`` 生效中旧条目，
          存在则 supersedes（旧行 ``invalidated_at`` 标记，新行 ``supersedes_id`` 链接）；
          不存在则新增。
        - 自由文本（``dimension`` 为空）：完全相等则 bump ``last_confirmed_at``（不新增）；
          高相似度（>= ``DEDUPE_RATIO``）走 supersedes；否则新增。

        Args:
            content: 画像内容（一句话，<= 200 字）。
            category: 类别，白名单；非白名单降级为 ``preference``。
            importance: 重要性 1-10。
            source: 写入来源（``per_turn`` / ``evolution`` / ``manual``）。
            evidence_session_id: 来源会话 id（可选）。
            dimension: 结构化维度键（如 ``response_length``）；为空走自由文本去重。

        Returns:
            新画像 ID；完全相等时返回旧 id（表示 bumped）；
            空内容 / 安全扫描拦截返回 None。
        """
        content = (content or "").strip()
        if not content:
            return None

        from backend.memory.safety import get_scanner

        scan = get_scanner().scan_write(content)
        if scan.blocked:
            logger.warning(
                f"User profile write blocked: {scan.reason} "
                f"(threat={scan.threat_level})"
            )
            return None

        if category not in VALID_CATEGORIES:
            logger.debug(f"未知画像类别 {category!r}，降级为 preference")
            category = "preference"

        importance = max(1, min(int(importance), 10))
        content = content[:200]
        now = _now_ms()
        conn = self.db.get_connection()

        if dimension:
            return self._upsert_dimensioned(
                conn,
                content=content,
                category=category,
                importance=importance,
                dimension=dimension,
                source=source,
                evidence_session_id=evidence_session_id,
                now=now,
            )
        return self._upsert_freeform(
            conn,
            content=content,
            category=category,
            importance=importance,
            source=source,
            evidence_session_id=evidence_session_id,
            now=now,
        )

    def add(
        self,
        content: str,
        category: str = "preference",
        importance: int = 5,
    ) -> Optional[str]:
        """向后兼容的 add 别名 —— 等价于 ``upsert(..., source='manual')``。"""
        return self.upsert(content, category, importance, source="manual")

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

    # ---- 会话级快照缓存 -----------------------------------------------------

    def preload_for_session(self, session_id: str) -> None:
        """为新会话预热独立快照；同 session_id 重复调用无副作用。

        让新会话启动时立即看到最新画像（不依赖进程级单例的首次 load 时机）。
        """
        if session_id in self._session_snapshots:
            return
        while len(self._session_snapshots) >= _SESSION_CACHE_MAX:
            oldest = next(iter(self._session_snapshots))
            del self._session_snapshots[oldest]
        store = UserProfileStore(self.db, self.char_limit)
        store.load()
        self._session_snapshots[session_id] = store
        logger.debug(f"UserProfileStore 为会话 {session_id[:8]} 预热快照")

    def get_snapshot_for(self, session_id: str) -> UserProfileStore:
        """返回会话级冻结快照 store；未预热则同步预热。

        访问时把该会话提到 LRU 末端——已开会话不会被最久未访问的会话挤掉，
        避免"长会话被驱逐后重建快照、system prompt 中途变脸"的 prefix cache 失效。
        """
        if session_id not in self._session_snapshots:
            self.preload_for_session(session_id)
        else:
            self._session_snapshots.move_to_end(session_id)
        return self._session_snapshots[session_id]

    def invalidate_session(self, session_id: str) -> None:
        """session 结束时清缓存，避免内存膨胀。"""
        self._session_snapshots.pop(session_id, None)

    # ---- 内部实现 ----------------------------------------------------------

    def _upsert_dimensioned(
        self,
        conn,
        *,
        content: str,
        category: str,
        importance: int,
        dimension: str,
        source: str,
        evidence_session_id: Optional[str],
        now: int,
    ) -> str:
        """结构化维度覆盖：同 (category, dimension) 生效中旧条目被 supersedes。

        旧内容与新内容完全相等时只 bump ``last_confirmed_at``，不产生新行
        （进化任务每轮重算同一偏好时避免无意义行churn）。
        """
        row = conn.execute(
            "SELECT id, content FROM user_profile "
            "WHERE category=? AND dimension=? "
            "AND (invalidated_at = 0 OR invalidated_at IS NULL) "
            "LIMIT 1",
            (category, dimension),
        ).fetchone()
        new_id = uuid.uuid4().hex
        if row:
            old_id = row["id"]
            if row["content"] == content:
                conn.execute(
                    "UPDATE user_profile SET last_confirmed_at=?, updated_at=? WHERE id=?",
                    (now, now, old_id),
                )
                conn.commit()
                for e in self._entries:
                    if e["id"] == old_id:
                        e["last_confirmed_at"] = now
                        break
                logger.debug(
                    f"User profile exact match (dimension={dimension}): "
                    f"bumped {old_id[:8]}"
                )
                return old_id
            conn.execute(
                "UPDATE user_profile SET invalidated_at=?, updated_at=? WHERE id=?",
                (now, now, old_id),
            )
            conn.execute(
                "INSERT INTO user_profile "
                "(id, content, category, importance, created_at, updated_at, "
                "supersedes_id, invalidated_at, source, evidence_session_id, dimension) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, 0, ?, ?, ?)",
                (
                    new_id,
                    content,
                    category,
                    importance,
                    now,
                    now,
                    old_id,
                    source,
                    evidence_session_id,
                    dimension,
                ),
            )
            # 同 (category, dimension) 的旧失效行（除本次 supersedes 的 old_id）
            # 已无审计价值，清掉避免无限链式堆积。
            conn.execute(
                "DELETE FROM user_profile "
                "WHERE category=? AND dimension=? AND invalidated_at > 0 AND id != ?",
                (category, dimension, old_id),
            )
            logger.debug(
                f"User profile upsert (dimension={dimension}): "
                f"superseded {old_id[:8]} -> {new_id[:8]}"
            )
        else:
            conn.execute(
                "INSERT INTO user_profile "
                "(id, content, category, importance, created_at, updated_at, "
                "invalidated_at, source, evidence_session_id, dimension) "
                "VALUES (?, ?, ?, ?, ?, ?, 0, ?, ?, ?)",
                (
                    new_id,
                    content,
                    category,
                    importance,
                    now,
                    now,
                    source,
                    evidence_session_id,
                    dimension,
                ),
            )
        conn.commit()
        if category == "environment":
            self._prune_environment_overflow(conn, keep=ENVIRONMENT_MAX_ENTRIES)
        self._entries = self._query_all_from(conn)
        return new_id

    def _upsert_freeform(
        self,
        conn,
        *,
        content: str,
        category: str,
        importance: int,
        source: str,
        evidence_session_id: Optional[str],
        now: int,
    ) -> str:
        """自由文本 upsert：完全相等 → bump；高相似度 → supersedes；否则新增。

        若匹配到带 ``dimension`` 的条目，新行继承该 dimension——保证同一画像
        知识始终落在一条维度轨道上（freeform 写入进化过的维度键时不会分裂为
        两条互不认识的维度行，避免下次进化任务再补一条重复维度行）。
        """
        match = self._match_existing(content, category=category)
        inherited_dim: Optional[str] = None
        if match is not None:
            for e in self._entries:
                if e["id"] == match["id"]:
                    inherited_dim = e.get("dimension")
                    break
        if match is None:
            new_id = uuid.uuid4().hex
            conn.execute(
                "INSERT INTO user_profile "
                "(id, content, category, importance, created_at, updated_at, "
                "invalidated_at, source, evidence_session_id) "
                "VALUES (?, ?, ?, ?, ?, ?, 0, ?, ?)",
                (
                    new_id,
                    content,
                    category,
                    importance,
                    now,
                    now,
                    source,
                    evidence_session_id,
                ),
            )
            conn.commit()
            if category == "environment":
                self._prune_environment_overflow(conn, keep=ENVIRONMENT_MAX_ENTRIES)
            self._entries = self._query_all_from(conn)
            logger.debug(f"User profile saved: [{category}] {content[:30]}")
            return new_id

        if match["kind"] == "exact":
            conn.execute(
                "UPDATE user_profile SET last_confirmed_at=?, updated_at=? WHERE id=?",
                (now, now, match["id"]),
            )
            conn.commit()
            for e in self._entries:
                if e["id"] == match["id"]:
                    e["last_confirmed_at"] = now
                    break
            logger.debug(
                f"User profile exact match (bumped last_confirmed_at): "
                f"{match['id'][:8]}"
            )
            return match["id"]

        # match["kind"] == "similar" → supersedes
        old_id = match["id"]
        new_id = uuid.uuid4().hex
        conn.execute(
            "UPDATE user_profile SET invalidated_at=?, updated_at=? WHERE id=?",
            (now, now, old_id),
        )
        conn.execute(
            "INSERT INTO user_profile "
            "(id, content, category, importance, created_at, updated_at, "
            "supersedes_id, invalidated_at, source, evidence_session_id, dimension) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, 0, ?, ?, ?)",
            (
                new_id,
                content,
                category,
                importance,
                now,
                now,
                old_id,
                source,
                evidence_session_id,
                inherited_dim,
            ),
        )
        conn.commit()
        # 同 (category, dimension) 的旧失效行（除本次 supersedes 的 old_id）已无审计价值，
        # 清掉避免无限链式堆积（evolution 周期写入会每轮留一行）。
        if inherited_dim is not None:
            conn.execute(
                "DELETE FROM user_profile "
                "WHERE category=? AND dimension=? AND invalidated_at > 0 AND id != ?",
                (category, inherited_dim, old_id),
            )
            conn.commit()
        self._entries = self._query_all_from(conn)
        logger.debug(
            f"User profile upsert (similar {match['ratio']:.2f}): "
            f"superseded {old_id[:8]} -> {new_id[:8]}"
        )
        return new_id

    def _prune_environment_overflow(
        self, conn, keep: int = ENVIRONMENT_MAX_ENTRIES
    ) -> None:
        """environment 画像超出 keep 条时删除最旧的（DB + 内存条目同步）。"""
        rows = conn.execute(
            "SELECT id FROM user_profile "
            "WHERE category = 'environment' AND (invalidated_at = 0 "
            "OR invalidated_at IS NULL) "
            "ORDER BY created_at DESC, rowid DESC"
        ).fetchall()
        stale_ids = {row["id"] for row in list(rows)[keep:]}
        if not stale_ids:
            return
        conn.executemany(
            "DELETE FROM user_profile WHERE id = ?", [(pid,) for pid in stale_ids]
        )
        conn.commit()
        self._entries = [e for e in self._entries if e["id"] not in stale_ids]

    def _query_all(self) -> List[Dict[str, Any]]:
        """从 DB 读取全部（未失效）画像条目。"""
        try:
            return self._query_all_from(self.db.get_connection())
        except Exception as exc:  # pragma: no cover - 防御性兜底
            logger.warning(f"读取用户画像失败: {exc}")
            return []

    def _query_all_from(self, conn) -> List[Dict[str, Any]]:
        """从给定连接读取全部（未失效）画像条目（带 v2 治理字段）。"""
        rows = conn.execute(
            "SELECT id, content, category, importance, created_at, "
            "supersedes_id, invalidated_at, source, evidence_session_id, "
            "last_confirmed_at, dimension "
            "FROM user_profile "
            "WHERE (invalidated_at = 0 OR invalidated_at IS NULL) "
            "ORDER BY importance DESC, created_at ASC"
        ).fetchall()
        return [
            {
                "id": row["id"],
                "content": row["content"],
                "category": row["category"],
                "importance": max(1, min(int(row["importance"] or 5), 10)),
                "created_at": row["created_at"],
                "supersedes_id": row["supersedes_id"],
                "invalidated_at": row["invalidated_at"] or 0,
                "source": row["source"] or "manual",
                "evidence_session_id": row["evidence_session_id"],
                "last_confirmed_at": row["last_confirmed_at"],
                "dimension": row["dimension"],
            }
            for row in rows
        ]

    def _rebuild_snapshot(self) -> None:
        """按重要性降序 + 字符上限重建冻结快照条目与文本。

        超长条目 ``continue``（跳过、尝试后续短条目），而非 ``break``，避免
        "第一条超长按下暂停、后面短条目全丢"的低效填充。
        """
        items = sorted(
            self._entries, key=lambda e: e.get("importance", 5), reverse=True
        )
        lines: List[str] = []
        kept: List[Dict[str, Any]] = []
        used = 0
        for e in items:
            line = f"- {e['content']}"
            if used + len(line) + 1 > self.char_limit:
                continue
            lines.append(line)
            used += len(line) + 1
            kept.append(e)
        self._snapshot_entries = kept
        self._snapshot = "## USER PROFILE\n" + "\n".join(lines) if kept else ""

    def _match_existing(
        self, content: str, category: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """返回与 content 最相似的生效中条目，用于 upsert 决策：

        - ``None``: 不匹配，应该新增；
        - ``{"kind": "exact", "id": ...}``: 完全相等 → bump last_confirmed_at；
        - ``{"kind": "similar", "id": ..., "ratio": ...}``: 高相似度 → supersedes。

        注：旧版"existing in content"子串规则已移除——"细化被当重复"的根因。
        仅在 ``category`` 指定时按类别过滤，防止跨类别误判相似。
        """
        best = None
        for e in self._entries:
            if e.get("invalidated_at") and e["invalidated_at"] > 0:
                continue
            if category is not None and e.get("category") != category:
                continue
            existing = e["content"]
            if content == existing:
                return {"kind": "exact", "id": e["id"], "ratio": 1.0}
            ratio = SequenceMatcher(None, content, existing).ratio()
            if ratio >= DEDUPE_RATIO and (best is None or ratio > best["ratio"]):
                best = {"kind": "similar", "id": e["id"], "ratio": ratio}
        return best


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
