"""压缩谱系 REST 端点集成测试（Round 4）"""

from __future__ import annotations

import time

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api.legacy_session_routes import router

pytestmark = pytest.mark.integration


@pytest.fixture()
def client():
    app = FastAPI()
    app.include_router(router)
    return TestClient(app, headers={"Authorization": "Bearer test-local-auth-token"})


def test_lineage_endpoint_lists_archives(tmp_path, client, monkeypatch):
    """压缩归档后，lineage 端点返回归档列表"""
    import tempfile

    from backend.data.database import Database
    from backend.data.session_lineage import archive_prefix_in_transaction
    from backend.data.session_repo import MessageRepository

    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db = Database(f.name)
        db.init_db()

    conn = db.get_connection()
    conn.execute(
        "INSERT INTO sessions (id, title, created_at, updated_at) "
        "VALUES ('sess-p', '排查构建', 1, 1)"
    )
    conn.commit()

    cursor = conn.cursor()
    ids = []
    for i in range(3):
        mid = f"lin-m{i}"
        cursor.execute(
            "INSERT INTO messages (id, session_id, role, content, created_at) "
            "VALUES (?, 'sess-p', 'user', ?, ?)",
            (mid, f"log {i}", int(time.time()) + i),
        )
        ids.append(mid)
    conn.commit()

    archive_prefix_in_transaction(cursor, "sess-p", ids, reason="compaction")
    conn.commit()

    # 让 MessageRepository 走同一个 db —— 通过 monkeypatch 单例
    import backend.data.database as db_mod

    monkeypatch.setattr(db_mod, "_db", db)

    resp = client.get("/sessions/sess-p/lineage")
    assert resp.status_code == 200
    data = resp.json()
    assert data["session_id"] == "sess-p"
    assert len(data["archives"]) == 1
    assert data["archives"][0]["message_count"] == 3
    assert data["archives"][0]["reason"] == "compaction"

    _ = MessageRepository  # 引用保持（实际经单例间接使用）
