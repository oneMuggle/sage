"""Wave 3 B2 — GET /orchestration/board 返回 LaneBoard snapshot。"""
from fastapi.testclient import TestClient

from backend.main import app


def test_board_endpoint_shape():
    with TestClient(app) as client:
        resp = client.get("/api/v1/orchestration/board")
    assert resp.status_code == 200
    body = resp.json()
    assert body["schema_version"]
    assert body["generated_by"] == "http-api"
    for key in ("active", "blocked", "finished"):
        assert key in body
        assert isinstance(body[key], list)
    assert "freshness_summary" in body
