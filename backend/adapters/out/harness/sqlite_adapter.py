"""Harness 组件注册表 SQLite adapter。

把 ``harness_components`` 表包装为 ``HarnessPort`` 协议实现。

设计要点
--------

- **DB 访问卸载到线程池**：全部公开方法为 async，内部经
  ``to_thread`` 调 ``_sync_X``，避免 SQLite 读写阻塞事件循环
  （与 ``SqliteStorageAdapter`` 一致）。
- **共享连接 + 模块级锁**：复用 ``Database.get_connection()`` 返回的
  加锁代理连接，与既有 repo 路径同锁，避免并发写事务冲突。
- **时间格式转换**：DB 内为 epoch 毫秒 INTEGER（与既有表一致），
  对外暴露为 ISO-8601 字符串（domain 层约定）。
- **config 序列化**：DB 内为 JSON TEXT，对外为 dict。
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any, Dict, List, Optional

from backend.data.database import _SQLITE_LOCK, get_database
from backend.domain.harness_component import (
    EffectivenessMetrics,
    HarnessComponent,
)
from backend.utils.py_compat import to_thread

logger = logging.getLogger(__name__)

# 8 类 harness 组件（对齐 Google Harness 2）
HARNESS_COMPONENT_TYPES = (
    "system_prompt",
    "guardrails",
    "memory",
    "tool_guidance",
    "subagents",
    "skills",
    "scripts",
    "plugins",
)


def _now_ms() -> int:
    """当前时间（epoch 毫秒）。"""
    return int(time.time() * 1000)


def _ms_to_iso(ms: Optional[int]) -> Optional[str]:
    """epoch 毫秒 → ISO-8601 字符串（秒级精度）。"""
    if ms is None:
        return None
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(ms / 1000))


def _row_to_component(row: Any) -> HarnessComponent:
    """DB 行 → ``HarnessComponent``。"""
    try:
        config = json.loads(row["config_json"] or "{}")
    except (ValueError, TypeError):
        config = {}
    if not isinstance(config, dict):
        config = {}

    metrics = EffectivenessMetrics.from_usage_data(
        usage_count=row["usage_count"],
        success_count=row["success_count"],
        total_latency_ms=row["total_latency_ms"],
        user_satisfaction_sum=row["user_satisfaction_sum"],
        user_satisfaction_count=row["user_satisfaction_count"],
        last_used_at=_ms_to_iso(row["last_used_at"]),
    )

    return HarnessComponent(
        id=row["id"],
        type=row["type"],
        name=row["name"],
        version=row["version"],
        config=config,
        effectiveness=metrics,
        created_at=_ms_to_iso(row["created_at"]),
        updated_at=_ms_to_iso(row["updated_at"]),
    )


class SqliteHarnessAdapter:
    """``HarnessPort`` 的 SQLite 实现。"""

    def __init__(self, db: Optional[Any] = None) -> None:
        """初始化 adapter。

        Args:
            db: ``Database`` 实例；缺省时懒加载全局单例（测试可注入临时库）。
        """
        self._db = db

    @property
    def db(self) -> Any:
        """惰性获取 Database 实例（不缓存：测试 teardown 换 DB 后须能拿到新的）。

        构造时显式注入的 ``_db``（测试 fixture）优先返回；否则每次重新解析
        ``get_database()``，避免缓存旧 DB 实例导致 close 后仍写入 use-after-free。
        """
        if self._db is not None:
            return self._db
        return get_database()

    # ------------------------------------------------------------------
    # 公开 async 接口
    # ------------------------------------------------------------------

    async def list_components(
        self,
        component_type: Optional[str] = None,
    ) -> List[HarnessComponent]:
        """列出已注册的 harness 组件。"""
        return await to_thread(self._sync_list_components, component_type)

    async def get_component(self, component_id: str) -> Optional[HarnessComponent]:
        """按 ID 获取单个组件。"""
        return await to_thread(self._sync_get_component, component_id)

    async def register_component(
        self,
        component_id: str,
        component_type: str,
        name: str,
        config: Optional[Dict[str, Any]] = None,
    ) -> HarnessComponent:
        """注册新组件（幂等：已存在则更新配置与名称）。"""
        return await to_thread(
            self._sync_register_component,
            component_id,
            component_type,
            name,
            config or {},
        )

    async def update_component(
        self,
        component_id: str,
        config: Dict[str, Any],
    ) -> Optional[HarnessComponent]:
        """热更新组件配置（整体替换 config_json）。"""
        return await to_thread(self._sync_update_component, component_id, config)

    async def record_usage(
        self,
        component_id: str,
        success: bool,
        latency_ms: float,
    ) -> None:
        """记录一次组件使用，累积 effectiveness 指标。

        组件不存在时静默忽略（埋点不应影响主路径）。
        """
        await to_thread(self._sync_record_usage, component_id, success, latency_ms)

    # ------------------------------------------------------------------
    # 同步实现（跑在线程池）
    # ------------------------------------------------------------------

    def _sync_list_components(
        self,
        component_type: Optional[str],
    ) -> List[HarnessComponent]:
        with _SQLITE_LOCK:
            conn = self.db.get_connection()
            cursor = conn.cursor()
            try:
                if component_type:
                    cursor.execute(
                        "SELECT * FROM harness_components WHERE type = ? ORDER BY id",
                        (component_type,),
                    )
                else:
                    cursor.execute("SELECT * FROM harness_components ORDER BY id")
                rows = cursor.fetchall()
            finally:
                cursor.close()
        return [_row_to_component(row) for row in rows]

    def _sync_get_component(self, component_id: str) -> Optional[HarnessComponent]:
        with _SQLITE_LOCK:
            conn = self.db.get_connection()
            cursor = conn.cursor()
            try:
                cursor.execute(
                    "SELECT * FROM harness_components WHERE id = ?",
                    (component_id,),
                )
                row = cursor.fetchone()
            finally:
                cursor.close()
        return _row_to_component(row) if row else None

    def _sync_register_component(
        self,
        component_id: str,
        component_type: str,
        name: str,
        config: Dict[str, Any],
    ) -> HarnessComponent:
        now = _now_ms()
        config_json = json.dumps(config, ensure_ascii=False)
        with _SQLITE_LOCK:
            conn = self.db.get_connection()
            cursor = conn.cursor()
            try:
                cursor.execute(
                    """
                    INSERT INTO harness_components (
                        id, type, name, version, config_json,
                        usage_count, success_count, total_latency_ms,
                        user_satisfaction_sum, user_satisfaction_count,
                        last_used_at, created_at, updated_at
                    ) VALUES (?, ?, ?, '1.0.0', ?, 0, 0, 0.0, 0.0, 0, NULL, ?, ?)
                    ON CONFLICT(id) DO UPDATE SET
                        name = excluded.name,
                        config_json = excluded.config_json,
                        updated_at = excluded.updated_at
                    """,
                    (component_id, component_type, name, config_json, now, now),
                )
            finally:
                cursor.close()
            conn.commit()

        component = self._sync_get_component(component_id)
        if component is None:  # pragma: no cover — 刚写入理论上不可达
            raise RuntimeError(f"组件注册后读取失败: {component_id}")
        return component

    def _sync_update_component(
        self,
        component_id: str,
        config: Dict[str, Any],
    ) -> Optional[HarnessComponent]:
        with _SQLITE_LOCK:
            conn = self.db.get_connection()
            cursor = conn.cursor()
            try:
                cursor.execute(
                    "UPDATE harness_components SET config_json = ?, updated_at = ? "
                    "WHERE id = ?",
                    (json.dumps(config, ensure_ascii=False), _now_ms(), component_id),
                )
                changed = cursor.rowcount
            finally:
                cursor.close()
            if not changed:
                return None
            conn.commit()
        return self._sync_get_component(component_id)

    def _sync_record_usage(
        self,
        component_id: str,
        success: bool,
        latency_ms: float,
    ) -> None:
        with _SQLITE_LOCK:
            conn = self.db.get_connection()
            cursor = conn.cursor()
            try:
                cursor.execute(
                    """
                    UPDATE harness_components SET
                        usage_count = usage_count + 1,
                        success_count = success_count + ?,
                        total_latency_ms = total_latency_ms + ?,
                        last_used_at = ?,
                        updated_at = ?
                    WHERE id = ?
                    """,
                    (
                        1 if success else 0,
                        float(latency_ms),
                        _now_ms(),
                        _now_ms(),
                        component_id,
                    ),
                )
            finally:
                cursor.close()
            conn.commit()
