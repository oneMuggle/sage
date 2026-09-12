# ruff: noqa: UP006, UP007, UP035, UP045 — release/win7 Python 3.8 兼容
"""SpeechToTextTool — 将音频文件转为文字"""

from __future__ import annotations

import asyncio
import concurrent.futures
import logging
from typing import Optional

from backend.domain.risk import RiskClass
from backend.tools.base import BaseTool, ToolResult, ToolSchema

logger = logging.getLogger(__name__)


class SpeechToTextTool(BaseTool):
    """将音频文件转为文字。支持工作区内的音频文件路径或聊天附件上传的音频。"""

    risk = RiskClass.READ
    is_blocking = True

    def _build_schema(self) -> ToolSchema:
        return ToolSchema(
            name="speech_to_text",
            description="将音频文件转为文字。支持工作区内的音频文件路径或聊天附件上传的音频。"
                        "需要先在设置中配置 ASR 模型。",
            parameters={
                "type": "object",
                "properties": {
                    "file_path": {
                        "type": "string",
                        "description": "音频文件的绝对或相对路径（支持 mp3/wav/ogg/webm/m4a/flac）",
                    },
                    "language": {
                        "type": "string",
                        "description": "音频语言（ISO 639-1 代码，如 zh/en/ja），可选",
                    },
                },
                "required": ["file_path"],
            },
        )

    def execute(self, *, file_path: str, language: Optional[str] = None, **kwargs) -> ToolResult:
        from backend.services.multimodal.asr import ASRCapability

        cap = ASRCapability()
        config = cap.load_config()
        if not config:
            return ToolResult(
                success=False,
                error="ASR 模型未配置，请先在 设置 → 模型 中配置语音识别(ASR)模型",
            )
        try:
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                loop = None

            if loop and loop.is_running():
                with concurrent.futures.ThreadPoolExecutor() as pool:
                    result = pool.submit(
                        asyncio.run,
                        cap.execute(config, file_path=file_path, language=language),
                    ).result()
            else:
                result = asyncio.run(
                    cap.execute(config, file_path=file_path, language=language)
                )

            return ToolResult(
                success=True,
                content=result["text"],
                output=result,
            )
        except FileNotFoundError:
            return ToolResult(success=False, error=f"音频文件不存在: {file_path}")
        except Exception as e:
            logger.exception("ASR execution failed")
            return ToolResult(success=False, error=f"ASR 转写失败: {e}")
