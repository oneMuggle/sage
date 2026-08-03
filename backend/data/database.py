"""
数据库连接和初始化
SQLite 实现
"""

from __future__ import annotations

import logging
import os
import sqlite3
import threading
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Module-level SQLite 写锁(PR B §1.2 fix):被所有同步 SQLite 写共享,
# 包括 PR A 的 legacy_routes.py handler(用 @with_db_lock 装饰器)和
# PR B 的 SqliteStorageAdapter._sync_X(在 asyncio.to_thread worker 内执行)。
# 必须用 threading.Lock 而不是 asyncio.Lock,因为 _sync_X 跑在线程池 worker
# 上,与 PR A 的 sync def handler 共享同一线程上下文;asyncio.Lock 只能保护
# event loop 上的协程,看不到 worker 线程。
_SQLITE_LOCK = threading.Lock()

def _migrate_memory_traceability(db: sqlite3.Connection) -> None:
    """Add source_turn_id / source_message_id / memory_category columns and
    supporting indexes to ``memories_episodic``.

    Idempotent — safe to call on every startup. Used by :meth:`Database.init_db`
    after the base schema is created so legacy DBs (pre-Task 4) pick up the
    new columns without a separate migration tool.
    """
    cur = db.execute("PRAGMA table_info(memories_episodic)")
    existing_cols = {row[1] for row in cur.fetchall()}

    new_cols = {
        "source_turn_id": "TEXT",
        "source_message_id": "TEXT",
        "memory_category": "TEXT",
    }
    for col, typedef in new_cols.items():
        if col not in existing_cols:
            db.execute(f"ALTER TABLE memories_episodic ADD COLUMN {col} {typedef}")
            logger.info("migration: added memories_episodic.%s", col)

    db.execute(
        "CREATE INDEX IF NOT EXISTS idx_mem_episodic_session_turn "
        "ON memories_episodic(session_id, source_turn_id)"
    )
    db.execute(
        "CREATE INDEX IF NOT EXISTS idx_mem_episodic_category "
        "ON memories_episodic(memory_category)"
    )
    db.commit()


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

        # Task 4 / Gap A — idempotent migration: add source_turn_id /
        # source_message_id / memory_category columns + indexes for memory
        # traceability (which turn/message a fact came from; which category).
        # Safe to call on every startup — see _migrate_memory_traceability.
        _migrate_memory_traceability(conn)

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

        # FTS5 虚拟表用于语义记忆全文搜索
        cursor.execute("""
            CREATE VIRTUAL TABLE IF NOT EXISTS memories_semantic_fts USING fts5(
                content, summary, tags,
                content='memories_semantic',
                content_rowid='rowid'
            )
        """)

        # FTS5 同步触发器
        # 注意：由于 contentless FTS5 表在 UPDATE 时可能出现 "database disk image is malformed"
        # 错误，暂时禁用所有触发器。FTS 索引由 SemanticMemory 方法手动维护。
        # 当前 search() 使用 LIKE + jieba 而非 FTS5，所以 FTS 索引暂不使用。
        # 未来升级 FTS5 中文支持时再启用。

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
        # NOTE (win7 sync): main 的 idx_review_events_status / idx_skill_drafts_status
        # 指向 review_events / skill_drafts 表,win7 无此二表,已删除以避免
        # sqlite3.OperationalError: no such table 导致 DB 初始化崩溃。
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
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS orch_tasks (
                task_id TEXT PRIMARY KEY,
                run_id TEXT NOT NULL REFERENCES orch_runs(run_id),
                agent_id TEXT NOT NULL,
                goal TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'queued',
                retry_count INTEGER NOT NULL DEFAULT 0,
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
