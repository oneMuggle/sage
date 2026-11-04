"""External browser extension bridge (Manus-style daily-browser sharing).

The user installs a small MV3 extension in their everyday Chrome/Edge, pairs
it with Sage through a short-lived code, and explicitly shares one tab.  The
extension long-polls this backend and forwards each command to the shared tab
through ``chrome.debugger`` (raw CDP).  ``browser_cdp`` exposes the shared tab
as a regular ``BrowserSession`` of type ``EXTERNAL``, so the existing
``browser_*`` tools work unchanged.

Security boundaries: device tokens are stored as SHA-256 only; pairing codes
are single-use with a short TTL and failure limit; at most one shared tab
exists; only an allow-list of CDP methods is forwarded, and target-scoped
commands must reference the shared tab; extension I/O routes authenticate
every request here; session snapshots only accept cookies/localStorage that
match the shared tab's host/origin.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import hmac
import logging
import secrets
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from backend.design.async_bridge import run_sync
from backend.services.browser_extension_security import (
    SETTINGS_KEY_BROWSER_EXTENSION_DEVICES,
    DeviceStore,
    InMemoryDeviceStore,
    SettingsDeviceStore,
    hash_token,
    http_host,
    http_origin,
    is_safe_cookie_domain,
    normalize_code,
    sanitize_label,
)

logger = logging.getLogger(__name__)

#: Fixed BrowserSession id for the user's shared tab (single shared tab in P0).
EXTENSION_BROWSER_ID = "external"

#: Placeholder executable shown in tool results.
EXTENSION_EXECUTABLE = "(browser-extension)"

#: Pairing code lifetime and alphabet (no 0/O/1/I to avoid transcription errors).
PAIRING_TTL_SECONDS = 300.0
PAIRING_CODE_LENGTH = 10
_PAIRING_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
MAX_PAIRING_FAILURES = 5
#: After too many wrong attempts, pause pairing briefly without destroying the
#: current code (an unauthenticated caller must not be able to invalidate it).
PAIRING_LOCK_SECONDS = 30.0

#: Device limits.
MAX_DEVICES = 5

#: Long-poll window and command timeout.  The extension re-polls immediately,
#: so a healthy bridge adds at most a few milliseconds of latency.
POLL_TIMEOUT_SECONDS = 20.0
COMMAND_TIMEOUT_SECONDS = 30.0

#: A device that has not polled for this long is considered offline.
OFFLINE_AFTER_SECONDS = 90.0

#: Maximum serialized command result accepted from the extension (screenshots).
MAX_RESULT_BYTES = 8 * 1024 * 1024

#: CDP methods the bridge is willing to forward to the shared tab.
#:
#: The existing browser tools only need this subset.  Methods that could open
#: or close user tabs, control the whole browser, or attach other targets are
#: deliberately absent; they raise ``unsupported_method``.
ALLOWED_CDP_METHODS = frozenset(
    {
        "Browser.getVersion",
        "DOM.getDocument",
        "DOM.querySelector",
        "Input.dispatchKeyEvent",
        "Input.dispatchMouseEvent",
        "Input.insertText",
        "Network.enable",
        "Network.getCookies",
        "Page.addScriptToEvaluateOnNewDocument",
        "Page.captureScreenshot",
        "Page.enable",
        "Page.getLayoutMetrics",
        "Page.navigate",
        "Runtime.enable",
        "Runtime.evaluate",
        "Target.getTargets",
    }
)

#: Methods that are rejected with an explicit reason (better UX than unknown).
BLOCKED_CDP_METHODS = frozenset(
    {
        "Browser.close",
        "Browser.crash",
        "Target.activateTarget",
        "Target.attachToTarget",
        "Target.closeTarget",
        "Target.createTarget",
        "Target.detachFromTarget",
    }
)


class BrowserExtensionError(RuntimeError):
    """Base error with a stable machine-readable ``code``."""

    code = "browser_extension_error"


class PairingError(BrowserExtensionError):
    """Pairing code missing/expired/wrong, or device limit reached."""

    code = "invalid_pairing_code"


class ExtensionAuthError(BrowserExtensionError):
    """Unknown or revoked device token."""

    code = "extension_unauthorized"


class SharedTabError(BrowserExtensionError):
    """No shared tab, or another device already holds the share."""

    code = "shared_tab_error"


class UnsupportedCommandError(BrowserExtensionError):
    """CDP method outside the bridge allow-list."""

    code = "unsupported_method"


class CommandTimeoutError(BrowserExtensionError):
    """The extension did not answer within the command timeout."""

    code = "extension_timeout"


# ---------------------------------------------------------------------------
# Device persistence
# ---------------------------------------------------------------------------


def _session_manager():
    """Indirection for tests (monkeypatch to avoid touching the real manager)."""
    from backend.tools.browser_cdp import get_browser_manager

    return get_browser_manager()


def extension_directory() -> Optional[str]:
    """Locate the unpacked extension directory for the settings UI.

    Dev checkout: ``<repo>/extension/agent-bridge``.
    Packaged app: ``<resources>/extension/agent-bridge`` (extraResources).
    """
    root = Path(__file__).resolve().parents[2]
    candidate = root / "extension" / "agent-bridge"
    return str(candidate) if candidate.is_dir() else None


class BrowserExtensionBridge:
    """Process-wide bridge between the extension and ``browser_*`` tools."""

    def __init__(
        self,
        store: Optional[DeviceStore] = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._store = store or SettingsDeviceStore()
        self._clock = clock
        self._lock = threading.RLock()

        self._devices: Dict[str, Dict[str, Any]] = {}
        self._loaded = False

        self._pairing_code = ""
        self._pairing_expires_at = 0.0
        self._pairing_failures = 0
        self._pairing_locked_until = 0.0

        #: Currently shared tab.  Owned by the bridge loop, guarded by _lock
        #: because tools and status endpoints read it from other threads.
        self._shared: Optional[Dict[str, Any]] = None

        #: Per-device command queue (loop-owned).
        self._queues: Dict[str, asyncio.Queue] = {}
        #: command_id -> Future (loop-owned).
        self._pending: Dict[str, asyncio.Future] = {}

    # -- pairing ---------------------------------------------------------

    def _ensure_loaded(self) -> None:
        """Load persisted devices once, off the import path.

        The module-level singleton must not touch the database at import time
        (``browser_cdp`` and the FastAPI app import this module early); failing
        to read the registry degrades to "no paired devices" rather than
        breaking startup.
        """
        with self._lock:
            if self._loaded:
                return
            self._loaded = True
            try:
                items = self._store.load()
            except Exception:  # noqa: BLE001 — startup must survive a broken DB
                logger.warning("读取浏览器扩展设备列表失败", exc_info=True)
                items = []
            for item in items:
                device_id = str(item.get("device_id") or "")
                token_hash = str(item.get("token_sha256") or "")
                if device_id and len(token_hash) == 64:
                    self._devices[device_id] = {
                        "device_id": device_id,
                        "label": sanitize_label(str(item.get("label") or "")),
                        "token_sha256": token_hash,
                        "created_at": float(item.get("created_at") or 0),
                        "last_seen_at": 0.0,
                    }

    def issue_pairing_code(self) -> Dict[str, Any]:
        """Generate a fresh single-use pairing code (invalidates the previous)."""
        code = "".join(secrets.choice(_PAIRING_ALPHABET) for _ in range(PAIRING_CODE_LENGTH))
        expires_at = self._clock() + PAIRING_TTL_SECONDS
        with self._lock:
            self._pairing_code = code
            self._pairing_expires_at = expires_at
            self._pairing_failures = 0
            self._pairing_locked_until = 0.0
        return {"code": code, "expires_at": int(expires_at)}

    def pair(self, code: str, label: str = "") -> Dict[str, Any]:
        """Exchange a pairing code for a device token (returned exactly once)."""
        self._ensure_loaded()
        submitted = normalize_code(code)
        with self._lock:
            now = self._clock()
            if now < self._pairing_locked_until:
                raise PairingError("配对尝试次数过多，请稍后重试")
            if (
                not self._pairing_code
                or now >= self._pairing_expires_at
                or not submitted
                or not hmac.compare_digest(submitted, self._pairing_code)
            ):
                self._pairing_failures += 1
                if self._pairing_failures >= MAX_PAIRING_FAILURES:
                    # Pause instead of clearing the code: an unauthenticated
                    # caller must not be able to destroy a valid pairing code.
                    self._pairing_failures = 0
                    self._pairing_locked_until = now + PAIRING_LOCK_SECONDS
                raise PairingError("配对码无效或已过期，请在 Sage 设置页重新生成")
            if len(self._devices) >= MAX_DEVICES:
                raise PairingError(f"已配对设备达到上限 {MAX_DEVICES}，请先撤销旧设备")
            self._pairing_code = ""
            self._pairing_expires_at = 0.0
            self._pairing_failures = 0
            self._pairing_locked_until = 0.0

            device_id = "dev_" + secrets.token_hex(8)
            token = secrets.token_urlsafe(32)
            now = self._clock()
            device = {
                "device_id": device_id,
                "label": sanitize_label(label),
                "token_sha256": hash_token(token),
                "created_at": now,
                "last_seen_at": 0.0,
            }
            self._devices[device_id] = device
            self._save_locked()
        return {
            "device_id": device_id,
            "device_token": token,
            "label": device["label"],
        }

    # -- device registry -------------------------------------------------

    def list_devices(self) -> List[Dict[str, Any]]:
        """Masked device list for the settings UI (no token material)."""
        self._ensure_loaded()
        now = self._clock()
        with self._lock:
            shared_device = (self._shared or {}).get("device_id")
            return [
                {
                    "device_id": device["device_id"],
                    "label": device["label"],
                    "created_at": int(device.get("created_at") or 0),
                    "last_seen_at": int(device.get("last_seen_at") or 0),
                    "connected": bool(
                        device.get("last_seen_at")
                        and now - float(device["last_seen_at"]) < OFFLINE_AFTER_SECONDS
                    ),
                    "sharing": device["device_id"] == shared_device,
                }
                for device in sorted(
                    self._devices.values(), key=lambda item: item.get("created_at", 0)
                )
            ]

    def revoke_device(self, device_id: str) -> bool:
        """Remove a device and detach its shared tab (if any)."""
        self._ensure_loaded()
        with self._lock:
            if device_id not in self._devices:
                return False
            del self._devices[device_id]
            self._save_locked()
        try:
            run_sync(self._detach_async(device_id, reason="revoked"), timeout=5)
        except concurrent.futures.TimeoutError:
            logger.warning("撤销扩展设备时清理会话超时（设备已移除）")
        return True

    def _save_locked(self) -> None:
        try:
            self._store.save(
                [
                    {
                        "device_id": device["device_id"],
                        "label": device["label"],
                        "token_sha256": device["token_sha256"],
                        "created_at": device["created_at"],
                    }
                    for device in self._devices.values()
                ]
            )
        except Exception:  # noqa: BLE001 — persistence failure must not break the live bridge
            logger.warning("浏览器扩展设备列表持久化失败", exc_info=True)

    def _authenticate(self, token: str) -> Dict[str, Any]:
        self._ensure_loaded()
        if not token:
            raise ExtensionAuthError("缺少扩展设备凭据")
        digest = hash_token(token)
        with self._lock:
            for device in self._devices.values():
                if hmac.compare_digest(digest, device["token_sha256"]):
                    return dict(device)
        raise ExtensionAuthError("扩展设备凭据无效或已被撤销")

    # -- long poll / command dispatch -----------------------------------

    def poll(self, token: str, tab: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        """Block for up to ``POLL_TIMEOUT_SECONDS`` and return one command."""
        device = self._authenticate(token)
        try:
            return run_sync(
                self._poll_async(device, tab), timeout=POLL_TIMEOUT_SECONDS + 5.0
            )
        except concurrent.futures.TimeoutError:
            # Shared-loop stall: let the extension re-poll rather than 500.
            logger.warning("浏览器扩展轮询等待超时（后台事件循环繁忙）")
            return None

    async def _poll_async(
        self, device: Dict[str, Any], tab: Optional[Dict[str, Any]]
    ) -> Optional[Dict[str, Any]]:
        device_id = device["device_id"]
        now = self._clock()
        with self._lock:
            stored = self._devices.get(device_id)
            if stored is None:
                raise ExtensionAuthError("扩展设备已被撤销")
            stored["last_seen_at"] = now

        if tab:
            self._update_shared(device, tab)
        else:
            await self._detach_async(device_id, reason="tab_unshared")

        queue = self._queues.get(device_id)
        if queue is None:
            queue = asyncio.Queue()
            self._queues[device_id] = queue
        try:
            command = await asyncio.wait_for(queue.get(), timeout=POLL_TIMEOUT_SECONDS)
        except asyncio.TimeoutError:  # noqa: UP041 — py3.8 不同源
            return None
        return command

    def _update_shared(self, device: Dict[str, Any], tab: Dict[str, Any]) -> None:
        device_id = device["device_id"]
        tab_id = tab.get("id")
        url = str(tab.get("url") or "")
        origin = http_origin(url)
        if tab_id is None or not origin:
            raise SharedTabError("共享的标签页必须是 http/https 页面")
        title = " ".join(str(tab.get("title") or "").split())[:200]
        with self._lock:
            current = self._shared
            if current is not None and current["device_id"] != device_id:
                raise SharedTabError("另一个设备已在共享标签页，请先停止那边的共享")
            self._shared = {
                "device_id": device_id,
                "tab_id": str(tab_id),
                "url": url,
                "origin": origin,
                "host": http_host(url),
                "title": title,
                "shared_at": self._clock(),
            }
        try:
            self._ensure_session(device_id, tab)
        except Exception as exc:  # noqa: BLE001 — translate to a clean 409
            with self._lock:
                if self._shared and self._shared["device_id"] == device_id:
                    self._shared = None
            raise SharedTabError(f"无法注册共享标签页: {str(exc)[:200]}") from exc

    def _ensure_session(self, device_id: str, tab: Dict[str, Any]) -> None:
        """Register (or refresh) the EXTERNAL BrowserSession."""
        from backend.tools.browser_cdp import BrowserSession, BrowserType

        manager = _session_manager()
        existing = manager.get(EXTENSION_BROWSER_ID)
        if existing is not None:
            existing.external_device_id = device_id
            existing.external_tab_id = str(tab.get("id") or "")
            return
        session = BrowserSession(
            browser_id=EXTENSION_BROWSER_ID,
            executable=EXTENSION_EXECUTABLE,
            headless=False,
            user_data_dir="",
            process=_ExternalProcess(),
            port=0,
            ws_path="",
            persistent=True,
            profile_name="browser-extension",
            browser_type=BrowserType.EXTERNAL,
            external_device_id=device_id,
        )
        session.external_tab_id = str(tab.get("id") or "")
        manager.register(session)

    async def _detach_async(self, device_id: str, reason: str = "") -> None:
        with self._lock:
            current = self._shared
            if current is None or current["device_id"] != device_id:
                return
            self._shared = None
        # Fail in-flight commands so tools do not wait for the timeout.
        for command_id, future in list(self._pending.items()):
            if not future.done():
                future.set_exception(
                    SharedTabError(f"标签页共享已停止（{reason or 'detached'}）")
                )
            self._pending.pop(command_id, None)
        self._queues.pop(device_id, None)
        try:
            _session_manager().remove(EXTENSION_BROWSER_ID)
        except Exception:  # noqa: BLE001 — session cleanup is best-effort
            logger.debug("清理外部浏览器会话失败", exc_info=True)

    def detach(self, token: str, reason: str = "user") -> None:
        device = self._authenticate(token)
        try:
            run_sync(self._detach_async(device["device_id"], reason=reason), timeout=5)
        except concurrent.futures.TimeoutError:
            logger.warning("停止共享时清理会话超时（后端将继续轮询清理）")

    # -- command execution ----------------------------------------------

    def execute_cdp(
        self,
        method: str,
        params: Optional[Dict[str, Any]] = None,
        target_id: Optional[str] = None,
        timeout: float = COMMAND_TIMEOUT_SECONDS,
    ) -> Dict[str, Any]:
        """Send one CDP command to the shared tab (sync call from tool threads)."""
        try:
            return run_sync(
                self._execute_cdp_async(method, params or {}, target_id, timeout),
                timeout=timeout + 5.0,
            )
        except concurrent.futures.TimeoutError as exc:
            raise CommandTimeoutError(
                f"浏览器扩展桥等待超时（{method}）"
            ) from exc

    async def _execute_cdp_async(
        self,
        method: str,
        params: Dict[str, Any],
        target_id: Optional[str],
        timeout: float,
    ) -> Dict[str, Any]:
        if method in BLOCKED_CDP_METHODS:
            raise UnsupportedCommandError(f"扩展桥不支持 {method}（不操作用户其它标签页/浏览器）")
        if method not in ALLOWED_CDP_METHODS:
            raise UnsupportedCommandError(f"扩展桥未开放 CDP 方法 {method}")

        with self._lock:
            shared = dict(self._shared) if self._shared else None
            if shared is None:
                raise SharedTabError(
                    "浏览器扩展未共享标签页：请在扩展弹窗中点击「共享此标签页」"
                )
            device = self._devices.get(shared["device_id"])
            if device is None or (
                not device.get("last_seen_at")
                or self._clock() - float(device["last_seen_at"]) > OFFLINE_AFTER_SECONDS
            ):
                raise SharedTabError("浏览器扩展已离线，请确认浏览器仍打开")
            if target_id and str(target_id) != str(shared["tab_id"]):
                raise SharedTabError("目标标签页不是用户共享的标签页")
            device_id = shared["device_id"]
            shared_url = shared["url"]

        if method == "Network.getCookies":
            # CDP defaults to "all page targets" when urls is omitted.  Force
            # the shared tab URL so cookies from other user tabs never cross
            # the bridge (cookie export still gets parent-domain cookies).
            params = {"urls": [shared_url]}

        command_id = "cmd-" + uuid.uuid4().hex
        future: asyncio.Future = asyncio.get_running_loop().create_future()
        self._pending[command_id] = future
        command = {
            "id": command_id,
            "method": method,
            "params": params,
            "deadline": self._clock() + timeout,
        }
        queue = self._queues.get(device_id)
        if queue is None:
            queue = asyncio.Queue()
            self._queues[device_id] = queue
        queue.put_nowait(command)
        try:
            result = await asyncio.wait_for(future, timeout=timeout)
        except asyncio.TimeoutError as exc:  # noqa: UP041 — py3.8 不同源
            raise CommandTimeoutError(
                f"浏览器扩展未在 {timeout:.0f} 秒内响应（{method}）"
            ) from exc
        finally:
            self._pending.pop(command_id, None)
        return result if isinstance(result, dict) else {"result": result}

    def submit_result(
        self,
        token: str,
        command_id: str,
        ok: bool,
        result: Any = None,
        error: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """Resolve a pending command with the extension's reply."""
        device = self._authenticate(token)
        try:
            return bool(
                run_sync(
                    self._resolve_async(device["device_id"], command_id, ok, result, error),
                    timeout=5,
                )
            )
        except concurrent.futures.TimeoutError:
            logger.warning("回传扩展命令结果超时（命令可能已超时）")
            return False

    async def _resolve_async(
        self,
        device_id: str,
        command_id: str,
        ok: bool,
        result: Any,
        error: Optional[Dict[str, Any]],
    ) -> bool:
        future = self._pending.get(command_id)
        if future is None or future.done():
            return False
        with self._lock:
            shared = self._shared
            if shared is None or shared["device_id"] != device_id:
                return False
        if ok:
            future.set_result(result if result is not None else {})
        else:
            message = ""
            if isinstance(error, dict):
                message = str(error.get("message") or "")
            future.set_exception(
                BrowserExtensionError(message[:500] or "扩展执行命令失败")
            )
        return True

    # -- session snapshot -------------------------------------------------

    def sync_session(self, token: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Persist the shared tab's cookies/localStorage into the vault.

        Values are encrypted by ``credential_vault`` and never returned.
        """
        device = self._authenticate(token)
        with self._lock:
            shared = dict(self._shared) if self._shared else None
            if shared is None or shared["device_id"] != device["device_id"]:
                raise SharedTabError("请先在扩展中共享标签页，再保存登录状态")
            shared_url = shared["url"]
            shared_host = shared["host"]
            shared_origin = shared["origin"]

        submitted_url = str(payload.get("url") or "")
        if http_host(submitted_url) != shared_host:
            raise SharedTabError("提交的页面与共享标签页不一致")
        cookies = payload.get("cookies")
        if not isinstance(cookies, list):
            cookies = []
        if len(cookies) > 500:
            raise SharedTabError("cookie 数量超过上限 500")

        from backend.tools.credential_vault import (
            cookie_domain_matches,
            list_credentials,
            save_credential,
            save_storage_state,
        )

        try:
            header_domains = {
                str(record.get("domain") or "").lower()
                for record in list_credentials()
                if str(record.get("kind") or "") == "header"
            }
        except Exception:  # noqa: BLE001 — vault read failure must not leak values
            logger.warning("读取既有 header 凭据失败，按无冲突处理", exc_info=True)
            header_domains = set()

        by_domain: Dict[str, List[Dict[str, Any]]] = {}
        for cookie in cookies:
            if not isinstance(cookie, dict) or not cookie.get("name"):
                continue
            cookie_domain = str(cookie.get("domain") or "").lower()
            if not cookie_domain:
                continue
            if not cookie_domain_matches(shared_host, cookie_domain):
                continue
            if not is_safe_cookie_domain(shared_host, cookie_domain):
                continue
            by_domain.setdefault(cookie_domain, []).append(cookie)

        raw_origins = payload.get("origins")
        origins: List[Dict[str, Any]] = []
        if isinstance(raw_origins, list):
            for item in raw_origins[:50]:
                if not isinstance(item, dict):
                    continue
                origin = str(item.get("origin") or "")
                storage = item.get("localStorage")
                if origin != shared_origin or not isinstance(storage, dict):
                    continue
                cleaned = {
                    str(key): str(value)
                    for key, value in storage.items()
                    if isinstance(key, str) and isinstance(value, str) and value
                }
                if cleaned:
                    origins.append({"origin": origin, "localStorage": cleaned})

        if not by_domain and not origins:
            raise SharedTabError("当前页面没有可保存的登录状态")
        if not by_domain:
            # The vault is keyed by cookie domain; a localStorage-only origin
            # cannot be represented without a fake cookie, so fail honestly.
            raise SharedTabError("当前页面没有可保存的 Cookie（仅有 localStorage）")

        saved: List[Dict[str, Any]] = []
        skipped: List[str] = []
        for domain, domain_cookies in sorted(by_domain.items()):
            if domain in header_domains:
                # Never let a cookie sync silently downgrade an existing
                # header credential (e.g. API token) for the same domain.
                skipped.append(domain)
                continue
            has_storage = bool(origins) and any(
                cookie_domain_matches(http_host(origin_entry["origin"]), domain)
                for origin_entry in origins
            )
            if has_storage:
                save_storage_state(
                    domain,
                    domain_cookies,
                    origins,
                    source_profile="browser-extension",
                )
            else:
                save_credential(
                    domain, domain_cookies, source_profile="browser-extension"
                )
            saved.append(
                {
                    "domain": domain,
                    "count": len(domain_cookies),
                    "has_storage": has_storage,
                }
            )
        if not saved:
            raise SharedTabError("目标域名的凭据未被覆盖（已有 header 凭据）")
        return {
            "saved": saved,
            "skipped": skipped,
            "total_cookies": sum(item["count"] for item in saved),
            "has_storage": bool(origins),
            "shared_url": shared_url,
        }

    # -- status -----------------------------------------------------------

    def shared_summary(self) -> Optional[Dict[str, Any]]:
        with self._lock:
            shared = self._shared
            if shared is None:
                return None
            return {
                "device_id": shared["device_id"],
                "origin": shared["origin"],
                "host": shared["host"],
                "title": shared["title"],
                "shared_at": int(shared["shared_at"]),
            }

    def reset_for_tests(self) -> None:
        """Drop in-memory state (not persisted devices)."""
        with self._lock:
            self._shared = None
            self._pairing_code = ""
            self._pairing_expires_at = 0.0
            self._pairing_failures = 0
            self._pairing_locked_until = 0.0
        self._queues.clear()
        self._pending.clear()


class _ExternalProcess:
    """Fake process handle: the user's browser owns the session lifetime."""

    pid = 0

    def poll(self) -> Optional[int]:
        return None

    def terminate(self) -> None:
        return None

    def kill(self) -> None:
        return None

    def wait(self, timeout: Optional[float] = None) -> int:
        return 0


#: Process-wide singleton used by routes and ``browser_cdp``.
browser_extension_bridge = BrowserExtensionBridge()


__all__ = [
    "ALLOWED_CDP_METHODS",
    "BLOCKED_CDP_METHODS",
    "BrowserExtensionBridge",
    "BrowserExtensionError",
    "CommandTimeoutError",
    "EXTENSION_BROWSER_ID",
    "EXTENSION_EXECUTABLE",
    "ExtensionAuthError",
    "InMemoryDeviceStore",
    "MAX_RESULT_BYTES",
    "OFFLINE_AFTER_SECONDS",
    "POLL_TIMEOUT_SECONDS",
    "PairingError",
    "SETTINGS_KEY_BROWSER_EXTENSION_DEVICES",
    "SharedTabError",
    "UnsupportedCommandError",
    "browser_extension_bridge",
    "extension_directory",
]
