"""Integration tests for the ASR transcribe endpoint (阶段 1b 语音录入)."""
from __future__ import annotations

import base64
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api.asr_router import build_router
from backend.services.multimodal.asr import ASRCapability


@pytest.fixture()
def client() -> TestClient:
    app = FastAPI()
    app.include_router(build_router(), prefix="/api/v1")
    return TestClient(app)


def _audio_b64() -> str:
    return base64.b64encode(b"fake-audio-bytes").decode("ascii")


def test_transcribe_returns_text(client: TestClient):
    # 不用括号多上下文 with（3.10+ 语法）；单 with + 逗号在 py38 可用。
    with patch.object(ASRCapability, "load_config", return_value=object()), patch.object(
        ASRCapability,
        "execute",
        new=AsyncMock(return_value={"text": "明天下午三点开会"}),
    ):
        resp = client.post(
            "/api/v1/asr/transcribe",
            json={"audio_base64": _audio_b64(), "format": "webm"},
        )

    assert resp.status_code == 200
    assert resp.json() == {"text": "明天下午三点开会"}


def test_transcribe_rejects_invalid_base64(client: TestClient):
    resp = client.post(
        "/api/v1/asr/transcribe", json={"audio_base64": "!!!not-base64!!!"}
    )
    assert resp.status_code == 400


def test_transcribe_returns_409_when_asr_not_configured(client: TestClient):
    with patch.object(ASRCapability, "load_config", return_value=None):
        resp = client.post(
            "/api/v1/asr/transcribe", json={"audio_base64": _audio_b64()}
        )

    assert resp.status_code == 409
    assert "ASR 模型未配置" in resp.json()["detail"]


def test_transcribe_rejects_unknown_format(client: TestClient):
    resp = client.post(
        "/api/v1/asr/transcribe",
        json={"audio_base64": _audio_b64(), "format": "exe"},
    )
    assert resp.status_code == 422


def test_transcribe_maps_upstream_failure_to_502(client: TestClient):
    with patch.object(ASRCapability, "load_config", return_value=object()), patch.object(
        ASRCapability,
        "execute",
        new=AsyncMock(side_effect=RuntimeError("upstream down")),
    ):
        resp = client.post(
            "/api/v1/asr/transcribe", json={"audio_base64": _audio_b64()}
        )

    assert resp.status_code == 502
