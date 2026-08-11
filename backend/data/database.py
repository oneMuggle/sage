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
from typing import Optional, Tuple

logger = logging.getLogger(__name__)

# Module-level SQLite 写锁(PR B §1.2 fix):被所有同步 SQLite 写共享,
# 包括 PR A 的 legacy_routes.py handler(用 @with_db_lock 装饰器)和
# PR B 的 SqliteStorageAdapter._sync_X(在 asyncio.to_thread worker 内执行)。
# 必须用 threading.Lock 而不是 asyncio.Lock,因为 _sync_X 跑在线程池 worker
# 上,与 PR A 的 sync def handler 共享同一线程上下文;asyncio.Lock 只能保护
# event loop 上的协程,看不到 worker 线程。
_SQLITE_LOCK = threading.Lock()

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

    def get_connection(self) -> sqlite3.Connection:
        """获取数据库连接"""
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
        return self._connection

    def close(self):
        """关闭数据库连接"""
        if self._connection:
            self._connection.close()
            self._connection = None

    def init_db(self):
        """初始化数据库表结构"""
        conn = self.get_connection()
        cursor = conn.cursor()

        # 会话表
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

        # 数据库迁移 (M4 会话分叉)：为已有数据库的 sessions 表添加
        # fork_root / forked_at_message_id 列（如果不存在）。两列均可空，
        # 存量行保持合法；新库走同一 ALTER 分支补齐。
        cursor.execute("PRAGMA table_info(sessions)")
        session_columns = [row["name"] for row in cursor.fetchall()]
        if "fork_root" not in session_columns:
            cursor.execute("ALTER TABLE sessions ADD COLUMN fork_root TEXT")
        if "forked_at_message_id" not in session_columns:
            cursor.execute("ALTER TABLE sessions ADD COLUMN forked_at_message_id TEXT")
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

        # 技能表
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS skills (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL UNIQUE,
                version TEXT NOT NULL DEFAULT '1.0.0',
                description TEXT,
                triggers TEXT,
                code TEXT NOT NULL,
                author TEXT,
                homepage TEXT,
                icon TEXT,
                permissions TEXT,
                is_enabled INTEGER DEFAULT 1,
                is_builtin INTEGER DEFAULT 0,
                usage_count INTEGER DEFAULT 0,
                success_count INTEGER DEFAULT 0,
                last_used_at INTEGER,
                created_at INTEGER NOT NULL,
                updated_at INTEGER
            )
        """)

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
                archived_at INTEGER
            )
        """)

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

        # review_events: 审查事件队列表
        # ReviewQueue 入队/出队的持久化载体。与 ReviewQueue._initialize_db
        # 中的 schema 保持一致 (CREATE TABLE IF NOT EXISTS 幂等)。
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

        # skill_drafts: 技能草稿表
        # Background Review 在会话结束提炼出的候选技能, 等待用户审阅后
        # 决定是否晋升为正式技能 (写入 skills 表)。
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
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_skills_enabled ON skills(is_enabled)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_skills_name ON skills(name)")
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_preferences_category ON preferences(category)"
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_semantic_created ON memories_semantic(created_at DESC)"
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_evolution_memory ON memories_evolution_log(memory_id)"
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
