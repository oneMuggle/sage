"""Security and persistence helpers for the browser-extension bridge.

Kept separate from ``browser_extension_bridge`` so the bridge module stays
below the 800-line quality gate and these helpers can be audited on their own:

- device registry persistence (SHA-256 token digests only);
- pairing-code / label normalization;
- http(s) origin/host parsing;
- conservative cookie-domain validation (reject public suffixes).
"""

from __future__ import annotations

import hashlib
import ipaddress
from typing import Any, Dict, List, Optional
from urllib.parse import urlsplit

#: SettingsRepository key holding the persisted device registry.
SETTINGS_KEY_BROWSER_EXTENSION_DEVICES = "browser_extension_devices"

MAX_LABEL_LENGTH = 64

#: Conservative public-suffix denylist for extension-supplied cookie domains.
#: A full PSL would be a new dependency; rejecting single-label suffixes plus
#: this common set prevents a malicious extension from planting a vault entry
#: for ".com" / ".co.uk" that later matches unrelated sites.
PUBLIC_SUFFIXES = frozenset(
    {
        "com",
        "net",
        "org",
        "edu",
        "gov",
        "mil",
        "int",
        "io",
        "cn",
        "uk",
        "jp",
        "kr",
        "de",
        "fr",
        "ru",
        "com.cn",
        "net.cn",
        "org.cn",
        "gov.cn",
        "edu.cn",
        "ac.cn",
        "co.uk",
        "org.uk",
        "ac.uk",
        "gov.uk",
        "co.jp",
        "ne.jp",
        "or.jp",
        "ac.jp",
    }
)


class DeviceStore:
    """Minimal persistence interface (injectable for tests)."""

    def load(self) -> List[Dict[str, Any]]:
        raise NotImplementedError

    def save(self, devices: List[Dict[str, Any]]) -> None:
        raise NotImplementedError


class SettingsDeviceStore(DeviceStore):
    """Persist the device registry in the settings KV table."""

    def load(self) -> List[Dict[str, Any]]:
        from backend.data.settings_repo import SettingsRepository

        raw = SettingsRepository().get_json(SETTINGS_KEY_BROWSER_EXTENSION_DEVICES)
        if not isinstance(raw, list):
            return []
        return [item for item in raw if isinstance(item, dict)]

    def save(self, devices: List[Dict[str, Any]]) -> None:
        from backend.data.settings_repo import SettingsRepository

        SettingsRepository().set_json(
            SETTINGS_KEY_BROWSER_EXTENSION_DEVICES, devices, category="network"
        )


class InMemoryDeviceStore(DeviceStore):
    """Test double that keeps the registry in a list."""

    def __init__(self, initial: Optional[List[Dict[str, Any]]] = None) -> None:
        self.devices = list(initial or [])

    def load(self) -> List[Dict[str, Any]]:
        return [dict(item) for item in self.devices]

    def save(self, devices: List[Dict[str, Any]]) -> None:
        self.devices = [dict(item) for item in devices]


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def normalize_code(raw: str) -> str:
    return "".join(ch for ch in (raw or "").upper() if ch.isalnum())[:64]


def sanitize_label(raw: str) -> str:
    label = " ".join((raw or "").split()).strip()
    return label[:MAX_LABEL_LENGTH] or "浏览器扩展"


def http_origin(url: str) -> str:
    """Return the http(s) origin of *url*, or an empty string."""
    try:
        parsed = urlsplit((url or "").strip())
    except ValueError:
        return ""
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        return ""
    return f"{parsed.scheme}://{parsed.netloc.lower()}"


def http_host(url: str) -> str:
    try:
        parsed = urlsplit((url or "").strip())
    except ValueError:
        return ""
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        return ""
    return parsed.hostname.lower()


def is_safe_cookie_domain(shared_host: str, cookie_domain: str) -> bool:
    """Only accept the shared host itself or a real parent domain.

    Rejects public suffixes (``com``, ``co.uk``, …) and suffix games on IP
    hosts, which would otherwise let an extension plant a vault entry that
    matches unrelated sites.
    """
    host = (shared_host or "").strip().lower().rstrip(".")
    domain = (cookie_domain or "").strip().lower().lstrip(".").rstrip(".")
    if not host or not domain:
        return False
    try:
        ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        return domain == host
    if domain in PUBLIC_SUFFIXES or "." not in domain:
        return False
    return host == domain or host.endswith("." + domain)


__all__ = [
    "DeviceStore",
    "InMemoryDeviceStore",
    "MAX_LABEL_LENGTH",
    "PUBLIC_SUFFIXES",
    "SETTINGS_KEY_BROWSER_EXTENSION_DEVICES",
    "SettingsDeviceStore",
    "hash_token",
    "http_host",
    "http_origin",
    "is_safe_cookie_domain",
    "normalize_code",
    "sanitize_label",
]
