"""
Hardened MCP server pool — parallel discovery, per-server isolation,
reconnection, and degraded-mode status reporting.

Lifecycle decision (M3)
------------------------
The pre-M3 ``backend/mcp/lifecycle/`` package (async MCPLifecycleManager +
CREATED→INITIALIZING→READY→RUNNING⇄PAUSED→SHUTDOWN state machine) has been
**deleted** in this milestone. Rationale:

1. The production MCP client (``backend/mcp/client.py``) is synchronous
   (blocking subprocess + JSON-RPC over stdio). The lifecycle manager was
   fully async (``asyncio.create_task`` health loops, ``asynccontextmanager``
   lifespan) — wiring it to the sync client would require an executor
   bridge at every state transition, i.e. two threading models for zero
   functional gain.
2. Its states model a single generic *service* (database-style resource
   with pause/resume), not N independent stdio subprocesses. MCP servers
   have no meaningful PAUSED state — a paused stdio child is just a dead
   one.
3. It was dead code: nothing imported it outside its own tests.

Instead this module implements a minimal **sync** per-server state model
that maps exactly to what the pool does:

    DISCOVERING → READY  (handshake + tools/list succeeded)
    DISCOVERING → FAILED (startup/handshake error, per-server isolated)
    READY       → FAILED (subprocess died mid-session)
    FAILED      → READY  (reconnect / background re-discovery)
    *           → DISABLED (config.enabled = false)

Per-server records carry ``state / tool_count / last_error /
last_state_change / attempts`` and feed :class:`McpStatusReport`
(degraded-mode reporting, cf. claw-code ``McpDegradedReport``).
"""

from __future__ import annotations

import contextlib
import logging
import re
import threading
import time
import weakref
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Tuple

from backend.mcp.client import McpClient, McpClientError
from backend.mcp.config import (
    ServerConfig,
    builtin_names,
    config_file_lock,
    delete_user_server_config,
    load_server_configs,
    upsert_user_server_config,
    validate_server_config,
)

logger = logging.getLogger(__name__)

#: Background re-discovery cooldown after a failure (seconds).
REDISCOVERY_COOLDOWN_SECONDS = 60.0

#: Grace added on top of per-server timeout when waiting on executor futures.
EXECUTOR_GRACE_SECONDS = 5.0

#: Metadata caps for tools/list ingestion. A malicious or buggy server
#: must not be able to flood the tool registry (and therefore the LLM
#: context) with unbounded or garbage tool definitions: excess and
#: invalid specs are skipped + logged, never ingested.
MAX_TOOLS_PER_SERVER = 100
MAX_TOOL_NAME_LENGTH = 128
TOOL_NAME_REGEX = re.compile(r"^[A-Za-z0-9_.-]+$")


def sanitize_tool_specs(
    specs: List[Any], server_name: str
) -> List[Dict[str, Any]]:
    """Filter a tools/list payload down to safe, registry-worthy specs.

    Skips (with a log naming the server): non-dict entries, missing /
    empty / overlong names, and names outside ``[A-Za-z0-9_.-]`` (tool
    names become LLM-visible identifiers and registry keys). Then caps
    the total at :data:`MAX_TOOLS_PER_SERVER` (first N win).
    """
    kept: List[Dict[str, Any]] = []
    for spec in specs:
        name = spec.get("name") if isinstance(spec, dict) else None
        if (
            not isinstance(name, str)
            or not name
            or len(name) > MAX_TOOL_NAME_LENGTH
            or not TOOL_NAME_REGEX.match(name)
        ):
            logger.warning(
                "[MCP:%s] skipping tool spec with invalid name %r", server_name, name
            )
            continue
        kept.append(spec)
    if len(kept) > MAX_TOOLS_PER_SERVER:
        logger.warning(
            "[MCP:%s] server advertised %d tools; keeping first %d",
            server_name,
            len(kept),
            MAX_TOOLS_PER_SERVER,
        )
        kept = kept[:MAX_TOOLS_PER_SERVER]
    return kept


class ServerState(str, Enum):
    """Per-server lifecycle state (sync pool — see module docstring)."""

    DISCOVERING = "discovering"
    READY = "ready"
    FAILED = "failed"
    DISABLED = "disabled"


def namespaced_tool_name(server_name: str, tool_name: str) -> str:
    """LLM-visible tool name: ``mcp__<server>__<tool>``.

    M3 change: pre-M3 tools were registered as ``<server>__<tool>``
    (e.g. ``drawio__render_diagram``). The ``mcp__`` prefix disambiguates
    MCP-provided tools from built-ins and matches the claw-code
    ``mcp__server__tool`` convention.
    """
    return f"mcp__{server_name}__{tool_name}"


@dataclass
class ServerRecord:
    """Mutable per-server bookkeeping held by the pool."""

    config: ServerConfig
    state: ServerState = ServerState.DISCOVERING
    tool_count: int = 0
    tool_specs: List[Dict[str, Any]] = field(default_factory=list)
    last_error: Optional[str] = None
    last_state_change: float = field(default_factory=time.time)
    attempts: int = 0
    client: Optional[Any] = None  # McpClient (or test fake)
    #: Discovery gate — True while a thread is inside _discover_record
    #: for this record. Concurrent attempts see it and fail fast instead
    #: of double-spawning subprocesses (last-writer-wins orphans N-1).
    discovering: bool = False

    def set_state(self, state: ServerState, error: Optional[str] = None) -> None:
        self.state = state
        if error is not None:
            self.last_error = error
        elif state == ServerState.READY:
            self.last_error = None
        self.last_state_change = time.time()


@dataclass(frozen=True)
class ServerStatusEntry:
    """Immutable snapshot of one server for the status report."""

    name: str
    state: str
    tool_count: int
    last_error: Optional[str]
    since: float
    required: bool

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "state": self.state,
            "tool_count": self.tool_count,
            "last_error": self.last_error,
            "since": self.since,
            "required": self.required,
        }


@dataclass(frozen=True)
class McpStatusReport:
    """Degraded-mode status report across all configured servers."""

    generated_at: float
    servers: Tuple[ServerStatusEntry, ...]

    @property
    def all_ready(self) -> bool:
        return all(s.state == ServerState.READY.value for s in self.servers)

    @property
    def degraded(self) -> bool:
        return any(s.state == ServerState.FAILED.value for s in self.servers)

    @property
    def failed_required(self) -> bool:
        return any(
            s.state == ServerState.FAILED.value and s.required for s in self.servers
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "generated_at": self.generated_at,
            "all_ready": self.all_ready,
            "degraded": self.degraded,
            "failed_required": self.failed_required,
            "servers": [s.to_dict() for s in self.servers],
        }


class McpServerPool:
    """Thread-safe multi-server pool with best-effort parallel discovery.

    Args:
        client_factory: Injectable seam — builds a client for a config.
            Tests inject in-process fakes here; production uses McpClient.
        rediscovery_cooldown: Seconds before background re-discovery of a
            FAILED server (default 60; not per-call).
    """

    def __init__(
        self,
        client_factory: Callable[[ServerConfig], Any] = McpClient,
        rediscovery_cooldown: float = REDISCOVERY_COOLDOWN_SECONDS,
    ) -> None:
        self._client_factory = client_factory
        self._rediscovery_cooldown = rediscovery_cooldown
        self._lock = threading.RLock()
        self._records: Dict[str, ServerRecord] = {}
        self._registries: List[weakref.ReferenceType] = []
        self._initial_sync_done = False
        self._initial_discovery_done = False
        self._rediscover_at: Dict[str, float] = {}
        self._rediscover_timers: Dict[str, threading.Timer] = {}
        #: Terminal shutdown flag — once set (under the lock, by
        #: shutdown_all), every discovery path becomes a no-op so an
        #: in-flight timer callback can never spawn after Electron exit.
        self._shutdown = False

    # ---- config (re)loading ------------------------------------------------

    def sync_configs(self, configs: Optional[List[ServerConfig]] = None) -> None:
        """Load (merged) configs; create/update records, mark disabled.

        Does not start processes — call :meth:`discover_all` for that.
        Records for servers removed from config are stopped and dropped.
        """
        configs = configs if configs is not None else load_server_configs()
        with self._lock:
            incoming = {c.name: c for c in configs}
            # drop records no longer configured
            for name in list(self._records):
                if name not in incoming:
                    self._stop_record(self._records[name])
                    del self._records[name]
            for config in configs:
                record = self._records.get(config.name)
                if record is None:
                    self._records[config.name] = ServerRecord(
                        config=config,
                        state=(
                            ServerState.DISABLED
                            if not config.enabled
                            else ServerState.DISCOVERING
                        ),
                    )
                else:
                    record.config = config
                    if not config.enabled and record.state != ServerState.DISABLED:
                        self._stop_record(record)
                        record.set_state(ServerState.DISABLED)
                    elif config.enabled and record.state == ServerState.DISABLED:
                        record.set_state(ServerState.DISCOVERING)

    def ensure_synced(self) -> None:
        """Load configs into records once, WITHOUT starting subprocesses.

        Lightweight idempotent hook for the REST API layer: GET routes
        can report config/state without paying for process discovery.
        """
        with self._lock:
            if self._initial_sync_done:
                return
            self._initial_sync_done = True
        self.sync_configs()

    def ensure_discovered(self) -> None:
        """Run full parallel discovery once (idempotent startup hook)."""
        with self._lock:
            if self._initial_discovery_done:
                return
            self._initial_discovery_done = True
        self.ensure_synced()
        self.discover_all()

    # ---- discovery ----------------------------------------------------------

    def discover_all(self) -> McpStatusReport:
        """Best-effort parallel discovery of every enabled server.

        One server failing never blocks the others: each discovery runs
        on its own worker thread bounded by the server's configured
        timeout. Returns the post-discovery status report.
        """
        with self._lock:
            targets = [
                r for r in self._records.values() if r.config.enabled
            ]

        if targets:
            workers = min(8, len(targets))
            with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="mcp-discover") as ex:
                futures = {
                    ex.submit(self._discover_record, record): record for record in targets
                }
                for future, record in futures.items():
                    timeout = record.config.timeout_seconds + EXECUTOR_GRACE_SECONDS
                    try:
                        future.result(timeout=timeout)
                    except Exception as exc:  # noqa: BLE001 — isolation is the point
                        with self._lock:
                            record.set_state(
                                ServerState.FAILED,
                                error=f"discovery timed out or crashed: {exc}",
                            )
                        logger.error(
                            "[MCP:%s] discovery failed: %s", record.config.name, exc
                        )
        return self.status_report()

    def discover_one(self, name: str) -> ServerRecord:
        """(Re)discover a single server by name. Raises KeyError if unknown."""
        with self._lock:
            record = self._records[name]
        self._discover_record(record)
        return record

    def _discover_record(self, record: ServerRecord) -> None:
        """Start subprocess, handshake, tools/list; update record + registries.

        Single discovery choke point: startup, call-time reconnect, and
        background timers all funnel through here. Three gates:

        - ``_shutdown`` (pool-level): post-shutdown attempts are no-ops,
          so an in-flight timer callback never spawns a lingering process.
        - ``record.discovering`` (per-record): a concurrent attempt finds
          discovery already running and returns without spawning — N
          simultaneous reconnects produce exactly one subprocess.
        - disabled configs short-circuit to DISABLED.

        Every except path that discards a started client stops it —
        McpClient.start() spawns the subprocess BEFORE the handshake, so
        dropping the reference without stop() leaks the process.
        """
        name = record.config.name
        with self._lock:
            if self._shutdown:
                logger.debug("[MCP:%s] discovery skipped — pool shut down", name)
                return
            if not record.config.enabled:
                record.set_state(ServerState.DISABLED)
                return
            if record.discovering:
                logger.debug("[MCP:%s] discovery already in progress — skipping", name)
                return
            record.discovering = True
            record.attempts += 1
            record.set_state(ServerState.DISCOVERING)
            self._stop_record(record)  # stop stale client if any

        client = None
        try:
            try:
                client = self._client_factory(record.config)
                client.start()
                tool_specs = sanitize_tool_specs(client.list_tools(), name)
            except McpClientError as exc:
                self._stop_discarded_client(client)
                with self._lock:
                    record.set_state(ServerState.FAILED, error=str(exc))
                logger.error("[MCP:%s] discovery failed: %s", name, exc)
                self._unregister_server_tools(name)
                return
            except Exception as exc:  # noqa: BLE001 — never let one server crash the pool
                self._stop_discarded_client(client)
                with self._lock:
                    record.set_state(
                        ServerState.FAILED,
                        error=f"{type(exc).__name__}: {exc}",
                    )
                logger.exception("[MCP:%s] unexpected discovery error", name)
                self._unregister_server_tools(name)
                return

            with self._lock:
                record.client = client
                record.tool_specs = tool_specs
                record.tool_count = len(tool_specs)
                record.set_state(ServerState.READY)
            logger.info(
                "[MCP:%s] READY — %d tools discovered", name, len(tool_specs)
            )
            self._register_server_tools(record)
        finally:
            with self._lock:
                record.discovering = False

    @staticmethod
    def _stop_discarded_client(client: Optional[Any]) -> None:
        """Stop a client discarded by a failed start/handshake/tools-list.

        McpClient.start() spawns Popen before the handshake, so any
        except path that drops the client reference MUST reap it or the
        subprocess outlives the error (leak). Suppress: cleanup must
        never mask the original failure.
        """
        if client is not None:
            with contextlib.suppress(Exception):
                client.stop()

    # ---- tool call path -----------------------------------------------------

    def call_tool(self, server_name: str, tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Call an MCP tool with per-server failure isolation.

        Reconnection policy: a dead client triggers ONE immediate
        reconnect attempt, then the call fails with a clean error.
        Background re-discovery is scheduled on a cooldown — never
        per-call.
        """
        with self._lock:
            record = self._records.get(server_name)

        if record is None:
            raise McpClientError(
                f"MCP 服务器 {server_name} 不可用: 未配置"
            )
        if not record.config.enabled or record.state == ServerState.DISABLED:
            raise McpClientError(
                f"MCP 服务器 {server_name} 不可用: 已禁用"
            )

        client = record.client
        if client is None or not client.is_running:
            client = self._reconnect_once(record)

        try:
            return client.call_tool(tool_name, arguments)
        except McpClientError:
            # Distinguish transport death (server gone) from tool-level
            # protocol errors: only transport death flips state to FAILED.
            if not client.is_running:
                with self._lock:
                    record.set_state(
                        ServerState.FAILED,
                        error="server process exited mid-session",
                    )
                self._schedule_background_rediscovery(record)
            raise

    def _reconnect_once(self, record: ServerRecord) -> Any:
        """ONE immediate reconnect attempt; raises clean error on failure.

        Funnels through :meth:`_discover_record` so reconnects are gated:
        if another thread is already discovering this record, this call
        fails fast with a clean "reconnect in progress" error instead of
        spawning a second subprocess (N concurrent callers → 1 spawn,
        N-1 clean errors, 0 orphans).
        """
        name = record.config.name
        logger.warning("[MCP:%s] client dead — attempting one reconnect", name)
        with self._lock:
            current = record.client
            if current is not None and current.is_running and not record.discovering:
                # Another call path already reconnected — reuse it.
                logger.info("[MCP:%s] reconnect raced — reusing live client", name)
                return current
        self._discover_record(record)
        with self._lock:
            client = record.client
            detail = record.last_error
        if client is None or not client.is_running:
            self._schedule_background_rediscovery(record)
            raise McpClientError(
                f"MCP 服务器 {name} 不可用: 重连失败 ({detail or 'reconnect in progress'})"
            )
        logger.info("[MCP:%s] reconnect succeeded", name)
        return client

    def _schedule_background_rediscovery(self, record: ServerRecord) -> None:
        """Background re-discovery on a cooldown; one timer per server."""
        name = record.config.name
        with self._lock:
            now = time.time()
            not_before = self._rediscover_at.get(name, 0.0)
            if now < not_before or name in self._rediscover_timers:
                return
            self._rediscover_at[name] = now + self._rediscovery_cooldown
            timer = threading.Timer(
                self._rediscovery_cooldown, self._background_rediscover, args=(name,)
            )
            timer.daemon = True
            self._rediscover_timers[name] = timer
        timer.start()

    def _background_rediscover(self, name: str) -> None:
        with self._lock:
            self._rediscover_timers.pop(name, None)
            if self._shutdown:
                return  # stale timer firing after shutdown_all — no spawn
            record = self._records.get(name)
        if record is None or not record.config.enabled:
            return
        if record.state == ServerState.READY:
            return
        logger.info("[MCP:%s] background re-discovery starting", name)
        self._discover_record(record)

    # ---- runtime management (used by REST API) ------------------------------

    def add_server(self, config: ServerConfig) -> ServerRecord:
        """Persist a new user server and trigger discovery for it.

        Raises McpClientError if the name already exists in the merged view.

        The duplicate check + config-file upsert + record insert run as
        ONE critical section under the config-file lock (shared with the
        config module's RMW helpers) — closing the check-then-act gap
        where two concurrent POSTs with the same name could both pass
        the check and double-discover.
        """
        with config_file_lock():
            with self._lock:
                if config.name in self._records:
                    raise McpClientError(
                        f"MCP 服务器名称已存在: {config.name}"
                    )
            upsert_user_server_config(config)
            with self._lock:
                self._records[config.name] = ServerRecord(
                    config=config,
                    state=(
                        ServerState.DISABLED
                        if not config.enabled
                        else ServerState.DISCOVERING
                    ),
                )
        if config.enabled:
            self.discover_one(config.name)
        with self._lock:
            return self._records[config.name]

    def update_server(
        self,
        name: str,
        enabled: Optional[bool] = None,
        timeout_seconds: Optional[float] = None,
    ) -> ServerRecord:
        """Merge-patch a server (enabled / timeout_seconds) and start/stop.

        Persists a user entry (built-in fields inherited when patching a
        built-in). Raises KeyError if the server is unknown.

        A ``timeout_seconds`` change on a RUNNING (READY) server
        triggers re-discovery: the timeout is baked into the live
        client at construction, so only a fresh client picks up the new
        deadline — silently persisting it would leave the running
        server on the old value. An unchanged timeout never churns a
        healthy server.
        """
        with self._lock:
            record = self._records.get(name)
            if record is None:
                raise KeyError(name)
            base = record.config
            timeout_changed = (
                timeout_seconds is not None
                and float(timeout_seconds) != base.timeout_seconds
            )
            new_config = validate_server_config(
                name=base.name,
                command=base.command,
                args=base.args,
                env=dict(base.env),
                enabled=base.enabled if enabled is None else enabled,
                required=base.required,
                timeout_seconds=(
                    base.timeout_seconds if timeout_seconds is None else timeout_seconds
                ),
            )
        upsert_user_server_config(new_config)

        with self._lock:
            record.config = new_config

        if not new_config.enabled:
            with self._lock:
                self._stop_record(record)
                record.set_state(ServerState.DISABLED)
            self._unregister_server_tools(name)
        elif record.state in (ServerState.DISABLED, ServerState.FAILED) or (
            timeout_changed and record.state == ServerState.READY
        ):
            self.discover_one(name)
        return record

    def remove_server(self, name: str) -> None:
        """Remove a user entry; built-ins without override are rejected.

        Raises:
            KeyError: unknown server name.
            McpClientError: built-in server with no user override (→ 400).
        """
        is_builtin = name in builtin_names()
        with self._lock:
            known = name in self._records
        if not known and not is_builtin:
            raise KeyError(name)
        removed_user_entry = delete_user_server_config(name)
        if is_builtin and not removed_user_entry:
            raise McpClientError(f"内置 MCP 服务器不可删除: {name}")

        effective = next(
            (c for c in load_server_configs() if c.name == name), None
        )
        with self._lock:
            if effective is None:
                record = self._records.pop(name, None)
                if record is not None:
                    self._stop_record(record)
            else:
                # built-in resurfaces after user override removal
                record = self._records.get(name)
                if record is not None:
                    record.config = effective
        if effective is not None:
            self.discover_one(name)
        else:
            self._unregister_server_tools(name)

    def shutdown_all(self) -> None:
        """Terminal shutdown: block future discovery, cancel timers, stop clients.

        Ordering matters: ``_shutdown`` is raised FIRST (under the lock)
        so an in-flight ``_background_rediscover`` callback that already
        passed its own check still hits the gate inside
        :meth:`_discover_record` — canceling timers alone cannot stop a
        callback that is already running. After this returns the pool
        never spawns again (late timer callbacks, REST calls, and
        tool calls all become clean no-ops / errors) — no lingering
        processes after Electron exit.
        """
        with self._lock:
            self._shutdown = True
            for timer in self._rediscover_timers.values():
                timer.cancel()
            self._rediscover_timers.clear()
            records = list(self._records.values())
        for record in records:
            with self._lock:
                self._stop_record(record)

    # ---- status -------------------------------------------------------------

    def status_report(self) -> McpStatusReport:
        with self._lock:
            entries = tuple(
                ServerStatusEntry(
                    name=r.config.name,
                    state=r.state.value,
                    tool_count=r.tool_count,
                    last_error=r.last_error,
                    since=r.last_state_change,
                    required=r.config.required,
                )
                for r in sorted(self._records.values(), key=lambda r: r.config.name)
            )
        return McpStatusReport(generated_at=time.time(), servers=entries)

    def effective_configs(self) -> List[ServerConfig]:
        """Merged configs currently held by the pool (built-ins + user)."""
        with self._lock:
            return [r.config for r in sorted(self._records.values(), key=lambda r: r.config.name)]

    def get_record(self, name: str) -> Optional[ServerRecord]:
        with self._lock:
            return self._records.get(name)

    # ---- tool registry fan-out ----------------------------------------------

    def track_registry(self, registry: Any) -> None:
        """Remember a ToolRegistry (weak ref) for dynamic tool fan-out."""
        with self._lock:
            self._registries = [ref for ref in self._registries if ref() is not None]
            if not any(ref() is registry for ref in self._registries):
                self._registries.append(weakref.ref(registry))

    def _live_registries(self) -> List[Any]:
        with self._lock:
            live = [ref() for ref in self._registries]
        return [r for r in live if r is not None]

    def register_tools_into(self, registry: Any) -> int:
        """Register all READY servers' tools into one registry. Returns count."""
        from backend.mcp.tool import McpTool

        count = 0
        with self._lock:
            ready_records = [
                r for r in self._records.values() if r.state == ServerState.READY
            ]
        for record in ready_records:
            for spec in record.tool_specs:
                tool_name = namespaced_tool_name(record.config.name, spec["name"])
                if registry.exists(tool_name):
                    # With mcp__<server>__<tool> namespacing collisions are
                    # structurally impossible across servers; this guards
                    # same-name re-registration (first wins + warn).
                    logger.warning(
                        "MCP tool %s already registered — first wins, skipping",
                        tool_name,
                    )
                    continue
                registry.register(McpTool(self, record.config.name, spec))
                count += 1
        return count

    def _register_server_tools(self, record: ServerRecord) -> None:
        from backend.mcp.tool import McpTool

        for registry in self._live_registries():
            for spec in record.tool_specs:
                tool_name = namespaced_tool_name(record.config.name, spec["name"])
                if registry.exists(tool_name):
                    logger.warning(
                        "MCP tool %s already registered — first wins, skipping",
                        tool_name,
                    )
                    continue
                registry.register(McpTool(self, record.config.name, spec))

    def _unregister_server_tools(self, server_name: str) -> None:
        for registry in self._live_registries():
            prefix = f"mcp__{server_name}__"
            for tool_name in list(registry.list_names()):
                if tool_name.startswith(prefix):
                    registry.unregister(tool_name)

    # ---- helpers -------------------------------------------------------------

    def _stop_record(self, record: ServerRecord) -> None:
        """Stop the record's client if any (caller may hold the lock)."""
        client = record.client
        record.client = None
        if client is not None:
            try:
                client.stop()
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "[MCP:%s] error stopping client: %s", record.config.name, exc
                )


# ---- module-level singleton --------------------------------------------------

_pool: Optional[McpServerPool] = None
_pool_lock = threading.Lock()


def get_pool() -> McpServerPool:
    """Process-wide pool singleton (created lazily on first use)."""
    global _pool
    if _pool is None:
        with _pool_lock:
            if _pool is None:
                _pool = McpServerPool()
    return _pool


def reset_pool(pool: Optional[McpServerPool] = None) -> None:
    """Replace (or clear) the singleton — test hook."""
    global _pool
    with _pool_lock:
        _pool = pool
