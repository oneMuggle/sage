"""Stdlib-only worker process for the out-of-process plugin host (R83).

The host launches this file with the plugin directory as ``cwd``.  Stdout is
reserved for one-JSON-object-per-line JSON-RPC frames; after the protocol
streams are captured, ``sys.stdout`` is redirected to stderr so ordinary
plugin ``print()`` calls cannot corrupt the protocol.

This worker provides crash isolation and bounded supervision.  It is not an
operating-system security sandbox: plugin code still runs as the current OS
user.
"""

from __future__ import annotations

import asyncio
import importlib
import inspect
import json
import os
import sys
import traceback
from pathlib import Path
from typing import Any, Callable, Dict, Optional, Set

PROTOCOL_VERSION = 1
DEFAULT_MAX_MESSAGE_BYTES = 1024 * 1024
_CONVENTIONAL_ATTRS = ("run", "execute", "handler", "main")
_PAYLOAD_ARG_NAMES = {"args", "arguments", "data", "input", "params", "payload", "request"}


class WorkerError(Exception):
    """Structured worker/protocol error returned to the host."""

    def __init__(self, code: str, message: str, rpc_code: int = -32000) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.rpc_code = rpc_code


def _truncate(value: Any, limit: int = 1000) -> str:
    text = str(value)
    if len(text) <= limit:
        return text
    return text[:limit] + "...[truncated]"


def _apply_posix_limits(memory_bytes: int, cpu_seconds: int) -> Dict[str, bool]:
    """Apply resource limits before any plugin module is imported."""

    applied = {"memory": False, "cpu": False}
    if os.name == "nt":
        return applied

    try:
        import resource
    except ImportError:
        return applied

    candidates = []
    if memory_bytes > 0 and hasattr(resource, "RLIMIT_AS"):
        candidates.append(("memory", resource.RLIMIT_AS, memory_bytes))
    if cpu_seconds > 0 and hasattr(resource, "RLIMIT_CPU"):
        candidates.append(("cpu", resource.RLIMIT_CPU, cpu_seconds))

    for field, kind, limit in candidates:
        try:
            _, hard = resource.getrlimit(kind)
            effective_limit = limit
            if hard != resource.RLIM_INFINITY:
                effective_limit = min(limit, hard)
            resource.setrlimit(kind, (effective_limit, effective_limit))
            applied[field] = True
        except (OSError, ValueError) as exc:
            sys.stderr.write(f"[plugin-worker] resource limit {field} unavailable: {exc}\n")

    return applied


def _remove_script_directory_from_path() -> None:
    script_dir = str(Path(__file__).resolve().parent)
    sys.path[:] = [entry for entry in sys.path if entry and str(Path(entry).resolve()) != script_dir]


def _traverse_attrs(instance: Any, attr_path: str, entry_point: str) -> Any:
    current = instance
    for attr in attr_path.split("."):
        if not attr:
            continue
        if not hasattr(current, attr):
            raise WorkerError(
                "PLUGIN_LOAD_FAILED",
                f"entry_point {entry_point!r} does not define {attr_path!r}",
                rpc_code=-32020,
            )
        current = getattr(current, attr)
    return current


def _resolve_entry(entry_point: str) -> Any:
    """Import an entry point, returning the raw module/object/class/function."""

    entry_point = entry_point.strip()
    if not entry_point:
        raise WorkerError("INVALID_ENTRY_POINT", "entry_point is empty", rpc_code=-32602)

    try:
        if ":" in entry_point:
            module_name, attr_path = entry_point.split(":", 1)
            if not module_name or not attr_path:
                raise WorkerError(
                    "INVALID_ENTRY_POINT",
                    f"invalid entry_point: {entry_point!r}",
                    rpc_code=-32602,
                )
            module = importlib.import_module(module_name)
            return _traverse_attrs(module, attr_path, entry_point)

        try:
            return importlib.import_module(entry_point)
        except ModuleNotFoundError as exc:
            missing = exc.name or ""
            can_split = "." in entry_point and (
                missing == entry_point or entry_point.startswith(missing + ".")
            )
            if not can_split:
                raise
            module_name, attr = entry_point.rsplit(".", 1)
            module = importlib.import_module(module_name)
            return _traverse_attrs(module, attr, entry_point)
    except WorkerError:
        raise
    except Exception as exc:  # noqa: BLE001 - converted to structured load error
        raise WorkerError(
            "PLUGIN_LOAD_FAILED",
            f"could not import entry_point {entry_point!r}: {type(exc).__name__}: {_truncate(exc)}",
            rpc_code=-32020,
        ) from exc


def _configure_once(instance: Any, config: Dict[str, Any], seen: Set[int]) -> None:
    marker = id(instance)
    if marker in seen:
        return
    seen.add(marker)
    configure = getattr(instance, "configure", None)
    if callable(configure):
        configure(config)


def _make_callable(instance: Any, config: Dict[str, Any], seen: Set[int]) -> Callable[..., Any]:
    if inspect.ismodule(instance):
        _configure_once(instance, config, seen)
        for attr in _CONVENTIONAL_ATTRS:
            if hasattr(instance, attr):
                return _make_callable(getattr(instance, attr), config, seen)
        raise WorkerError(
            "PLUGIN_LOAD_FAILED",
            "plugin module does not define run/execute/handler/main",
            rpc_code=-32020,
        )

    if inspect.isclass(instance):
        try:
            created = instance()
        except Exception as exc:  # noqa: BLE001 - converted below
            raise WorkerError(
                "PLUGIN_LOAD_FAILED",
                f"could not instantiate plugin class {instance.__name__}: "
                f"{type(exc).__name__}: {_truncate(exc)}",
                rpc_code=-32020,
            ) from exc
        _configure_once(created, config, seen)
        execute = getattr(created, "execute", None)
        if callable(execute):
            return execute
        if callable(created):
            return created
        raise WorkerError(
            "PLUGIN_LOAD_FAILED",
            f"plugin class {instance.__name__} has no execute() and is not callable",
            rpc_code=-32020,
        )

    execute = getattr(instance, "execute", None)
    if callable(execute) and not inspect.isfunction(instance):
        _configure_once(instance, config, seen)
        return execute
    if callable(instance):
        return instance

    raise WorkerError(
        "PLUGIN_LOAD_FAILED",
        f"plugin entry point is not callable: {type(instance).__name__}",
        rpc_code=-32020,
    )


def _load_capability(
    entry_point: str,
    config: Dict[str, Any],
    seen: Set[int],
) -> Callable[..., Any]:
    raw = _resolve_entry(entry_point)
    try:
        module_name = getattr(raw, "__module__", None)
        module = sys.modules.get(module_name) if isinstance(module_name, str) else None
        if module is not None:
            _configure_once(module, config, seen)
        return _make_callable(raw, config, seen)
    except WorkerError:
        raise
    except Exception as exc:  # noqa: BLE001 - converted to structured load error
        raise WorkerError(
            "PLUGIN_LOAD_FAILED",
            f"could not initialize entry_point {entry_point!r}: "
            f"{type(exc).__name__}: {_truncate(exc)}",
            rpc_code=-32020,
        ) from exc


def _call_target(target: Callable[..., Any], arguments: Dict[str, Any]) -> Any:
    try:
        signature = inspect.signature(target)
    except (TypeError, ValueError):
        result = target(arguments)
    else:
        params = list(signature.parameters.values())
        positional = [
            param
            for param in params
            if param.kind in (inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD)
        ]
        has_var_keyword = any(param.kind == inspect.Parameter.VAR_KEYWORD for param in params)
        has_var_positional = any(param.kind == inspect.Parameter.VAR_POSITIONAL for param in params)

        if len(positional) == 1 and not has_var_keyword and not has_var_positional:
            param_name = positional[0].name
            if param_name in _PAYLOAD_ARG_NAMES:
                result = target(arguments)
            elif set(arguments.keys()) == {param_name}:
                result = target(arguments[param_name])
            else:
                result = target(arguments)
        elif not params:
            result = target()
        else:
            result = target(**arguments)

    if inspect.isawaitable(result):
        result = asyncio.run(result)
    return result


class PluginWorker:
    """Synchronous one-request-at-a-time JSON-RPC worker."""

    def __init__(self, input_stream: Any, output_stream: Any) -> None:
        self._input = input_stream
        self._output = output_stream
        self._max_message_bytes = DEFAULT_MAX_MESSAGE_BYTES
        self._initialized = False
        self._plugin_name = ""
        self._plugin_root: Optional[Path] = None
        self._capabilities: Dict[str, Callable[..., Any]] = {}

    def serve(self) -> None:
        while True:
            raw_line = self._input.readline(self._max_message_bytes + 2)
            if not raw_line:
                return
            if len(raw_line) > self._max_message_bytes + 1:
                self._send_error(None, -32600, "MESSAGE_TOO_LARGE", "request exceeds message limit")
                return
            if not raw_line.strip():
                continue
            if not self._handle_line(raw_line):
                return

    def _handle_line(self, raw_line: bytes) -> bool:
        request_id = None
        try:
            payload = json.loads(raw_line.decode("utf-8"))
            if not isinstance(payload, dict):
                raise WorkerError("INVALID_REQUEST", "request must be a JSON object", -32600)
            request_id = payload.get("id")
            if payload.get("jsonrpc") != "2.0":
                raise WorkerError("INVALID_REQUEST", "jsonrpc must be '2.0'", -32600)
            method = payload.get("method")
            params = payload.get("params") or {}
            if not isinstance(method, str) or not isinstance(params, dict):
                raise WorkerError("INVALID_REQUEST", "method/params have invalid types", -32600)

            if method == "initialize":
                result = self._initialize(params)
            elif not self._initialized:
                raise WorkerError("NOT_INITIALIZED", "initialize is required", -32002)
            elif method == "ping":
                result = {"plugin_name": self._plugin_name, "pid": os.getpid()}
            elif method == "tools/list":
                result = {"tools": [{"name": name} for name in sorted(self._capabilities)]}
            elif method == "tools/call":
                result = self._call_tool(params)
            elif method == "shutdown":
                self._send_result(request_id, {})
                return False
            else:
                raise WorkerError("METHOD_NOT_FOUND", f"method not found: {method}", -32601)

            self._send_result(request_id, result)
            return True
        except WorkerError as exc:
            self._send_error(request_id, exc.rpc_code, exc.code, exc.message)
            return True
        except (UnicodeDecodeError, json.JSONDecodeError):
            self._send_error(request_id, -32700, "PARSE_ERROR", "invalid JSON")
            return True
        except Exception as exc:  # noqa: BLE001 - protocol boundary
            traceback.print_exc(file=sys.stderr)
            self._send_error(
                request_id,
                -32603,
                "WORKER_INTERNAL_ERROR",
                f"{type(exc).__name__}: {_truncate(exc)}",
            )
            return True

    def _initialize(self, params: Dict[str, Any]) -> Dict[str, Any]:
        if self._initialized:
            raise WorkerError("ALREADY_INITIALIZED", "worker is already initialized", -32600)
        if params.get("protocol_version") != PROTOCOL_VERSION:
            raise WorkerError(
                "UNSUPPORTED_PROTOCOL",
                f"unsupported protocol_version: {params.get('protocol_version')!r}",
                -32602,
            )

        plugin_name = str(params.get("plugin_name") or "")
        root_value = str(params.get("plugin_root") or "")
        config = params.get("config") or {}
        capabilities = params.get("capabilities") or []
        limits = params.get("limits") or {}
        if not plugin_name or not root_value:
            raise WorkerError("INVALID_PARAMS", "plugin_name and plugin_root are required", -32602)
        if not isinstance(config, dict) or not isinstance(capabilities, list):
            raise WorkerError("INVALID_PARAMS", "config/capabilities have invalid types", -32602)

        root = Path(root_value).resolve()
        if not root.is_dir():
            raise WorkerError("PLUGIN_ROOT_NOT_FOUND", f"plugin root is not a directory: {root}", -32602)

        try:
            self._max_message_bytes = max(1024, int(limits.get("max_message_bytes") or DEFAULT_MAX_MESSAGE_BYTES))
            memory_bytes = int(limits.get("memory_bytes") or 0)
            cpu_seconds = int(limits.get("cpu_seconds") or 0)
        except (TypeError, ValueError) as exc:
            raise WorkerError("INVALID_PARAMS", "resource limits must be integers", -32602) from exc

        limits_applied = _apply_posix_limits(memory_bytes, cpu_seconds)

        os.chdir(str(root))
        _remove_script_directory_from_path()
        root_text = str(root)
        if root_text in sys.path:
            sys.path.remove(root_text)
        sys.path.insert(0, root_text)

        os.environ["SAGE_PLUGIN_NAME"] = plugin_name
        os.environ["SAGE_PLUGIN_ROOT"] = root_text
        os.environ["SAGE_PLUGIN_CONFIG_JSON"] = json.dumps(config, ensure_ascii=False)

        loaded: Dict[str, Callable[..., Any]] = {}
        seen_configured: Set[int] = set()
        for capability in capabilities:
            if not isinstance(capability, dict):
                raise WorkerError("INVALID_PARAMS", "capability entries must be objects", -32602)
            name = str(capability.get("name") or "")
            entry_point = str(capability.get("entry_point") or "")
            if not name or not entry_point:
                raise WorkerError("INVALID_PARAMS", "capability name/entry_point are required", -32602)
            if name in loaded:
                raise WorkerError("INVALID_PARAMS", f"duplicate capability: {name}", -32602)
            loaded[name] = _load_capability(entry_point, config, seen_configured)

        if not loaded:
            raise WorkerError("NO_CAPABILITIES", "plugin did not load any tool capability", -32602)

        self._plugin_name = plugin_name
        self._plugin_root = root
        self._capabilities = loaded
        self._initialized = True
        return {
            "protocol_version": PROTOCOL_VERSION,
            "plugin_name": plugin_name,
            "pid": os.getpid(),
            "capabilities": sorted(loaded.keys()),
            "limits_applied": limits_applied,
        }

    def _call_tool(self, params: Dict[str, Any]) -> Any:
        name = params.get("name")
        arguments = params.get("arguments") or {}
        if not isinstance(name, str) or name not in self._capabilities:
            raise WorkerError("CAPABILITY_NOT_FOUND", f"unknown tool capability: {name!r}", -32602)
        if not isinstance(arguments, dict):
            raise WorkerError("INVALID_PARAMS", "arguments must be an object", -32602)

        try:
            return _call_target(self._capabilities[name], arguments)
        except WorkerError:
            raise
        except SystemExit as exc:
            raise WorkerError(
                "PLUGIN_TOOL_ERROR",
                f"plugin tool attempted to exit the worker: {exc.code!r}",
                -32010,
            ) from exc
        except Exception as exc:  # noqa: BLE001 - plugin errors are structured results
            traceback.print_exc(file=sys.stderr)
            raise WorkerError(
                "PLUGIN_TOOL_ERROR",
                f"{type(exc).__name__}: {_truncate(exc)}",
                -32010,
            ) from exc

    def _send_result(self, request_id: Any, result: Any) -> None:
        try:
            self._send_payload({"jsonrpc": "2.0", "id": request_id, "result": result})
        except (TypeError, ValueError) as exc:
            self._send_error(
                request_id,
                -32011,
                "RESULT_NOT_SERIALIZABLE",
                f"plugin result is not JSON serializable: {_truncate(exc)}",
            )

    def _send_error(self, request_id: Any, rpc_code: int, code: str, message: str) -> None:
        self._send_payload(
            {
                "jsonrpc": "2.0",
                "id": request_id,
                "error": {
                    "code": rpc_code,
                    "message": _truncate(message),
                    "data": {"code": code},
                },
            }
        )

    def _send_payload(self, payload: Dict[str, Any]) -> None:
        raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        if len(raw) > self._max_message_bytes:
            if "result" in payload:
                self._send_error(
                    payload.get("id"),
                    -32012,
                    "RESULT_TOO_LARGE",
                    f"plugin result exceeds {self._max_message_bytes} bytes",
                )
                return
            raw = raw[: self._max_message_bytes]
        self._output.write(raw + b"\n")
        self._output.flush()


def main() -> int:
    input_stream = sys.stdin.buffer
    output_stream = sys.stdout.buffer
    # stdout now belongs to the protocol; plugin prints go to stderr.
    sys.stdout = sys.stderr
    try:
        PluginWorker(input_stream, output_stream).serve()
    except BrokenPipeError:
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
