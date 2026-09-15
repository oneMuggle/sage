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
import os
import random
import re
import subprocess
import threading
import time
from typing import Any, Dict, Optional

import httpx

logger = logging.getLogger(__name__)

#: preferences 表的 key（需在 ``SettingsRepository.KEYS`` 白名单内）
SETTINGS_KEY_WEB_PROXY = "web_proxy"

#: 兜底 Chrome 大版本号（本地未发现 Chrome / 版本探测失败时使用；U1 Round 2 定为 126）
FALLBACK_CHROME_MAJOR = 126

#: 浏览器级默认请求头模板（Round 5 X1：三个出网工具共用，避免再出现"下载不发 UA"的漂移）。
#: 缺 User-Agent 的请求会被很多站点（小说站 / 学术站 / 论坛 / 文献库）按 bot 拒 403;
#: Accept-Language 让国内站点返回中文页,避免西文 fallback 误判。
#: Round 5 AB2：补齐 Chrome 实际发送的 Client Hints / Sec-Fetch / UIR 头 —— 现代 Chrome
#: 一定会带 ``Sec-CH-UA``，"UA 说是 Chrome 却没有 Client Hints" 本身是比版本号更廉价的
#: bot 信号。版本号从本地已发现的 Chrome 读取（与真浏览器通道一致且永不过期），
#: 读不到回退 ``FALLBACK_CHROME_MAJOR``。注意与 httpx 的 TLS 指纹解耦,硬风控站点仍走
#: browser 通道（AB1 自动升级）。
_HEADER_TEMPLATE: Dict[str, str] = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/{major}.0.0.0 Safari/537.36"
    ),
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;q=0.9,"
        "image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7"
    ),
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Sec-CH-UA": '"Not/A)Brand";v="8", "Chromium";v="{major}", "Google Chrome";v="{major}"',
    "Sec-CH-UA-Mobile": "?0",
    "Sec-CH-UA-Platform": '"Windows"',
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
    "Upgrade-Insecure-Requests": "1",
}

_chrome_major_cache: Dict[str, Optional[int]] = {}
_chrome_major_lock = threading.Lock()

_VERSION_RE = re.compile(r"(\d+)\.\d+\.\d+\.\d+")


def _probe_chrome_major() -> Optional[int]:
    """读取本地 Chromium 系浏览器的大版本号；任何失败返回 ``None``。

    Windows 上 ``chrome.exe --version`` 不输出到 stdout，改读可执行文件同级的
    版本目录名（``<dir>/<major>.<minor>.<build>.<patch>/``）；POSIX 走 ``--version``。
    """
    try:
        from backend.tools.browser_cdp import discover_browser_executable

        executable = discover_browser_executable()
    except Exception:  # noqa: BLE001 — 探测失败按未知处理
        return None
    if not executable:
        return None
    try:
        exe_dir = os.path.dirname(executable)
        versions = [
            int(match.group(1))
            for name in os.listdir(exe_dir)
            for match in [_VERSION_RE.fullmatch(name)]
            if match and os.path.isdir(os.path.join(exe_dir, name))
        ]
        if versions:
            return max(versions)
    except OSError:
        pass
    if os.name == "nt":
        return None
    try:
        completed = subprocess.run(  # noqa: S603 — 可执行路径来自受控发现逻辑
            [executable, "--version"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        match = _VERSION_RE.search(completed.stdout or "")
        return int(match.group(1)) if match else None
    except Exception:  # noqa: BLE001 — 子进程失败按未知处理
        return None


def chrome_major_version(refresh: bool = False) -> int:
    """当前默认头使用的 Chrome 大版本号（进程级缓存；探测失败回退兜底值）。

    只接受不小于兜底值的探测结果——本地装着老浏览器（win7 的 Chrome 109）时
    对外声明过旧版本反而是 bot 信号，此时仍声明兜底版本。
    """
    with _chrome_major_lock:
        if refresh or "major" not in _chrome_major_cache:
            probed = _probe_chrome_major()
            _chrome_major_cache["major"] = (
                probed if probed is not None and probed >= FALLBACK_CHROME_MAJOR else None
            )
        cached = _chrome_major_cache["major"]
    return cached if cached is not None else FALLBACK_CHROME_MAJOR


def default_headers() -> Dict[str, str]:
    """返回默认请求头的副本（调用方可安全修改）；版本号按 ``chrome_major_version()`` 填充。"""
    major = chrome_major_version()
    return {key: value.replace("{major}", str(major)) for key, value in _HEADER_TEMPLATE.items()}


class _DefaultHeaders(dict):
    """兼容别名：``DEFAULT_HEADERS`` 读取时按当前版本号即时求值。

    早期代码以常量形式引用（``web_tool._DEFAULT_HEADERS``、测试 ``["User-Agent"]``），
    保留 dict 语义；每次访问键都反映最新探测值。
    """

    def __getitem__(self, key: str) -> str:
        return default_headers()[key]

    def get(self, key: str, default: Any = None) -> Any:
        return default_headers().get(key, default)

    def items(self):  # type: ignore[override]
        return default_headers().items()

    def keys(self):  # type: ignore[override]
        return default_headers().keys()

    def values(self):  # type: ignore[override]
        return default_headers().values()

    def __iter__(self):
        return iter(default_headers())

    def __len__(self) -> int:
        return len(_HEADER_TEMPLATE)

    def __contains__(self, key: object) -> bool:
        return key in _HEADER_TEMPLATE

    def copy(self) -> Dict[str, str]:  # type: ignore[override]
        return default_headers()


DEFAULT_HEADERS: Dict[str, str] = _DefaultHeaders()


# ---------------------------------------------------------------------------
# AB5：请求级重试 + Retry-After + 同 host 限速
# ---------------------------------------------------------------------------

#: 可重试状态码（与 download_tool 同口径）
RETRYABLE_STATUS = frozenset({408, 425, 429, 500, 502, 503, 504})

#: 可重试异常（连接 / 超时 / 协议错 / 读写错）
RETRYABLE_EXCEPTIONS = (
    httpx.ConnectError,
    httpx.ConnectTimeout,
    httpx.ReadTimeout,
    httpx.WriteTimeout,
    httpx.PoolTimeout,
    httpx.RemoteProtocolError,
    httpx.ReadError,
    httpx.WriteError,
)

#: 网页抓取 / 搜索的默认重试次数（比下载保守：正文请求便宜，重试也便宜，但等待要短）
DEFAULT_FETCH_RETRIES = 2

_FETCH_BACKOFF_BASE = 0.8
_FETCH_BACKOFF_MAX = 8.0
_FETCH_RETRY_AFTER_CAP = 30.0

#: 同 host 令牌桶：默认 2 req/s，桶容量 4（允许短突发）
HOST_RATE_PER_SECOND = 2.0
HOST_RATE_BURST = 4

#: 测试钩子
_sleep = time.sleep


def parse_retry_after(value: Optional[str]) -> Optional[float]:
    """解析 ``Retry-After``（秒数或 HTTP-date）；不可解析返回 ``None``。"""
    if not value:
        return None
    value = value.strip()
    if value.isdigit():
        return float(value)
    try:
        from email.utils import parsedate_to_datetime

        return max(0.0, parsedate_to_datetime(value).timestamp() - time.time())
    except Exception:  # noqa: BLE001 — 非法日期按无 Retry-After 处理
        return None


class HostRateLimiter:
    """进程级同 host 令牌桶。工具跑在 executor 线程，持锁更新。

    子代理并发抓同一站点时把请求间隔拉开——这是 C1 缓存之外的另一半限流对策。
    """

    def __init__(self, rate: float = HOST_RATE_PER_SECOND, burst: int = HOST_RATE_BURST) -> None:
        self.rate = rate
        self.burst = burst
        self._lock = threading.Lock()
        self._buckets: Dict[str, Any] = {}

    def acquire(self, host: str) -> float:
        """为 ``host`` 取一个令牌；返回实际等待秒数（已经 sleep 过）。"""
        host = (host or "").lower()
        if not host or self.rate <= 0:
            return 0.0
        with self._lock:
            now = time.monotonic()
            tokens, last = self._buckets.get(host, (float(self.burst), now))
            tokens = min(float(self.burst), tokens + (now - last) * self.rate)
            if tokens >= 1.0:
                self._buckets[host] = (tokens - 1.0, now)
                wait = 0.0
            else:
                wait = (1.0 - tokens) / self.rate
                self._buckets[host] = (0.0, now + wait)
        if wait > 0:
            _sleep(wait)
        return wait

    def reset(self) -> None:
        with self._lock:
            self._buckets.clear()


_host_limiter = HostRateLimiter()


def get_host_rate_limiter() -> HostRateLimiter:
    return _host_limiter


def retrying_send(
    client: httpx.Client,
    request: httpx.Request,
    retries: int = DEFAULT_FETCH_RETRIES,
    stream: bool = False,
    rate_limit: bool = True,
) -> httpx.Response:
    """``client.send`` 加重试 / 退避 / Retry-After / 同 host 限速。

    - 可重试异常与 ``RETRYABLE_STATUS`` 状态码触发重试（非流式 / 流式都会先 close 旧响应）；
    - 429 / 503 的 ``Retry-After`` 优先（上限 30s），否则指数退避 ``0.8·2^n + jitter``；
    - 用尽后：最后一次是异常则抛出，是状态码则**返回该响应**（由调用方决定 4xx/5xx 语义）。
    """
    host = request.url.host or ""
    attempt = 0
    while True:
        if rate_limit:
            _host_limiter.acquire(host)
        try:
            response = client.send(request, stream=stream)
        except RETRYABLE_EXCEPTIONS:
            if attempt >= retries:
                raise
            retry_after = None
        else:
            if response.status_code not in RETRYABLE_STATUS or attempt >= retries:
                return response
            retry_after = parse_retry_after(response.headers.get("retry-after"))
            response.close()
        if retry_after is not None:
            wait = min(retry_after, _FETCH_RETRY_AFTER_CAP)
        else:
            base = min(_FETCH_BACKOFF_BASE * (2**attempt), _FETCH_BACKOFF_MAX)
            wait = base + random.uniform(0, base * 0.25)
        logger.info("http retry %s attempt=%d wait=%.1fs", request.url, attempt + 1, wait)
        _sleep(wait)
        attempt += 1
        # httpx.Request 可重复 send（无 body 流）；GET 场景恒满足


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
    ``client_class`` 可指定 ``httpx.Client`` 子类（如 web_tool 的重试 client）。
    """
    client_class = kwargs.pop("client_class", httpx.Client)
    explicit_mounts = kwargs.pop("mounts", None)
    proxy_mounts = build_proxy_mounts()
    if proxy_mounts:
        merged = dict(proxy_mounts)
        if explicit_mounts:
            merged.update(explicit_mounts)
        kwargs["mounts"] = merged
    return client_class(**kwargs)


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
    "DEFAULT_FETCH_RETRIES",
    "DEFAULT_HEADERS",
    "FALLBACK_CHROME_MAJOR",
    "HostRateLimiter",
    "RETRYABLE_EXCEPTIONS",
    "RETRYABLE_STATUS",
    "SETTINGS_KEY_WEB_PROXY",
    "chrome_major_version",
    "default_headers",
    "get_host_rate_limiter",
    "parse_retry_after",
    "retrying_send",
    "browser_proxy_flag",
    "build_client",
    "build_proxy_mounts",
    "load_proxy_config",
]
