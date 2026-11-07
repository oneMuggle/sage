"""P2-5 渐进式授权 — /api/v1/permissions/trust-policy 契约回归测试。

缺陷 F 回归守卫：修复前 POST /trust-policy 返回 500（SettingsRepository.KEYS
缺登记 → set() 抛 ValueError），GET 恒返回 enabled=false（get() 返 None）。
本模块走真实 ASGI app + 真实仓储路径，确保链路不再整体失效。
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.unit


async def test_get_trust_policy_defaults_to_disabled(client):
    """GET 默认：enabled=false、threshold=DEFAULT_TRUST_THRESHOLD、ok=True。"""
    from backend.services.trust_escalation import DEFAULT_TRUST_THRESHOLD

    resp = await client.get("/api/v1/permissions/trust-policy")

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["enabled"] is False
    assert body["threshold"] == DEFAULT_TRUST_THRESHOLD
    assert body["default_threshold"] == DEFAULT_TRUST_THRESHOLD
    assert body["settings_keys"]["enabled"] == "trust_escalation_enabled"
    assert body["settings_keys"]["threshold"] == "trust_escalation_threshold"
    assert isinstance(body["consecutive"], dict)


async def test_post_trust_policy_enables_and_get_reflects(client):
    """POST 开启 + 阈值 → 200；再次 GET 反映写入值。

    缺陷 F 修复前本用例会因 POST 500 直接失败。
    """
    post_resp = await client.post(
        "/api/v1/permissions/trust-policy",
        json={"enabled": True, "threshold": 5},
    )
    assert post_resp.status_code == 200, post_resp.text
    post_body = post_resp.json()
    assert post_body["ok"] is True
    assert post_body["enabled"] is True
    assert post_body["threshold"] == 5

    get_resp = await client.get("/api/v1/permissions/trust-policy")
    assert get_resp.status_code == 200
    get_body = get_resp.json()
    assert get_body["enabled"] is True
    assert get_body["threshold"] == 5


async def test_post_trust_policy_can_disable(client):
    """POST 关闭开关 → GET 反映 enabled=false。"""
    # 先开启（确保关闭路径不是空数据库的默认值巧合）
    await client.post(
        "/api/v1/permissions/trust-policy",
        json={"enabled": True, "threshold": 3},
    )

    disable_resp = await client.post(
        "/api/v1/permissions/trust-policy",
        json={"enabled": False},
    )
    assert disable_resp.status_code == 200
    body = disable_resp.json()
    assert body["enabled"] is False
    # 未提供 threshold 时使用默认值（不是继承上一次）
    from backend.services.trust_escalation import DEFAULT_TRUST_THRESHOLD

    assert body["threshold"] == DEFAULT_TRUST_THRESHOLD

    get_resp = await client.get("/api/v1/permissions/trust-policy")
    assert get_resp.json()["enabled"] is False


async def test_post_trust_policy_clamps_threshold_to_valid_range(client):
    """阈值超 [1, 20] 区间 → 服务端自动夹紧，不报 500/422。"""
    low = await client.post(
        "/api/v1/permissions/trust-policy",
        json={"enabled": True, "threshold": -7},
    )
    assert low.status_code == 200
    assert low.json()["threshold"] == 1

    high = await client.post(
        "/api/v1/permissions/trust-policy",
        json={"enabled": True, "threshold": 999},
    )
    assert high.status_code == 200
    assert high.json()["threshold"] == 20


async def test_post_trust_policy_ignores_extra_fields(client):
    """TrustPolicyBody 未开 extra=forbid → 多余字段被忽略，不影响主流程。"""
    resp = await client.post(
        "/api/v1/permissions/trust-policy",
        json={"enabled": True, "threshold": 4, "bogus": "x"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["enabled"] is True
    assert body["threshold"] == 4
