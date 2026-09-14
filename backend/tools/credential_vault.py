# ruff: noqa: UP006, UP007, UP035, UP038, UP045 — release/win7 Python 3.8 兼容，保留 typing 注解
"""站点凭据档案（方案 2026-09-13 §2.5 cookie 桥 + Round 5 §2.4 AU1/AU2/AU4）。

CDP 浏览器里导出的 cookie（或用户显式设置的头部凭据）经 SecretBox 静态加密落
``preferences`` KV（key ``browser_credential_vault``），供 ``web_fetch`` /
``http_download`` 以 ``credential_domain`` 参数引用 —— 登录墙后的资源
（订阅源文献 PDF）从此可达。

**存储格式**（domain → 档案条目）::

    {"kind": "cookie", "cookies_enc": "enc:...", "saved_at": <ms>, "updated_at": <ms>}
    {"kind": "header", "headers_enc": "enc:...", "saved_at": <ms>, "expires_at": <ms>|None}

旧档案没有 ``kind`` 字段，按 ``cookie`` 处理。cookie 条目保留
``expires``（epoch 秒，session cookie 无此键）/ ``secure`` / ``httpOnly`` /
``sameSite`` 元数据（AU1），供附加时按过期 / 协议 / path 过滤。

domain 取 CDP cookie 的 domain 属性（如 ``.cnki.net``），附加时按 RFC 6265
域匹配规则判定 host 是否命中。

**安全口径**：明文凭据只在单次工具调用的内存中存在；落库走
SecretBox（DPAPI/keychain，scheme=none 平台诚实降级为不包裹）；
``llm_trace.redactor`` 已对 Cookie / Authorization 头日志脱敏；
任何读接口都不回显值（``list_credentials`` 只给名字与时效）。

py3.8 纪律：本模块同时服务 main 与 release/win7 — stdlib only。
"""

from __future__ import annotations

import json
import logging
import re
import time
from email.utils import parsedate_to_datetime
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse

from backend.services.secret_box import decrypt_secret, encrypt_secret

logger = logging.getLogger(__name__)

#: preferences 表的 key（需在 ``SettingsRepository.KEYS`` 白名单内）
SETTINGS_KEY_CREDENTIAL_VAULT = "browser_credential_vault"

_VAULT_ACCOUNT_PREFIX = "browser-cookie:"
_HEADER_ACCOUNT_PREFIX = "browser-header:"

KIND_COOKIE = "cookie"
KIND_HEADER = "header"

#: 头部凭据禁止覆盖的头（由传输层 / cookie 通道各自负责）
_FORBIDDEN_CREDENTIAL_HEADERS = frozenset(
    {"cookie", "host", "content-length", "transfer-encoding", "connection", "accept-encoding"}
)
_HEADER_NAME_RE = re.compile(r"^[!#$%&'*+\-.^_`|~0-9A-Za-z]+$")

#: 登录墙启发式（AU2）：URL 的 host 前缀 / path 片段 / 页面密码框
_LOGIN_HOST_RE = re.compile(r"^(?:login|signin|sign-in|sso|passport|auth|idp|accounts?)\.", re.I)
_LOGIN_PATH_RE = re.compile(
    r"(?:^|[/._\-?&=])(?:login|log-in|logon|signin|sign-in|sign_in|sso|passport|"
    r"authenticate|authorize|oauth2?|cas|idp)(?:$|[/._\-?&=])",
    re.I,
)
_PASSWORD_INPUT_RE = re.compile(r"<input\b[^>]*\btype\s*=\s*[\"']?password\b", re.I)


# --------------------------------------------------------------------------- storage


def _load_vault(repo: Any) -> Dict[str, Any]:
    raw = repo.get(SETTINGS_KEY_CREDENTIAL_VAULT)
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except (ValueError, TypeError):
        logger.warning("凭据档案 JSON 解析失败，按空档案处理")
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _save_vault(repo: Any, vault: Dict[str, Any]) -> None:
    repo.set(SETTINGS_KEY_CREDENTIAL_VAULT, json.dumps(vault, ensure_ascii=False))


def _get_repo(repo: Optional[Any]) -> Any:
    if repo is not None:
        return repo
    from backend.data.settings_repo import SettingsRepository

    return SettingsRepository()


def _now_ms() -> int:
    return int(time.time() * 1000)


def _entry_kind(entry: Any) -> Optional[str]:
    if not isinstance(entry, dict):
        return None
    kind = entry.get("kind")
    if kind in (KIND_COOKIE, KIND_HEADER):
        return str(kind)
    return KIND_COOKIE if entry.get("cookies_enc") else None


# --------------------------------------------------------------------------- matching


def cookie_domain_matches(hostname: str, cookie_domain: str) -> bool:
    """RFC 6265 域匹配：``.cnki.net`` 命中 ``cnki.net`` 及任意子域。

    ``cookie_domain`` 是 CDP cookie 的 domain 属性（可能带/不带前导点）。
    """
    host = (hostname or "").strip().lower().rstrip(".")
    domain = (cookie_domain or "").strip().lower().lstrip(".").rstrip(".")
    if not host or not domain:
        return False
    return host == domain or host.endswith("." + domain)


def cookie_path_matches(request_path: str, cookie_path: str) -> bool:
    """RFC 6265 §5.1.4 path 匹配。"""
    req = request_path or "/"
    cpath = cookie_path or "/"
    if req == cpath:
        return True
    if not req.startswith(cpath):
        return False
    return cpath.endswith("/") or req[len(cpath) :].startswith("/")


def looks_like_login_url(url: str) -> bool:
    """URL 是否像登录 / SSO 入口（AU2 登录墙启发式，纯函数）。"""
    try:
        parsed = urlparse(url or "")
    except ValueError:
        return False
    host = (parsed.hostname or "").lower()
    if host and _LOGIN_HOST_RE.search(host):
        return True
    target = parsed.path or "/"
    if parsed.query:
        target += "?" + parsed.query
    return bool(_LOGIN_PATH_RE.search(target))


def looks_like_login_html(html: str) -> bool:
    """页面是否含密码输入框（AU2 登录墙启发式，纯函数）。"""
    return bool(_PASSWORD_INPUT_RE.search((html or "")[:300_000]))


# --------------------------------------------------------------------------- cookie kind


def _clean_cookie(item: Dict[str, Any], default_domain: str) -> Optional[Dict[str, Any]]:
    if not isinstance(item, dict) or not item.get("name"):
        return None
    cleaned: Dict[str, Any] = {
        "name": str(item.get("name") or ""),
        "value": str(item.get("value") or ""),
        "domain": str(item.get("domain") or default_domain),
        "path": str(item.get("path") or "/"),
    }
    # CDP: expires 为 epoch 秒（float），session cookie 为 -1 / 缺省
    expires = item.get("expires")
    if isinstance(expires, (int, float)) and not isinstance(expires, bool) and expires > 0:
        cleaned["expires"] = int(expires)
    for flag in ("secure", "httpOnly"):
        if item.get(flag):
            cleaned[flag] = True
    same_site = item.get("sameSite")
    if same_site:
        cleaned["sameSite"] = str(same_site)
    return cleaned


def save_credential(domain: str, cookies: List[Dict[str, Any]], repo: Optional[Any] = None) -> None:
    """把某 cookie domain 的 cookie 列表加密存入档案（覆盖旧值，kind=cookie）。

    Args:
        domain:  CDP cookie 的 domain 属性（如 ``.cnki.net``）。
        cookies: ``[{"name", "value", "domain", "path", "expires"?, "secure"?, ...}, ...]``
                 （多余字段忽略；``expires`` 为 epoch 秒，≤0 视为 session）。
    """
    domain = (domain or "").strip().lower()
    if not domain or not cookies:
        raise ValueError("save_credential: domain 与 cookies 均不能为空")
    cleaned = [c for c in (_clean_cookie(item, domain) for item in cookies) if c]
    if not cleaned:
        raise ValueError("save_credential: cookies 中没有可保存的条目")
    store = _get_repo(repo)
    vault = _load_vault(store)
    now = _now_ms()
    vault[domain] = {
        "kind": KIND_COOKIE,
        "cookies_enc": encrypt_secret(
            json.dumps(cleaned, ensure_ascii=False), account=_VAULT_ACCOUNT_PREFIX + domain
        ),
        "saved_at": now,
        "updated_at": now,
    }
    _save_vault(store, vault)


def _decrypt_cookies(entry: Dict[str, Any], domain: str) -> Optional[List[Dict[str, Any]]]:
    if not entry.get("cookies_enc"):
        return None
    try:
        cookies = json.loads(decrypt_secret(str(entry["cookies_enc"])))
    except Exception:  # noqa: BLE001 — 解密失败按无档案处理（不阻断调用方）
        logger.warning("凭据档案解密失败: %s", domain, exc_info=True)
        return None
    return cookies if isinstance(cookies, list) else None


def load_credential(domain: str, repo: Optional[Any] = None) -> Optional[List[Dict[str, Any]]]:
    """取某 domain 的 cookie 列表（已解密、含元数据）；无档案 / 非 cookie 档案 / 解密失败返回 ``None``。"""
    domain = (domain or "").strip().lower()
    if not domain:
        return None
    entry = _load_vault(_get_repo(repo)).get(domain)
    if _entry_kind(entry) != KIND_COOKIE:
        return None
    return _decrypt_cookies(entry, domain)


def _split_cookies(
    cookies: List[Dict[str, Any]], url: Optional[str], now: float
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """→ (可发送, 已过期)。``url`` 给定时按 secure / path 过滤（不计入过期）。"""
    scheme = path = ""
    if url:
        parsed = urlparse(url)
        scheme = (parsed.scheme or "").lower()
        path = parsed.path or "/"
    usable: List[Dict[str, Any]] = []
    expired: List[Dict[str, Any]] = []
    for item in cookies:
        if not isinstance(item, dict) or not item.get("name"):
            continue
        expires = item.get("expires")
        if isinstance(expires, (int, float)) and expires > 0 and expires <= now:
            expired.append(item)
            continue
        if url:
            if item.get("secure") and scheme != "https":
                continue
            if not cookie_path_matches(path, str(item.get("path") or "/")):
                continue
        usable.append(item)
    return usable, expired


def cookie_header_for(
    domain: str,
    repo: Optional[Any] = None,
    url: Optional[str] = None,
    now: Optional[float] = None,
) -> Optional[str]:
    """把档案 cookie 拼成 ``Cookie`` 头值（``n=v; n2=v2``）；无档案返回 ``None``。

    AU1：已过期 cookie 不发送；``url`` 给定时 ``secure`` cookie 只发 https、按 path
    匹配。全部过期时返回 ``None``（需要区分"无档案 / 已过期"请用 ``resolve_credential``）。
    """
    cookies = load_credential(domain, repo)
    if not cookies:
        return None
    usable, _expired = _split_cookies(cookies, url, time.time() if now is None else now)
    if not usable:
        return None
    return "; ".join(f"{item['name']}={item['value']}" for item in usable)


# --------------------------------------------------------------------------- header kind


def save_header_credential(
    domain: str,
    headers: Dict[str, str],
    repo: Optional[Any] = None,
    ttl_seconds: Optional[int] = None,
) -> None:
    """保存头部型凭据（AU4：``Authorization: Bearer …`` / API key 自定义头）。

    Args:
        domain:      凭据归属域（如 ``api.example.com`` 或 ``.example.com``），附加时同 cookie 域匹配。
        headers:     ``{"Authorization": "Bearer xxx"}``；禁止 Cookie / Host 等传输头。
        ttl_seconds: 可选有效期，过期后 ``resolve_credential`` 返回 ``expired``。
    """
    domain = (domain or "").strip().lower()
    if not domain or not headers:
        raise ValueError("save_header_credential: domain 与 headers 均不能为空")
    cleaned: Dict[str, str] = {}
    for name, value in headers.items():
        key = str(name or "").strip()
        val = str(value if value is not None else "").strip()
        if not key or not val:
            continue
        if not _HEADER_NAME_RE.match(key) or key.lower() in _FORBIDDEN_CREDENTIAL_HEADERS:
            raise ValueError(f"save_header_credential: 非法或不允许的头名 {key!r}")
        if any(ch in val for ch in "\r\n"):
            raise ValueError("save_header_credential: 头值不能包含换行")
        cleaned[key] = val
    if not cleaned:
        raise ValueError("save_header_credential: headers 中没有可保存的条目")
    store = _get_repo(repo)
    vault = _load_vault(store)
    now = _now_ms()
    vault[domain] = {
        "kind": KIND_HEADER,
        "headers_enc": encrypt_secret(
            json.dumps(cleaned, ensure_ascii=False), account=_HEADER_ACCOUNT_PREFIX + domain
        ),
        "saved_at": now,
        "updated_at": now,
        "expires_at": (now + int(ttl_seconds) * 1000) if ttl_seconds and ttl_seconds > 0 else None,
    }
    _save_vault(store, vault)


def _decrypt_headers(entry: Dict[str, Any], domain: str) -> Optional[Dict[str, str]]:
    if not entry.get("headers_enc"):
        return None
    try:
        headers = json.loads(decrypt_secret(str(entry["headers_enc"])))
    except Exception:  # noqa: BLE001
        logger.warning("头部凭据档案解密失败: %s", domain, exc_info=True)
        return None
    if not isinstance(headers, dict):
        return None
    return {str(k): str(v) for k, v in headers.items() if k}


# --------------------------------------------------------------------------- resolve


class CredentialResolution:
    """``resolve_credential`` 的结果：``status`` ∈ ok / not_found / expired。

    ``headers`` 是要附加到命中域请求上的头（cookie 档案 → ``{"Cookie": …}``，
    头部档案 → 原样头）。``expired_names`` / ``expires_in`` 供文案与 list 使用。
    """

    __slots__ = ("status", "kind", "headers", "expired_names", "expires_in", "domain")

    def __init__(
        self,
        status: str,
        kind: Optional[str] = None,
        headers: Optional[Dict[str, str]] = None,
        expired_names: Optional[List[str]] = None,
        expires_in: Optional[int] = None,
        domain: str = "",
    ) -> None:
        self.status = status
        self.kind = kind
        self.headers = headers or {}
        self.expired_names = expired_names or []
        self.expires_in = expires_in
        self.domain = domain

    @property
    def ok(self) -> bool:
        return self.status == "ok"

    def __repr__(self) -> str:  # 不回显值
        return (
            f"CredentialResolution(status={self.status!r}, kind={self.kind!r}, "
            f"headers={sorted(self.headers)!r})"
        )


def resolve_credential(  # noqa: PLR0911 — 各状态独立 return，扁平更直读
    domain: str,
    url: Optional[str] = None,
    repo: Optional[Any] = None,
    now: Optional[float] = None,
) -> CredentialResolution:
    """按档案类型解析要附加的请求头（AU1 过期过滤 + AU4 头部凭据统一入口）。"""
    domain = (domain or "").strip().lower()
    if not domain:
        return CredentialResolution("not_found", domain=domain)
    entry = _load_vault(_get_repo(repo)).get(domain)
    kind = _entry_kind(entry)
    if kind is None:
        return CredentialResolution("not_found", domain=domain)
    current = time.time() if now is None else now

    if kind == KIND_HEADER:
        headers = _decrypt_headers(entry, domain)
        if not headers:
            return CredentialResolution("not_found", kind=kind, domain=domain)
        expires_at = entry.get("expires_at")
        expires_in: Optional[int] = None
        if isinstance(expires_at, (int, float)) and expires_at > 0:
            expires_in = int(expires_at / 1000 - current)
            if expires_in <= 0:
                return CredentialResolution(
                    "expired", kind=kind, expired_names=sorted(headers), domain=domain
                )
        return CredentialResolution(
            "ok", kind=kind, headers=headers, expires_in=expires_in, domain=domain
        )

    cookies = _decrypt_cookies(entry, domain)
    if not cookies:
        return CredentialResolution("not_found", kind=kind, domain=domain)
    usable, expired = _split_cookies(cookies, url, current)
    expired_names = [str(c.get("name")) for c in expired]
    if not usable and expired:
        return CredentialResolution(
            "expired", kind=kind, expired_names=expired_names, domain=domain
        )
    expires_in = _min_expires_in(usable, current)
    headers = {"Cookie": "; ".join(f"{c['name']}={c['value']}" for c in usable)} if usable else {}
    return CredentialResolution(
        "ok",
        kind=kind,
        headers=headers,
        expired_names=expired_names,
        expires_in=expires_in,
        domain=domain,
    )


def _min_expires_in(cookies: List[Dict[str, Any]], now: float) -> Optional[int]:
    values = [
        int(c["expires"] - now)
        for c in cookies
        if isinstance(c.get("expires"), (int, float)) and c["expires"] > 0
    ]
    return min(values) if values else None


# --------------------------------------------------------------------------- Set-Cookie 回写


def parse_set_cookie(value: str, request_url: str) -> Optional[Dict[str, Any]]:
    """解析一条 ``Set-Cookie``（stdlib 手写，容忍非标值）。

    返回 ``{"name","value","domain","path","expires"?,"secure"?,"httpOnly"?,"sameSite"?,
    "host_only": bool, "delete": bool}``；``delete`` 表示 Max-Age≤0 或 Expires 已过。
    """
    if not value:
        return None
    parts = [p.strip() for p in value.split(";")]
    if not parts or "=" not in parts[0]:
        return None
    name, _, raw_value = parts[0].partition("=")
    name = name.strip()
    if not name:
        return None
    parsed_url = urlparse(request_url or "")
    request_host = (parsed_url.hostname or "").lower()
    cookie: Dict[str, Any] = {
        "name": name,
        "value": raw_value.strip(),
        "domain": request_host,
        "path": "/",
        "host_only": True,
        "delete": False,
    }
    max_age: Optional[int] = None
    expires_ts: Optional[int] = None
    for attr in parts[1:]:
        key, _, val = attr.partition("=")
        key = key.strip().lower()
        val = val.strip()
        if key == "domain" and val:
            cookie["domain"] = val.lower() if val.startswith(".") else "." + val.lower()
            cookie["host_only"] = False
        elif key == "path" and val.startswith("/"):
            cookie["path"] = val
        elif key == "max-age":
            try:
                max_age = int(val)
            except ValueError:
                max_age = None
        elif key == "expires" and val:
            try:
                expires_ts = int(parsedate_to_datetime(val).timestamp())
            except (TypeError, ValueError, IndexError, OverflowError):
                expires_ts = None
        elif key == "secure":
            cookie["secure"] = True
        elif key == "httponly":
            cookie["httpOnly"] = True
        elif key == "samesite" and val:
            cookie["sameSite"] = val
    now = int(time.time())
    if max_age is not None:
        if max_age <= 0:
            cookie["delete"] = True
        else:
            cookie["expires"] = now + max_age
    elif expires_ts is not None:
        if expires_ts <= now:
            cookie["delete"] = True
        else:
            cookie["expires"] = expires_ts
    return cookie


def merge_set_cookies(
    domain: str,
    set_cookie_values: List[str],
    request_url: str,
    repo: Optional[Any] = None,
) -> List[str]:
    """把响应 ``Set-Cookie`` 合并回 cookie 档案（AU2 续期回写）。

    只接受归属域落在档案域内的 cookie（防止把第三方 cookie 混入档案）；
    ``Max-Age≤0`` / 已过期的 Expires 视为删除。返回被更新 / 删除的 cookie 名。
    """
    domain = (domain or "").strip().lower()
    if not domain or not set_cookie_values:
        return []
    store = _get_repo(repo)
    vault = _load_vault(store)
    entry = vault.get(domain)
    if _entry_kind(entry) != KIND_COOKIE:
        return []
    cookies = _decrypt_cookies(entry, domain)
    if cookies is None:
        return []
    changed: List[str] = []
    for raw in set_cookie_values:
        parsed = parse_set_cookie(raw, request_url)
        if not parsed:
            continue
        effective_domain = str(parsed["domain"] or "")
        if not cookie_domain_matches(effective_domain.lstrip("."), domain):
            continue
        key_name, key_path = parsed["name"], parsed["path"]
        cookies = [
            c
            for c in cookies
            if not (
                isinstance(c, dict)
                and c.get("name") == key_name
                and str(c.get("path") or "/") == key_path
            )
        ]
        if not parsed["delete"]:
            stored = {k: v for k, v in parsed.items() if k not in ("host_only", "delete")}
            cookies.append(stored)
        changed.append(key_name)
    if not changed:
        return []
    if cookies:
        entry["cookies_enc"] = encrypt_secret(
            json.dumps(cookies, ensure_ascii=False), account=_VAULT_ACCOUNT_PREFIX + domain
        )
        entry["kind"] = KIND_COOKIE
        entry["updated_at"] = _now_ms()
        vault[domain] = entry
    else:
        vault.pop(domain, None)
    _save_vault(store, vault)
    return changed


# --------------------------------------------------------------------------- misc


def delete_credential(domain: str, repo: Optional[Any] = None) -> bool:
    """删除某 domain 档案；返回是否确有删除。"""
    domain = (domain or "").strip().lower()
    if not domain:
        return False
    store = _get_repo(repo)
    vault = _load_vault(store)
    if domain not in vault:
        return False
    del vault[domain]
    _save_vault(store, vault)
    return True


def list_credentials(repo: Optional[Any] = None) -> List[Dict[str, Any]]:
    """档案清单（脱敏：domain / kind / 名字列表 / 保存时间 / 最短剩余时效，不含值）。"""
    store = _get_repo(repo)
    entries: List[Dict[str, Any]] = []
    now = time.time()
    for domain, entry in sorted(_load_vault(store).items()):
        kind = _entry_kind(entry) or KIND_COOKIE
        names: List[str] = []
        expires_in: Optional[int] = None
        expired = False
        if kind == KIND_HEADER:
            headers = _decrypt_headers(entry, domain) if isinstance(entry, dict) else None
            names = sorted(headers) if headers else ["<解密失败>"]
            expires_at = entry.get("expires_at") if isinstance(entry, dict) else None
            if isinstance(expires_at, (int, float)) and expires_at > 0:
                expires_in = int(expires_at / 1000 - now)
                expired = expires_in <= 0
        else:
            cookies = _decrypt_cookies(entry, domain) if isinstance(entry, dict) else None
            if cookies is None:
                names = ["<解密失败>"]
            else:
                names = [str(item.get("name")) for item in cookies if isinstance(item, dict)]
                usable, expired_items = _split_cookies(cookies, None, now)
                expired = bool(expired_items) and not usable
                expires_in = _min_expires_in(usable, now)
        record: Dict[str, Any] = {
            "domain": domain,
            "kind": kind,
            "cookie_names": names if kind == KIND_COOKIE else [],
            "saved_at": entry.get("saved_at") if isinstance(entry, dict) else None,
            "expires_in_seconds": expires_in,
            "expired": expired,
        }
        if kind == KIND_HEADER:
            record["header_names"] = names
        entries.append(record)
    return entries


__all__ = [
    "KIND_COOKIE",
    "KIND_HEADER",
    "SETTINGS_KEY_CREDENTIAL_VAULT",
    "CredentialResolution",
    "cookie_domain_matches",
    "cookie_header_for",
    "cookie_path_matches",
    "delete_credential",
    "list_credentials",
    "load_credential",
    "looks_like_login_html",
    "looks_like_login_url",
    "merge_set_cookies",
    "parse_set_cookie",
    "resolve_credential",
    "save_credential",
    "save_header_credential",
]
