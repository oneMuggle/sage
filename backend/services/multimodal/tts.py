"""TTS（文本转语音）能力实现"""

from __future__ import annotations

from .capability import (
    AICapability,
    AIHttpRequest,
    AIHttpResponse,
    CapabilityConfig,
    CapabilityKind,
)
from .media_store import MediaKind, MediaRef, MediaStore


class TTSCapability(AICapability):
    """OpenAI 兼容 TTS API: POST {base_url}/audio/speech"""

    kind = CapabilityKind.TTS
    settings_slot = "ttsModel"

    def build_request(
        self,
        config: CapabilityConfig,
        *,
        text: str,
        voice: str = "alloy",
        response_format: str = "mp3",
        speed: float = 1.0,
    ) -> AIHttpRequest:
        headers = {"Content-Type": "application/json"}
        if config.api_key:
            headers["Authorization"] = f"Bearer {config.api_key}"
        return AIHttpRequest(
            url=f"{config.base_url}/audio/speech",
            headers=headers,
            body={
                "model": config.model,
                "input": text,
                "voice": voice,
                "response_format": response_format,
                "speed": speed,
            },
            timeout=120.0,
        )

    def parse_response(self, response: AIHttpResponse, **kwargs) -> MediaRef:
        if response.status_code != 200:
            raise ValueError(
                f"TTS upstream returned {response.status_code}: "
                f"{response.content[:200].decode(errors='replace')}"
            )
        store = MediaStore()
        return store.save(
            content=response.content,
            kind=MediaKind.AUDIO,
            source="tts",
            metadata={"text_preview": kwargs.get("text", "")[:100]},
            ext=kwargs.get("response_format", "mp3"),
        )
