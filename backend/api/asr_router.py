"""ASR 转写 REST API（语音快速录入用）。

POST /api/v1/asr/transcribe ``{audio_base64, format, language?}`` → ``{text}``。
音频解码后写临时文件（处理后删除），复用 :class:`ASRCapability`
（OpenAI 兼容 ``/audio/transcriptions``）。ASR 模型未配置时返回 409。
"""
from __future__ import annotations

import base64
import binascii
import logging
import tempfile
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

# 与聊天附件一致：音频 ≤25MB；base64 膨胀约 4/3，余量 1KB。
MAX_AUDIO_BYTES = 25 * 1024 * 1024
MAX_BASE64_CHARS = (MAX_AUDIO_BYTES * 4) // 3 + 1024


class TranscribeIn(BaseModel):
    audio_base64: str = Field(min_length=1, max_length=MAX_BASE64_CHARS)
    format: str = Field(default="webm", pattern="^(webm|wav|ogg|mp3|m4a)$")
    language: Optional[str] = Field(default=None, max_length=10)

    class Config:
        extra = "forbid"


class TranscribeOut(BaseModel):
    text: str


def build_router() -> APIRouter:
    router = APIRouter()

    @router.post("/asr/transcribe", response_model=TranscribeOut)
    async def transcribe(payload: TranscribeIn) -> TranscribeOut:
        try:
            audio = base64.b64decode(payload.audio_base64, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise HTTPException(
                status_code=400, detail="音频数据不是合法的 base64"
            ) from exc
        if not audio:
            raise HTTPException(status_code=400, detail="音频数据为空")
        if len(audio) > MAX_AUDIO_BYTES:
            raise HTTPException(status_code=400, detail="音频超过 25MB 上限")

        # 延迟导入：与工具层保持一致，避免模块加载期耦合多模态注册表。
        from backend.services.multimodal.asr import ASRCapability

        cap = ASRCapability()
        config = cap.load_config()
        if not config:
            raise HTTPException(
                status_code=409,
                detail="ASR 模型未配置，请先在 设置 → 模型 中配置语音识别(ASR)模型",
            )

        tmp_path: Optional[Path] = None
        try:
            with tempfile.NamedTemporaryFile(
                suffix=f".{payload.format}", delete=False
            ) as tmp:
                tmp.write(audio)
                tmp_path = Path(tmp.name)
            result = await cap.execute(
                config, file_path=str(tmp_path), language=payload.language
            )
            return TranscribeOut(text=(result or {}).get("text", ""))
        except ValueError as exc:
            # build_request 的扩展名/大小校验等，回传给用户
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except Exception as exc:  # noqa: BLE001 — 上游 ASR 失败统一 502
            logger.exception("ASR transcribe failed")
            raise HTTPException(
                status_code=502, detail=f"ASR 转写失败: {exc}"
            ) from exc
        finally:
            if tmp_path is not None:
                tmp_path.unlink(missing_ok=True)

    return router
