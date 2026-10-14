# ruff: noqa: UP006, UP007, UP035 — release/win7 Python 3.8 兼容，保留 typing 注解
"""schema 版本化迁移框架（DSH 对标 R9，C3）。

对标 deepseek-harness 的会话格式"代"纪律：**迁移只新增版本命名的后继，
绝不移动 / 覆写 / 删除已提交代**。

现状：`database.py` 的 schema 演进全靠 `CREATE TABLE IF NOT EXISTS` +
散落的 `ALTER ... IF NOT IN columns` 防御块，没有版本号——无法回答
"这个库跑的是哪一版 schema"，也无法表达"需要数据改写"的迁移（加列
防御块覆盖不了的场景）。本框架提供：

- `schema_version` 表（版本号 → 已应用迁移的账本）；
- `MIGRATIONS`：有序迁移注册表（版本号 → 迁移函数）；
- :func:`run_pending_migrations`：幂等应用所有未执行迁移（已应用版本
  直接跳过）。`init_db` 末尾调用一次。

SE1 的 `session_events` 表等既有 DDL 保持原位（它们是幂等 DDL，等价于
基线 schema 的一部分）；本框架服务于**未来**的迁移（需要数据改写、
无法用 IF NOT EXISTS 表达的变更）。

迁移函数约定：
- 签名 ``(conn) -> None``（sqlite3.Connection，调用方控制事务/提交——
  迁移函数内自行 commit，失败自行回滚并抛异常，框架不吞错）；
- 一旦合入，版本号与函数体**只修 bug 不改语义**（对齐 dsh 纪律）；
- 新迁移追加在 `MIGRATIONS` 末尾，版本号严格递增。
"""

from __future__ import annotations

import logging
from typing import Any, Callable, List, Tuple

logger = logging.getLogger(__name__)

#: 迁移注册表：(版本号, 名称, 迁移函数)。**只追加，不改历史条目。**
MIGRATIONS: List[Tuple[int, str, Callable[[Any], None]]] = []


def register_migration(version: int, name: str, fn: Callable[[Any], None]) -> None:
    """注册一个迁移（供本包内模块与测试使用；版本号必须严格递增）。"""
    if MIGRATIONS and version <= MIGRATIONS[-1][0]:
        raise ValueError(
            f"迁移版本号必须严格递增: {version} <= {MIGRATIONS[-1][0]}"
        )
    MIGRATIONS.append((version, name, fn))


def _v1_schema_baseline(conn: Any) -> None:
    """v1 基线迁移：no-op（当前 DDL 状态由 init_db 幂等 DDL 保证）。"""


register_migration(1, "schema_baseline", _v1_schema_baseline)


def _v2_messages_columns(conn: Any) -> None:
    """v2：messages 表补齐 reasoning_content/step_index/segment_id/subtype 列。

    收编自 init_db 中散落的 ALTER 防御块（C3b v2）。幂等：PRAGMA 检查
    列存在性，已存在则跳过。
    """
    cursor = conn.cursor()
    cursor.execute("PRAGMA table_info(messages)")
    columns = {row["name"] for row in cursor.fetchall()}
    if "reasoning_content" not in columns:
        cursor.execute("ALTER TABLE messages ADD COLUMN reasoning_content TEXT")
        conn.commit()
    if "step_index" not in columns:
        cursor.execute("ALTER TABLE messages ADD COLUMN step_index INTEGER")
        conn.commit()
    if "segment_id" not in columns:
        cursor.execute(
            "ALTER TABLE messages ADD COLUMN segment_id INTEGER DEFAULT 0"
        )
        conn.commit()
    if "subtype" not in columns:
        cursor.execute("ALTER TABLE messages ADD COLUMN subtype TEXT")
        conn.commit()


register_migration(2, "messages_columns", _v2_messages_columns)


def _v3_sessions_columns(conn: Any) -> None:
    """v3：sessions 表补齐 fork_root/forked_at_message_id/run_status/last_error/last_run_at 列。

    收编自 init_db 中散落的 ALTER 防御块（C3b v3）。幂等：PRAGMA 检查
    列存在性，已存在则跳过。
    """
    cursor = conn.cursor()
    cursor.execute("PRAGMA table_info(sessions)")
    columns = {row["name"] for row in cursor.fetchall()}
    if "fork_root" not in columns:
        cursor.execute("ALTER TABLE sessions ADD COLUMN fork_root TEXT")
        conn.commit()
    if "forked_at_message_id" not in columns:
        cursor.execute("ALTER TABLE sessions ADD COLUMN forked_at_message_id TEXT")
        conn.commit()
    if "run_status" not in columns:
        cursor.execute(
            "ALTER TABLE sessions ADD COLUMN run_status TEXT DEFAULT 'idle'"
        )
        conn.commit()
    if "last_error" not in columns:
        cursor.execute("ALTER TABLE sessions ADD COLUMN last_error TEXT")
        conn.commit()
    if "last_run_at" not in columns:
        cursor.execute("ALTER TABLE sessions ADD COLUMN last_run_at INTEGER")
        conn.commit()


register_migration(3, "sessions_columns", _v3_sessions_columns)


def _v4_memories_episodic_columns(conn: Any) -> None:
    """v4：memories_episodic 表补齐 scope/project_key/invalid_at/supersedes_id 列。

    收编自 init_db 中散落的 ALTER 防御块（C3b v4）。幂等：PRAGMA 检查
    列存在性，已存在则跳过。scope 默认 'user'（P1 作用域轴，存量行跨
    项目可见，与旧行为一致）；invalid_at/supersedes_id 为 P3 时间有效区。
    """
    cursor = conn.cursor()
    cursor.execute("PRAGMA table_info(memories_episodic)")
    columns = {row["name"] for row in cursor.fetchall()}
    if "scope" not in columns:
        cursor.execute(
            "ALTER TABLE memories_episodic ADD COLUMN scope TEXT DEFAULT 'user'"
        )
        conn.commit()
    if "project_key" not in columns:
        cursor.execute("ALTER TABLE memories_episodic ADD COLUMN project_key TEXT")
        conn.commit()
    if "invalid_at" not in columns:
        cursor.execute("ALTER TABLE memories_episodic ADD COLUMN invalid_at INTEGER")
        conn.commit()
    if "supersedes_id" not in columns:
        cursor.execute(
            "ALTER TABLE memories_episodic ADD COLUMN supersedes_id TEXT"
        )
        conn.commit()


register_migration(4, "memories_episodic_columns", _v4_memories_episodic_columns)


def _v5_artifacts_office_columns(conn: Any) -> None:
    """v5：artifacts 表补齐 workspace_path 与 format_spec 列（F1 产物直通交付抽屉）。"""
    cursor = conn.cursor()
    cursor.execute("PRAGMA table_info(artifacts)")
    columns = {row["name"] for row in cursor.fetchall()}
    if "workspace_path" not in columns:
        cursor.execute("ALTER TABLE artifacts ADD COLUMN workspace_path TEXT")
        conn.commit()
    if "format_spec" not in columns:
        cursor.execute("ALTER TABLE artifacts ADD COLUMN format_spec TEXT")
        conn.commit()


register_migration(5, "artifacts_office_columns", _v5_artifacts_office_columns)


def _v6_project_milestones_hierarchy(conn: Any) -> None:
    """v6：project_milestones 表新增 parent_id / estimated_days 列。

    支撑 AI 任务分解（M1）：里程碑可嵌套为树形结构，子里程碑指向父节点；
    estimated_days 记录 AI 估算工时，供项目进度顾问（M3）使用。
    幂等：PRAGMA 检查列存在性，已存在则跳过。
    """
    cursor = conn.cursor()
    cursor.execute("PRAGMA table_info(project_milestones)")
    columns = {row["name"] for row in cursor.fetchall()}
    if "parent_id" not in columns:
        cursor.execute(
            "ALTER TABLE project_milestones ADD COLUMN parent_id TEXT"
        )
        conn.commit()
    if "estimated_days" not in columns:
        cursor.execute(
            "ALTER TABLE project_milestones ADD COLUMN estimated_days REAL"
        )
        conn.commit()
    # parent_id 索引（get_tree 查询子节点用）
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_milestones_parent"
        " ON project_milestones(parent_id)"
    )
    conn.commit()


register_migration(6, "project_milestones_hierarchy", _v6_project_milestones_hierarchy)


def _v7_material_semantic_index_marker(conn: Any) -> None:
    """v7：M4 语义索引管线激活标记。

    向量表 ``project_materials_vec_{dims}`` 由 ProjectMaterialIndexer
    在首次索引时按需创建（sqlite-vec virtual table），不在此处硬编码。
    此迁移仅标记 schema 版本已升级到 M4，同时删除 P0 backfill 的残留
    （P0 backfill 此前在 database.py init_db 中把 pending_index 全量回填
    为 ready，M4 接入后不再需要）。
    """
    # No-op: 向量表由 indexer 动态创建
    # P0 backfill 删除在 database.py 中同步执行


register_migration(7, "material_semantic_index", _v7_material_semantic_index_marker)


def _v8_add_design_tables(conn: Any) -> None:
    """v8：创建设计工作室的 design_projects 与 design_artifacts 表。

    design_projects 存储设计项目元数据（名称、类型、系统/模板 ID、简报、
    状态机）；design_artifacts 存储每个项目产出的产物（版本化文件路径、
    导出格式、来源 prompt）。外键 CASCADE 删除，索引覆盖常用查询路径。
    """
    conn.execute("""
        CREATE TABLE IF NOT EXISTS design_projects (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            kind TEXT NOT NULL CHECK(kind IN ('prototype', 'deck')),
            system_id TEXT NOT NULL,
            template_id TEXT NOT NULL,
            brief TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'draft'
                CHECK(status IN ('draft', 'generating', 'complete', 'error')),
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS design_artifacts (
            id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL
                REFERENCES design_projects(id) ON DELETE CASCADE,
            version INTEGER NOT NULL,
            file_path TEXT NOT NULL,
            kind TEXT NOT NULL
                CHECK(kind IN ('html', 'deck', 'standalone')),
            title TEXT NOT NULL,
            export_formats TEXT NOT NULL DEFAULT '[]',
            source_prompt TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            UNIQUE(project_id, version)
        )
    """)
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_design_artifacts_project "
        "ON design_artifacts(project_id)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_design_projects_status "
        "ON design_projects(status)"
    )


register_migration(8, "add_design_tables", _v8_add_design_tables)


def ensure_version_table(conn: Any) -> None:
    """建 `schema_version` 账本表（幂等）。"""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_version (
            version INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            applied_at INTEGER NOT NULL
        )
        """
    )
    conn.commit()


def applied_versions(conn: Any) -> set:
    """已应用的版本号集合。"""
    cursor = conn.execute("SELECT version FROM schema_version")
    return {int(row[0]) for row in cursor.fetchall()}


def run_pending_migrations(conn: Any) -> List[int]:
    """按序应用所有未执行迁移，返回本次实际应用的版本号列表（升序）。

    单个迁移失败：异常向上抛（由调用方决定降级——init_db 语境下
    fail-fast 比带病启动安全，与"绝不覆写已提交代"的纪律配套：
    半应用的迁移留下 schema_version 缺口即可定位）。
    """
    import time

    ensure_version_table(conn)
    done = applied_versions(conn)
    applied_now: List[int] = []
    for version, name, fn in MIGRATIONS:
        if version in done:
            continue
        logger.info("应用 schema 迁移 v%s: %s", version, name)
        fn(conn)
        conn.execute(
            "INSERT INTO schema_version (version, name, applied_at) VALUES (?, ?, ?)",
            (version, name, int(time.time())),
        )
        conn.commit()
        applied_now.append(version)
    if applied_now:
        logger.info("schema 迁移完成: %s", applied_now)
    return applied_now


__all__ = [
    "MIGRATIONS",
    "applied_versions",
    "ensure_version_table",
    "register_migration",
    "run_pending_migrations",
]
