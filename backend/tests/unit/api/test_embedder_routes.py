"""R124 — 嵌入器状态与切换路由单元测试。

handler 直调（fake Request = SimpleNamespace(app.state)）。
覆盖：status payload 七键、adapter/embedder 未装配 503、select 非法
mode 422、settings 持久化 + create_embedder + reconfigure 调用链、
mode 归一化（大写/空白）、空 mode 422。
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from backend.api import embedder_routes as er
from backend.api.embedder_routes import get_embedder_status, select_embedder

pytestmark = pytest.mark.unit


class _FakeEmbedder:
    is_semantic = True
    dimensions = 512


class _FakeVectorStore:
    table_name = "memories_vec_512"


def _fake_request(adapter=None) -> SimpleNamespace:
    return SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(memory_adapter=adapter)))


def _fake_adapter():
    return SimpleNamespace(
        embedder=_FakeEmbedder(),
        vector_store=_FakeVectorStore(),
        reconfigure=lambda embedder: None,
    )


@pytest.fixture(autouse=True)
def _patch_model_paths(monkeypatch, tmp_path):
    monkeypatch.setattr(er, "onnx_model_dir", lambda: str(tmp_path / "onnx"))
    monkeypatch.setattr(er, "onnx_model_ready", lambda _dir: False)


# ---------------------------------------------------------------------------
# GET /status
# ---------------------------------------------------------------------------


def test_status_payload_shape():
    req = _fake_request(_fake_adapter())
    out = get_embedder_status(req)
    assert out["type"] == "_FakeEmbedder"
    assert out["semantic"] is True
    assert out["dimensions"] == 512
    assert out["table"] == "memories_vec_512"
    assert out["model_dir"].endswith("onnx")
    assert out["model_ready"] is False


def test_status_missing_adapter_503():
    req = _fake_request(None)
    with pytest.raises(HTTPException) as excinfo:
        get_embedder_status(req)
    assert excinfo.value.status_code == 503


def test_status_missing_embedder_503():
    req = _fake_request(SimpleNamespace(embedder=None, vector_store=None))
    with pytest.raises(HTTPException) as excinfo:
        get_embedder_status(req)
    assert excinfo.value.status_code == 503


# ---------------------------------------------------------------------------
# POST /select
# ---------------------------------------------------------------------------


def test_select_invalid_mode_422():
    with pytest.raises(HTTPException) as excinfo:
        select_embedder(_fake_request(_fake_adapter()), {"mode": "bogus"})
    assert excinfo.value.status_code == 422


def test_select_empty_mode_422():
    with pytest.raises(HTTPException) as excinfo:
        select_embedder(_fake_request(_fake_adapter()), {})
    assert excinfo.value.status_code == 422


def test_select_mode_normalized(monkeypatch):
    req = _fake_request(_fake_adapter())
    seen = {}
    monkeypatch.setattr(er, "create_embedder", lambda preferred_mode: seen.update(m=preferred_mode) or _FakeEmbedder())
    out = select_embedder(req, {"mode": "  HASH "})
    assert seen["m"] == "hash"
    assert out["mode"] == "hash"


def test_select_adapter_without_reconfigure_503(monkeypatch):
    req = _fake_request(SimpleNamespace(embedder=_FakeEmbedder()))  # 无 reconfigure
    monkeypatch.setattr("backend.data.settings_repo.SettingsRepository", lambda: None)
    with pytest.raises(HTTPException) as excinfo:
        select_embedder(req, {"mode": "hash"})
    assert excinfo.value.status_code == 503


def test_select_success_persists_and_reconfigures(monkeypatch):
    persisted = {}
    monkeypatch.setattr(
        "backend.data.settings_repo.SettingsRepository",
        lambda: SimpleNamespace(
            set=lambda key, value, value_type=None: persisted.update({key: value})
        ),
    )
    created = {}
    fresh = _FakeEmbedder()

    def fake_factory(preferred_mode):
        created["mode"] = preferred_mode
        return fresh

    monkeypatch.setattr(er, "create_embedder", fake_factory)
    reconfigured = []
    adapter = _fake_adapter()
    adapter.reconfigure = reconfigured.append

    out = select_embedder(_fake_request(adapter), {"mode": "onnx"})
    assert persisted == {"embedding_mode": "onnx"}
    assert created["mode"] == "onnx"
    assert reconfigured == [fresh]  # 热重载收到工厂产物
    assert out["mode"] == "onnx"
    assert out["type"] == "_FakeEmbedder"  # payload 反映切换后状态
