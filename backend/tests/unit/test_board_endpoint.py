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


def test_board_endpoint_default_view_is_ops_full():
    """P2-5: 不带 view 参数 = ops_full，保持既有形态（无 projection 字段）。"""
    with TestClient(app) as client:
        resp = client.get("/api/v1/orchestration/board")
    assert resp.status_code == 200
    body = resp.json()
    # ops_full 直接返回 snapshot.to_dict()，不含 projection 专属字段
    assert "view" not in body
    assert "redaction_provenance" not in body


def test_board_endpoint_ui_minimal_projection():
    with TestClient(app) as client:
        resp = client.get("/api/v1/orchestration/board", params={"view": "ui_minimal"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["view"] == "ui_minimal"
    assert "redaction_provenance" in body


def test_board_endpoint_unknown_view_400():
    with TestClient(app) as client:
        resp = client.get("/api/v1/orchestration/board", params={"view": "bogus"})
    assert resp.status_code == 400
