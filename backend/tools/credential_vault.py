# ruff: noqa: UP006, UP007, UP035, UP045 — release/win7 Python 3.8 兼容，保留 typing 注解
"""站点 cookie 凭据档案（方案 2026-09-13 §2.5 cookie 桥）。

CDP 浏览器里导出的 cookie 经 SecretBox 静态加密落 ``preferences`` KV
（key ``browser_credential_vault``），供 ``web_fetch`` / ``http_download``
以 ``credential_domain`` 参数引用 —— 登录墙后的资源（订阅源文献 PDF）
从此可达。

**存储格式**：``{domain: {"cookies_enc": "enc:...", "saved_at": <ms>}}``。
domain 取 CDP cookie 的 domain 属性（如 ``.cnki.net``），附加时按 RFC 6265
域匹配规则判定 host 是否命中。

**安全口径**：明文 cookie 只在单次工具调用的内存中存在；落库走
SecretBox（DPAPI/keychain，scheme=none 平台诚实降级为不包裹）；
``llm_trace.redactor`` 已对 Cookie 头日志脱敏。

py3.8 纪律：本模块同时服务 main 与 release/win7 — stdlib only。
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any, Dict, List, Optional

from backend.services.secret_box import decrypt_secret, encrypt_secret

logger = logging.getLogger(__name__)

#: preferences 表的 key（需在 ``SettingsRepository.KEYS`` 白名单内）
SETTINGS_KEY_CREDENTIAL_VAULT = "browser_credential_vault"

_VAULT_ACCOUNT_PREFIX = "browser-cookie:"


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


def cookie_domain_matches(hostname: str, cookie_domain: str) -> bool:
    """RFC 6265 域匹配：``.cnki.net`` 命中 ``cnki.net`` 及任意子域。

    ``cookie_domain`` 是 CDP cookie 的 domain 属性（可能带/不带前导点）。
    """
    host = (hostname or "").strip().lower().rstrip(".")
    domain = (cookie_domain or "").strip().lower().lstrip(".").rstrip(".")
    if not host or not domain:
        return False
    return host == domain or host.endswith("." + domain)


def save_credential(
    domain: str, cookies: List[Dict[str, Any]], repo: Optional[Any] = None
) -> None:
    """把某 cookie domain 的 cookie 列表加密存入档案（覆盖旧值）。

    Args:
        domain:  CDP cookie 的 domain 属性（如 ``.cnki.net``）。
        cookies: ``[{"name", "value", "domain", "path"}, ...]``（多余字段忽略）。
    """
    domain = (domain or "").strip().lower()
    if not domain or not cookies:
        raise ValueError("save_credential: domain 与 cookies 均不能为空")
    cleaned = [
        {
            "name": str(item.get("name") or ""),
            "value": str(item.get("value") or ""),
            "domain": str(item.get("domain") or domain),
            "path": str(item.get("path") or "/"),
        }
        for item in cookies
        if isinstance(item, dict) and item.get("name")
    ]
    if not cleaned:
        raise ValueError("save_credential: cookies 中没有可保存的条目")
    store = _get_repo(repo)
    vault = _load_vault(store)
    vault[domain] = {
        "cookies_enc": encrypt_secret(
            json.dumps(cleaned, ensure_ascii=False), account=_VAULT_ACCOUNT_PREFIX + domain
        ),
        "saved_at": int(time.time() * 1000),
    }
    _save_vault(store, vault)


def load_credential(domain: str, repo: Optional[Any] = None) -> Optional[List[Dict[str, str]]]:
    """取某 domain 的 cookie 列表（已解密）；无档案/解密失败返回 ``None``。"""
    domain = (domain or "").strip().lower()
    if not domain:
        return None
    store = _get_repo(repo)
    entry = _load_vault(store).get(domain)
    if not isinstance(entry, dict) or not entry.get("cookies_enc"):
        return None
    try:
        cookies = json.loads(decrypt_secret(str(entry["cookies_enc"])))
    except Exception:  # noqa: BLE001 — 解密失败按无档案处理（不阻断调用方）
        logger.warning("凭据档案解密失败: %s", domain, exc_info=True)
        return None
    return cookies if isinstance(cookies, list) else None


def cookie_header_for(domain: str, repo: Optional[Any] = None) -> Optional[str]:
    """把档案 cookie 拼成 ``Cookie`` 头值（``n=v; n2=v2``）；无档案返回 ``None``。"""
    cookies = load_credential(domain, repo)
    if not cookies:
        return None
    return "; ".join(
        f"{item['name']}={item['value']}" for item in cookies if item.get("name")
    )


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
    """档案清单（脱敏：只有 domain / cookie 名列表 / 保存时间，不含值）。"""
    store = _get_repo(repo)
    entries: List[Dict[str, Any]] = []
    for domain, entry in sorted(_load_vault(store).items()):
        names: List[str] = []
        if isinstance(entry, dict) and entry.get("cookies_enc"):
            try:
                cookies = json.loads(decrypt_secret(str(entry["cookies_enc"])))
                names = [str(item.get("name")) for item in cookies if isinstance(item, dict)]
            except Exception:  # noqa: BLE001 — 清单脱敏视角，解密失败标未知
                names = ["<解密失败>"]
        entries.append(
            {
                "domain": domain,
                "cookie_names": names,
                "saved_at": entry.get("saved_at") if isinstance(entry, dict) else None,
            }
        )
    return entries


__all__ = [
    "SETTINGS_KEY_CREDENTIAL_VAULT",
    "cookie_domain_matches",
    "cookie_header_for",
    "delete_credential",
    "list_credentials",
    "load_credential",
    "save_credential",
]
