"""
MCP server configuration — multi-server schema + JSON file persistence.

Source of truth
---------------
Server definitions live in a structured JSON file
(``$SAGE_USER_DATA_DIR/mcp_servers.json``, falling back to
``<project>/backend/data/mcp_servers.json`` when the env var is unset,
mirroring the scheduled-tasks store convention). We deliberately do NOT
use ``settings_repo`` here: that store is a flat key/value preference
bucket serialized as JSON strings, while MCP server definitions are
structured, validated records that must survive schema checks, support
atomic writes, and remain diff-able/edit-able by hand. A dedicated file
keeps the contract explicit and avoids smuggling typed config through a
KV store.

Merge rules
-----------
1. Built-in defaults (currently: ``drawio``, enabled only when
   ``packages/drawio-mcp-server/dist/index.js`` exists — preserves the
   pre-M3 behavior).
2. User entries from the JSON file override built-ins by ``name``.

A missing or corrupt user file degrades to built-in defaults plus a
logged warning — startup never crashes because of MCP config.
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import re
import tempfile
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Tuple

logger = logging.getLogger(__name__)

#: Serializes every read-modify-write cycle on the user config file.
#: RLock (not Lock) because the pool's add_server holds it around the
#: duplicate check + upsert pair while upsert/delete re-acquire it
#: internally — one critical section, no self-deadlock.
_config_lock = threading.RLock()


def config_file_lock() -> threading.RLock:
    """Process-wide lock guarding user config file RMW cycles.

    Exposed so the REST-facing pool methods can wrap their
    check-then-act sequences (duplicate check + upsert) in the SAME
    critical section as the file write — otherwise concurrent routes
    race the read-modify-write and lose updates.
    """
    return _config_lock

#: Server name slug: lowercase alnum / underscore / hyphen, 1..64 chars.
#: Names become LLM-visible tool prefixes (``mcp__<server>__<tool>``),
#: so the charset is deliberately strict.
SERVER_NAME_REGEX = re.compile(r"^[a-z0-9_-]{1,64}$")

#: Built-in server name that cannot be deleted via the REST API.
BUILTIN_DRAWIO = "drawio"


class McpConfigError(ValueError):
    """Raised when an MCP server config fails validation."""


@dataclass(frozen=True)
class ServerConfig:
    """Immutable configuration for a single MCP server."""

    name: str
    command: str
    args: Tuple[str, ...] = ()
    env: Dict[str, str] = field(default_factory=dict)
    enabled: bool = True
    required: bool = False
    timeout_seconds: float = 30.0

    def __post_init__(self) -> None:
        # frozen dataclass: normalize list → tuple via object.__setattr__
        if not isinstance(self.args, tuple):
            object.__setattr__(self, "args", tuple(self.args))

    def to_dict(self) -> Dict[str, object]:
        """JSON-serializable dict (for persistence / API responses)."""
        return {
            "name": self.name,
            "command": self.command,
            "args": list(self.args),
            "env": dict(self.env),
            "enabled": self.enabled,
            "required": self.required,
            "timeout_seconds": self.timeout_seconds,
        }


# Backwards-compatible alias: pre-M3 code (and the M1/M2 branches)
# imports McpServerConfig. The canonical name going forward is ServerConfig.
McpServerConfig = ServerConfig


def validate_server_config(
    name: str,
    command: str,
    args: Tuple[str, ...] = (),
    env: Dict[str, str] | None = None,
    enabled: bool = True,
    required: bool = False,
    timeout_seconds: float = 30.0,
) -> ServerConfig:
    """Validate raw fields and return an immutable ServerConfig.

    Raises:
        McpConfigError: on invalid name slug, empty command, bad timeout,
            or non-string env/args entries.
    """
    env = dict(env or {})
    if not isinstance(name, str) or not SERVER_NAME_REGEX.match(name):
        raise McpConfigError(
            f"invalid server name {name!r}: must match ^[a-z0-9_-]{{1,64}}$"
        )
    if not isinstance(command, str) or not command.strip():
        raise McpConfigError(f"server {name!r}: command must be a non-empty string")
    args = tuple(args)
    for arg in args:
        if not isinstance(arg, str):
            raise McpConfigError(
                f"server {name!r}: args entries must be strings, got {type(arg)!r}"
            )
    for key, value in env.items():
        if not isinstance(key, str) or not isinstance(value, str):
            raise McpConfigError(
                f"server {name!r}: env keys and values must be strings"
            )
    try:
        timeout = float(timeout_seconds)
    except (TypeError, ValueError):
        raise McpConfigError(
            f"server {name!r}: timeout_seconds must be a number"
        )
    if timeout <= 0:
        raise McpConfigError(
            f"server {name!r}: timeout_seconds must be > 0"
        )
    return ServerConfig(
        name=name,
        command=command.strip(),
        args=args,
        env=env,
        enabled=bool(enabled),
        required=bool(required),
        timeout_seconds=timeout,
    )


def _project_root() -> Path:
    """Return the sage project root directory."""
    return Path(__file__).resolve().parent.parent.parent


def get_user_config_path() -> Path:
    """Path of the user-writable MCP server config JSON.

    Honors ``SAGE_USER_DATA_DIR`` (injected by the packaged Electron app);
    falls back to ``<project>/backend/data/mcp_servers.json`` for
    ``npm run electron:dev`` where the env var is absent — same
    convention as the scheduled-tasks store.
    """
    user_data_dir = os.environ.get("SAGE_USER_DATA_DIR")
    if user_data_dir:
        return Path(user_data_dir) / "mcp_servers.json"
    return _project_root() / "backend" / "data" / "mcp_servers.json"


def builtin_server_configs() -> List[ServerConfig]:
    """Built-in server defaults.

    drawio: wired only when the bundled server entry point exists —
    preserves the pre-M3 "enabled if built" behavior.
    """
    root = _project_root()
    mcp_server_entry = root / "packages" / "drawio-mcp-server" / "dist" / "index.js"

    servers: List[ServerConfig] = []
    if mcp_server_entry.exists():
        env: Dict[str, str] = {
            "DRAWIO_BASE_URL": os.environ.get("DRAWIO_BASE_URL", "http://localhost:8080"),
        }
        chrome_path = os.environ.get("CHROME_PATH", "")
        if chrome_path:
            env["CHROME_PATH"] = chrome_path
        servers.append(
            ServerConfig(
                name=BUILTIN_DRAWIO,
                command="node",
                args=(str(mcp_server_entry),),
                env=env,
            )
        )
    return servers


def builtin_names() -> List[str]:
    """Names of built-in servers (used by DELETE guard in the REST API)."""
    return [s.name for s in builtin_server_configs()]


def _config_from_dict(raw: Dict[str, object]) -> ServerConfig:
    """Parse one user JSON entry into a validated ServerConfig."""
    return validate_server_config(
        name=str(raw.get("name", "")),
        command=str(raw.get("command", "")),
        args=tuple(raw.get("args") or ()),  # type: ignore[arg-type]
        env=dict(raw.get("env") or {}),  # type: ignore[arg-type]
        enabled=bool(raw.get("enabled", True)),
        required=bool(raw.get("required", False)),
        timeout_seconds=float(raw.get("timeout_seconds", 30.0) or 30.0),
    )


def load_user_server_configs(path: Path | None = None) -> List[ServerConfig]:
    """Load user server configs from the JSON file.

    Missing file → empty list (not an error). Corrupt file or invalid
    entries → log a warning and return the salvageable subset; startup
    must never crash because of MCP config.
    """
    path = path or get_user_config_path()
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return []
    except OSError as exc:
        logger.warning("MCP user config unreadable (%s): %s", path, exc)
        return []

    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        logger.warning("MCP user config corrupt (%s): %s — using defaults", path, exc)
        return []

    if not isinstance(parsed, dict) or not isinstance(parsed.get("servers"), list):
        logger.warning(
            'MCP user config has wrong shape (%s): expected {"servers": [...]} — using defaults',
            path,
        )
        return []

    configs: List[ServerConfig] = []
    seen: set = set()
    for entry in parsed["servers"]:
        if not isinstance(entry, dict):
            logger.warning("MCP user config: skipping non-object entry %r", entry)
            continue
        try:
            config = _config_from_dict(entry)
        except (McpConfigError, TypeError, ValueError) as exc:
            logger.warning("MCP user config: skipping invalid entry %r: %s", entry, exc)
            continue
        if config.name in seen:
            logger.warning("MCP user config: duplicate server name %r ignored", config.name)
            continue
        seen.add(config.name)
        configs.append(config)
    return configs


def save_user_server_configs(configs: List[ServerConfig], path: Path | None = None) -> None:
    """Atomically persist user server configs (temp file + rename).

    Raises:
        McpConfigError: on duplicate names within the list.
        OSError: propagated from the filesystem (caller surfaces as 500).
    """
    path = path or get_user_config_path()
    names = [c.name for c in configs]
    if len(names) != len(set(names)):
        raise McpConfigError("duplicate server names in config list")

    payload = {"version": 1, "servers": [c.to_dict() for c in configs]}
    path.parent.mkdir(parents=True, exist_ok=True)

    fd, tmp_name = tempfile.mkstemp(
        dir=str(path.parent), prefix=".mcp_servers.", suffix=".tmp"
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False, indent=2)
            fh.write("\n")
            fh.flush()
            os.fsync(fh.fileno())
        Path(tmp_name).replace(path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp_name)
        raise


def load_server_configs(path: Path | None = None) -> List[ServerConfig]:
    """Merged view: built-ins overlaid with user entries (user wins by name)."""
    merged: Dict[str, ServerConfig] = {}
    for config in builtin_server_configs():
        merged[config.name] = config
    for config in load_user_server_configs(path):
        merged[config.name] = config
    return list(merged.values())


def upsert_user_server_config(config: ServerConfig, path: Path | None = None) -> List[ServerConfig]:
    """Insert or replace one user entry and persist atomically.

    The read-modify-write is one critical section under
    :func:`config_file_lock` — concurrent upserts/deletes serialize so
    no update is lost to an interleaved stale read.
    """
    with _config_lock:
        configs = [c for c in load_user_server_configs(path) if c.name != config.name]
        configs.append(config)
        save_user_server_configs(configs, path)
        return configs


def delete_user_server_config(name: str, path: Path | None = None) -> bool:
    """Remove a user entry by name; returns True if an entry was removed.

    Serialized under :func:`config_file_lock` (see upsert).
    """
    with _config_lock:
        configs = load_user_server_configs(path)
        remaining = [c for c in configs if c.name != name]
        if len(remaining) == len(configs):
            return False
        save_user_server_configs(remaining, path)
        return True


# ---- backwards-compat shim -------------------------------------------------


def get_mcp_server_configs() -> List[ServerConfig]:
    """Deprecated pre-M3 entry point; use :func:`load_server_configs`."""
    return load_server_configs()
