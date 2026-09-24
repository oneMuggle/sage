# ruff: noqa: UP006, UP007, UP035, UP045 — release/win7 Python 3.8 兼容，保留 typing 注解
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
