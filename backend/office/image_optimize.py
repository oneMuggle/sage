"""图片懒加载优化管线（Round 22）——超限嵌入图片的自动降采样压缩。

设计要点：
- **Pillow 为可选依赖**：沿 matplotlib/formulas 的懒加载降级模式——
  未安装时 ``optimize_image_bytes`` 原样返回输入，行为与 R21 之前完全
  一致（生产行为由上层 ≤10MB 校验兜底）；
- 只处理明确可重编码的格式（JPEG/PNG），GIF（动画）/位图等原样返回；
- best-effort：任何 Pillow 异常吞掉并原样返回 + warning，绝不因优化
  失败破坏既有嵌入流程；
- 降采样策略：最长边 >2000px 等比缩到 2000px，JPEG 质量 85→75→65
  逐级尝试，取第一个 ≤max_bytes 的结果；全失败返回质量最低的一版
  （仍可能超限，由上层校验拒绝）。
"""

from __future__ import annotations

import logging
from importlib.util import find_spec
from typing import Optional

logger = logging.getLogger(__name__)

#: 触发优化的字节阈值（≤8MB 原样返回；嵌入硬上限仍为 10MB）
OPTIMIZE_THRESHOLD_BYTES = 8 * 1024 * 1024

#: 降采样后的最长边像素
_MAX_LONG_EDGE = 2000

#: JPEG 重编码质量阶梯
_JPEG_QUALITIES = (85, 75, 65)


def is_pillow_available() -> bool:
    """探测 Pillow 是否可导入（不实际 import PIL，避免加载开销）。"""
    return find_spec("PIL") is not None


def _reencode_jpeg(source: bytes, max_bytes: int) -> Optional[bytes]:
    """Pillow 重编码 JPEG（降采样 + 质量阶梯）。失败返回 None。"""
    try:
        from PIL import Image
    except Exception:  # noqa: BLE001 — Pillow 缺失/损坏
        return None
    try:
        import io as _io

        with Image.open(_io.BytesIO(source)) as source_img:
            img = source_img.convert("RGB")
            width, height = img.size
            long_edge = max(width, height)
            if long_edge > _MAX_LONG_EDGE:
                scale = _MAX_LONG_EDGE / long_edge
                img = img.resize(
                    (max(1, int(width * scale)), max(1, int(height * scale)))
                )
            for quality in _JPEG_QUALITIES:
                buf = _io.BytesIO()
                img.save(buf, format="JPEG", quality=quality, optimize=True)
                if buf.tell() <= max_bytes:
                    return buf.getvalue()
                buf = _io.BytesIO()
                img.save(buf, format="JPEG", quality=quality, optimize=True)
                if buf.tell() <= max_bytes:
                    return buf.getvalue()
            # 最低质量仍超限 → 返回最低质量版本（可能仍超限，上层兜底）
            return buf.getvalue()
    except Exception:  # noqa: BLE001 — 图片数据损坏/格式怪异
        logger.warning("Pillow 重编码失败，原样返回", exc_info=True)
        return None


def optimize_image_bytes(data: bytes, max_bytes: int = OPTIMIZE_THRESHOLD_BYTES) -> bytes:
    """超 ``max_bytes`` 的图片尝试 Pillow 压缩；不可优化时原样返回。

    - ≤ 阈值：原样返回（零开销）；
    - Pillow 未安装：原样返回 + debug 日志；
    - 压缩成功且 ≤ 阈值：返回压缩结果；压缩后仍超限：返回压缩结果
      （上层 ≤10MB 校验兜底拒绝）。
    """
    if len(data) <= max_bytes:
        return data
    if not is_pillow_available():
        logger.debug("Pillow 未安装，跳过图片压缩（%d 字节原样嵌入）", len(data))
        return data
    # 仅 JPEG/PNG 可重编码（GIF 动画/位图等原样返回）
    if data[:3] == b"\xff\xd8\xff" or data[:8] == b"\x89PNG\r\n\x1a\n":  # JPEG magic
        optimized = _reencode_jpeg(data, max_bytes)
    else:
        logger.debug("不可重编码的图片格式，跳过优化")
        optimized = None
    return optimized if optimized is not None else data
