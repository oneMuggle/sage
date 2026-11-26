"""2026-11-26: FailoverEvent → 前端 retry_info 映射测试。"""

from backend.core.legacy.agent import _failover_retry_info
from backend.core.legacy.llm_client import FailoverEvent


def test_failover_event_maps_to_retry_info():
    info = _failover_retry_info(
        FailoverEvent(
            from_endpoint="ep1",
            from_endpoint_name="Primary",
            to_endpoint="ep2",
            to_endpoint_name="Backup",
            reason="timeout",
            hop_index=0,
            total_hops=2,
        )
    )
    assert info["kind"] == "failover"
    assert info["from_endpoint"] == "ep1"
    assert info["to_endpoint"] == "ep2"
    assert info["from_endpoint_name"] == "Primary"
    assert info["to_endpoint_name"] == "Backup"
    assert info["error_type"] == "timeout"
    assert info["total_hops"] == 2
