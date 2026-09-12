"""图像生成能力实现"""

from __future__ import annotations

import base64
import logging
from typing import List

from .capability import (
    AICapability,
    AIHttpRequest,
    AIHttpResponse,
    CapabilityConfig,
    CapabilityKind,
)
from .media_store import MediaKind, MediaRef, MediaStore

logger = logging.getLogger(__name__)


class ImageGenCapability(AICapability):
    """OpenAI 兼容图像生成 API: POST {base_url}/images/generations"""

    kind = CapabilityKind.IMAGE_GEN
    settings_slot = "imageGenModel"

    def build_request(
        self,
        config: CapabilityConfig,
        *,
        prompt: str,
        size: str = "1024x1024",
        quality: str = "standard",
        n: int = 1,
    ) -> AIHttpRequest:
        headers = {"Content-Type": "application/json"}
        if config.api_key:
            headers["Authorization"] = f"Bearer {config.api_key}"
        return AIHttpRequest(
            url=f"{config.base_url}/images/generations",
            headers=headers,
            body={
                "model": config.model,
                "prompt": prompt,
                "size": size,
                "quality": quality,
                "n": n,
                "response_format": "b64_json",
            },
            timeout=120.0,
        )

    def parse_response(self, response: AIHttpResponse, **kwargs) -> List[MediaRef]:
        if response.status_code != 200:
            raise ValueError(
                f"ImageGen upstream returned {response.status_code}: "
                f"{response.content[:200].decode(errors='replace')}"
            )
        data = response.json or {}
        items = data.get("data", [])
        store = MediaStore()
        refs: List[MediaRef] = []
        for item in items:
            b64_data = item.get("b64_json")
            if not b64_data:
                continue
            content = base64.b64decode(b64_data)
            ref = store.save(
                content=content,
                kind=MediaKind.IMAGE,
                source="image_gen",
                metadata={
                    "prompt": kwargs.get("prompt", ""),
                    "revised_prompt": item.get("revised_prompt", ""),
                },
                ext="png",
            )
            refs.append(ref)
        return refs
