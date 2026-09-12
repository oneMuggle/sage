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

    #: 允许上传的音频扩展名（R22-D8: 防"任意本地文件经 ASR 通道出网"）
    ALLOWED_EXTENSIONS = frozenset({".mp3", ".wav", ".ogg", ".webm", ".m4a", ".flac", ".aac"})
    #: 上传字节上限（对齐聊天附件 25MB）
    MAX_UPLOAD_BYTES = 25 * 1024 * 1024

    def build_request(
        self,
        config: CapabilityConfig,
        *,
        file_path: str = None,
        file_content: bytes = None,
        language: str = None,
    ) -> AIHttpRequest:
        if file_path and not file_content:
            path = Path(file_path)
            if path.suffix.lower() not in self.ALLOWED_EXTENSIONS:
                raise ValueError(
                    f"不支持的音频扩展名: {path.suffix or '(无)'} —— "
                    f"允许: {', '.join(sorted(self.ALLOWED_EXTENSIONS))}"
                )
            if path.stat().st_size > self.MAX_UPLOAD_BYTES:
                raise ValueError(
                    f"音频文件超过 {self.MAX_UPLOAD_BYTES // (1024 * 1024)}MB 上限"
                )
            file_content = path.read_bytes()
            filename = path.name
        elif file_content:
            if len(file_content) > self.MAX_UPLOAD_BYTES:
                raise ValueError(
                    f"音频数据超过 {self.MAX_UPLOAD_BYTES // (1024 * 1024)}MB 上限"
                )
            filename = "upload.ogg"
        else:
            raise ValueError("必须提供 file_path 或 file_content")

        headers = {}
        if config.api_key:
            headers["Authorization"] = f"Bearer {config.api_key}"

        files = {"file": (filename, file_content)}
        data = {"model": config.model}
        if language:
            data["language"] = language

        return AIHttpRequest(
            url=f"{config.base_url}/audio/transcriptions",
            headers=headers,
            files=files,
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
