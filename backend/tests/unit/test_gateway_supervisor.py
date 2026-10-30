"""GatewaySupervisor 单元测试（懒启动 / 动态启停 / 故障隔离）。"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from backend.gateway import supervisor as sup_mod

pytestmark = pytest.mark.unit


class FakeGateway:
    def __init__(self) -> None:
        self.started = 0
        self.stopped = 0

    def start_polling(self) -> None:
        self.started += 1

    def stop_polling(self) -> None:
        self.stopped += 1


def _install_fake_module(monkeypatch, platform: str, state: dict, reset_count: dict) -> None:
    """把 supervisor 的平台表替换为单个假平台，getter 读取 state['gateway']。"""

    def get_gateway():
        return state["gateway"]

    def reset_gateway():
        reset_count["n"] += 1

    fake_module = SimpleNamespace(get_gateway=get_gateway, reset_gateway=reset_gateway)
    monkeypatch.setattr(
        sup_mod,
        "_PLATFORMS",
        {platform: ("fake.module", "get_gateway", "reset_gateway")},
    )
    monkeypatch.setattr(sup_mod.importlib, "import_module", lambda name: fake_module)


def test_apply_starts_configured_gateway(monkeypatch):
    gateway = FakeGateway()
    state = {"gateway": gateway}
    resets = {"n": 0}
    _install_fake_module(monkeypatch, "demo", state, resets)

    supervisor = sup_mod.GatewaySupervisor()
    assert supervisor.apply("demo") is gateway
    assert gateway.started == 1
    assert supervisor.is_running("demo")
    assert resets["n"] == 1


def test_apply_stops_old_instance_on_reconfigure(monkeypatch):
    first = FakeGateway()
    second = FakeGateway()
    state = {"gateway": first}
    resets = {"n": 0}
    _install_fake_module(monkeypatch, "demo", state, resets)

    supervisor = sup_mod.GatewaySupervisor()
    supervisor.apply("demo")
    state["gateway"] = second
    assert supervisor.apply("demo") is second
    assert first.stopped == 1
    assert second.started == 1


def test_apply_keeps_stopped_when_config_removed(monkeypatch):
    gateway = FakeGateway()
    state = {"gateway": gateway}
    resets = {"n": 0}
    _install_fake_module(monkeypatch, "demo", state, resets)

    supervisor = sup_mod.GatewaySupervisor()
    supervisor.apply("demo")
    state["gateway"] = None
    assert supervisor.apply("demo") is None
    assert gateway.stopped == 1
    assert not supervisor.is_running("demo")


def test_unknown_platform_raises():
    supervisor = sup_mod.GatewaySupervisor()
    with pytest.raises(KeyError):
        supervisor.apply("unknown")


def test_start_enabled_isolates_platform_failures(monkeypatch):
    good = FakeGateway()
    monkeypatch.setattr(
        sup_mod,
        "_PLATFORMS",
        {
            "bad": ("fake.bad", "get_gateway", "reset_gateway"),
            "good": ("fake.good", "get_gateway", "reset_gateway"),
        },
    )

    def import_module(name):
        if name == "fake.bad":
            raise RuntimeError("boom")
        return SimpleNamespace(
            get_gateway=lambda: good,
            reset_gateway=lambda: None,
        )

    monkeypatch.setattr(sup_mod.importlib, "import_module", import_module)

    report = sup_mod.GatewaySupervisor().start_enabled()
    assert report == {"bad": False, "good": True}
