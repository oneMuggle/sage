"""
数据库连接和初始化
SQLite 实现
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import threading
from pathlib import Path
from typing import Any, Optional, Tuple

logger = logging.getLogger(__name__)

# Module-level SQLite 访问锁(PR B §1.2 fix / B2 下沉):被所有同步 SQLite
# 访问共享 —— @with_db_lock 装饰的 handler、SqliteStorageAdapter._sync_X,
# 以及 Database.get_connection() 返回的代理连接 (B2: 此前 Session/Message/
# memory 仓库等方法直接用共享单连接不加锁, 被工具 executor 线程 /
# asyncio.to_thread / APScheduler 线程并发调用, 存在游标交错与事务互踩风险)。
# 必须用 RLock: with _SQLITE_LOCK 块内调用仓库方法时代理会再次加锁,
# 同线程可重入; threading.Lock 在该场景下会自死锁。
# 必须用线程锁而不是 asyncio.Lock,因为 _sync_X 跑在线程池 worker
# 上,与 sync def handler 共享同一线程上下文;asyncio.Lock 只能保护
# event loop 上的协程,看不到 worker 线程。
_SQLITE_LOCK = threading.RLock()


class _LockedCursor:
    """sqlite3.Cursor 代理: 常用方法在 _SQLITE_LOCK 内执行。

    未显式列出的属性/方法经 __getattr__ 透传 (lastrowid / description 等)。
    """

    def __init__(self, cursor: sqlite3.Cursor) -> None:
        self._cursor = cursor

    def execute(self, *args: Any, **kwargs: Any) -> _LockedCursor:
        with _SQLITE_LOCK:
            return _LockedCursor(self._cursor.execute(*args, **kwargs))

    def executemany(self, *args: Any, **kwargs: Any) -> _LockedCursor:
        with _SQLITE_LOCK:
            return _LockedCursor(self._cursor.executemany(*args, **kwargs))

    def fetchone(self) -> Any:
        with _SQLITE_LOCK:
            return self._cursor.fetchone()

    def fetchall(self) -> Any:
        with _SQLITE_LOCK:
            return self._cursor.fetchall()

    def fetchmany(self, size: Optional[int] = None) -> Any:
        with _SQLITE_LOCK:
            if size is None:
                return self._cursor.fetchmany()
            return self._cursor.fetchmany(size)

    def close(self) -> None:
        with _SQLITE_LOCK:
            self._cursor.close()

    def __iter__(self) -> _LockedCursor:
        return self

    def __next__(self) -> Any:
        with _SQLITE_LOCK:
            return next(self._cursor)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._cursor, name)


class _LockedConnection:
    """sqlite3.Connection 代理: 写路径与事务边界在 _SQLITE_LOCK 内执行。

    覆盖 execute / executemany / executescript / commit / rollback / cursor。
    代理缓存于 Database 实例 (get_connection 返回同一对象, 保持身份稳定);
    真实连接仅 Database 内部持有。cursor() 返回 _LockedCursor。
    """

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def cursor(self, *args: Any, **kwargs: Any) -> _LockedCursor:
        with _SQLITE_LOCK:
            return _LockedCursor(self._conn.cursor(*args, **kwargs))

    def execute(self, *args: Any, **kwargs: Any) -> _LockedCursor:
        with _SQLITE_LOCK:
            return _LockedCursor(self._conn.execute(*args, **kwargs))

    def executemany(self, *args: Any, **kwargs: Any) -> _LockedCursor:
        with _SQLITE_LOCK:
            return _LockedCursor(self._conn.executemany(*args, **kwargs))

    def executescript(self, *args: Any, **kwargs: Any) -> Any:
        with _SQLITE_LOCK:
            return self._conn.executescript(*args, **kwargs)

    def commit(self) -> None:
        with _SQLITE_LOCK:
            self._conn.commit()

    def rollback(self) -> None:
        with _SQLITE_LOCK:
            self._conn.rollback()

    def __getattr__(self, name: str) -> Any:
        return getattr(self._conn, name)

# ==================== 语义记忆 FTS5 索引 ====================
# 独立 FTS5 表（非 external-content）+ jieba 分词文本 + Python 侧显式同步。
#
# 历史 "database disk image is malformed" 根因（WS-B 诊断结论）：
# 旧表使用 external-content 模式（content='memories_semantic'），该模式自身不存储
# 内容，要求调用方严格遵守同步协议——删除必须通过 'delete' 命令并提供索引时的原始
# 列值、UPDATE 必须先 'delete' 旧值再 insert 新值。当时的触发器/手动维护使用了
# plain DELETE 且 FTS rowid 与内容表 rowid 漂移，留下悬空索引条目，破坏 shadow
# 表 B 树，后续查询即报 malformed。修复：改用独立（存内容）FTS5 表，plain
# INSERT/UPDATE/DELETE 均合法；写入由 SemanticMemory 单一入口显式同步（无触发器）。

SEMANTIC_FTS_TABLE = "memories_semantic_fts"


def _segment_for_index(text: Optional[str]) -> str:
    """索引侧分词：jieba 搜索引擎模式（cut_for_search），空格连接。

    相比精确模式额外把长词细分出子词（如 "吃火锅" → 同时产出 "火锅"），
    保证短词查询（"火锅"）能命中包含长词的文本；查询侧用精确模式的
    tokenize_for_search 即可，因为长词本身也保留在索引中。
    """
    if not text:
        return ""
    # 延迟导入，避免 backend.data ↔ backend.memory 包级循环依赖
    import jieba

    return " ".join(w.strip() for w in jieba.cut_for_search(text) if w.strip())


def _warm_jieba() -> None:
    """§1.2 修复：模块导入时预热 jieba 词典，避免首次 FTS 写入冷启动 500ms+。

    触发场景：用户首次保存记忆时 `_segment_for_index` 调 `jieba.cut_for_search()`,
    jieba 首次执行需从磁盘加载主词典（~500ms 阻塞）。预热把这次开销从「用户请求路径」
    转移到「后端启动路径」，聊天主链路不被拖累。

    fail-open：jieba 缺失 / 词典损坏 → 跳过预热，不阻塞 import（首次 FTS 写入会
    触发自然加载，多花 500ms 但不影响功能）。
    """
    try:
        import jieba

        list(jieba.cut("__warmup__"))  # 触发主词典加载
        logger.debug("database: jieba pre-warmed at import time")
    except Exception as exc:  # noqa: BLE001
        # jieba 缺失 / import 失败 / 词典损坏 — 不阻塞 backend 启动
        logger.debug("database: jieba warmup skipped (non-fatal): %s", exc)


# 副作用：模块导入即预热 jieba。这是 _segment_for_index 的"前辈路径"，
# 把 ~500ms 冷启动成本从「首次用户请求」前移到「后端启动」窗口。
_warm_jieba()


def fts_row_texts(
    content: Optional[str], summary: Optional[str], tags_json: Optional[str]
) -> Tuple[str, str, str]:
    """生成一行 memories_semantic 写入 FTS 索引表的 jieba 分词文本三元组。

    FTS5 默认 unicode61 分词器不切分中文（整句成为一个 token），因此索引表写入
    分词后的文本而非原文，使中文 MATCH 可用。tags 为 JSON 数组字符串，展开为
    空格连接的标签文本再分词。
    """
    tags_text = ""
    if tags_json:
        try:
            tags = json.loads(tags_json)
            if isinstance(tags, list):
                tags_text = _segment_for_index(" ".join(str(t) for t in tags))
        except (json.JSONDecodeError, TypeError):
            tags_text = ""
    return (_segment_for_index(content), _segment_for_index(summary), tags_text)


def _drop_semantic_fts(cursor: sqlite3.Cursor) -> None:
    """删除 FTS 虚拟表（连带 shadow 表），并清理残留在 memories_semantic 上的旧 FTS 触发器。"""
    cursor.execute(f"DROP TABLE IF EXISTS {SEMANTIC_FTS_TABLE}")
    legacy_triggers = cursor.execute(
        "SELECT name FROM sqlite_master WHERE type = 'trigger' "
        "AND tbl_name = 'memories_semantic' AND lower(name) LIKE '%fts%'"
    ).fetchall()
    for trigger_row in legacy_triggers:
        cursor.execute(f'DROP TRIGGER IF EXISTS "{trigger_row[0]}"')


def ensure_semantic_fts_schema(conn: sqlite3.Connection) -> bool:
    """确保 memories_semantic_fts 为健康的独立 FTS5 虚拟表，返回是否发生了重建。

    处理两类坏状态（幂等，可重复调用）：
    1. 结构不可靠：非虚拟表残留，或旧 external-content 定义（malformed 根因）
       → drop 后重建为独立表；
    2. 数据损坏：轻量完整性探测（count(*)）捕获 sqlite3.DatabaseError
       （含 "malformed" / "corruption found"）→ drop 重建。

    永不抛出：FTS 为非关键路径，任何失败降级为 warning，不阻塞后端启动。
    重建后调用方应以 force=True 触发 backfill_semantic_fts 回填。
    """
    try:
        cursor = conn.cursor()
        rebuilt = False
        row = cursor.execute(
            "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = ?",
            (SEMANTIC_FTS_TABLE,),
        ).fetchone()
        if row is not None:
            schema_sql = (row[0] or "").replace(" ", "").lower()
            if "virtualtable" not in schema_sql or "content=" in schema_sql:
                logger.warning(
                    "memories_semantic_fts 为旧 external-content/残留结构，drop 重建为独立 FTS5 表"
                )
                _drop_semantic_fts(cursor)
                rebuilt = True
            else:
                try:
                    cursor.execute(f"SELECT count(*) FROM {SEMANTIC_FTS_TABLE}")
                    cursor.fetchone()
                except sqlite3.DatabaseError as exc:
                    logger.warning("memories_semantic_fts 损坏（%s），drop 重建", exc)
                    _drop_semantic_fts(cursor)
                    rebuilt = True
        cursor.execute(
            f"CREATE VIRTUAL TABLE IF NOT EXISTS {SEMANTIC_FTS_TABLE} "
            "USING fts5(content, summary, tags)"
        )
        conn.commit()
        return rebuilt
    except sqlite3.DatabaseError as exc:
        logger.warning("语义记忆 FTS 表初始化失败（搜索将降级为 LIKE）: %s", exc)
        return False


def backfill_semantic_fts(conn: sqlite3.Connection, force: bool = False) -> None:
    """幂等回填：把 memories_semantic 现有行同步进 FTS 索引表（jieba 分词）。

    - force=False：仅当两表行数不一致时回填（正常启动快速跳过，避免全量分词）；
    - force=True：整体清空重填（ensure_semantic_fts_schema 重建表后使用）。

    覆盖绕过 SemanticMemory 直接写主表的路径（如 evolution 晋升），下次 init_db
    时被同步进索引。FTS 为非关键路径，失败只记 warning，不影响主表数据与启动。
    """
    try:
        cursor = conn.cursor()
        if not force:
            fts_count = cursor.execute(f"SELECT count(*) FROM {SEMANTIC_FTS_TABLE}").fetchone()[0]
            memory_count = cursor.execute("SELECT count(*) FROM memories_semantic").fetchone()[0]
            if fts_count == memory_count:
                return
        cursor.execute(f"DELETE FROM {SEMANTIC_FTS_TABLE}")
        rows = cursor.execute(
            "SELECT rowid, content, summary, tags FROM memories_semantic"
        ).fetchall()
        for row in rows:
            cursor.execute(
                f"INSERT INTO {SEMANTIC_FTS_TABLE} (rowid, content, summary, tags) "
                "VALUES (?, ?, ?, ?)",
                (row[0],) + fts_row_texts(row[1], row[2], row[3]),
            )
        conn.commit()
    except sqlite3.DatabaseError as exc:
        logger.warning("语义记忆 FTS 回填失败（搜索将降级为 LIKE）: %s", exc)


class Database:
    """SQLite 数据库管理"""

    def __init__(self, db_path: Optional[str] = None):
        if db_path is None:
            env_path = os.environ.get("SAGE_DB_PATH")
            if env_path:
                db_path = env_path
                # SAGE_DB_PATH 由 Electron main process 注入 (packaged 模式下
                # 指向 %APPDATA%/Sage/sage.db)。若该目录尚未被 Electron 创建
                # (首次启动 / 全新安装), sqlite3.connect() 会因父目录不存在而
                # 抛 OperationalError: unable to open database file, 进而导致
                # lifespan 失败 → 后端无法启动 → 前端白屏。防御性创建父目录。
                Path(db_path).parent.mkdir(parents=True, exist_ok=True)
            else:
                # 默认路径：项目根目录下的 data/sage.db
                base_dir = Path(__file__).parent.parent.parent
                data_dir = base_dir / "data"
                data_dir.mkdir(exist_ok=True)
                db_path = str(data_dir / "sage.db")

        self.db_path = db_path
        self._connection: Optional[sqlite3.Connection] = None
        self._conn_proxy: Optional[_LockedConnection] = None

    def get_connection(self) -> sqlite3.Connection:
        """获取数据库连接 (B2: 返回加锁代理, 全部 SQLite 访问共享 _SQLITE_LOCK)"""
        if self._connection is None:
            self._connection = sqlite3.connect(self.db_path, check_same_thread=False)
            self._connection.row_factory = sqlite3.Row
            # 启用 WAL 模式提高并发性能
            self._connection.execute("PRAGMA journal_mode=WAL")
            self._connection.execute("PRAGMA busy_timeout=5000")
            # fix/security-perf-quickwins (2026-08-09): 启用外键约束。否则
            # session_workspace_bindings 等表的 ON DELETE CASCADE 是 silent no-op,
            # 删会话后留下悬挂行 (见 docs/technical/33-office-m1-m2-completion.md §6-2).
            self._connection.execute("PRAGMA foreign_keys=ON")
            # feat/sqlite-fast-pragma: 测试期跳过 fsync (~5x faster setup)。
            # 仅当 SAGE_TEST_FAST_SQLITE=1 时启用 synchronous=OFF。
            # 注意：synchronous=OFF 在断电/OS crash 时可能丢最后几个事务，但
            # Sage 测试用 tempfile，OS crash 后整个文件不存在 → 仅对测试场景安全。
            # 生产 DB（data/sage.db）始终保持 synchronous=FULL（默认值）。
            if os.environ.get("SAGE_TEST_FAST_SQLITE") == "1":
                self._connection.execute("PRAGMA synchronous=OFF")
            self._conn_proxy = _LockedConnection(self._connection)
        assert self._conn_proxy is not None
        return self._conn_proxy

    def close(self):
        """关闭数据库连接"""
        if self._connection:
            self._connection.close()
            self._connection = None
            self._conn_proxy = None

    def init_db(self):
        """初始化数据库表结构"""
        conn = self.get_connection()
        cursor = conn.cursor()

        # 会话表
        # S1 (2026-09-06): run_status/last_error/last_run_at —— 会话级运行态
        # 持久化,侧边栏状态徽章数据源。idle=无运行;running/suspended=活跃流;
        # completed/failed=上一轮流终态(带时间戳与错误摘要)。
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS sessions (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL DEFAULT '新对话',
                created_at INTEGER NOT NULL,
                updated_at INTEGER NOT NULL,
                last_message_at INTEGER,
                message_count INTEGER DEFAULT 0,
                metadata TEXT,
                total_tokens INTEGER DEFAULT 0,
                total_cost REAL DEFAULT 0,
                is_pinned INTEGER DEFAULT 0,
                is_archived INTEGER DEFAULT 0,
                parent_id TEXT,
                run_status TEXT DEFAULT 'idle',
                last_error TEXT,
                last_run_at INTEGER,
                FOREIGN KEY (parent_id) REFERENCES sessions(id)
            )
        """)

        # 消息表
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS messages (
                id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL,
                role TEXT NOT NULL CHECK (role IN ('user', 'assistant', 'system', 'tool')),
                content TEXT NOT NULL,
                model TEXT,
                provider TEXT,
                finish_reason TEXT,
                input_tokens INTEGER,
                output_tokens INTEGER,
                total_tokens INTEGER,
                tool_calls TEXT,
                tool_call_id TEXT,
                reasoning_content TEXT,
                created_at INTEGER NOT NULL,
                latency_ms INTEGER,
                FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE
            )
        """)

        # 数据库迁移：为已有数据库添加 reasoning_content 列（如果不存在）
        cursor.execute("PRAGMA table_info(messages)")
        columns = [row["name"] for row in cursor.fetchall()]
        if "reasoning_content" not in columns:
            cursor.execute("ALTER TABLE messages ADD COLUMN reasoning_content TEXT")
            conn.commit()

        # 会话摘要表（批次三 step 3，spec §4.3）
        # Dedicated table for compressed session summaries; deliberately
        # separate from memories_episodic so a derived summary never gets
        # mistaken for an ordinary fact. status CHECK-constrained at the SQL
        # layer to {pending, ready, failed}; error_message is required when
        # status='failed' so a broken LLM call never masquerades as a fact.
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS session_summaries (
                id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL,
                source_turn_id TEXT,
                created_at_ms INTEGER NOT NULL,
                updated_at_ms INTEGER NOT NULL,
                status TEXT NOT NULL CHECK (status IN ('pending', 'ready', 'failed')),
                content TEXT NOT NULL DEFAULT '',
                error_message TEXT,
                FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE
            )
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_session_summaries_session_created
            ON session_summaries(session_id, created_at_ms DESC)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_session_summaries_status
            ON session_summaries(session_id, status)
        """)

        # 数据库迁移 (M4 会话分叉)：为已有数据库的 sessions 表添加
        # fork_root / forked_at_message_id 列（如果不存在）。两列均可空，
        # 存量行保持合法；新库走同一 ALTER 分支补齐。
        cursor.execute("PRAGMA table_info(sessions)")
        session_columns = [row["name"] for row in cursor.fetchall()]
        if "fork_root" not in session_columns:
            cursor.execute("ALTER TABLE sessions ADD COLUMN fork_root TEXT")
        if "forked_at_message_id" not in session_columns:
            cursor.execute("ALTER TABLE sessions ADD COLUMN forked_at_message_id TEXT")
        # S1 (2026-09-06) 迁移: 会话运行态三列。均可空/带默认值,存量行
        # run_status 为 NULL → 仓储层读时兜底 'idle',无需回填。
        if "run_status" not in session_columns:
            cursor.execute("ALTER TABLE sessions ADD COLUMN run_status TEXT DEFAULT 'idle'")
        if "last_error" not in session_columns:
            cursor.execute("ALTER TABLE sessions ADD COLUMN last_error TEXT")
        if "last_run_at" not in session_columns:
            cursor.execute("ALTER TABLE sessions ADD COLUMN last_run_at INTEGER")
        conn.commit()

        # 情景记忆表
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS memories_episodic (
                id TEXT PRIMARY KEY,
                session_id TEXT,
                content TEXT NOT NULL,
                summary TEXT,
                memory_type TEXT DEFAULT 'conversation',
                importance INTEGER DEFAULT 5 CHECK (importance BETWEEN 1 AND 10),
                source TEXT DEFAULT 'auto',
                tags TEXT,
                created_at INTEGER NOT NULL,
                accessed_at INTEGER,
                access_count INTEGER DEFAULT 0,
                sentiment TEXT,
                is_valid INTEGER DEFAULT 1,
                expires_at INTEGER,
                FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE SET NULL
            )
        """)

        # 技能定义不再由 SQLite ``skills`` 表承载。
        # 当前实现从 SkillRegistry / SKILL.md 文件加载；故新数据库不得创建
        # 孤儿 ``skills`` 表。已有数据库中的旧表不主动 DROP，以保留用户数据。

        # 技能使用统计表（借鉴 hermes-agent 的 .usage.json 概念）:
        # 按技能名聚合 use_count / success_count / fail_count / last_used_at,
        # 供技能生命周期（curator）与前端使用统计使用。
        # registry（InprocSkillAdapter）是技能来源真相, 本表只记聚合统计。
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS skill_usage (
                name TEXT PRIMARY KEY,
                use_count INTEGER DEFAULT 0,
                success_count INTEGER DEFAULT 0,
                fail_count INTEGER DEFAULT 0,
                last_used_at INTEGER
            )
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_skill_usage_last_used
            ON skill_usage(last_used_at DESC)
        """)

        # 数据库迁移：为已有数据库的 skill_usage 表添加 fail_count 列
        # （Task 1: background-review 2026-08-02）。
        cursor.execute("PRAGMA table_info(skill_usage)")
        skill_usage_columns = [row["name"] for row in cursor.fetchall()]
        if "fail_count" not in skill_usage_columns:
            cursor.execute(
                "ALTER TABLE skill_usage ADD COLUMN fail_count INTEGER DEFAULT 0"
            )

        # 技能生命周期（curator）表：归档软标记（spec 2026-08-02-skill-curator-lifecycle）。
        # 独立于 skill_usage —— 从未使用的技能无 usage 行但同样可归档，需以 name
        # 独立寻址。archived_at 记归档时刻（ms epoch），未归档为 NULL。
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS skill_lifecycle (
                name TEXT PRIMARY KEY,
                archived INTEGER DEFAULT 0,
                archived_at INTEGER,
                enabled INTEGER DEFAULT 1,
                enabled_at INTEGER
            )
        """)

        # 数据库迁移：为已有数据库的 skill_lifecycle 表补齐技能开关列。
        # enabled 默认 1，确保历史技能和未登记技能保持启用语义；enabled_at
        # 仅记录显式切换时间，存量行保持 NULL。
        cursor.execute("PRAGMA table_info(skill_lifecycle)")
        skill_lifecycle_columns = [row["name"] for row in cursor.fetchall()]
        if "enabled" not in skill_lifecycle_columns:
            cursor.execute(
                "ALTER TABLE skill_lifecycle ADD COLUMN enabled INTEGER DEFAULT 1"
            )
        if "enabled_at" not in skill_lifecycle_columns:
            cursor.execute(
                "ALTER TABLE skill_lifecycle ADD COLUMN enabled_at INTEGER"
            )
        conn.commit()

        # 用户偏好表
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS preferences (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                value_type TEXT DEFAULT 'string',
                description TEXT,
                category TEXT DEFAULT 'general',
                created_at INTEGER NOT NULL,
                updated_at INTEGER
            )
        """)

        # 用户画像表 (USER.md 概念, 借鉴 hermes-agent):
        # 持久化"关于用户的知识"（偏好 / 沟通风格 / 工作习惯 / 身份）,
        # 与通用记忆分离, 以冻结快照方式始终注入 system prompt。
        # category 取值: preference / communication_style / workflow_habit / identity
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS user_profile (
                id TEXT PRIMARY KEY,
                content TEXT NOT NULL,
                category TEXT NOT NULL DEFAULT 'preference',
                importance INTEGER DEFAULT 5 CHECK (importance BETWEEN 1 AND 10),
                created_at INTEGER NOT NULL,
                updated_at INTEGER
            )
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_user_profile_category
            ON user_profile(category)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_user_profile_importance
            ON user_profile(importance DESC)
        """)

        # Office 文档表 (Phase 1, plan §4.1.2 step 10)
        # Stores metadata for .pptx/.docx/.xlsx documents in user workspaces.
        # Actual files live in <workspace>/office/<doc_type>/<id>/ on disk.
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS office_documents (
                id TEXT PRIMARY KEY,
                workspace_path TEXT NOT NULL,
                doc_type TEXT NOT NULL,
                original_filename TEXT,
                generated_filename TEXT NOT NULL,
                status TEXT NOT NULL,
                created_at INTEGER NOT NULL,
                updated_at INTEGER NOT NULL,
                metadata TEXT
            )
        """)
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_office_docs_workspace "
            "ON office_documents(workspace_path)"
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_office_docs_created "
            "ON office_documents(created_at DESC)"
        )

        # M0 Task 3: idempotent migration — add derived_from / archived_at
        # columns for legacy DBs that pre-date the Chat-native Office plan.
        # ``derived_from`` records the source document id for edited/copied
        # docs; ``archived_at`` (ms epoch) hides soft-deleted rows from
        # list_documents(include_archived=False). Both nullable so existing
        # rows remain valid.
        cursor.execute("PRAGMA table_info(office_documents)")
        _office_columns = {row["name"] for row in cursor.fetchall()}
        if "derived_from" not in _office_columns:
            cursor.execute("ALTER TABLE office_documents ADD COLUMN derived_from TEXT")
        if "archived_at" not in _office_columns:
            cursor.execute("ALTER TABLE office_documents ADD COLUMN archived_at INTEGER")
        # Persist the migration immediately so a crash between this point
        # and the final commit at the end of init_db doesn't leave the
        # schema half-migrated for the next process.
        conn.commit()

        # Session-workspace binding table (M1, plan §4.1.2 step 11).
        # Maps a chat session id to the active workspace directory. A
        # session has AT MOST ONE active (revoked_at IS NULL) binding; the
        # ``generation`` column is bumped on every rebind so concurrent
        # callers can detect stale references. ``revoked_at`` is set when
        # the binding is explicitly torn down (workspace change, session
        # deletion, etc.) and the row is left as a tombstone for audit.
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS session_workspace_bindings (
                session_id TEXT PRIMARY KEY,
                workspace_path TEXT NOT NULL,
                generation INTEGER NOT NULL DEFAULT 1,
                activated_at INTEGER NOT NULL,
                revoked_at INTEGER NULL,
                FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE
            )
        """)
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_session_workspace_active "
            "ON session_workspace_bindings(session_id, revoked_at)"
        )
        conn.commit()

        # 进化日志表
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS evolution_log (
                id TEXT PRIMARY KEY,
                evolution_type TEXT NOT NULL,
                description TEXT NOT NULL,
                before_state TEXT,
                after_state TEXT,
                trigger_type TEXT,
                trigger_condition TEXT,
                status TEXT DEFAULT 'pending',
                error_message TEXT,
                tokens_used INTEGER,
                created_at INTEGER NOT NULL,
                completed_at INTEGER
            )
        """)

        # 工具使用记录表
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS tool_usage (
                id TEXT PRIMARY KEY,
                session_id TEXT,
                message_id TEXT,
                tool_name TEXT NOT NULL,
                tool_args TEXT,
                tool_result TEXT,
                status TEXT DEFAULT 'success',
                error_message TEXT,
                duration_ms INTEGER,
                created_at INTEGER NOT NULL,
                FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE SET NULL,
                FOREIGN KEY (message_id) REFERENCES messages(id) ON DELETE SET NULL
            )
        """)

        # 产物表:追踪 AI 工具调用(write_file)生成的文件
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS artifacts (
                id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL,
                tool_call_id TEXT,
                path TEXT NOT NULL,
                name TEXT NOT NULL,
                kind TEXT NOT NULL,
                size INTEGER DEFAULT 0,
                created_at INTEGER NOT NULL
            )
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_artifacts_session
            ON artifacts(session_id, created_at DESC)
        """)

        # L8 用量事件表 (对标增强第二轮批次 C): 每次成功 LLM 调用一行,
        # 支撑会话级用量/成本显示 (U14) 与花费限额 (F5)。内存 tracker
        # (usage_tracker) 重启即失, 此表为持久事实源。
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS usage_events (
                id TEXT PRIMARY KEY,
                session_id TEXT,
                model TEXT NOT NULL,
                prompt_tokens INTEGER NOT NULL,
                completion_tokens INTEGER NOT NULL,
                total_tokens INTEGER NOT NULL,
                estimated_cost_usd REAL,
                created_at INTEGER NOT NULL,
                cached_tokens INTEGER NOT NULL DEFAULT 0
            )
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_usage_events_session
            ON usage_events(session_id, created_at DESC)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_usage_events_created
            ON usage_events(created_at DESC)
        """)
        # L4 缓存感知记账: 为已有库补 cached_tokens 列（新装库建表已含）
        cursor.execute("PRAGMA table_info(usage_events)")
        _usage_cols = [row["name"] for row in cursor.fetchall()]
        if "cached_tokens" not in _usage_cols:
            cursor.execute(
                "ALTER TABLE usage_events ADD COLUMN cached_tokens INTEGER NOT NULL DEFAULT 0"
            )
            conn.commit()

        # Agent 配置表 (PR-3)
        # 4 个默认 agent (primary/researcher/coder/memory_manager) 在 lifespan
        # 启动时由 backend/data/agent_repo.py:AgentRepository.seed_defaults_if_empty 种子化
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS agents (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                role TEXT NOT NULL,
                system_prompt TEXT NOT NULL DEFAULT '',
                tools TEXT NOT NULL DEFAULT '[]',
                memory_access TEXT NOT NULL DEFAULT '[]',
                model_config TEXT NOT NULL DEFAULT '{}',
                max_iterations INTEGER NOT NULL DEFAULT 10,
                enabled INTEGER NOT NULL DEFAULT 1,
                description TEXT NOT NULL DEFAULT '',
                updated_at INTEGER NOT NULL
            )
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_agents_role ON agents(role)
        """)

        # 语义记忆表（用于 FTS5 全文搜索）
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS memories_semantic (
                id TEXT PRIMARY KEY,
                content TEXT NOT NULL,
                summary TEXT,
                tags TEXT DEFAULT '[]',
                created_at INTEGER NOT NULL
            )
        """)

        # FTS5 独立虚拟表用于语义记忆全文搜索（jieba 分词文本）。
        # 不再使用 external-content 模式与同步触发器（历史 malformed 根因，详见
        # ensure_semantic_fts_schema docstring）：写入路径由 SemanticMemory 在
        # Python 侧显式同步（单一事实来源），此处负责结构检测 + 完整性自愈。
        fts_rebuilt = ensure_semantic_fts_schema(conn)

        # 记忆进化日志表（预留）
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS memories_evolution_log (
                id TEXT PRIMARY KEY,
                memory_type TEXT NOT NULL,
                memory_id TEXT NOT NULL,
                operation TEXT NOT NULL,
                before_content TEXT,
                after_content TEXT,
                reason TEXT,
                created_at INTEGER NOT NULL
            )
        """)

        # 工作记忆快照表（持久化 WorkingMemory 的 deque 内容）
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS working_memory_snapshot (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                tokens INTEGER NOT NULL DEFAULT 0,
                timestamp REAL NOT NULL,
                created_at INTEGER NOT NULL
            )
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_wm_snapshot_session
            ON working_memory_snapshot(session_id)
        """)

        # ==================== 多智能体协调层表 ====================
        # Phase 1: 任务/Lane/Team/事件 持久化

        # 任务表
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS orchestration_tasks (
                task_id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                description TEXT NOT NULL DEFAULT '',
                task_type TEXT NOT NULL DEFAULT 'general',
                status TEXT NOT NULL DEFAULT 'created',
                priority INTEGER NOT NULL DEFAULT 0,
                executor_type TEXT NOT NULL DEFAULT 'agent',
                parameters TEXT NOT NULL DEFAULT '{}',
                packet TEXT,
                blocks TEXT NOT NULL DEFAULT '[]',
                blocked_by TEXT NOT NULL DEFAULT '[]',
                result TEXT,
                created_at INTEGER NOT NULL,
                started_at INTEGER,
                completed_at INTEGER,
                team_id TEXT
            )
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_orch_tasks_status
            ON orchestration_tasks(status)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_orch_tasks_team
            ON orchestration_tasks(team_id)
        """)

        # Lane 表（执行单元）
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS orchestration_lanes (
                lane_id TEXT PRIMARY KEY,
                task_id TEXT NOT NULL,
                agent_id TEXT,
                status TEXT NOT NULL DEFAULT 'created',
                created_at INTEGER NOT NULL,
                started_at INTEGER,
                completed_at INTEGER,
                worktree TEXT,
                heartbeat TEXT,
                error TEXT,
                permission_preset TEXT NOT NULL DEFAULT 'implement',
                metadata TEXT NOT NULL DEFAULT '{}',
                FOREIGN KEY (task_id) REFERENCES orchestration_tasks(task_id) ON DELETE CASCADE
            )
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_orch_lanes_task
            ON orchestration_lanes(task_id)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_orch_lanes_status
            ON orchestration_lanes(status)
        """)

        # Lane 事件表（生命周期事件流）
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS orchestration_lane_events (
                event_id TEXT PRIMARY KEY,
                event_type TEXT NOT NULL,
                lane_id TEXT NOT NULL,
                task_id TEXT NOT NULL,
                agent_id TEXT,
                timestamp INTEGER NOT NULL,
                provenance TEXT NOT NULL DEFAULT 'LiveLane',
                metadata TEXT NOT NULL DEFAULT '{}',
                FOREIGN KEY (lane_id) REFERENCES orchestration_lanes(lane_id) ON DELETE CASCADE
            )
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_orch_events_lane
            ON orchestration_lane_events(lane_id, timestamp)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_orch_events_task
            ON orchestration_lane_events(task_id)
        """)

        # Team 表（工作流分组）
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS orchestration_teams (
                team_id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                task_ids TEXT NOT NULL DEFAULT '[]',
                status TEXT NOT NULL DEFAULT 'created',
                created_at INTEGER NOT NULL,
                updated_at INTEGER NOT NULL,
                metadata TEXT NOT NULL DEFAULT '{}'
            )
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_orch_teams_status
            ON orchestration_teams(status)
        """)

        # ==================== Background Review 表 ====================
        # Task 4 of 2026-08-02-background-review:
        # review_events 与 skill_drafts 表放在主初始化路径, 确保任何进程启动
        # 时都可用, 无需依赖 ReviewQueue 自己的 _initialize_db。

        # review_events 表：审查事件队列表。
        # ReviewQueue 入队/出队的持久化载体，与其初始化 schema 保持一致。
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS review_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                trigger_type TEXT NOT NULL,
                session_id TEXT NOT NULL,
                context TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                created_at INTEGER NOT NULL,
                processed_at INTEGER,
                error_message TEXT
            )
        """)

        # skill_drafts 表：Background Review 生成的候选技能记录。
        # 草稿经用户审阅后，再决定是否写入 skills 表。
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS skill_drafts (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                description TEXT NOT NULL,
                when_to_use TEXT NOT NULL,
                content TEXT NOT NULL,
                trigger_type TEXT NOT NULL,
                source_session_id TEXT,
                source_context TEXT,
                status TEXT NOT NULL DEFAULT 'pending',
                created_at INTEGER NOT NULL,
                reviewed_at INTEGER,
                reviewed_by_user_id TEXT
            )
        """)

        # 创建索引
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_sessions_updated ON sessions(updated_at DESC)"
        )
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_sessions_pinned ON sessions(is_pinned)")
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id, created_at)"
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_episodic_importance ON memories_episodic(importance DESC)"
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_episodic_created ON memories_episodic(created_at DESC)"
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_episodic_session ON memories_episodic(session_id)"
        )
        # fix/security-perf-quickwins (2026-08-09): 补 4 个查询/清理热路径索引,
        # 见 docs/plans/2026-08-09_feature-optimization-proposal.md §1.3a c.
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_episodic_expires ON memories_episodic(expires_at)"
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_tool_usage_session ON tool_usage(session_id)"
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_review_events_status ON review_events(status)"
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_skill_drafts_status ON skill_drafts(status)"
        )
        # ``skills`` 是历史遗留表；不为新数据库创建，也不为其创建索引。
        # 若用户数据库已有该表，保留原数据，但不再由初始化流程维护其 schema。
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_preferences_category ON preferences(category)"
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_semantic_created ON memories_semantic(created_at DESC)"
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_evolution_memory ON memories_evolution_log(memory_id)"
        )

        # Wave 2 P1-4 (2026-08-14): 编排 run / task 持久化表, 供 resume 端点重建 ChatDispatcher。
        # schema 与 spec §4 verbatim, 幂等 (CREATE TABLE IF NOT EXISTS)。
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS orch_runs (
                run_id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'running',
                created_at INTEGER NOT NULL,
                plan_json TEXT NOT NULL,
                final_summary TEXT,
                dispatched_at INTEGER,
                original_request TEXT
            )
            """
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_orch_runs_session ON orch_runs(session_id)"
        )
        # Wave 3 A9 (2026-08-14): original_request 列 —— resume plan_override 恢复流
        # 用（前端 resumeRun 要拿原始请求逐字重发）。既有库 ALTER 补列，幂等。
        cursor.execute("PRAGMA table_info(orch_runs)")
        _orch_cols = {row[1] for row in cursor.fetchall()}
        if "original_request" not in _orch_cols:
            cursor.execute("ALTER TABLE orch_runs ADD COLUMN original_request TEXT")
        # Phase 3 (2026-09-06): revision 列 —— CAS 并发控制（steer_subagent 用）。
        # orch_runs/orch_tasks 每次状态变更自增，steer 接口以此作为 expected 比对。
        if "revision" not in _orch_cols:
            cursor.execute(
                "ALTER TABLE orch_runs ADD COLUMN revision INTEGER NOT NULL DEFAULT 0"
            )
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS orch_tasks (
                task_id TEXT PRIMARY KEY,
                run_id TEXT NOT NULL REFERENCES orch_runs(run_id),
                agent_id TEXT NOT NULL,
                goal TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'queued',
                retry_count INTEGER NOT NULL DEFAULT 0,
                revision INTEGER NOT NULL DEFAULT 0,
                error TEXT,
                output_preview TEXT,
                blocked_by TEXT,
                scratch_dir TEXT,
                started_at INTEGER,
                finished_at INTEGER
            )
            """
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_orch_tasks_run ON orch_tasks(run_id)"
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_orch_tasks_status ON orch_tasks(status)"
        )
        # Phase 3 (2026-09-06): revision 列回填（已存在的旧库）。幂等。
        cursor.execute("PRAGMA table_info(orch_tasks)")
        _task_cols = {row[1] for row in cursor.fetchall()}
        if "revision" not in _task_cols:
            cursor.execute(
                "ALTER TABLE orch_tasks ADD COLUMN revision INTEGER NOT NULL DEFAULT 0"
            )

        # Subagent 实时可观测性 schema (run-events@1.0)。全部 DDL 幂等，兼容旧库。
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS orch_events (
                event_id TEXT PRIMARY KEY,
                run_id TEXT NOT NULL REFERENCES orch_runs(run_id),
                seq INTEGER NOT NULL,
                event_type TEXT NOT NULL,
                task_id TEXT,
                lane_id TEXT,
                step_id TEXT,
                agent_id TEXT,
                occurred_at INTEGER NOT NULL,
                producer TEXT NOT NULL,
                producer_generation INTEGER NOT NULL DEFAULT 0,
                payload TEXT NOT NULL,
                visibility TEXT NOT NULL DEFAULT 'user',
                command_id TEXT,
                schema_version TEXT NOT NULL DEFAULT 'run-events@1.0',
                UNIQUE(run_id, seq),
                UNIQUE(command_id)
            )
            """
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_orch_events_run_seq ON orch_events(run_id, seq)"
        )
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS orch_steps (
                step_id TEXT PRIMARY KEY,
                run_id TEXT NOT NULL REFERENCES orch_runs(run_id),
                task_id TEXT NOT NULL REFERENCES orch_tasks(task_id),
                sequence INTEGER NOT NULL,
                kind TEXT NOT NULL,
                name TEXT NOT NULL,
                status TEXT NOT NULL,
                input_summary TEXT,
                output_preview TEXT,
                tool_name TEXT,
                error_code TEXT,
                retry_count INTEGER NOT NULL DEFAULT 0,
                started_at INTEGER,
                finished_at INTEGER,
                created_at INTEGER NOT NULL
            )
            """
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_orch_steps_run_seq ON orch_steps(run_id, sequence)"
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_orch_steps_task_seq ON orch_steps(task_id, sequence)"
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_orch_steps_task_status ON orch_steps(task_id, status)"
        )
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS orch_context_messages (
                context_id TEXT PRIMARY KEY,
                run_id TEXT NOT NULL REFERENCES orch_runs(run_id),
                task_id TEXT NOT NULL REFERENCES orch_tasks(task_id),
                source TEXT NOT NULL CHECK (source IN ('user', 'parent_agent', 'system')),
                message_type TEXT NOT NULL CHECK (message_type IN ('constraint', 'clarification', 'additional_context', 'correction', 'priority_update', 'reference')),
                content_redacted TEXT NOT NULL,
                apply_mode TEXT NOT NULL DEFAULT 'next_boundary' CHECK (apply_mode IN ('next_boundary', 'new_followup')),
                expected_task_revision INTEGER,
                created_at INTEGER NOT NULL,
                created_by TEXT,
                applied_at INTEGER,
                applied_step_id TEXT,
                status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'delivered', 'acknowledged', 'rejected'))
            )
            """
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_orch_context_task_status "
            "ON orch_context_messages(task_id, status)"
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_orch_context_run "
            "ON orch_context_messages(run_id)"
        )
        # Phase 3 (2026-09-06): message_type / apply_mode / expected_task_revision
        # 列回填（旧库）。幂等。
        cursor.execute("PRAGMA table_info(orch_context_messages)")
        _ctx_cols = {row[1] for row in cursor.fetchall()}
        if "message_type" not in _ctx_cols:
            cursor.execute(
                "ALTER TABLE orch_context_messages "
                "ADD COLUMN message_type TEXT NOT NULL DEFAULT 'additional_context'"
            )
        if "apply_mode" not in _ctx_cols:
            cursor.execute(
                "ALTER TABLE orch_context_messages "
                "ADD COLUMN apply_mode TEXT NOT NULL DEFAULT 'next_boundary'"
            )
        if "expected_task_revision" not in _ctx_cols:
            cursor.execute(
                "ALTER TABLE orch_context_messages "
                "ADD COLUMN expected_task_revision INTEGER"
            )

        # FTS 幂等回填：把 memories_semantic 现有行同步进索引（含绕过 SemanticMemory
        # 直接写主表的行，如 evolution 晋升；重建后 force 全量重填，否则行数一致即跳过）
        backfill_semantic_fts(conn, force=fts_rebuilt)

        conn.commit()
        print(f"数据库初始化完成: {self.db_path}")  # noqa: T201 (历史遗留, init 阶段一次性输出)


# 全局数据库实例
_db: Optional[Database] = None


def get_database() -> Database:
    """获取全局数据库实例"""
    global _db
    if _db is None:
        _db = Database()
    return _db
