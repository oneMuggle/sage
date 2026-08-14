"""Wave 3 B2 — HTTP 集成：POST /orchestration/lanes?wait=true 同步执行到终态。

conftest autouse ``setup_test_db`` 已隔离 DB（每测试独立临时库），无需
monkeypatch SAGE_DB_PATH。无 LLM 配置时 lane 全部 failed（明确错误）——
仍是终态；断言写「全部 lane 终态 + ok is True + review 字段在」，不要求全 done。
"""
from __future__ import annotations

from fastapi.testclient import TestClient


def test_create_lanes_wait_true_returns_terminal():
    """wait=true：TestClient POST /orchestration/lanes?wait=true → lanes 终态 + review 字段。"""
    from backend.main import app

    with TestClient(app) as client:
        # 需要 app_settings 配置 LLM（否则 lane failed with 明确错误 —— 仍为终态）。
        resp = client.post(
            "/api/v1/orchestration/lanes?wait=true", json={"goal": "写一段三行文字"}
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["ok"] is True
        # 终态集合按 LaneStatus 实际序列化值（brief 原文 ("done", "failed")
        # 中 "done" 并不存在 —— LaneStatus.succeeded 序列化为 "succeeded"）。
        assert all(
            lane["status"] in ("succeeded", "failed", "stopped", "cancelled")
            for lane in body["lanes"]
        )
        # CreateLanesOut.review 字段恒在（无 LLM 配置时聚合为空 → None）。
        assert "review" in body
