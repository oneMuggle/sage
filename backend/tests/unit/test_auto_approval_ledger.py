"""对标 S3：会话自动放行台账 + 权限三档路由。"""

import pytest

from backend.services.auto_approval_ledger import (
    AutoApprovalLedger,
    get_auto_approval_ledger,
    reset_auto_approval_ledger,
    summarize_args,
)

pytestmark = pytest.mark.unit


class TestLedger:
    def test_record_count_side_effect_only(self):
        led = AutoApprovalLedger()
        led.record(session_id="s", tool_name="read_file", capability="read", mode="workspace_write", reason="r", args={"path": "a.md"})
        led.record(session_id="s", tool_name="write_file", capability="write", mode="workspace_write", reason="r", args={"path": "b.md"})
        led.record(session_id="s", tool_name="bash", capability="execute", mode="full_access", reason="r", args={"command": "ls  -la"})
        assert led.count("s") == 2
        assert led.count("s", side_effect_only=False) == 3
        items = led.list("s", side_effect_only=True)
        assert [i.tool_name for i in items] == ["write_file", "bash"]
        assert items[1].summary == "ls -la"
        assert items[1].to_dict()["capability"] == "execute"

    def test_ignores_missing_session(self):
        led = AutoApprovalLedger()
        assert led.record(session_id=None, tool_name="bash", capability="execute", mode="", reason="") is None
        assert led.count("x") == 0
        assert led.list("x") == []

    def test_bounds(self):
        led = AutoApprovalLedger(per_session_limit=2, session_limit=1)
        for i in range(3):
            led.record(session_id="a", tool_name=f"t{i}", capability="write", mode="", reason="")
        assert [i.tool_name for i in led.list("a")] == ["t1", "t2"]
        led.record(session_id="b", tool_name="x", capability="write", mode="", reason="")
        assert led.list("a") == []

    def test_summarize_args(self):
        assert summarize_args("bash", {"command": "x" * 500}).endswith("…")
        assert summarize_args("t", {"foo": 1, "bar": 2}) == "args: bar, foo"
        assert summarize_args("t", None) == ""

    def test_singleton_reset(self):
        reset_auto_approval_ledger()
        a = get_auto_approval_ledger()
        assert get_auto_approval_ledger() is a
        reset_auto_approval_ledger()
        assert get_auto_approval_ledger() is not a


class TestRoutes:
    @pytest.mark.asyncio
    async def test_preset_roundtrip(self, client):
        r = await client.get("/api/v1/permissions/preset")
        assert r.status_code == 200
        assert r.json()["preset"] == "standard"  # 默认 workspace_write
        assert r.json()["custom"] is False

        r2 = await client.post("/api/v1/permissions/preset", json={"preset": "auto"})
        assert r2.status_code == 200
        assert r2.json() == {"ok": True, "preset": "auto", "mode": "full_access"}
        r3 = await client.get("/api/v1/permissions/preset")
        assert r3.json()["preset"] == "auto"
        assert r3.json()["mode"] == "full_access"

        r4 = await client.post("/api/v1/permissions/preset", json={"preset": "bogus"})
        assert r4.status_code == 400

    @pytest.mark.asyncio
    async def test_preset_custom_mode(self, client):
        from backend.data.settings_repo import SettingsRepository

        SettingsRepository().set("permission_mode", "read_only", category="permissions")
        r = await client.get("/api/v1/permissions/preset")
        assert r.json()["custom"] is True
        assert r.json()["mode"] == "read_only"

    @pytest.mark.asyncio
    async def test_preset_origin_guard(self, client):
        r = await client.post(
            "/api/v1/permissions/preset",
            json={"preset": "auto"},
            headers={"Origin": "https://evil.example"},
        )
        assert r.status_code == 403

    @pytest.mark.asyncio
    async def test_session_auto_approvals(self, client):
        led = get_auto_approval_ledger()
        led.record(session_id="s9", tool_name="read_file", capability="read", mode="workspace_write", reason="只读")
        led.record(session_id="s9", tool_name="write_file", capability="write", mode="workspace_write", reason="放行", args={"path": "x.md"})
        r = await client.get("/api/v1/permissions/session/s9/auto-approvals")
        body = r.json()
        assert body["count"] == 1
        assert body["total"] == 2
        assert [i["tool_name"] for i in body["items"]] == ["write_file"]
        r2 = await client.get("/api/v1/permissions/session/s9/auto-approvals", params={"side_effect_only": "false"})
        assert len(r2.json()["items"]) == 2
        r3 = await client.get("/api/v1/permissions/session/none/auto-approvals")
        assert r3.json() == {"session_id": "none", "count": 0, "total": 0, "items": []}
