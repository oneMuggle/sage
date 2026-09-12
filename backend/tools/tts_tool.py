"""TextToSpeechTool — 将文本转为语音音频"""

from __future__ import annotations

import asyncio
import concurrent.futures
import logging

from backend.domain.risk import RiskClass
from backend.tools.base import BaseTool, ToolResult, ToolSchema

logger = logging.getLogger(__name__)


class TextToSpeechTool(BaseTool):
    """将文本转为语音音频。返回可播放的音频文件引用。"""

    risk = RiskClass.WRITE_LOCAL
    is_blocking = True

    def _build_schema(self) -> ToolSchema:
        return ToolSchema(
            name="text_to_speech",
            description="将文本转为语音音频。返回可播放的音频文件引用路径。"
                        "需要先在设置中配置 TTS 模型。",
            parameters={
                "type": "object",
                "properties": {
                    "text": {
                        "type": "string",
                        "description": "要转为语音的文本内容",
                    },
                    "voice": {
                        "type": "string",
                        "default": "alloy",
                        "enum": ["alloy", "echo", "fable", "onyx", "nova", "shimmer"],
                        "description": "语音角色",
                    },
                    "speed": {
                        "type": "number",
                        "default": 1.0,
                        "minimum": 0.25,
                        "maximum": 4.0,
                        "description": "语速倍率 (0.25-4.0)",
                    },
                },
                "required": ["text"],
            },
        )

    def execute(self, *, text: str, voice: str = "alloy", speed: float = 1.0,
                **kwargs) -> ToolResult:
        from backend.services.multimodal.tts import TTSCapability

        cap = TTSCapability()
        config = cap.load_config()
        if not config:
            return ToolResult(
                success=False,
                error="TTS 模型未配置，请先在 设置 → 模型 中配置语音合成(TTS)模型",
            )
        try:
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                loop = None

            if loop and loop.is_running():
                with concurrent.futures.ThreadPoolExecutor() as pool:
                    media_ref = pool.submit(
                        asyncio.run,
                        cap.execute(config, text=text, voice=voice, speed=speed),
                    ).result()
            else:
                media_ref = asyncio.run(
                    cap.execute(config, text=text, voice=voice, speed=speed)
                )

            return ToolResult(
                success=True,
                content=f"已生成音频: {media_ref.api_url}",
                output={"media_ref": media_ref, "api_url": media_ref.api_url},
            )
        except Exception as e:
            logger.exception("TTS execution failed")
            return ToolResult(success=False, error=f"TTS 生成失败: {e}")
