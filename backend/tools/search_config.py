# ruff: noqa: UP006, UP007, UP035, UP045 — release/win7 Python 3.8 兼容，保留 typing 注解
"""从 preferences KV 加载搜索配置（引擎链顺序 + 可选 API 引擎的 key）。

存储位置是 ``preferences`` 表的 ``search_config`` key（JSON 字符串），与
``network_policy`` 同一套 KV 机制（见 ``network_config.py`` 的设计说明）。

**fail-safe 方向**：任何读取/解析/校验失败都回退默认链 ``("bing", "ddg")``
——搜索是只读操作，配置坏了不应该把搜索功能整个锁死。

API 引擎 key 的静态加密：值允许是 ``enc:<scheme>:v1:<payload>``（由
``secret_box.encrypt_secret`` 产生，设置 UI 落库时包裹），读取时在
``load_search_config`` 里显式解包 —— 与 ``app_settings`` 走
SettingsRepository 咽喉点透明加解密不同，独立 KV key 需自己处理。

py3.8 纪律：本模块同时服务 main 与 release/win7 — stdlib + httpx only。
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any, Optional, Tuple

logger = logging.getLogger(__name__)

#: preferences 表的 key（需在 ``SettingsRepository.KEYS`` 白名单内）
SETTINGS_KEY_SEARCH_CONFIG = "search_config"

#: 默认引擎链：Bing 大陆可达作首选，DDG 后备（方案 2026-09-13 §2.2）
DEFAULT_ENGINE_ORDER: Tuple[str, ...] = ("bing", "ddg")

#: 已知引擎名（用于过滤配置里的未知条目，防手滑写错导致链为空）
_KNOWN_ENGINES = frozenset({"bing", "ddg", "tavily", "zhipu"})


@dataclass(frozen=True)
class SearchConfig:
    """搜索配置（不可变）。

    Fields:
        engine_order: 引擎尝试顺序，逐个 fallback 直到有结果。
        tavily_key:   Tavily API key（可选，空 = 不启用该引擎）。
        zhipu_key:    智谱 web-search API key（可选，空 = 不启用该引擎）。
    """

    engine_order: Tuple[str, ...] = DEFAULT_ENGINE_ORDER
    tavily_key: str = ""
    zhipu_key: str = ""
    #: 并行聚合（Round 8 P1）：true 时链上前 parallel_first_n 个引擎并发搜索
    #: 并按优先级合并去重；false 保持串行 fallback。
    parallel: bool = False
    #: 并行模式取链上前 N 个引擎（下限 1）
    parallel_first_n: int = 2


def _unwrap_secret(value: Any) -> str:
    """API key 可能是 ``enc:`` 包裹的密文；解包失败按空处理（不阻断搜索）。"""
    if not isinstance(value, str) or not value:
        return ""
    if not value.startswith("enc:"):
        return value
    try:
        from backend.services.secret_box import decrypt_secret

        return decrypt_secret(value)
    except Exception:  # noqa: BLE001 — 解密失败不阻断搜索链
        logger.warning("search_config: API key 解密失败，该引擎按未配置处理", exc_info=True)
        return ""


def load_search_config(repo: Optional[Any] = None) -> SearchConfig:
    """读取搜索配置；任何失败回退 ``SearchConfig()``（默认链）。

    Args:
        repo: 可注入的 ``SettingsRepository``（测试用）；``None`` 时新建。
    """
    try:
        if repo is None:
            # 惰性 import 避免 tools ↔ data 循环依赖（与 network_config 同手法）
            from backend.data.settings_repo import SettingsRepository

            repo = SettingsRepository()
        raw = repo.get(SETTINGS_KEY_SEARCH_CONFIG)
    except Exception:  # noqa: BLE001 — 配置读取失败绝不阻断工具注册
        logger.warning("搜索配置读取失败，回退默认引擎链", exc_info=True)
        return SearchConfig()

    if not raw:
        return SearchConfig()

    try:
        parsed = json.loads(raw)
    except (ValueError, TypeError):
        logger.warning("搜索配置 JSON 解析失败，回退默认引擎链")
        return SearchConfig()

    if not isinstance(parsed, dict):
        logger.warning("搜索配置不是 JSON 对象，回退默认引擎链")
        return SearchConfig()

    order = parsed.get("order")
    engine_order: Tuple[str, ...] = DEFAULT_ENGINE_ORDER
    if isinstance(order, list):
        cleaned = tuple(
            item for item in order if isinstance(item, str) and item in _KNOWN_ENGINES
        )
        if cleaned:
            engine_order = cleaned

    parallel = parsed.get("parallel")
    first_n = parsed.get("parallel_first_n")
    return SearchConfig(
        engine_order=engine_order,
        tavily_key=_unwrap_secret(parsed.get("tavily_key")),
        zhipu_key=_unwrap_secret(parsed.get("zhipu_key")),
        parallel=bool(parallel),
        parallel_first_n=first_n if isinstance(first_n, int) and first_n >= 1 else 2,
    )
