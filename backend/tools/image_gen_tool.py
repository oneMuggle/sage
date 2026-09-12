"""ImageGenerationTool — 根据文本描述生成图像"""

from __future__ import annotations

import asyncio
import concurrent.futures
import logging

from backend.domain.risk import RiskClass
from backend.tools.base import BaseTool, ToolResult, ToolSchema

logger = logging.getLogger(__name__)


class ImageGenerationTool(BaseTool):
    """根据文本描述生成图像。返回图片文件引用。"""

    risk = RiskClass.WRITE_LOCAL
    is_blocking = True

    def _build_schema(self) -> ToolSchema:
        return ToolSchema(
            name="generate_image",
            description="根据文本描述生成图像。返回图片文件引用路径。"
            "需要先在设置中配置图像生成模型。",
            parameters={
                "type": "object",
                "properties": {
                    "prompt": {
                        "type": "string",
                        "description": "图像描述（英文效果更佳）",
                    },
                    "size": {
                        "type": "string",
                        "default": "1024x1024",
                        "enum": [
                            "256x256",
                            "512x512",
                            "1024x1024",
                            "1792x1024",
                        ],
                        "description": "图片尺寸",
                    },
                    "quality": {
                        "type": "string",
                        "default": "standard",
                        "enum": ["standard", "hd"],
                        "description": "图片质量",
                    },
                },
                "required": ["prompt"],
            },
        )

    def execute(
        self,
        *,
        prompt: str,
        size: str = "1024x1024",
        quality: str = "standard",
        **kwargs,
    ) -> ToolResult:
        from backend.services.multimodal.image_gen import ImageGenCapability

        cap = ImageGenCapability()
        config = cap.load_config()
        if not config:
            return ToolResult(
                success=False,
                error="图像生成模型未配置，请先在 设置 → 模型 中配置图像生成模型",
            )
        try:
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                loop = None

            if loop and loop.is_running():
                with concurrent.futures.ThreadPoolExecutor() as pool:
                    media_refs = pool.submit(
                        asyncio.run,
                        cap.execute(
                            config, prompt=prompt, size=size, quality=quality
                        ),
                    ).result()
            else:
                media_refs = asyncio.run(
                    cap.execute(config, prompt=prompt, size=size, quality=quality)
                )

            urls = [ref.api_url for ref in media_refs]
            return ToolResult(
                success=True,
                content=f"已生成 {len(media_refs)} 张图片: {urls[0] if urls else 'none'}",
                output={"media_refs": media_refs, "api_urls": urls},
            )
        except Exception as e:
            logger.exception("ImageGen execution failed")
            return ToolResult(success=False, error=f"图像生成失败: {e}")
