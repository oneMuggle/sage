# ruff: noqa: UP006, UP007, UP035, UP045 — release/win7 Python 3.8 兼容，保留 typing 注解
"""出网工具的 httpx.Client 工厂 —— 统一注入用户代理配置（方案 2026-09-13 §2.3）。

存储位置是 ``preferences`` 表的 ``web_proxy`` key（JSON
``{"http": "", "https": ""}``），与 ``network_policy`` 同一套 KV 机制。

**fail-safe 方向**：任何读取/解析失败都按"未配置"处理（不注入代理，保持
既有 ``trust_env`` 行为）——代理配置坏了不应该把出网能力整个锁死。

**注入语义**：manual 代理以 mounts 形式覆盖 httpx 默认 transport，优先于
环境变量（``HTTP_PROXY`` 等，经 ``trust_env`` 的既有通道）。``build_client``
每次现读配置 —— 用户改设置即时生效，不必重开工具/会话。

py3.8 纪律：本模块同时服务 main 与 release/win7 — stdlib + httpx only。
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, Optional

import httpx

logger = logging.getLogger(__name__)

#: preferences 表的 key（需在 ``SettingsRepository.KEYS`` 白名单内）
SETTINGS_KEY_WEB_PROXY = "web_proxy"


def load_proxy_config(repo: Optional[Any] = None) -> Dict[str, str]:
    """读取代理配置；任何失败回退空配置（不启用代理）。

    Args:
        repo: 可注入的 ``SettingsRepository``（测试用）；``None`` 时新建。
    """
    empty = {"http": "", "https": ""}
    try:
        if repo is None:
            # 惰性 import 避免 tools ↔ data 循环依赖（与 network_config 同手法）
            from backend.data.settings_repo import SettingsRepository

            repo = SettingsRepository()
        raw = repo.get(SETTINGS_KEY_WEB_PROXY)
    except Exception:  # noqa: BLE001 — 配置读取失败绝不阻断工具注册
        logger.warning("代理配置读取失败，按未配置处理", exc_info=True)
        return empty

    if not raw:
        return empty

    try:
        parsed = json.loads(raw)
    except (ValueError, TypeError):
        logger.warning("代理配置 JSON 解析失败，按未配置处理")
        return empty

    if not isinstance(parsed, dict):
        logger.warning("代理配置不是 JSON 对象，按未配置处理")
        return empty

    result: Dict[str, str] = {}
    for field in ("http", "https"):
        value = parsed.get(field)
        result[field] = value.strip() if isinstance(value, str) else ""
    return result


def build_proxy_mounts(config: Optional[Dict[str, str]] = None) -> Dict[str, httpx.HTTPTransport]:
    """把代理配置转成 httpx mounts（scheme → transport）；未配置返回空 dict。"""
    if config is None:
        config = load_proxy_config()
    mounts: Dict[str, httpx.HTTPTransport] = {}
    http_proxy = (config.get("http") or "").strip()
    https_proxy = (config.get("https") or "").strip()
    if http_proxy:
        mounts["http://"] = httpx.HTTPTransport(proxy=http_proxy)
    if https_proxy:
        mounts["https://"] = httpx.HTTPTransport(proxy=https_proxy)
    return mounts


def build_client(**kwargs: Any) -> httpx.Client:
    """httpx.Client 工厂：自动注入用户代理配置。

    调用方照常传 timeout/follow_redirects/verify/trust_env/headers 等；
    调用方显式传入的 ``mounts`` 条目优先于代理 mounts（不覆盖）。
    """
    explicit_mounts = kwargs.pop("mounts", None)
    proxy_mounts = build_proxy_mounts()
    if proxy_mounts:
        merged = dict(proxy_mounts)
        if explicit_mounts:
            merged.update(explicit_mounts)
        kwargs["mounts"] = merged
    return httpx.Client(**kwargs)


def browser_proxy_flag(config: Optional[Dict[str, str]] = None) -> str:
    """把代理配置转成 Chrome ``--proxy-server`` 参数值；未配置返回空串。

    双协议齐全用 ``http=<url>;https=<url>`` 形态；单协议直接给 URL
    （Chrome 会作用于其余 scheme）。
    """
    if config is None:
        config = load_proxy_config()
    http_proxy = (config.get("http") or "").strip()
    https_proxy = (config.get("https") or "").strip()
    if http_proxy and https_proxy:
        return f"http={http_proxy};https={https_proxy}"
    if http_proxy:
        return http_proxy
    if https_proxy:
        return https_proxy
    return ""


__all__ = [
    "SETTINGS_KEY_WEB_PROXY",
    "browser_proxy_flag",
    "build_client",
    "build_proxy_mounts",
    "load_proxy_config",
]
