"""视觉描述（Vision Caption）。

使用视觉 LLM 为图片生成描述，支持多模态 Ingest。
支持 OpenAI GPT-4V、Anthropic Claude 3 with vision 等。
"""

import base64
import hashlib
import json
import logging
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Dict, Optional

import httpx

logger = logging.getLogger(__name__)


class VisionProvider(str, Enum):
    """视觉 LLM 提供者。"""

    OPENAI = "openai"  # GPT-4V
    ANTHROPIC = "anthropic"  # Claude 3 with vision
    OLLAMA = "ollama"  # Ollama with vision models


@dataclass
class VisionConfig:
    """视觉 LLM 配置。"""

    provider: VisionProvider
    base_url: str
    api_key: str
    model: str
    max_tokens: int = 300


@dataclass
class ImageCaption:
    """图片描述结果。"""

    image_path: str
    sha256: str
    caption: str
    cached: bool = False


# 缓存文件路径
def _get_cache_path(project_root: Path) -> Path:
    """获取视觉描述缓存文件路径。"""
    return project_root / ".llm-wiki" / "vision-cache.json"


def _load_cache(project_root: Path) -> Dict[str, str]:
    """加载视觉描述缓存。"""
    cache_path = _get_cache_path(project_root)
    if not cache_path.exists():
        return {}
    try:
        return json.loads(cache_path.read_text(encoding="utf-8"))
    except Exception as e:
        logger.warning(f"加载视觉描述缓存失败: {e}")
        return {}


def _save_cache(project_root: Path, cache: Dict[str, str]) -> None:
    """保存视觉描述缓存。"""
    cache_path = _get_cache_path(project_root)
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(
        json.dumps(cache, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def compute_image_hash(image_data: bytes) -> str:
    """计算图片的 SHA256 哈希。"""
    return hashlib.sha256(image_data).hexdigest()


def encode_image_base64(image_data: bytes) -> str:
    """将图片编码为 base64。"""
    return base64.b64encode(image_data).decode("utf-8")


async def caption_image(
    config: VisionConfig,
    image_data: bytes,
    image_path: str = "",
    project_root: Optional[Path] = None,
    context: str = "",
) -> ImageCaption:
    """为图片生成描述。

    Args:
        config: 视觉 LLM 配置
        image_data: 图片二进制数据
        image_path: 图片路径（用于缓存和日志）
        project_root: 项目根目录（用于缓存）
        context: 上下文信息（如图片所在文档的标题）

    Returns:
        ImageCaption: 描述结果
    """
    # 计算图片哈希
    sha256 = compute_image_hash(image_data)

    # 检查缓存
    if project_root:
        cache = _load_cache(project_root)
        if sha256 in cache:
            logger.info(f"使用缓存的图片描述: {image_path}")
            return ImageCaption(
                image_path=image_path,
                sha256=sha256,
                caption=cache[sha256],
                cached=True,
            )

    # 调用视觉 LLM
    if config.provider == VisionProvider.OPENAI:
        caption = await _caption_openai(config, image_data, context)
    elif config.provider == VisionProvider.ANTHROPIC:
        caption = await _caption_anthropic(config, image_data, context)
    elif config.provider == VisionProvider.OLLAMA:
        caption = await _caption_ollama(config, image_data, context)
    else:
        raise ValueError(f"不支持的视觉提供者: {config.provider}")

    # 保存到缓存
    if project_root:
        cache = _load_cache(project_root)
        cache[sha256] = caption
        _save_cache(project_root, cache)

    return ImageCaption(
        image_path=image_path,
        sha256=sha256,
        caption=caption,
        cached=False,
    )


async def _caption_openai(config: VisionConfig, image_data: bytes, context: str) -> str:
    """使用 OpenAI GPT-4V 生成图片描述。"""
    base64_image = encode_image_base64(image_data)

    prompt = build_caption_prompt(context)

    async with httpx.AsyncClient(timeout=60) as client:
        response = await client.post(
            f"{config.base_url}/chat/completions",
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {config.api_key}",
            },
            json={
                "model": config.model,
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "text",
                                "text": prompt,
                            },
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:image/jpeg;base64,{base64_image}",
                                },
                            },
                        ],
                    }
                ],
                "max_tokens": config.max_tokens,
            },
        )

        if response.status_code != 200:
            raise Exception(f"OpenAI Vision API 错误: {response.status_code} - {response.text}")

        data = response.json()
        return data["choices"][0]["message"]["content"].strip()


async def _caption_anthropic(config: VisionConfig, image_data: bytes, context: str) -> str:
    """使用 Anthropic Claude 3 with vision 生成图片描述。"""
    base64_image = encode_image_base64(image_data)

    prompt = build_caption_prompt(context)

    # 检测图片类型
    media_type = detect_media_type(image_data)

    async with httpx.AsyncClient(timeout=60) as client:
        response = await client.post(
            f"{config.base_url}/v1/messages",
            headers={
                "Content-Type": "application/json",
                "x-api-key": config.api_key,
                "anthropic-version": "2023-06-01",
            },
            json={
                "model": config.model,
                "max_tokens": config.max_tokens,
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "image",
                                "source": {
                                    "type": "base64",
                                    "media_type": media_type,
                                    "data": base64_image,
                                },
                            },
                            {
                                "type": "text",
                                "text": prompt,
                            },
                        ],
                    }
                ],
            },
        )

        if response.status_code != 200:
            raise Exception(f"Anthropic Vision API 错误: {response.status_code} - {response.text}")

        data = response.json()
        return data["content"][0]["text"].strip()


async def _caption_ollama(config: VisionConfig, image_data: bytes, context: str) -> str:
    """使用 Ollama 视觉模型生成图片描述。"""
    base64_image = encode_image_base64(image_data)

    prompt = build_caption_prompt(context)

    async with httpx.AsyncClient(timeout=120) as client:
        response = await client.post(
            f"{config.base_url}/api/generate",
            json={
                "model": config.model,
                "prompt": prompt,
                "images": [base64_image],
                "stream": False,
            },
        )

        if response.status_code != 200:
            raise Exception(f"Ollama Vision API 错误: {response.status_code} - {response.text}")

        data = response.json()
        return data["response"].strip()


def build_caption_prompt(context: str = "") -> str:
    """构建图片描述 prompt。

    Args:
        context: 上下文信息

    Returns:
        str: Prompt
    """
    base_prompt = """请为这张图片生成一个简洁的描述（2-4 句话）。

要求:
1. 描述图片的主要内容、关键元素和重要信息
2. 如果是图表或数据可视化，提取关键数据点
3. 使用清晰、客观的语言
4. 匹配上下文语言（中文/英文）
5. 只输出描述内容，不要添加"这是一张图片"等前缀"""

    if context:
        return f"{base_prompt}\n\n上下文: {context}"
    return base_prompt


def detect_media_type(image_data: bytes) -> str:
    """检测图片的 MIME 类型。"""
    # 检查文件头魔数
    if image_data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    elif image_data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    elif image_data.startswith(b"GIF87a") or image_data.startswith(b"GIF89a"):
        return "image/gif"
    elif image_data.startswith(b"RIFF") and image_data[8:12] == b"WEBP":
        return "image/webp"
    else:
        # 默认返回 jpeg
        return "image/jpeg"
