"""2026-11-26: 端点健康注册表状态机测试。"""

from backend.services.endpoint_health import (
    DEGRADED,
    FAILED,
    HEALTHY,
    EndpointHealthRegistry,
)


def test_state_machine_and_recovery():
    now = {"t": 1000.0}
    reg = EndpointHealthRegistry(threshold=2, cooldown_s=60, clock=lambda: now["t"])
    reg.record_failure("ep1", "timeout")
    assert reg.get("ep1").status == DEGRADED
    reg.record_failure("ep1", "timeout")
    assert reg.get("ep1").status == FAILED
    assert reg.is_available("ep1") is False
    now["t"] += 61
    assert reg.is_available("ep1") is True  # 被动 failback：冷却期满允许重试
    reg.record_success("ep1")
    state = reg.get("ep1")
    assert state.status == HEALTHY
    assert state.consecutive_failures == 0
    assert state.last_failure_reason is None


def test_snapshot_includes_requested_endpoints_as_healthy():
    reg = EndpointHealthRegistry()
    reg.record_failure("ep1", "rate_limited")
    snap = {row["endpointId"]: row for row in reg.snapshot(["ep1", "ep2"])}
    assert snap["ep1"]["status"] == DEGRADED
    assert snap["ep2"]["status"] == HEALTHY
    assert snap["ep2"]["consecutiveFailures"] == 0


def test_record_failover_counter():
    reg = EndpointHealthRegistry()
    reg.record_failover("ep1")
    assert reg.snapshot(["ep1"])[0]["failoverCount"] == 1


def test_configure_updates_threshold_and_cooldown():
    now = {"t": 100.0}
    reg = EndpointHealthRegistry(threshold=5, cooldown_s=600, clock=lambda: now["t"])
    reg.configure(threshold=1, cooldown_s=10)
    reg.record_failure("ep1", "probe")
    assert reg.get("ep1").status == FAILED
    assert reg.is_available("ep1") is False
    now["t"] += 11
    assert reg.is_available("ep1") is True


def test_unknown_endpoint_is_available():
    reg = EndpointHealthRegistry()
    assert reg.is_available("missing") is True
    assert reg.is_available(None) is True
