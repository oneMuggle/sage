"""ASR（语音识别 / 语音转写）能力实现"""

from __future__ import annotations

from pathlib import Path

from .capability import (
    AICapability,
    AIHttpRequest,
    AIHttpResponse,
    CapabilityConfig,
    CapabilityKind,
)


class ASRCapability(AICapability):
    """OpenAI 兼容 ASR API: POST {base_url}/audio/transcriptions (multipart)"""

    kind = CapabilityKind.ASR
    settings_slot = "asrModel"

    def build_request(
        self,
        config: CapabilityConfig,
        *,
        file_path: str = None,
        file_content: bytes = None,
        language: str = None,
    ) -> AIHttpRequest:
        if file_path and not file_content:
            file_content = Path(file_path).read_bytes()
            filename = Path(file_path).name
        elif file_content:
            filename = "upload.ogg"
        else:
            raise ValueError("必须提供 file_path 或 file_content")

        headers = {}
        if config.api_key:
            headers["Authorization"] = f"Bearer {config.api_key}"

        fields = {"model": config.model}
        if language:
            fields["language"] = language

        data = {
            "file": (filename, file_content),
            **{k: (None, v) for k, v in fields.items()},
        }

        return AIHttpRequest(
            url=f"{config.base_url}/audio/transcriptions",
            headers=headers,
            data=data,
        )

    def parse_response(self, response: AIHttpResponse, **kwargs) -> dict:
        if response.status_code != 200:
            raise ValueError(
                f"ASR upstream returned {response.status_code}: "
                f"{response.content[:200].decode(errors='replace')}"
            )
        data = response.json or {}
        return {
            "text": data.get("text", ""),
            "language": data.get("language", ""),
        }
