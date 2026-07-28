"""M3 — hardened MCP server pool unit tests (in-process fakes).

Fakes are injected at the client_factory seam: no subprocesses here.
Covers parallel discovery isolation, per-server state machine, call-time
reconnect, background re-discovery cooldown, status report, runtime
add/update/remove, and tool fan-out into tracked registries.
"""

import time

import pytest

from backend.mcp import pool as pool_mod
from backend.mcp.client import McpClientError
from backend.mcp.config import validate_server_config
from backend.mcp.pool import McpServerPool, ServerState, namespaced_tool_name
from backend.tools.registry import ToolRegistry


class FakeMcpClient:
    """In-process stand-in for McpClient (same surface the pool uses)."""

    def __init__(self, config, tools=None, fail_start=None, fail_call=None):
        self.config = config
        self._tools = tools or []
        self._fail_start = fail_start
        self._fail_call = fail_call
        self._running = False
        self.start_count = 0
        self.calls = []

    def start(self):
        self.start_count += 1
        if self._fail_start:
            raise McpClientError(self._fail_start)
        self._running = True

    def list_tools(self):
        return list(self._tools)

    def call_tool(self, name, arguments):
        self.calls.append((name, arguments))
        if self._fail_call:
            raise McpClientError(self._fail_call)
        return {
            "content": [{"type": "text", "text": f"ok:{name}:{arguments}"}],
            "isError": False,
        }

    @property
    def is_running(self):
        return self._running

    def stop(self):
        self._running = False

    def die(self):
        """Simulate subprocess death without stop() bookkeeping."""
        self._running = False


def make_tools(*names):
    return [
        {"name": n, "description": "d-" + n, "inputSchema": {"type": "object"}}
        for n in names
    ]


class FakeFactory:
    """Records every client the pool creates; per-server behavior map."""

    def __init__(self, behavior=None):
        self.behavior = behavior or {}
        self.created = []

    def __call__(self, config):
        params = self.behavior.get(config.name, {})
        client = FakeMcpClient(config, **params)
        self.created.append(client)
        return client


def build_pool(factory, configs, cooldown=60.0):
    pool = McpServerPool(client_factory=factory, rediscovery_cooldown=cooldown)
    pool.sync_configs(configs)
    return pool


class TestDiscovery:
    def test_parallel_discovery_all_ready(self):
        factory = FakeFactory(
            {"a": {"tools": make_tools("t1", "t2")}, "b": {"tools": make_tools("x")}}
        )
        pool = build_pool(
            factory,
            [
                validate_server_config(name="a", command="node"),
                validate_server_config(name="b", command="node"),
            ],
        )
        report = pool.discover_all()
        assert report.all_ready
        assert not report.degraded
        by_name = {s.name: s for s in report.servers}
        assert by_name["a"].tool_count == 2
        assert by_name["b"].tool_count == 1
        assert by_name["a"].state == "ready"

    def test_one_failure_never_blocks_others(self):
        factory = FakeFactory(
            {
                "good": {"tools": make_tools("t")},
                "bad": {"fail_start": "command not found"},
            }
        )
        pool = build_pool(
            factory,
            [
                validate_server_config(name="good", command="node"),
                validate_server_config(name="bad", command="nope"),
            ],
        )
        report = pool.discover_all()
        states = {s.name: s.state for s in report.servers}
        assert states == {"good": "ready", "bad": "failed"}
        assert report.degraded
        assert not report.all_ready
        bad = pool.get_record("bad")
        assert "command not found" in bad.last_error
        # good server still serves calls
        resp = pool.call_tool("good", "t", {"k": 1})
        assert resp["isError"] is False

    def test_disabled_server_not_discovered(self):
        factory = FakeFactory({"off": {"tools": make_tools("t")}})
        pool = build_pool(
            factory, [validate_server_config(name="off", command="node", enabled=False)]
        )
        report = pool.discover_all()
        assert factory.created == []
        (entry,) = report.servers
        assert entry.state == "disabled"

    def test_required_failure_flagged(self):
        factory = FakeFactory({"crit": {"fail_start": "boom"}})
        pool = build_pool(
            factory, [validate_server_config(name="crit", command="x", required=True)]
        )
        report = pool.discover_all()
        assert report.failed_required

    def test_unexpected_exception_isolated_as_failed(self):
        class BoomFactory:
            def __call__(self, config):
                raise RuntimeError("surprise")

        pool = build_pool(BoomFactory(), [validate_server_config(name="s", command="c")])
        report = pool.discover_all()
        (entry,) = report.servers
        assert entry.state == "failed"
        assert "surprise" in entry.last_error


class TestCallIsolation:
    def test_call_on_unknown_server_clean_error(self):
        pool = build_pool(FakeFactory(), [])
        with pytest.raises(McpClientError, match="不可用"):
            pool.call_tool("ghost", "t", {})

    def test_call_on_disabled_server_clean_error(self):
        pool = build_pool(
            FakeFactory(), [validate_server_config(name="off", command="c", enabled=False)]
        )
        with pytest.raises(McpClientError, match="禁用"):
            pool.call_tool("off", "t", {})

    def test_dead_client_triggers_one_reconnect_and_succeeds(self):
        factory = FakeFactory({"s": {"tools": make_tools("t")}})
        pool = build_pool(factory, [validate_server_config(name="s", command="c")])
        pool.discover_all()
        first = factory.created[0]
        first.die()

        resp = pool.call_tool("s", "t", {"a": 1})
        assert resp["isError"] is False
        assert len(factory.created) == 2  # exactly one reconnect
        assert pool.get_record("s").state == ServerState.READY

    def test_reconnect_failure_yields_clean_error_and_failed_state(self):
        factory = FakeFactory(
            {"s": {"tools": make_tools("t")}}
        )
        pool = build_pool(factory, [validate_server_config(name="s", command="c")])
        pool.discover_all()
        factory.created[0].die()
        # reconnect attempt will fail from now on
        factory.behavior["s"] = {"fail_start": "still dead"}

        with pytest.raises(McpClientError, match="不可用"):
            pool.call_tool("s", "t", {})
        assert pool.get_record("s").state == ServerState.FAILED

    def test_tool_level_error_does_not_flip_state(self):
        factory = FakeFactory({"s": {"tools": make_tools("t"), "fail_call": "tool exploded"}})
        pool = build_pool(factory, [validate_server_config(name="s", command="c")])
        pool.discover_all()
        with pytest.raises(McpClientError, match="tool exploded"):
            pool.call_tool("s", "t", {})
        # server still alive → still READY
        assert pool.get_record("s").state == ServerState.READY
        assert len(factory.created) == 1  # no reconnect for tool errors


class TestBackgroundRediscovery:
    def test_background_timer_recovers_failed_server(self):
        factory = FakeFactory({"s": {"fail_start": "down"}})
        pool = build_pool(
            factory, [validate_server_config(name="s", command="c")], cooldown=0.2
        )
        pool.discover_all()
        assert pool.get_record("s").state == ServerState.FAILED

        # call-time reconnect fails too → schedules background rediscovery
        with pytest.raises(McpClientError):
            pool.call_tool("s", "t", {})

        # now the server "comes back": the cooldown timer must recover it
        factory.behavior["s"] = {"tools": make_tools("t")}
        deadline = time.time() + 5
        while time.time() < deadline:
            if pool.get_record("s").state == ServerState.READY:
                break
            time.sleep(0.05)
        assert pool.get_record("s").state == ServerState.READY
        assert pool.call_tool("s", "t", {})["isError"] is False

    def test_cooldown_prevents_timer_stampede(self):
        factory = FakeFactory({"s": {"fail_start": "down"}})
        pool = build_pool(
            factory, [validate_server_config(name="s", command="c")], cooldown=60
        )
        pool.discover_all()
        for _ in range(5):
            with pytest.raises(McpClientError):
                pool.call_tool("s", "t", {})
        # one timer, not five
        assert len(pool._rediscover_timers) == 1
        pool.shutdown_all()


class TestRuntimeManagement:
    def test_add_server_duplicate_rejected(self, tmp_path, monkeypatch):
        monkeypatch.setattr(pool_mod, "upsert_user_server_config", lambda c, path=None: [])
        factory = FakeFactory({"a": {"tools": make_tools("t")}})
        pool = build_pool(factory, [validate_server_config(name="a", command="c")])
        with pytest.raises(McpClientError, match="已存在"):
            pool.add_server(validate_server_config(name="a", command="c"))

    def test_add_server_persists_and_discovers(self, monkeypatch):
        saved = []
        monkeypatch.setattr(
            pool_mod, "upsert_user_server_config", lambda c, path=None: saved.append(c)
        )
        factory = FakeFactory({"new": {"tools": make_tools("t")}})
        pool = build_pool(factory, [])
        record = pool.add_server(validate_server_config(name="new", command="c"))
        assert record.state == ServerState.READY
        assert [c.name for c in saved] == ["new"]

    def test_update_disable_stops_and_unregisters(self, monkeypatch):
        monkeypatch.setattr(pool_mod, "upsert_user_server_config", lambda c, path=None: [])
        factory = FakeFactory({"s": {"tools": make_tools("t")}})
        pool = build_pool(factory, [validate_server_config(name="s", command="c")])
        pool.discover_all()
        registry = ToolRegistry()
        pool.track_registry(registry)
        pool.register_tools_into(registry)
        assert registry.exists("mcp__s__t")

        record = pool.update_server("s", enabled=False)
        assert record.state == ServerState.DISABLED
        assert not registry.exists("mcp__s__t")
        assert factory.created[0].is_running is False

    def test_update_timeout_persists(self, monkeypatch):
        saved = []
        monkeypatch.setattr(
            pool_mod, "upsert_user_server_config", lambda c, path=None: saved.append(c)
        )
        factory = FakeFactory({"s": {"tools": make_tools("t")}})
        pool = build_pool(factory, [validate_server_config(name="s", command="c")])
        pool.discover_all()
        pool.update_server("s", timeout_seconds=99.0)
        assert saved[-1].timeout_seconds == 99.0

    def test_update_unknown_server_raises_keyerror(self, monkeypatch):
        pool = build_pool(FakeFactory(), [])
        with pytest.raises(KeyError):
            pool.update_server("ghost", enabled=True)

    def test_remove_builtin_without_override_rejected(self, monkeypatch):
        monkeypatch.setattr(pool_mod, "builtin_names", lambda: ["drawio"])
        monkeypatch.setattr(pool_mod, "delete_user_server_config", lambda name, path=None: False)
        factory = FakeFactory({"drawio": {"tools": make_tools("t")}})
        pool = build_pool(factory, [validate_server_config(name="drawio", command="c")])
        with pytest.raises(McpClientError, match="内置"):
            pool.remove_server("drawio")

    def test_remove_user_server_stops_and_drops(self, monkeypatch):
        monkeypatch.setattr(pool_mod, "builtin_names", lambda: [])
        monkeypatch.setattr(pool_mod, "delete_user_server_config", lambda name, path=None: True)
        monkeypatch.setattr(pool_mod, "load_server_configs", lambda path=None: [])
        factory = FakeFactory({"s": {"tools": make_tools("t")}})
        pool = build_pool(factory, [validate_server_config(name="s", command="c")])
        pool.discover_all()
        registry = ToolRegistry()
        pool.track_registry(registry)
        pool.register_tools_into(registry)

        pool.remove_server("s")
        assert pool.get_record("s") is None
        assert not registry.exists("mcp__s__t")
        assert factory.created[0].is_running is False


class TestRegistryFanout:
    def test_tools_registered_with_mcp_namespace(self):
        factory = FakeFactory({"s": {"tools": make_tools("alpha", "beta")}})
        pool = build_pool(factory, [validate_server_config(name="s", command="c")])
        registry = ToolRegistry()
        pool.track_registry(registry)
        pool.discover_all()  # discovery after tracking → live fan-out
        assert registry.exists("mcp__s__alpha")
        assert registry.exists("mcp__s__beta")

    def test_register_tools_into_is_first_wins(self):
        factory = FakeFactory({"s": {"tools": make_tools("t")}})
        pool = build_pool(factory, [validate_server_config(name="s", command="c")])
        pool.discover_all()
        registry = ToolRegistry()
        first = pool.register_tools_into(registry)
        second = pool.register_tools_into(registry)
        assert first == 1
        assert second == 0  # already registered → skipped with warning

    def test_dead_registry_ref_pruned(self):
        factory = FakeFactory({"s": {"tools": make_tools("t")}})
        pool = build_pool(factory, [validate_server_config(name="s", command="c")])
        registry = ToolRegistry()
        pool.track_registry(registry)
        del registry  # weak ref dies
        pool.discover_all()  # must not raise on dead ref
        assert pool.get_record("s").state == ServerState.READY

    def test_execute_through_mcp_tool(self):
        from backend.mcp.tool import McpTool

        factory = FakeFactory({"s": {"tools": make_tools("t")}})
        pool = build_pool(factory, [validate_server_config(name="s", command="c")])
        pool.discover_all()
        tool = McpTool(pool, "s", make_tools("t")[0])
        assert tool.name == "mcp__s__t"
        result = tool.execute(text="hi")
        assert result.success
        assert "ok:t:" in result.content

    def test_execute_on_failed_server_returns_clean_tool_result(self):
        from backend.mcp.tool import McpTool

        factory = FakeFactory({"s": {"fail_start": "gone"}})
        pool = build_pool(factory, [validate_server_config(name="s", command="c")])
        pool.discover_all()
        tool = McpTool(pool, "s", make_tools("t")[0])
        result = tool.execute()
        assert result.success is False
        assert "不可用" in result.error


class TestNamespacing:
    def test_namespaced_tool_name(self):
        assert namespaced_tool_name("drawio", "render") == "mcp__drawio__render"
        assert namespaced_tool_name("a-b_1", "x") == "mcp__a-b_1__x"
