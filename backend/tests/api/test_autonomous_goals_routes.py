"""
闲时自主目标执行系统 — API 集成测试

测试 REST API 端点:
- GET/POST/PUT/DELETE /api/v1/goals
- POST /api/v1/goals/{id}/start|pause|cancel
- GET /api/v1/goals/{id}/report
"""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from backend.main import app

pytestmark = pytest.mark.integration


@pytest.fixture
async def client():
    """创建测试客户端"""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


class TestGoalsCRUD:
    """CRUD 端点测试"""

    @pytest.mark.asyncio
    async def test_create_goal(self, client):
        """测试创建目标"""
        payload = {
            "name": "Test Goal",
            "description": "Test description for autonomous goal",
        }
        resp = await client.post("/api/v1/goals", json=payload)
        assert resp.status_code == 201
        data = resp.json()
        assert data["name"] == "Test Goal"
        assert data["description"] == "Test description for autonomous goal"
        assert data["status"] == "pending"
        assert data["id"].startswith("goal_")

    @pytest.mark.asyncio
    async def test_create_goal_with_options(self, client):
        """测试创建目标（带时间窗口和预算）"""
        payload = {
            "name": "Night Task",
            "description": "Run during off-peak hours",
            "time_window": {
                "off_peak_start": "23:00",
                "off_peak_end": "05:00",
                "weekends_off_peak": True,
            },
            "budget": {
                "max_rounds": 5,
                "max_hours": 4.0,
                "max_tokens": 500000,
            },
        }
        resp = await client.post("/api/v1/goals", json=payload)
        assert resp.status_code == 201
        data = resp.json()
        assert data["time_window"]["off_peak_start"] == "23:00"
        assert data["budget"]["max_rounds"] == 5

    @pytest.mark.asyncio
    async def test_list_goals(self, client):
        """测试列出目标"""
        # 先创建两个
        await client.post("/api/v1/goals", json={"name": "Goal A", "description": "A"})
        await client.post("/api/v1/goals", json={"name": "Goal B", "description": "B"})

        resp = await client.get("/api/v1/goals")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] >= 2
        assert len(data["items"]) >= 2

    @pytest.mark.asyncio
    async def test_list_goals_filter_status(self, client):
        """测试按状态过滤"""
        # 创建一个 pending 目标
        await client.post(
            "/api/v1/goals", json={"name": "Filter Test", "description": "Test"}
        )

        resp = await client.get("/api/v1/goals?status=pending")
        assert resp.status_code == 200
        data = resp.json()
        assert all(item["status"] == "pending" for item in data["items"])

    @pytest.mark.asyncio
    async def test_get_goal(self, client):
        """测试获取目标详情"""
        create_resp = await client.post(
            "/api/v1/goals", json={"name": "Get Test", "description": "Test"}
        )
        goal_id = create_resp.json()["id"]

        resp = await client.get(f"/api/v1/goals/{goal_id}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == goal_id
        assert data["name"] == "Get Test"

    @pytest.mark.asyncio
    async def test_get_goal_not_found(self, client):
        """测试获取不存在目标"""
        resp = await client.get("/api/v1/goals/goal_nonexistent")
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_update_goal(self, client):
        """测试更新目标"""
        create_resp = await client.post(
            "/api/v1/goals", json={"name": "Original", "description": "Original desc"}
        )
        goal_id = create_resp.json()["id"]

        resp = await client.put(
            f"/api/v1/goals/{goal_id}",
            json={"name": "Updated", "description": "Updated desc"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "Updated"
        assert data["description"] == "Updated desc"

    @pytest.mark.asyncio
    async def test_delete_goal(self, client):
        """测试删除目标"""
        create_resp = await client.post(
            "/api/v1/goals", json={"name": "Delete Me", "description": "Test"}
        )
        goal_id = create_resp.json()["id"]

        resp = await client.delete(f"/api/v1/goals/{goal_id}")
        assert resp.status_code == 204

        # 确认已删除
        resp = await client.get(f"/api/v1/goals/{goal_id}")
        assert resp.status_code == 404


class TestGoalsExecutionControl:
    """执行控制端点测试"""

    @pytest.mark.asyncio
    async def test_start_goal(self, client):
        """测试启动目标"""
        create_resp = await client.post(
            "/api/v1/goals", json={"name": "Start Test", "description": "Test"}
        )
        goal_id = create_resp.json()["id"]

        resp = await client.post(f"/api/v1/goals/{goal_id}/start")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "running"

    @pytest.mark.asyncio
    async def test_start_goal_not_found(self, client):
        """测试启动不存在目标"""
        resp = await client.post("/api/v1/goals/goal_nonexistent/start")
        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_pause_goal(self, client):
        """测试暂停目标"""
        create_resp = await client.post(
            "/api/v1/goals", json={"name": "Pause Test", "description": "Test"}
        )
        goal_id = create_resp.json()["id"]

        # 直接通过 update 设为 running（避免后台 _execute_loop 干扰）
        await client.put(
            f"/api/v1/goals/{goal_id}", json={"status": "running"}
        )

        # 再暂停
        resp = await client.post(f"/api/v1/goals/{goal_id}/pause")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "paused"

    @pytest.mark.asyncio
    async def test_cancel_goal(self, client):
        """测试取消目标"""
        create_resp = await client.post(
            "/api/v1/goals", json={"name": "Cancel Test", "description": "Test"}
        )
        goal_id = create_resp.json()["id"]

        resp = await client.post(f"/api/v1/goals/{goal_id}/cancel")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "cancelled"


class TestGoalsReport:
    """报告端点测试"""

    @pytest.mark.asyncio
    async def test_get_report(self, client):
        """测试获取执行报告"""
        create_resp = await client.post(
            "/api/v1/goals", json={"name": "Report Test", "description": "Test"}
        )
        goal_id = create_resp.json()["id"]

        resp = await client.get(f"/api/v1/goals/{goal_id}/report")
        assert resp.status_code == 200
        data = resp.json()
        assert data["goal_id"] == goal_id
        assert data["goal_name"] == "Report Test"
        assert data["total_rounds"] == 0

    @pytest.mark.asyncio
    async def test_get_report_not_found(self, client):
        """测试获取不存在目标的报告"""
        resp = await client.get("/api/v1/goals/goal_nonexistent/report")
        assert resp.status_code == 404


class TestGoalsValidation:
    """输入验证测试"""

    @pytest.mark.asyncio
    async def test_create_goal_missing_name(self, client):
        """测试缺少名称"""
        resp = await client.post(
            "/api/v1/goals", json={"description": "No name"}
        )
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_create_goal_missing_description(self, client):
        """测试缺少描述"""
        resp = await client.post("/api/v1/goals", json={"name": "No desc"})
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_create_goal_invalid_budget(self, client):
        """测试无效预算"""
        resp = await client.post(
            "/api/v1/goals",
            json={
                "name": "Test",
                "description": "Test",
                "budget": {"max_rounds": -1},
            },
        )
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_list_goals_invalid_status(self, client):
        """测试无效状态过滤"""
        resp = await client.get("/api/v1/goals?status=invalid_status")
        assert resp.status_code == 400
