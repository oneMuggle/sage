# ruff: noqa: UP006, UP007, UP035, UP045 — release/win7 Python 3.8 兼容
"""2026-11-26: 端点健康快照 API 测试。"""

from unittest.mock import patch

from backend.api.endpoint_health_routes import build_health_payload
from backend.services.endpoint_health import get_health_registry, reset_health_registry


def test_payload_lists_configured_endpoints_with_health():
    reset_health_registry()
    try:
        get_health_registry().record_failure("ep1", "timeout")
        with patch(
            "backend.api.endpoint_health_routes._configured_endpoint_ids",
            return_value=["ep1", "ep2"],
        ):
            payload = build_health_payload()
        by_id = {row["endpointId"]: row for row in payload["endpoints"]}
        assert by_id["ep1"]["status"] == "degraded"
        assert by_id["ep2"]["status"] == "healthy"
    finally:
        reset_health_registry()
