"""Zotero DB 路径解析 —— 单一来源。

历史上同一个「用户配置的 Zotero 数据库路径」有两条独立解析链：

- REST（``backend/api/zotero_routes.py``）读 ``settings_repo.zotero_db_path``；
- MCP 子进程（``backend/mcp/config.py``）只认 ``ZOTERO_DB_PATH`` 环境变量。

结果是设置页能连、LLM 侧 MCP 工具却读不到同一个库（Zotero 不可见根因 ②）。
本模块收敛两处为一个函数，新增消费者（索引层、wiki 沉淀层）也只引用这里。

解析优先级：settings_repo → 环境变量 → 空字符串（交由 ``ZoteroClient``
走其内置默认路径搜索）。任何异常都降级到环境变量 —— 本函数在 MCP 配置
构建与后端启动期被调用，不允许抛错。
"""

from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)

#: settings_repo 中的偏好键名（前端设置页写入）。
SETTINGS_KEY = "zotero_db_path"

#: 环境变量兜底（开发者 / CI 显式指定）。
ENV_VAR = "ZOTERO_DB_PATH"


def resolve_zotero_db_path() -> str:
    """返回用户配置的 Zotero SQLite 路径；未配置时返回空字符串。

    settings_repo 优先于环境变量：设置页是面向用户的权威来源，
    环境变量只是无 UI 场景的兜底（与修复前 REST 侧语义一致）。
    """
    try:
        from backend.data.settings_repo import SettingsRepository

        configured = SettingsRepository().get(SETTINGS_KEY)
        if configured:
            return str(configured)
    except Exception:  # noqa: BLE001 — 路径解析不可拖垮启动
        logger.debug("zotero db path from settings unavailable", exc_info=True)
    return os.environ.get(ENV_VAR, "")


__all__ = ["ENV_VAR", "SETTINGS_KEY", "resolve_zotero_db_path"]
