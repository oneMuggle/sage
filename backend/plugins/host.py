"""Out-of-process host for Python plugins (R83).

The database lifecycle state (``installed/enabled/...``) deliberately does
not imply that code is running.  A plugin process is started only by an
explicit call to :meth:`PluginHostManager.start`; application startup never
auto-starts persisted ``enabled`` records.

The host is a crash-isolation and supervision boundary, not an OS security
sandbox.  Plugin code runs in a child Python process as the current OS user,
with a whitelisted environment, bounded stdio JSON-RPC messages, request
timeouts, and best-available platform memory/CPU limits.
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import sys
import threading
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence

from backend.domain.plugin import FiberState
from backend.plugins.host_process import (
    PROTOCOL_VERSION,
    PluginHostError,
    PluginHostLimits,
    PluginRuntimeStatus,
    _PluginProcess,
    _truncate,
)
from backend.plugins.lifecycle import PluginRecord, PluginStatus
from backend.plugins.manifest import CapabilityType, PluginCapability, PluginManifest
from backend.plugins.registry import (
    CapabilityConflictError,
    CapabilityRegistry,
    get_capability_registry,
)

logger = logging.getLogger(__name__)

_WORKER_SCRIPT = Path(__file__).resolve().with_name("host_worker.py")


def _validate_entry_point(entry_point: str) -> str:
    value = entry_point.strip()
    if not value or value.count(":") > 1:
        raise PluginHostError(
            "INVALID_ENTRY_POINT",
            f"invalid plugin entry_point: {entry_point!r}",
            status_code=422,
        )
    paths = value.split(":", 1) if ":" in value else [value]
    for path in paths:
        if not path or any(not part.isidentifier() for part in path.split(".")):
            raise PluginHostError(
                "INVALID_ENTRY_POINT",
                f"invalid plugin entry_point: {entry_point!r}",
                status_code=422,
            )
    return value




class PluginHostManager:
    """Owns all plugin worker sessions for one backend process."""

    def __init__(
        self,
        limits: Optional[PluginHostLimits] = None,
        *,
        registry: Optional[CapabilityRegistry] = None,
        python_executable: Optional[str] = None,
        worker_script: Optional[Path] = None,
    ) -> None:
        self._limits = limits or PluginHostLimits()
        self._registry = registry if registry is not None else get_capability_registry()
        self._python_executable = python_executable or sys.executable
        self._worker_script = Path(worker_script) if worker_script is not None else _WORKER_SCRIPT
        self._sessions: Dict[str, _PluginProcess] = {}
        self._sessions_lock = threading.RLock()
        self._plugin_locks: Dict[str, threading.RLock] = {}
        self._restart_counts: Dict[str, int] = {}
        self._registry_lock = threading.RLock()

    @property
    def registry(self) -> CapabilityRegistry:
        return self._registry

    @property
    def limits(self) -> PluginHostLimits:
        return self._limits

    def start(self, record: PluginRecord) -> PluginRuntimeStatus:
        with self._plugin_lock(record.name):
            return self._start_locked(record)

    def restart(self, record: PluginRecord) -> PluginRuntimeStatus:
        with self._plugin_lock(record.name):
            self._stop_locked(record.name)
            self._restart_counts[record.name] = self._restart_counts.get(record.name, 0) + 1
            return self._start_locked(record)

    def stop(self, plugin_name: str) -> PluginRuntimeStatus:
        with self._plugin_lock(plugin_name):
            return self._stop_locked(plugin_name)

    def status(self, plugin_name: str) -> PluginRuntimeStatus:
        session = self._get_session(plugin_name)
        if session is None:
            return PluginRuntimeStatus(
                plugin_name=plugin_name,
                restart_count=self._restart_counts.get(plugin_name, 0),
                limits=self._limits,
            )
        transitioned = session.reconcile()
        status = session.snapshot()
        if transitioned or status.state == FiberState.FAILED:
            self._unregister(plugin_name)
        return status

    def invoke(
        self,
        plugin_name: str,
        capability_name: str,
        arguments: Optional[Dict[str, Any]] = None,
    ) -> Any:
        session = self._get_session(plugin_name)
        if session is None:
            raise PluginHostError(
                "PLUGIN_NOT_RUNNING",
                f"plugin runtime is not running: {plugin_name}",
                status_code=409,
            )
        try:
            return session.invoke(capability_name, dict(arguments or {}))
        finally:
            if session.state == FiberState.FAILED:
                self._unregister(plugin_name)

    def shutdown_all(self) -> None:
        with self._sessions_lock:
            names = list(self._sessions.keys())
        for name in names:
            with contextlib.suppress(Exception):
                self.stop(name)

    def _start_locked(self, record: PluginRecord) -> PluginRuntimeStatus:
        existing = self._get_session(record.name)
        if existing is not None:
            existing.reconcile()
            if existing.running:
                return existing.snapshot()
            self._unregister(record.name)
            existing.stop()

        status_value = str(getattr(record.status, "value", record.status))
        if status_value != PluginStatus.ENABLED.value:
            raise PluginHostError(
                "PLUGIN_NOT_ENABLED",
                "only an enabled plugin record can start a runtime "
                f"(current status: {status_value})",
                status_code=409,
            )

        root = Path(record.install_path).expanduser()
        if not root.is_dir():
            raise PluginHostError(
                "PLUGIN_INSTALL_PATH_NOT_FOUND",
                f"plugin install_path is not a directory: {record.install_path}",
                status_code=422,
            )
        root = root.resolve()
        manifest = self._load_manifest(record, root)
        capabilities = self._supported_capabilities(manifest)
        try:
            json.dumps(record.config)
        except (TypeError, ValueError) as exc:
            raise PluginHostError(
                "INVALID_PLUGIN_CONFIG",
                "plugin config is not JSON serializable",
                status_code=422,
            ) from exc

        self._check_registry_conflicts(record.name, capabilities)
        session = _PluginProcess(
            plugin_name=record.name,
            plugin_root=root,
            capabilities=capabilities,
            config=record.config,
            limits=self._limits,
            restart_count=self._restart_counts.get(record.name, 0),
            python_executable=self._python_executable,
            worker_script=self._worker_script,
        )
        with self._sessions_lock:
            self._sessions[record.name] = session

        try:
            status = session.start()
            self._register_proxies(record.name, capabilities)
        except PluginHostError:
            self._unregister(record.name)
            if session.state != FiberState.FAILED:
                session.stop()
            raise
        except Exception as exc:  # noqa: BLE001 - host boundary
            self._unregister(record.name)
            session.stop()
            raise PluginHostError(
                "PLUGIN_WORKER_START_FAILED",
                f"could not start plugin runtime: {type(exc).__name__}: {_truncate(exc)}",
                status_code=502,
            ) from exc
        return status

    def _stop_locked(self, plugin_name: str) -> PluginRuntimeStatus:
        session = self._get_session(plugin_name)
        self._unregister(plugin_name)
        if session is None:
            return PluginRuntimeStatus(
                plugin_name=plugin_name,
                state=FiberState.DISPOSED,
                restart_count=self._restart_counts.get(plugin_name, 0),
                limits=self._limits,
            )
        return session.stop()

    def _get_session(self, plugin_name: str) -> Optional[_PluginProcess]:
        with self._sessions_lock:
            return self._sessions.get(plugin_name)

    def _plugin_lock(self, plugin_name: str) -> threading.RLock:
        with self._sessions_lock:
            lock = self._plugin_locks.get(plugin_name)
            if lock is None:
                lock = threading.RLock()
                self._plugin_locks[plugin_name] = lock
            return lock

    @staticmethod
    def _load_manifest(record: PluginRecord, root: Path) -> PluginManifest:
        try:
            if record.manifest:
                manifest = PluginManifest.from_json(json.dumps(record.manifest, ensure_ascii=False))
            else:
                manifest_path = root / "plugin.json"
                if not manifest_path.is_file():
                    raise PluginHostError(
                        "PLUGIN_MANIFEST_MISSING",
                        "plugin record has no manifest and install_path has no plugin.json",
                        status_code=422,
                    )
                manifest = PluginManifest.from_file(manifest_path)
        except PluginHostError:
            raise
        except (OSError, TypeError, ValueError) as exc:
            raise PluginHostError(
                "INVALID_PLUGIN_MANIFEST",
                f"could not load plugin manifest: {_truncate(exc)}",
                status_code=422,
            ) from exc

        if manifest.name.strip().lower() != record.name.strip().lower():
            raise PluginHostError(
                "PLUGIN_MANIFEST_MISMATCH",
                f"manifest name {manifest.name!r} does not match plugin record {record.name!r}",
                status_code=422,
            )
        return manifest

    @staticmethod
    def _supported_capabilities(manifest: PluginManifest) -> List[PluginCapability]:
        supported: List[PluginCapability] = []
        seen: set = set()
        for capability in manifest.capabilities:
            if capability.type != CapabilityType.TOOL or not capability.entry_point:
                continue
            if capability.name in seen:
                raise PluginHostError(
                    "DUPLICATE_PLUGIN_CAPABILITY",
                    f"duplicate tool capability: {capability.name}",
                    status_code=422,
                )
            seen.add(capability.name)
            capability.entry_point = _validate_entry_point(capability.entry_point)
            supported.append(capability)
        if not supported:
            raise PluginHostError(
                "NO_SUPPORTED_CAPABILITIES",
                "plugin has no tool capability with an entry_point for the R83 host",
                status_code=422,
            )
        return supported

    def _check_registry_conflicts(
        self,
        plugin_name: str,
        capabilities: Sequence[PluginCapability],
    ) -> None:
        with self._registry_lock:
            registered = {
                item.capability.name: item.plugin_name
                for item in self._registry.list_capabilities(capability_type=CapabilityType.TOOL)
            }
            for capability in capabilities:
                owner = registered.get(capability.name)
                if owner is not None and owner != plugin_name:
                    raise PluginHostError(
                        "CAPABILITY_CONFLICT",
                        f"tool capability {capability.name!r} is already provided by {owner!r}",
                        status_code=409,
                    )

    def _register_proxies(
        self,
        plugin_name: str,
        capabilities: Sequence[PluginCapability],
    ) -> None:
        with self._registry_lock:
            self._check_registry_conflicts(plugin_name, capabilities)
            self._registry.unregister_all(plugin_name)
            try:
                for capability in capabilities:
                    self._registry.register(
                        plugin_name,
                        capability,
                        handler=self._make_proxy(plugin_name, capability.name),
                    )
            except CapabilityConflictError as exc:
                self._registry.unregister_all(plugin_name)
                raise PluginHostError(
                    "CAPABILITY_CONFLICT",
                    _truncate(exc),
                    status_code=409,
                ) from exc

    def _make_proxy(self, plugin_name: str, capability_name: str) -> Callable[..., Any]:
        def handler(arguments: Optional[Dict[str, Any]] = None, **kwargs: Any) -> Any:
            payload: Dict[str, Any] = {}
            if arguments is not None:
                if not isinstance(arguments, dict):
                    raise PluginHostError(
                        "INVALID_ARGUMENTS",
                        "plugin tool arguments must be an object",
                        status_code=422,
                    )
                payload.update(arguments)
            payload.update(kwargs)
            return self.invoke(plugin_name, capability_name, payload)

        handler.__name__ = f"plugin_proxy_{plugin_name}_{capability_name}".replace("-", "_")
        return handler

    def _unregister(self, plugin_name: str) -> None:
        with self._registry_lock, contextlib.suppress(Exception):
            self._registry.unregister_all(plugin_name)


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _limits_from_env() -> PluginHostLimits:
    defaults = PluginHostLimits()
    try:
        return PluginHostLimits(
            startup_timeout_seconds=_env_float(
                "SAGE_PLUGIN_HOST_STARTUP_TIMEOUT", defaults.startup_timeout_seconds
            ),
            request_timeout_seconds=_env_float(
                "SAGE_PLUGIN_HOST_REQUEST_TIMEOUT", defaults.request_timeout_seconds
            ),
            shutdown_timeout_seconds=_env_float(
                "SAGE_PLUGIN_HOST_SHUTDOWN_TIMEOUT", defaults.shutdown_timeout_seconds
            ),
            max_message_bytes=_env_int(
                "SAGE_PLUGIN_HOST_MAX_MESSAGE_BYTES", defaults.max_message_bytes
            ),
            memory_bytes=_env_int("SAGE_PLUGIN_HOST_MEMORY_BYTES", defaults.memory_bytes),
            cpu_seconds=_env_int("SAGE_PLUGIN_HOST_CPU_SECONDS", defaults.cpu_seconds),
            max_stderr_chars=_env_int(
                "SAGE_PLUGIN_HOST_MAX_STDERR_CHARS", defaults.max_stderr_chars
            ),
        )
    except ValueError:
        logger.warning("Invalid plugin host limit environment; using defaults")
        return defaults


_HOST_MANAGER: Optional[PluginHostManager] = None
_HOST_MANAGER_LOCK = threading.RLock()


def get_plugin_host_manager() -> PluginHostManager:
    """Return the process-wide plugin host manager."""

    global _HOST_MANAGER
    with _HOST_MANAGER_LOCK:
        if _HOST_MANAGER is None:
            _HOST_MANAGER = PluginHostManager(limits=_limits_from_env())
        return _HOST_MANAGER


def reset_plugin_host_manager() -> None:
    """Stop all workers and clear the singleton (primarily for tests)."""

    global _HOST_MANAGER
    with _HOST_MANAGER_LOCK:
        manager = _HOST_MANAGER
        _HOST_MANAGER = None
    if manager is not None:
        manager.shutdown_all()


def shutdown_plugin_hosts() -> None:
    """Stop all plugin workers during backend shutdown."""

    reset_plugin_host_manager()


__all__ = [
    "PROTOCOL_VERSION",
    "PluginHostError",
    "PluginHostLimits",
    "PluginHostManager",
    "PluginRuntimeStatus",
    "get_plugin_host_manager",
    "reset_plugin_host_manager",
    "shutdown_plugin_hosts",
]
