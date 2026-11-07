"""M1.1 自透明聚合服务 —— 一次返回 8 维运行时状态。

本模块把 ``sage_self_status`` 工具（以及 M1.2 ``read_sage_config`` 新增的
``self`` section）的取数逻辑集中在一处，避免工具层直接散落对多个服务
单例的 import。设计目标：

- **纯函数式聚合**：``gather_self_status() -> dict`` 不依赖 ToolResult /
  ToolExecutionContext 等工具框架类型；REST 路由 / 测试 / 未来 SSE 推送
  都可以复用同一份数据。
- **fail-open 但 fail 可见**：任一维度失败 → 该维度占位
  ``{"error": "<reason>"}``（或空 list / "unknown"），其他维度不受影响。
  工具层仍返回 ``success=True``（其他 7 个维度已给出有效信息）。
- **单一真相源**：版本号走 ``_read_package_json_version()``，不再依赖
  ``backend.__version__``（实际不存在）。

数据源对应：

- version          → package.json（与 Electron 共享）
- effective_model  → ``backend.orchestration.llm_factory.load_llm_config_for_chat``
- permission_mode  → ``backend.tools.permissions.load_enforcer_from_settings``
- mcp              → ``backend.mcp.pool.get_pool().status_report()``
- plugins          → ``backend.plugins.lifecycle.get_lifecycle_manager().list_plugins()``
- usage            → ``backend.services.usage_tracker``
- health           → 后端进程健康（基础检查）
- context          → 上下文占用（预留；当前无真实数据源，返回空 dict）
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Union

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 版本号 —— 单一真相源（package.json）
# ---------------------------------------------------------------------------


def _read_package_json_version() -> str:
    """读 package.json 的 version 字段。

    为什么读 package.json 而不是 ``backend.__version__``：后者从未被定义
    （``backend/__init__.py`` 为空），现有 ``_get_app_version()``（在
    ``diagnostic_routes.py``）走的是同一条 try/except 路径，始终返回
    "unknown"。Electron / CI / scripts/check_version_lockstep.py 的真相
    都在 package.json —— 这里直接对齐。
    """
    try:
        package_json = Path(__file__).resolve().parents[2] / "package.json"
        data = json.loads(package_json.read_text(encoding="utf-8"))
        version = data.get("version")
        return str(version) if version else "unknown"
    except Exception as exc:  # noqa: BLE001 —— 任何失败都降级为 unknown
        logger.debug("读取 package.json 版本失败: %s", exc)
        return "unknown"


# ---------------------------------------------------------------------------
# 各维度取数（每个函数独立 try/except，便于单维度降级）
# ---------------------------------------------------------------------------


def _gather_version() -> str:
    try:
        return _read_package_json_version()
    except Exception as exc:  # noqa: BLE001 —— 版本读取失败不拖垮整个聚合
        logger.debug("读取版本号失败: %s", exc)
        return "unknown"


def read_version() -> str:
    """公开版本号读取入口 —— ``read_sage_config(section="version")`` 等复用。"""
    return _gather_version()


def _gather_effective_model() -> Dict[str, Any]:
    """实际生效模型 —— 经 ``load_llm_config_for_chat`` 解析后含路由 overlay。

    ``load_llm_config_for_chat()`` 返回的是 ``LLMConfig`` 兼容 **dict**
    （键：model / provider / api_key / base_url / temperature / endpoint_id /
    max_tokens），不是对象 —— 必须用 ``.get()`` 取值。字段缺失时保留 None
    （UI 侧负责兜底展示）。
    """
    try:
        config = load_llm_config_for_chat()
        if not config:
            return {"error": "未配置可用的 LLM 端点"}
        return {
            "model": config.get("model"),
            "provider": config.get("provider"),
            "endpoint_id": config.get("endpoint_id"),
        }
    except Exception as exc:  # noqa: BLE001
        return {"error": f"加载 LLM 配置失败: {exc}"}


def _gather_permission_mode() -> str:
    """当前权限模式 —— 来自 settings 表 + PermissionEnforcer 实例。"""
    try:
        enforcer = load_enforcer_from_settings()
        return enforcer.mode.value
    except Exception as exc:  # noqa: BLE001
        logger.debug("读取权限模式失败，回退 workspace_write: %s", exc)
        return "workspace_write"


def _gather_mcp() -> Union[List[Dict[str, Any]], Dict[str, str]]:
    """MCP 服务器清单 —— 来自 mcp pool 的 status_report()。"""
    try:
        report = get_mcp_pool().status_report()
        return [
            {
                "name": entry.name,
                "state": entry.state,
                "tool_count": entry.tool_count,
                "last_error": entry.last_error,
                # ServerStatusEntry.since 是 float（time.time() 纪元秒），
                # 不是 datetime —— 直接 .isoformat() 会 AttributeError 拖垮
                # 整个维度。转成 UTC ISO-8601 便于 LLM / UI 展示。
                "since": (
                    datetime.fromtimestamp(entry.since, tz=timezone.utc).isoformat()  # noqa: UP017 - py38: datetime.UTC 是 3.11+
                    if entry.since
                    else None
                ),
                "required": entry.required,
            }
            for entry in report.servers
        ]
    except Exception as exc:  # noqa: BLE001
        logger.debug("读取 MCP 状态失败: %s", exc)
        return {"error": f"读取 MCP 状态失败: {exc}"}


def _gather_plugins() -> Union[List[Dict[str, Any]], Dict[str, str]]:
    """插件清单 —— 来自 PluginLifecycleManager.list_plugins()。"""
    try:
        records = get_plugin_lifecycle_manager().list_plugins()
        return [
            {
                "name": record.name,
                "version": record.version,
                # PluginRecord 字段是 str-Enum；JSON 序列化时 str 子类自动
                # 落值，但 f-string 会渲染成 "PluginStatus.ENABLED" —— 统一
                # 取 .value，保证两种消费方式一致。
                "status": getattr(record.status, "value", record.status),
                "plugin_type": getattr(record.plugin_type, "value", record.plugin_type),
            }
            for record in records
        ]
    except Exception as exc:  # noqa: BLE001
        logger.debug("读取插件清单失败: %s", exc)
        return {"error": f"读取插件清单失败: {exc}"}


def _gather_usage() -> Dict[str, Any]:
    """今日用量与成本 —— 来自 usage_tracker.summary_with_range()。"""
    try:
        summary = get_usage_summary()
        return summary if isinstance(summary, dict) else {}
    except Exception as exc:  # noqa: BLE001
        logger.debug("读取用量数据失败: %s", exc)
        return {"error": f"读取用量数据失败: {exc}"}


def _gather_health() -> Dict[str, Any]:
    """后端基础健康检查 —— 不做子进程探测，只验证主进程存活 + DB 连通。"""
    try:
        from backend.data.database import get_database

        # 必须走 get_database() 单例：Database 类本身没有 execute()，
        # 新建实例还会多开一条永不关闭的 SQLite 连接。get_connection()
        # 返回的 _LockedConnection.execute 内部已持有 _SQLITE_LOCK。
        db_ok = True
        try:
            get_database().get_connection().execute("SELECT 1")
        except Exception as exc:  # noqa: BLE001
            logger.debug("DB 健康检查失败: %s", exc)
            db_ok = False
        return {"backend_ok": True, "db_ok": db_ok}
    except Exception as exc:  # noqa: BLE001
        return {"backend_ok": False, "error": f"健康检查失败: {exc}"}


def _gather_context() -> Dict[str, Any]:
    """上下文占用 —— 预留位。

    真正的"上下文占用"需要会话级信息（当前对话 token 数），工具层拿不到。
    此处只返回 schema 占位，未来接入 context_window_tracker 后补字段。
    """
    return {}


# ---------------------------------------------------------------------------
# 聚合入口 —— 供 sage_self_status 工具与 read_sage_config self section 复用
# ---------------------------------------------------------------------------


def gather_self_status() -> Dict[str, Any]:
    """一次性聚合 8 维运行时状态。

    返回结构：

    {
        "version": "0.4.9-alpha.76",
        "effective_model": {...} | {"error": "..."},
        "permission_mode": "workspace_write",
        "mcp": [...] | {"error": "..."},
        "plugins": [...] | {"error": "..."},
        "usage": {...} | {"error": "..."},
        "health": {"backend_ok": True, "db_ok": True},
        "context": {},  # 预留
    }
    """
    return {
        "version": _gather_version(),
        "effective_model": _gather_effective_model(),
        "permission_mode": _gather_permission_mode(),
        "mcp": _gather_mcp(),
        "plugins": _gather_plugins(),
        "usage": _gather_usage(),
        "health": _gather_health(),
        "context": _gather_context(),
    }


# ---------------------------------------------------------------------------
# 测试/复用友好的别名（把间接 import 提到模块级，便于 mock.patch 替换）
# ---------------------------------------------------------------------------


def get_mcp_pool():
    from backend.mcp.pool import get_pool

    return get_pool()


def get_plugin_lifecycle_manager():
    from backend.plugins.lifecycle import get_lifecycle_manager

    return get_lifecycle_manager()


def get_usage_summary() -> Dict[str, Any]:
    from backend.services.usage_tracker import usage_tracker as _tracker

    return _tracker.summary_with_range("today")


def load_enforcer_from_settings():
    from backend.tools.permissions import load_enforcer_from_settings as _load

    return _load()


def load_llm_config_for_chat():
    from backend.orchestration.llm_factory import load_llm_config_for_chat as _load

    return _load()
