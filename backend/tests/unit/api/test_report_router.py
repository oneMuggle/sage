"""报告 REST 路由测试（P3）。

覆盖：生成即存档、列表、详情、404/503 分支，以及**字面量路径必须排在
``/reports/{report_id}`` 之前**这一路由顺序约束 —— 否则
``POST /reports/generate`` 会被整数路径参数吞掉。
"""
from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api.report_router import build_router
from backend.data.database import Database
from backend.services.report_service import ReportService
from backend.services.worklog_service import WorklogService


@pytest.fixture()
def service():
    with tempfile.TemporaryDirectory() as tmpdir:
        db = Database(db_path=str(Path(tmpdir) / "report_router_test.db"))
        db.init_db()
        report_service = ReportService(db)
        worklog_service = WorklogService(db)
        yield report_service, worklog_service
        db.close()


@pytest.fixture()
def client(service):
    report_service, worklog_service = service
    app = FastAPI()
    app.include_router(
        build_router(lambda: report_service, lambda: worklog_service)
    )
    return TestClient(app)


@pytest.fixture()
def uninitialised_client():
    """服务未初始化 —— 依赖注入应返回 503 而不是 AttributeError。"""
    app = FastAPI()
    app.include_router(build_router(lambda: None, lambda: None))
    return TestClient(app)


# ======================================================================
# 路由顺序
# ======================================================================


def test_generate_path_is_not_swallowed_by_path_param(client):
    """``/reports/generate`` 不能落到 ``/reports/{report_id}`` 上。"""
    response = client.post("/reports/generate", json={"report_type": "daily"})

    assert response.status_code == 201


# ======================================================================
# 生成即存档
# ======================================================================


def test_generate_creates_and_returns_report(client):
    response = client.post("/reports/generate", json={"report_type": "daily"})

    assert response.status_code == 201
    body = response.json()
    report = body["report"]
    assert report["id"] > 0
    assert report["report_type"] == "daily"
    assert report["content"]
    assert report["stats"]["ai_generated"] is False


def test_generate_defaults_period_to_today(client):
    response = client.post("/reports/generate", json={"report_type": "daily"})

    report = response.json()["report"]
    assert report["period_start"] == report["period_end"]


def test_generate_weekly_defaults_to_seven_day_window(client):
    response = client.post("/reports/generate", json={"report_type": "weekly"})

    report = response.json()["report"]
    assert report["period_start"] < report["period_end"]


def test_generate_accepts_explicit_period(client):
    response = client.post(
        "/reports/generate",
        json={
            "report_type": "daily",
            "period_start": "2026-11-20",
            "period_end": "2026-11-26",
        },
    )

    assert response.status_code == 201
    report = response.json()["report"]
    assert report["period_start"] == "2026-11-20"
    assert report["period_end"] == "2026-11-26"


def test_generate_uses_custom_title(client):
    response = client.post(
        "/reports/generate",
        json={"report_type": "daily", "title": "我的复盘"},
    )

    assert response.json()["report"]["title"] == "我的复盘"


def test_generate_rejects_unknown_report_type(client):
    response = client.post("/reports/generate", json={"report_type": "monthly"})

    assert response.status_code == 422


def test_generate_rejects_unknown_field(client):
    response = client.post(
        "/reports/generate", json={"report_type": "daily", "bogus": 1}
    )

    assert response.status_code == 422


def test_generate_rejects_invalid_date(client):
    response = client.post(
        "/reports/generate",
        json={"report_type": "daily", "period_start": "not-a-date"},
    )

    assert response.status_code == 400


def test_generate_rejects_inverted_period(client):
    response = client.post(
        "/reports/generate",
        json={
            "report_type": "weekly",
            "period_start": "2026-11-26",
            "period_end": "2026-11-20",
        },
    )

    assert response.status_code == 400


def test_generate_persists_report(client):
    """生成即存档 —— 返回的那条就在库里。"""
    created = client.post("/reports/generate", json={"report_type": "daily"})
    report_id = created.json()["report"]["id"]

    fetched = client.get(f"/reports/{report_id}")

    assert fetched.status_code == 200
    assert fetched.json()["id"] == report_id
    assert fetched.json()["content"] == created.json()["report"]["content"]


def test_generate_uses_llm_when_available(client, monkeypatch):
    from backend.services import report_ai

    class _FakeClient:
        async def complete(self, prompt: str) -> str:
            return "## 完成\n- 模型写的"

    monkeypatch.setattr(report_ai, "_client", lambda: _FakeClient())

    response = client.post("/reports/generate", json={"report_type": "daily"})

    report = response.json()["report"]
    assert report["stats"]["ai_generated"] is True
    assert "模型写的" in report["content"]


def test_generate_falls_back_to_template_without_llm(client, monkeypatch):
    from backend.services import report_ai
    from backend.services.llm_endpoint import LLMNotConfiguredError

    def _boom() -> Any:
        raise LLMNotConfiguredError("LLM 未配置")

    monkeypatch.setattr(report_ai, "_client", _boom)

    response = client.post("/reports/generate", json={"report_type": "daily"})

    assert response.status_code == 201
    report = response.json()["report"]
    assert report["stats"]["ai_generated"] is False
    assert report["content"]


# ======================================================================
# 列表
# ======================================================================


def test_list_reports_returns_envelope(client):
    client.post("/reports/generate", json={"report_type": "daily"})

    response = client.get("/reports")

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert len(body["items"]) == 1
    assert body["limit"] > 0
    assert body["offset"] == 0


def test_list_reports_filters_by_type(client):
    client.post("/reports/generate", json={"report_type": "daily"})
    client.post("/reports/generate", json={"report_type": "weekly"})

    daily = client.get("/reports", params={"report_type": "daily"}).json()
    weekly = client.get("/reports", params={"report_type": "weekly"}).json()

    assert daily["total"] == 1
    assert weekly["total"] == 1
    assert daily["items"][0]["report_type"] == "daily"


def test_list_reports_rejects_invalid_type(client):
    response = client.get("/reports", params={"report_type": "monthly"})

    assert response.status_code == 422


def test_list_reports_paginates(client):
    for _ in range(3):
        client.post("/reports/generate", json={"report_type": "daily"})

    page = client.get("/reports", params={"limit": 2, "offset": 0}).json()

    assert len(page["items"]) == 2
    assert page["total"] == 3


def test_list_reports_is_newest_first(client):
    first = client.post("/reports/generate", json={"report_type": "daily"})
    second = client.post("/reports/generate", json={"report_type": "daily"})

    items = client.get("/reports").json()["items"]

    assert items[0]["id"] == second.json()["report"]["id"]
    assert items[1]["id"] == first.json()["report"]["id"]


# ======================================================================
# 详情与错误分支
# ======================================================================


def test_get_report_returns_detail(client):
    created = client.post("/reports/generate", json={"report_type": "daily"})
    report_id = created.json()["report"]["id"]

    response = client.get(f"/reports/{report_id}")

    assert response.status_code == 200
    assert response.json()["id"] == report_id


def test_get_missing_report_returns_404(client):
    response = client.get("/reports/9999")

    assert response.status_code == 404
    assert response.json()["detail"] == "report not found"


def test_endpoints_return_503_without_service(uninitialised_client):
    assert (
        uninitialised_client.post(
            "/reports/generate", json={"report_type": "daily"}
        ).status_code
        == 503
    )
    assert uninitialised_client.get("/reports").status_code == 503
    assert uninitialised_client.get("/reports/1").status_code == 503


def test_generate_without_worklog_service_still_succeeds(service):
    """工作日志服务缺席 —— 报告照样出得来（只剩待办侧）。"""
    report_service, _ = service
    app = FastAPI()
    app.include_router(build_router(lambda: report_service, lambda: None))

    response = TestClient(app).post(
        "/reports/generate", json={"report_type": "daily"}
    )

    assert response.status_code == 201
    assert response.json()["report"]["stats"]["worklogs"]["total"] == 0
