"""Vision-enabled Ingest 流程。

集成文件解析、图片提取、视觉描述，生成包含图片描述的 Wiki 页面。
"""

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from .ingest import IngestConfig, ingest_source
from .vision import VisionConfig, caption_image

logger = logging.getLogger(__name__)


@dataclass
class ImageInfo:
    """提取的图片信息。"""

    index: int
    data: bytes
    format: str  # jpeg, png, etc.


@dataclass
class VisionIngestConfig:
    """Vision-enabled Ingest 配置。"""

    ingest_config: IngestConfig
    vision_config: VisionConfig
    project_root: Path
    auto_caption: bool = True


async def ingest_with_vision(
    config: VisionIngestConfig,
    source_file_path: Path,
    llm_call: Callable,
    http_post: Callable,
    progress_callback: Optional[Callable] = None,
) -> Any:
    """执行 Vision-enabled Ingest 流程。

    1. 解析文档并提取图片
    2. 为每个图片生成视觉描述
    3. 将描述插入到文档内容中
    4. 执行标准 Ingest 流程

    Args:
        config: Vision Ingest 配置
        source_file_path: 源文件路径
        llm_call: LLM 调用函数
        http_post: HTTP POST 函数
        progress_callback: 进度回调

    Returns:
        IngestResult: Ingest 结果
    """
    from .file_parser import parse_document

    if progress_callback:
        progress_callback({"stage": "parsing", "percent": 5, "message": "解析文档"})

    # Step 1: 解析文档文本
    try:
        text_content = parse_document(source_file_path)
    except Exception as e:
        logger.error(f"文档解析失败: {e}")
        text_content = source_file_path.read_text(encoding="utf-8", errors="ignore")

    # Step 2: 提取图片（如果支持）
    images: List[ImageInfo] = []
    try:
        from .file_parser import extract_images

        raw_images = extract_images(source_file_path)
        for idx, (img_data, img_format) in enumerate(raw_images):
            images.append(ImageInfo(index=idx, data=img_data, format=img_format))
        logger.info(f"提取到 {len(images)} 张图片")
    except (ImportError, AttributeError):
        logger.info("当前文件类型不支持图片提取")
    except Exception as e:
        logger.warning(f"图片提取失败（继续 Ingest）: {e}")

    # Step 3: 为每个图片生成描述
    image_captions: Dict[int, str] = {}
    if config.auto_caption and images:
        for i, img in enumerate(images):
            if progress_callback:
                progress_callback(
                    {
                        "stage": "captioning",
                        "percent": 20 + (i + 1) * 30 // len(images),
                        "message": f"为图片 {i + 1}/{len(images)} 生成描述",
                    }
                )

            try:
                result = await caption_image(
                    config=config.vision_config,
                    image_data=img.data,
                    image_path=f"{source_file_path.name}#image-{img.index}",
                    project_root=config.project_root,
                    context=f"来自文档: {source_file_path.name}",
                )
                image_captions[img.index] = result.caption
                logger.info(f"图片 {img.index} 描述: {result.caption[:50]}...")
            except Exception as e:
                logger.warning(f"图片 {img.index} 描述失败: {e}")
                image_captions[img.index] = "[图片描述生成失败]"

    # Step 4: 将图片描述插入到文档内容
    enhanced_content = _insert_image_captions(text_content, image_captions)

    # Step 5: 创建临时 Markdown 文件并执行 Ingest
    import tempfile

    with tempfile.NamedTemporaryFile(
        mode="w",
        suffix=".md",
        delete=False,
        encoding="utf-8",
    ) as f:
        f.write(enhanced_content)
        temp_path = Path(f.name)

    try:
        if progress_callback:
            progress_callback({"stage": "ingesting", "percent": 80, "message": "Ingest 到 Wiki"})

        return await ingest_source(
            config=config.ingest_config,
            project_root=config.project_root,
            source_file_path=temp_path,
            llm_call=llm_call,
            http_post=http_post,
        )

    finally:
        # 清理临时文件
        if temp_path.exists():
            temp_path.unlink()


def _insert_image_captions(content: str, captions: Dict[int, str]) -> str:
    """将图片描述插入到文档内容中。

    在文档末尾添加"图片描述"章节。

    Args:
        content: 原始文档内容
        captions: 图片索引到描述的映射

    Returns:
        str: 增强后的内容
    """
    if not captions:
        return content

    lines = [content, "", "---", "", "## 图片描述", ""]

    for idx in sorted(captions.keys()):
        caption = captions[idx]
        lines.append(f"### 图片 {idx + 1}")
        lines.append("")
        lines.append(caption)
        lines.append("")

    return "\n".join(lines)
