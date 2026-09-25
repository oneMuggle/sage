# ruff: noqa: UP006, UP007, UP035, UP038, UP045 — release/win7 Python 3.8 兼容，保留 typing 注解
"""AB3 TLS/HTTP2 指纹传输器（Round 27；可选依赖 ``curl_cffi``，main only）。

网络策略校验、重定向编排、AB5 重试、响应缓冲全部仍在 web_tool 的 httpx
客户端里 —— 本模块只提供一个 httpx 自定义 transport：开启
``web_access_config.tls_fingerprint`` 且 ``curl_cffi`` 可导入时，静态抓取的
TLS/HTTP2 握手（JA3 等指纹）与真实 Chrome 一致，站点侧无法仅凭握手指纹
把请求识别为脚本客户端。

口径与 AB4 stealth 相同：只做"不主动暴露自动化"，不做验证码破解、不绕过
明确的 robots/ToS 拒绝；403 升级链失败后仍以指引结束。curl_cffi 缺失或
配置关闭时回落标准 httpx 传输，行为与 R26 之前完全一致。

py3.8 纪律：主分支依赖可选（release/win7 不安装），import 全部懒加载。
"""

from __future__ import annotations

import logging
import threading
from typing import Any, Dict, Optional

import httpx

logger = logging.getLogger(__name__)

#: Chrome 指纹别名（curl_cffi 支持的 impersonate 目标；随库更新指向最新）
IMPERSONATE_TARGET = "chrome"

_import_failed = False

# R28/R34：指纹通道使用计数（诊断视角；线程安全）。仅统计经指纹传输器
# 实际发出的请求；错误 / 未启用不计数。R34 起按 host 细分（LRU 上限 100）。
_stats_lock = threading.Lock()
_stats = {"requests": 0}
_stats_hosts: Dict[str, int] = {}
MAX_TLS_STATS_HOSTS = 100


def stats() -> Dict[str, Any]:
    """指纹通道使用计数快照（拷贝；R28/R34）：
    ``{"requests": N, "hosts": {host: count}}``。"""
    with _stats_lock:
        return {
            "requests": _stats["requests"],
            "hosts": dict(sorted(_stats_hosts.items())),
        }


def fingerprint_enabled() -> bool:
    """读 ``web_access_config.tls_fingerprint``（默认关）；任何失败静默回退 False。"""
    global _import_failed
    if _import_failed:
        return False
    try:
        import json

        from backend.data.settings_repo import SettingsRepository

        raw = SettingsRepository().get("web_access_config")
        if not raw:
            return False
        parsed = json.loads(raw)
        return bool(isinstance(parsed, dict) and parsed.get("tls_fingerprint"))
    except Exception:  # noqa: BLE001 — 配置失败按关闭处理（保持现状行为）
        return False


class CurlImpersonateTransport(httpx.BaseTransport):
    """把 httpx.Request 经 curl_cffi 发出（Chrome TLS/HTTP2 指纹）。

    ``allow_redirects=False``：重定向编排在 web_tool 逐跳完成（策略校验、
    凭据剥离、hop 计数都在那里），传输层不做跟随。应用级代理配置
    （http_factory.load_proxy_config）在此透传给 curl；环境变量代理在指纹
    模式下不生效（subagent_only 的 trust_env=False 语义保持）。
    """

    def __init__(self, verify: bool = True, timeout: float = 30.0) -> None:
        self._verify = verify
        self._timeout = timeout

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        from curl_cffi import requests as creq

        body = request.read()
        kwargs: Dict[str, Any] = {
            "impersonate": IMPERSONATE_TARGET,
            "allow_redirects": False,
            "verify": self._verify,
            "timeout": self._timeout,
        }
        proxies = _app_proxies()
        if proxies:
            kwargs["proxies"] = proxies
        response = creq.request(
            request.method,
            str(request.url),
            headers=dict(request.headers),
            data=body,
            **kwargs,
        )
        with _stats_lock:
            _stats["requests"] += 1
            from urllib.parse import urlparse

            host = (urlparse(str(request.url)).hostname or "").lower()
            if host:
                if host not in _stats_hosts and len(_stats_hosts) >= MAX_TLS_STATS_HOSTS:
                    _stats_hosts.clear()  # 超限整体清零（诊断视角，保新弃旧）
                _stats_hosts[host] = _stats_hosts.get(host, 0) + 1
        return httpx.Response(
            response.status_code,
            headers=list(response.headers.items()),
            content=response.content,
            request=request,
        )


def _app_proxies() -> Dict[str, str]:
    """应用级代理配置（http/https）转 curl proxies 字典；未配置返回空。"""
    try:
        from .http_factory import load_proxy_config

        config = load_proxy_config()
        proxies: Dict[str, str] = {}
        for scheme in ("http", "https"):
            value = (config.get(scheme) or "").strip()
            if value:
                proxies[scheme] = value
        return proxies
    except Exception:  # noqa: BLE001 — 代理读取失败按直连处理
        return {}


def build_fingerprint_transport(verify: bool = True) -> Optional[httpx.BaseTransport]:
    """构造指纹传输器；curl_cffi 未安装时记一次日志并返回 None（调用方回落）。"""
    global _import_failed
    try:
        import curl_cffi  # noqa: F401

        return CurlImpersonateTransport(verify=verify)
    except ImportError:
        if not _import_failed:
            _import_failed = True
            logger.info(
                "tls_fingerprint 已开启但 curl_cffi 未安装 —— 静态抓取回落标准"
                " httpx 传输（可选安装：pip install curl_cffi）"
            )
        return None
