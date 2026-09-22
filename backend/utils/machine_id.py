"""Stable per-machine identifier for arena credential key derivation.

Spec: docs/superpowers/specs/2026-09-16-arena-automation-model-probe-design.md §7.1
    machine_id = hash(hostname + username + machine GUID)
      - Windows: registry ``HKLM\\SOFTWARE\\Microsoft\\Cryptography\\MachineGuid``
      - Linux:   ``/etc/machine-id`` (fallback ``/var/lib/dbus/machine-id``)
      - other:   ``uuid.getnode()`` (MAC) so the function stays total

Non-ASCII usernames are common on this codebase's target platform (Chinese
Windows accounts), so every component is encoded UTF-8 with ``errors="replace"``
— derivation must never raise.
"""

from __future__ import annotations

import hashlib
import logging
import socket
import uuid
from typing import Optional

logger = logging.getLogger(__name__)

_cached: Optional[str] = None


def _windows_machine_guid() -> str:
    """Read MachineGuid from the registry; empty string when unavailable."""
    try:
        import winreg
    except ImportError:  # non-Windows
        return ""
    try:
        key = winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Cryptography"
        )
    except OSError as exc:
        logger.debug("MachineGuid key unavailable: %s", exc)
        return ""
    try:
        value, _ = winreg.QueryValueEx(key, "MachineGuid")
        return str(value or "").strip()
    except OSError as exc:
        logger.debug("MachineGuid value unavailable: %s", exc)
        return ""
    finally:
        winreg.CloseKey(key)


def _linux_machine_id() -> str:
    for path in ("/etc/machine-id", "/var/lib/dbus/machine-id"):
        try:
            with open(path, encoding="utf-8") as handle:
                value = handle.read().strip()
        except OSError:
            continue
        if value:
            return value
    return ""


def hardware_id() -> str:
    """Platform machine GUID, falling back to the MAC address."""
    value = _windows_machine_guid() or _linux_machine_id()
    if value:
        return value
    try:
        return "mac-%d" % uuid.getnode()
    except Exception:  # noqa: BLE001 — derivation must stay total
        return "mac-unknown"


def machine_id() -> str:
    """Return the cached 64-hex machine identifier (spec §7.1)."""
    global _cached
    if _cached:
        return _cached
    components = []
    try:
        components.append(socket.gethostname() or "")
    except Exception:  # noqa: BLE001
        components.append("")
    try:
        import getpass

        components.append(getpass.getuser() or "")
    except Exception:  # noqa: BLE001
        components.append("")
    components.append(hardware_id())
    blob = "|".join(components).encode("utf-8", "replace")
    _cached = hashlib.sha256(blob).hexdigest()
    return _cached


def reset_cache() -> None:
    """Drop the cached value (test hook)."""
    global _cached
    _cached = None
