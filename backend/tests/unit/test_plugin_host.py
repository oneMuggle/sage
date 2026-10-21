"""R83 out-of-process plugin host tests."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional

import pytest

from backend.domain.plugin import FiberState
from backend.plugins.host import PluginHostError, PluginHostLimits, PluginHostManager
from backend.plugins.lifecycle import PluginRecord, PluginStatus
from backend.plugins.manifest import CapabilityType
from backend.plugins.registry import CapabilityRegistry


@pytest.fixture()
def host() -> Iterator[PluginHostManager]:
    manager = PluginHostManager(
        PluginHostLimits(
            startup_timeout_seconds=5,
            request_timeout_seconds=0.45,
            shutdown_timeout_seconds=1,
            max_message_bytes=2048,
        ),
        registry=CapabilityRegistry(),
    )
    try:
        yield manager
    finally:
        manager.shutdown_all()


def _record(
    tmp_path: Path,
    *,
    files: Dict[str, str],
    capabilities: List[Dict[str, Any]],
    status: PluginStatus = PluginStatus.ENABLED,
    config: Optional[Dict[str, Any]] = None,
) -> PluginRecord:
    root = tmp_path / "sample-plugin"
    root.mkdir(parents=True, exist_ok=True)
    for relative_path, content in files.items():
        target = root / relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")

    manifest = {
        "schema_version": "1.0",
        "name": "sample-plugin",
        "version": "1.0.0",
        "type": "personal",
        "metadata": {
            "display_name": "Sample Plugin",
            "description": "Host test plugin",
            "author": "Sage Tests",
        },
        "capabilities": capabilities,
        "dependencies": [],
        "min_sage_version": "0.4.0",
    }
    return PluginRecord(
        name="sample-plugin",
        version="1.0.0",
        status=status,
        install_path=str(root),
        installed_at=0.0,
        config=config or {},
        manifest=manifest,
    )


def _tool(name: str, entry_point: str) -> Dict[str, Any]:
    return {
        "type": "tool",
        "name": name,
        "description": name,
        "version": "1.0.0",
            "entry_point": entry_point,
        "permissions": [],
    }


_BASIC_PLUGIN = """
import json
import os
import time

print("plugin module loaded")
CONFIG = {}


def configure(config):
    CONFIG.clear()
    CONFIG.update(config)


def add(a, b):
    print("adding in plugin")
    return {"sum": a + b, "config": dict(CONFIG)}


def payload(arguments):
    return {"keys": sorted(arguments.keys())}


def env_info():
    return {
        "cwd": os.getcwd(),
        "secret": os.environ.get("SAGE_PLUGIN_TEST_SECRET"),
        "pythonpath": os.environ.get("PYTHONPATH"),
        "config": json.loads(os.environ["SAGE_PLUGIN_CONFIG_JSON"]),
    }


def fail():
    raise ValueError("kaput")


def big():
    return {"text": "x" * 3000}


def sleep():
    time.sleep(2)
    return {"slept": True}


def crash():
    os._exit(7)
"""


def _basic_record(tmp_path: Path, **kwargs: Any) -> PluginRecord:
    return _record(
        tmp_path,
        files={"handlers.py": _BASIC_PLUGIN},
        capabilities=[
            _tool("add", "handlers:add"),
            _tool("payload", "handlers.payload"),
            _tool("env_info", "handlers:env_info"),
            _tool("fail", "handlers:fail"),
            _tool("big", "handlers:big"),
            _tool("sleep", "handlers:sleep"),
            _tool("crash", "handlers:crash"),
        ],
        config={"greeting": "hello"},
        **kwargs,
    )


def test_host_starts_invokes_registers_and_stops(
    host: PluginHostManager,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SAGE_PLUGIN_TEST_SECRET", "do-not-leak")
    record = _basic_record(tmp_path)
    root = Path(record.install_path).resolve()

    status = host.start(record)

    assert status.state == FiberState.ACTIVE
    assert status.running is True
    assert status.pid is not None
    assert status.pid != os.getpid()
    assert set(status.capabilities) == {
        "add",
        "payload",
        "env_info",
        "fail",
        "big",
        "sleep",
        "crash",
    }

    assert host.invoke(record.name, "add", {"a": 2, "b": 3}) == {
        "sum": 5,
        "config": {"greeting": "hello"},
    }
    assert host.invoke(record.name, "payload", {"z": 1, "a": 2}) == {
        "keys": ["a", "z"]
    }

    handler = host.registry.get_handler(CapabilityType.TOOL, "add")
    assert handler is not None
    assert handler({"a": 4, "b": 6})["sum"] == 10
    assert handler(a=1, b=8)["sum"] == 9

    env = host.invoke(record.name, "env_info", {})
    assert Path(env["cwd"]).resolve() == root
    assert Path(env["pythonpath"]).resolve() == root
    assert env["secret"] is None
    assert env["config"] == {"greeting": "hello"}

    runtime = host.status(record.name)
    assert "plugin module loaded" in runtime.stderr_tail
    assert "adding in plugin" in runtime.stderr_tail

    stopped = host.stop(record.name)
    assert stopped.state == FiberState.DISPOSED
    assert stopped.running is False
    assert host.registry.get_handler(CapabilityType.TOOL, "add") is None

    with pytest.raises(PluginHostError) as exc_info:
        host.invoke(record.name, "add", {"a": 1, "b": 2})
    assert exc_info.value.code == "PLUGIN_NOT_RUNNING"
    assert exc_info.value.status_code == 409


def test_host_supports_class_async_execute_and_module_entry(
    host: PluginHostManager,
    tmp_path: Path,
) -> None:
    record = _record(
        tmp_path,
        files={
            "tools.py": """
class Greeter:
    def __init__(self):
        self.config = {}

    def configure(self, config):
        self.config = config

    async def execute(self, name):
        return {"message": f"{self.config.get('greeting', 'hi')} {name}"}


def run(arguments):
    return {"module_payload": arguments}
""",
        },
        capabilities=[
            _tool("greet", "tools:Greeter"),
            _tool("module_run", "tools"),
        ],
        config={"greeting": "hello"},
    )

    host.start(record)

    assert host.invoke(record.name, "greet", {"name": "Ada"}) == {
        "message": "hello Ada"
    }
    assert host.invoke(record.name, "module_run", {"x": 1}) == {
        "module_payload": {"x": 1}
    }


def test_plugin_errors_do_not_kill_worker_but_crash_and_timeout_do(
    host: PluginHostManager,
    tmp_path: Path,
) -> None:
    record = _basic_record(tmp_path)
    host.start(record)

    with pytest.raises(PluginHostError) as fail_error:
        host.invoke(record.name, "fail", {})
    assert fail_error.value.code == "PLUGIN_TOOL_ERROR"
    assert host.status(record.name).state == FiberState.ACTIVE
    assert host.invoke(record.name, "add", {"a": 1, "b": 1})["sum"] == 2

    with pytest.raises(PluginHostError) as big_error:
        host.invoke(record.name, "big", {})
    assert big_error.value.code == "RESULT_TOO_LARGE"
    assert host.status(record.name).state == FiberState.ACTIVE

    with pytest.raises(PluginHostError) as crash_error:
        host.invoke(record.name, "crash", {})
    assert crash_error.value.code == "PLUGIN_WORKER_EXITED"
    crashed = host.status(record.name)
    assert crashed.state == FiberState.FAILED
    assert crashed.exit_code == 7
    assert host.registry.get_handler(CapabilityType.TOOL, "add") is None

    restarted = host.restart(record)
    assert restarted.state == FiberState.ACTIVE
    assert restarted.restart_count == 1

    with pytest.raises(PluginHostError) as timeout_error:
        host.invoke(record.name, "sleep", {})
    assert timeout_error.value.code == "PLUGIN_REQUEST_TIMEOUT"
    assert timeout_error.value.status_code == 504
    assert host.status(record.name).state == FiberState.FAILED
    assert host.registry.get_handler(CapabilityType.TOOL, "add") is None


def test_host_refuses_unenabled_unsupported_and_broken_plugins(
    host: PluginHostManager,
    tmp_path: Path,
) -> None:
    unenabled = _basic_record(tmp_path / "unenabled", status=PluginStatus.INSTALLED)
    with pytest.raises(PluginHostError) as state_error:
        host.start(unenabled)
    assert state_error.value.code == "PLUGIN_NOT_ENABLED"
    assert state_error.value.status_code == 409

    unsupported = _record(
        tmp_path / "unsupported",
        files={"handlers.py": "def run(arguments):\n    return arguments\n"},
        capabilities=[
            {
                "type": "skill",
                "name": "skill-only",
                "description": "not hosted by R83",
                "version": "1.0.0",
                "entry_point": "handlers:run",
                "permissions": [],
            }
        ],
    )
    with pytest.raises(PluginHostError) as unsupported_error:
        host.start(unsupported)
    assert unsupported_error.value.code == "NO_SUPPORTED_CAPABILITIES"
    assert unsupported_error.value.status_code == 422

    broken = _record(
        tmp_path / "broken",
        files={},
        capabilities=[_tool("missing", "missing_module:run")],
    )
    with pytest.raises(PluginHostError) as load_error:
        host.start(broken)
    assert load_error.value.code == "PLUGIN_LOAD_FAILED"
    assert load_error.value.status_code == 422
    assert host.status(broken.name).state == FiberState.FAILED
    assert host.registry.list_plugins() == []
