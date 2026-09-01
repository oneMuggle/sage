"""Vision-enabled Ingest 流程。

集成文件解析、图片提取、视觉描述，生成包含图片描述的 Wiki 页面。
"""
from __future__ import annotations

import logging
import os
import stat
import tempfile
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

from .extract import MAX_FILE_BYTES
from .ingest import IngestConfig, ingest_source
from .vision import VisionConfig, caption_image

logger = logging.getLogger(__name__)


def _read_bounded_file(file_path: Path) -> bytes:
    """Read a stable, bounded snapshot without following a replaced path."""
    nofollow = getattr(os, "O_NOFOLLOW", 0)
    if os.name != "posix" or not nofollow:
        raise OSError("bounded file reads require POSIX O_NOFOLLOW")
    flags = os.O_RDONLY | nofollow
    fd = os.open(str(file_path), flags)
    try:
        opened = os.fstat(fd)
        if not stat.S_ISREG(opened.st_mode):
            raise OSError("拒绝读取非 regular Wiki 文件")
        if opened.st_nlink != 1:
            raise OSError("拒绝读取多链接 Wiki 文件")
        size = opened.st_size
        if size > MAX_FILE_BYTES:
            raise ValueError("source exceeds configured ingest limit")
        chunks = []
        remaining = MAX_FILE_BYTES + 1
        while remaining:
            chunk = os.read(fd, min(1024 * 1024, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        payload = b"".join(chunks)
        if len(payload) > MAX_FILE_BYTES:
            raise ValueError("source exceeds configured ingest limit")
        return payload
    finally:
        os.close(fd)


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

    source_payload = _read_bounded_file(source_file_path)
    source_snapshot = tempfile.NamedTemporaryFile(  # noqa: SIM115 — held fd spans all parser/caption stages
        mode="wb",
        suffix=source_file_path.suffix,
        delete=False,
    )
    source_snapshot_path = Path(source_snapshot.name)
    source_fd = source_snapshot.fileno()
    try:
        source_snapshot.write(source_payload)
        source_snapshot.flush()
        os.fsync(source_fd)

        if progress_callback:
            progress_callback({"stage": "parsing", "percent": 5, "message": "解析文档"})

        # Step 1: parse through the held descriptor, never by re-opening the path.
        try:
            text_content = parse_document(
                source_snapshot_path,
                opened_fd=source_fd,
                max_file_bytes=MAX_FILE_BYTES,
            )
        except Exception as e:
            logger.error("文档解析失败: error_type=%s", type(e).__name__)
            text_content = source_payload.decode("utf-8", errors="ignore")

        # Step 2: extract images from the same held descriptor.
        images: List[ImageInfo] = []
        try:
            from .file_parser import extract_images

            raw_images = extract_images(source_snapshot_path, opened_fd=source_fd)
            for idx, (img_data, img_format) in enumerate(raw_images):
                images.append(ImageInfo(index=idx, data=img_data, format=img_format))
            logger.info("提取到 %d 张图片", len(images))
        except (ImportError, AttributeError):
            logger.info("当前文件类型不支持图片提取")
        except Exception as e:
            logger.warning("图片提取失败（继续 Ingest）: error_type=%s", type(e).__name__)

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
                    logger.info("图片 %d 描述生成完成", img.index)
                except Exception as e:
                    logger.warning("图片 %d 描述失败: error_type=%s", img.index, type(e).__name__)
                    image_captions[img.index] = "[图片描述生成失败]"

        # Step 4: 将图片描述插入到文档内容
        enhanced_content = _insert_image_captions(text_content, image_captions)
        payload = enhanced_content.encode("utf-8")
        if len(payload) > MAX_FILE_BYTES:
            raise ValueError("enhanced source exceeds configured ingest limit")

        # Step 5: preserve the original bytes as the raw source; only analysis
        # and page generation receive the caption-enhanced text.
        if progress_callback:
            progress_callback({"stage": "ingesting", "percent": 80, "message": "Ingest 到 Wiki"})
        return await ingest_source(
            config=config.ingest_config,
            project_root=config.project_root,
            source_file_path=source_file_path,
            llm_call=llm_call,
            http_post=http_post,
            logical_filename=source_file_path.name,
            source_content=source_payload,
            processed_content=enhanced_content,
        )
    finally:
        # Each cleanup operation is best-effort and cannot mask the main error.
        with suppress(OSError):
            source_snapshot.close()
        with suppress(OSError):
            source_snapshot_path.unlink()


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
