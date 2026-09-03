"""网络访问策略领域模型（内网 Web 访问）。

三种模式决定出网工具的注册与 host 准入：

- ``ONLINE``：现状 —— 搜索可用，任意地址可访问（``allowed_hosts`` 不参与判定）。
- ``INTRANET``：搜索不注册；取页/下载仅允许 ``allowed_hosts`` 命中的 host。
- ``OFFLINE``：三个出网工具全部不注册。

**领域纯净性**：仅依赖标准库，不读文件/时钟/网络。配置加载由
``backend.tools.network_config`` 负责。
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, Optional, Tuple


def _extract_hostname(url: str) -> Optional[str]:
    """从 URL 字符串提取 hostname。

    手写实现以保持 ``domain/`` 纯净性（``test_no_external_imports_in_domain``
    仅允许基础 stdlib，``urllib.parse`` 不在白名单）。覆盖常见形式：

    - ``scheme://[userinfo@]host[:port][/path][?query][#fragment]``
    - IPv6: ``http://[::1]:8080/path`` → ``::1``
    - 带 userinfo: ``http://user:pwd@host/path`` → ``host``
    - 无 ``://`` 或 host 为空 → ``None``
    """
    s = url
    for sep in ("#", "?"):
        idx = s.find(sep)
        if idx >= 0:
            s = s[:idx]
    sep_idx = s.find("://")
    if sep_idx < 0:
        return None
    s = s[sep_idx + 3:]
    if "@" in s:
        s = s.split("@", 1)[1]
    end = len(s)
    for i, c in enumerate(s):
        if c == "/":
            end = i
            break
    hostport = s[:end]
    if not hostport:
        return None
    if hostport.startswith("["):
        end_bracket = hostport.find("]")
        if end_bracket < 0:
            return None
        return hostport[1:end_bracket] or None
    if ":" in hostport:
        hostport = hostport.rsplit(":", 1)[0]
    return hostport or None


class NetworkMode(str, Enum):
    """网络模式 —— 决定出网工具的注册与 host 准入。"""

    ONLINE = "online"
    INTRANET = "intranet"
    OFFLINE = "offline"


def normalize_host(value: str) -> str:
    """归一化 host：去空白、转小写、去尾点。

    尾点是合法的 FQDN 写法（``a.cnki.net.``），不归一化会让 ``A.CNKI.NET.``
    绕过白名单。
    """
    return value.strip().lower().rstrip(".")


def host_matches(host: str, pattern: str) -> bool:
    """判定 host 是否命中 pattern（精确或 ``*.`` 通配）。

    ``*.cnki.net`` 命中 ``cnki.net`` 自身及任意层级子域。后缀混淆
    （``evilcnki.net``）不命中 —— 通配比对的是"以 ``.cnki.net`` 结尾"，
    不是"以 ``cnki.net`` 结尾"。
    """
    host = normalize_host(host)
    pattern = normalize_host(pattern)
    if not pattern.startswith("*."):
        return host == pattern
    apex = pattern[2:]
    return host == apex or host.endswith("." + apex)


def _validate_pattern(pattern: str) -> None:
    """通配必须是 ``*.`` 前缀且 apex 至少两段，否则白名单形同虚设。

    先判 ``"*" in normalized`` 而非 ``startswith("*.")``：``normalize_host``
    的 ``rstrip(".")`` 会把 ``"*."`` 削成 ``"*"``，用 startswith 判断会让
    ``"*"`` 和 ``"*."`` 都走"非通配"早退分支被放行。
    """
    normalized = normalize_host(pattern)
    if not normalized:
        raise ValueError("host 条目不能为空")
    if "*" not in normalized:
        return
    if not normalized.startswith("*."):
        raise ValueError(f"通配 host {pattern!r} 格式非法：只支持 ``*.`` 前缀")
    apex = normalized[2:]
    if "*" in apex:
        raise ValueError(f"通配 host {pattern!r} 格式非法：``*`` 只能出现一次")
    if apex.count(".") < 1:
        raise ValueError(
            f"通配 host {pattern!r} 过宽：``*.`` 后至少需要两段域名（如 ``*.cnki.net``）"
        )


def _coerce_hosts(value: Any, field: str) -> Tuple[str, ...]:
    """把配置里的 host 列表强制成 ``Tuple[str, ...]``，类型不对就抛。

    不能直接 ``tuple(value)``：dict 会静默变成 key 元组（``{"a": 1}`` →
    ``("a",)``），裸字符串会被拆成单字符元组（``"a.internal"`` → ``("a",
    ".", "i", ...)``）。两种都会让白名单变成一堆无意义条目。
    """
    if value is None:
        return ()
    if not isinstance(value, (list, tuple)):  # noqa: UP038 — py3.8 不支持 X | Y isinstance
        raise TypeError(f"{field} 必须是字符串列表")
    for item in value:
        if not isinstance(item, str):
            raise TypeError(f"{field} 条目必须是字符串，得到 {type(item).__name__}")
    return tuple(value)


@dataclass(frozen=True)
class NetworkPolicy:
    """出网访问策略（不可变）。

    Fields:
        mode:               网络模式。
        allowed_hosts:      host 白名单，支持 ``*.`` 前缀通配。仅 ``INTRANET``
                            模式参与判定。
        insecure_tls_hosts: 允许跳过 TLS 校验的 host（内网自签证书）。每一项
                            都必须被 ``allowed_hosts`` 覆盖。
    """

    mode: NetworkMode = NetworkMode.ONLINE
    allowed_hosts: Tuple[str, ...] = ()
    insecure_tls_hosts: Tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for pattern in self.allowed_hosts:
            _validate_pattern(pattern)
        for pattern in self.insecure_tls_hosts:
            _validate_pattern(pattern)
            if not any(host_matches(pattern, allowed) for allowed in self.allowed_hosts):
                raise ValueError(
                    f"insecure_tls_hosts 条目 {pattern!r} 未被 allowed_hosts 覆盖："
                    "关闭 TLS 校验不能作用于白名单外的 host"
                )

    def search_enabled(self) -> bool:
        """``web_search`` 是否注册。"""
        return self.mode is NetworkMode.ONLINE

    def fetch_enabled(self) -> bool:
        """``web_fetch`` / ``http_download`` 是否注册。"""
        return self.mode is not NetworkMode.OFFLINE

    def check_host(self, url: str) -> Optional[str]:
        """执行期 host 准入。返回中文拒绝原因；``None`` 表示放行。"""
        if self.mode is NetworkMode.ONLINE:
            return None
        if self.mode is NetworkMode.OFFLINE:
            return "network_mode_offline: 当前为气隙模式，禁止一切出网访问"
        hostname = _extract_hostname(url)
        if not hostname:
            return f"invalid_url: 无法从 {url!r} 解析主机名"
        if any(host_matches(hostname, pattern) for pattern in self.allowed_hosts):
            return None
        return (
            f"host_not_allowed: {hostname} 不在内网白名单中"
            "（在设置 → 网络中添加后可访问）"
        )

    def allows_insecure_tls(self, url: str) -> bool:
        """该 URL 的 host 是否豁免 TLS 校验。"""
        hostname = _extract_hostname(url)
        if not hostname:
            return False
        return any(host_matches(hostname, pattern) for pattern in self.insecure_tls_hosts)

    @classmethod
    def from_config(cls, cfg: Dict[str, Any]) -> NetworkPolicy:
        """从已解析的 dict 构造，缺字段回退默认。

        非法 ``mode`` 抛 ``ValueError``，host 列表类型不对抛 ``TypeError``；
        两者都由 ``network_config.load_network_policy`` 捕获并 fail-safe。
        """
        defaults = cls()
        raw_mode = cfg.get("mode")
        mode = NetworkMode(raw_mode) if raw_mode is not None else defaults.mode
        return cls(
            mode=mode,
            allowed_hosts=_coerce_hosts(cfg.get("allowed_hosts"), "allowed_hosts"),
            insecure_tls_hosts=_coerce_hosts(
                cfg.get("insecure_tls_hosts"), "insecure_tls_hosts"
            ),
        )
