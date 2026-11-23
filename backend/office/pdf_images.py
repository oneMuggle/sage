"""M6c：PDF 内嵌图片的**有界**提取（预检 → 解码 → 缩放 → 编码）。

这个模块把「PDF 是不可信输入」这条约束落到代码里：

1. **解码前**拦截解压炸弹 —— 但**不能信字典里的 /Width /Height**。
   码流自带真实尺寸的过滤器（``JPXDecode`` / ``JBIG2Decode`` /
   ``CCITTFaxDecode``）可以让真实尺寸与字典完全不符：一张
   ``/Width 10 /Height 10`` 的 JPX 图，码流实际是 12000×12000 ——
   预检放行后 MuPDF 直接申请 432MB 位图（实测峰值 RSS 2.1GB）。
   因此只有「解码后尺寸由 PDF 字典决定」的过滤器才可信任字典尺寸，
   其余一律跳过（:func:`filter_chain_is_trusted`）。
2. 单图 / 单文档的**像素、字节、解码次数、枚举次数**都有硬上限。
3. 输出（base64）预算可由调用方收紧 —— 工具面据此联动，避免响应被
   输出预算拦腰截断成半截 JSON。
4. 透明度按 PDF 的真实语义处理：alpha 存在**独立的 SMask XObject**
   里，这里合成到白底（与 MuPDF 自己的页面渲染一致）。

过滤链的判定规则（:func:`filter_chain_is_trusted`）：PDF 的过滤器链
按顺序生效，**链尾**那个才是产生像素样本的编解码器；链头只是 ASCII
编码一类的包装。因此「解码后尺寸由字典决定」等价于「链尾是安全的
编解码器，且链中没有自带尺寸的编解码器」。

实测过的过滤器：

- ``DCTDecode``（JPEG）—— MuPDF 按字典尺寸缩放解码，6000×6000 的码流
  配 10×10 的字典只会产出 10×10，**安全**；
- ``FlateDecode`` / ``LZWDecode`` / ``RunLengthDecode`` —— 原始位图，
  尺寸完全由字典决定，**安全**；
- ``JPXDecode`` / ``JBIG2Decode`` / ``CCITTFaxDecode`` —— 码流自带真实
  尺寸，字典可以随便写小，**必须拒绝**。
"""

from __future__ import annotations

import base64
import logging
import re
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

logger = logging.getLogger(__name__)

# ── 预算常量 ─────────────────────────────────────────────────────────
#: 单图像素上限（宽×高）。**解码前**的预检 —— 用户可控的 PDF 里一张
#: 16000×16000 的 Flate 位图会让 MuPDF 分配 250MB+ 内存，而压缩后的
#: PNG 可能只有 100KB。按「解码后体积」设限才能真正挡住解压炸弹。
MAX_EMBEDDED_IMAGE_PIXELS = 12_000_000
#: 单图解码后位图字节上限（按 width×height×组件数×每组件字节估算）。
MAX_EMBEDDED_IMAGE_DECODED_BYTES = 64 * 1024 * 1024
#: 预览最长边（px）—— 与 Word 路径的缩略预览同量级。
MAX_EMBEDDED_IMAGE_EDGE = 1024
#: 单张图片 data_url 上限（base64 **编码后**字节）。
MAX_EMBEDDED_IMAGE_BYTES = 1_500_000
#: 单次读取的图片预算（base64 **编码后**字节）—— 直接约束 JSON 响应
#: 体积；原始字节约为该值的 3/4。
MAX_TOTAL_EMBEDDED_IMAGE_BYTES = 20_000_000
#: 每页图片数硬上限（与 ``PdfReadRequest.le=10`` 同源；服务层再兜一次底，
#: 不依赖调用方自觉）。
MAX_IMAGES_PER_PAGE = 10
#: 单文档返回的图片张数上限（含元数据条目）。
MAX_TOTAL_EMBEDDED_IMAGES = 200
#: 单文档**解码**次数上限 —— 解码是 CPU 与内存的大头，必须封顶。
MAX_IMAGE_DECODES_PER_DOCUMENT = 200
#: 单文档**枚举**图片的次数上限 —— 病理 PDF 的资源字典可以有上万个
#: XObject，``page.get_images()`` 单页可达 0.1s 以上。
MAX_TOTAL_IMAGE_INSPECTIONS = 2000
#: xref 预览缓存的**原始**字节上限（约束常驻内存，与输出预算分开算）。
MAX_IMAGE_CACHE_BYTES = 8 * 1024 * 1024

#: PDF colorspace 名 → 组件数。未知 colorspace 按最坏情况（4）估算；
#: ICCBased 可能是 1/3/4 分量，一律按 4 算。
COLORSPACE_COMPONENTS = {
    "DeviceGray": 1,
    "CalGray": 1,
    "G": 1,
    "DeviceRGB": 3,
    "CalRGB": 3,
    "RGB": 3,
    "ICCBased": 4,
    "DeviceCMYK": 4,
    "CMYK": 4,
}

# ── 过滤器白名单 ─────────────────────────────────────────────────────
#: 码流自带真实尺寸的编解码器 —— 字典尺寸不可信，一律拒绝。
UNSAFE_CODEC_FILTERS = frozenset(
    {
        "JPXDECODE",
        "JBIG2DECODE",
        "CCITTFAXDECODE",
    }
)
#: 解码后尺寸由 PDF 字典决定的编解码器 —— 字典尺寸可信。
SAFE_CODEC_FILTERS = frozenset(
    {
        "FLATEDECODE",
        "LZWDECODE",
        "RUNLENGTHDECODE",
        "DCTDECODE",
    }
)
#: 只做编码包装、不产生像素样本的过滤器（可出现在链头）。
ENCODING_ONLY_FILTERS = frozenset({"ASCII85DECODE", "ASCIIHEXDECODE"})

#: ``DecodeParms`` 是内联字典，它的键（Width/Height/Predictor...）**不是**
#: 过滤器 —— 解析过滤器数组时必须先剔除，否则安全判定会误拒正常图。
_INLINE_DICT_RE = re.compile(r"<<.*?>>", re.DOTALL)
_NAME_RE = re.compile(r"/([A-Za-z][A-Za-z0-9_+-]*)")

#: JPEG 质量阶梯 —— 装不下时先降质，再缩放，而不是整张丢弃。
JPEG_QUALITY_LADDER = (80, 60, 40)
#: 阶梯里最多再缩放几档（每档各除以 2）。
MAX_RESIZE_STEPS = 3

#: 图片元组：(xref, width, height, bpc, colorspace, smask_xref)。
_ImageInfo = Tuple[int, int, int, int, str, int]
#: 预览结果：(原始 JPEG 字节, 扩展名, 宽, 高)。
_Preview = Tuple[bytes, str, int, int]


def base64_length(raw_len: int) -> int:
    """base64 编码后的长度（不含 ``data:`` 前缀）。"""
    return 4 * ((raw_len + 2) // 3)


def _filter_names(value: str) -> List[str]:
    """从过滤器数组串里取出过滤器名（大写）。

    ``DecodeParms`` 是内联字典，其键名不是过滤器，必须先剔除。
    """
    stripped = _INLINE_DICT_RE.sub(" ", value)
    return [match.group(1).upper() for match in _NAME_RE.finditer(stripped)]


def image_filters(doc: Any, xref: int) -> Optional[List[str]]:
    """读图像 XObject 的 ``/Filter`` 链；读不出来返回 ``None``（不可信）。"""
    try:
        kind, value = doc.xref_get_key(xref, "Filter")
    except Exception:  # noqa: BLE001 — xref 不可读即视为不可信
        return None
    if kind == "null":
        return []
    if kind == "name":
        return [value.lstrip("/").upper()]
    if kind == "array":
        return _filter_names(value)
    return None


def filter_chain_is_trusted(filters: Optional[List[str]]) -> bool:
    """解码后的尺寸是否由 PDF 字典决定 —— 决定预检能否信任字典尺寸。

    ``None``（读不出过滤器）→ 不可信；空链（原始样本）→ 可信；链尾是
    安全编解码器且链中没有自带尺寸的编解码器 → 可信。
    """
    if filters is None:
        return False
    if not filters:
        return True
    if any(name in UNSAFE_CODEC_FILTERS for name in filters):
        return False
    return filters[-1] in SAFE_CODEC_FILTERS


def _xref_int(doc: Any, xref: int, key: str) -> Optional[int]:
    """读 xref 对象的整数键；读不到返回 ``None``。"""
    try:
        kind, value = doc.xref_get_key(xref, key)
    except Exception:  # noqa: BLE001 — 读不到即交给调用方按未知处理
        return None
    if kind not in ("int", "float"):
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _xref_name(doc: Any, xref: int, key: str) -> str:
    """读 xref 对象的名称键；数组形态取首元素名（``[/ICCBased 6 0 R]``）。"""
    try:
        kind, value = doc.xref_get_key(xref, key)
    except Exception:  # noqa: BLE001 — 读不到即交给调用方按未知处理
        return ""
    if kind == "name":
        return value.lstrip("/")
    if kind == "array":
        match = _NAME_RE.search(value)
        return match.group(1) if match else ""
    return ""


def estimate_image_bytes(width: int, height: int, bpc: int, ncomp: int) -> int:
    """按位图参数估算解码后的字节数（解码前预检用）。"""
    if width <= 0 or height <= 0:
        return 0
    per_pixel = max(1, (bpc + 7) // 8) * max(1, ncomp)
    return width * height * per_pixel


def image_precheck_ok(
    xref: int,
    width: int,
    height: int,
    bpc: int,
    colorspace: str,
    *,
    has_mask: bool = False,
) -> bool:
    """解码**前**预检：像素/字节预算。返回 False 表示这张图应当跳过。

    这是解压炸弹的有效拦截点之一 —— 用户可控的 PDF 里可以塞一张
    16000×16000 的 Flate 位图，压缩后只有几十 KB，但解码要 250MB+ 内存。
    """
    if width <= 0 or height <= 0:
        logger.warning("PDF image xref=%s skipped: unknown dimensions", xref)
        return False
    if width * height > MAX_EMBEDDED_IMAGE_PIXELS:
        logger.warning(
            "PDF image xref=%s skipped: %dx%d exceeds %d px budget",
            xref,
            width,
            height,
            MAX_EMBEDDED_IMAGE_PIXELS,
        )
        return False
    ncomp = COLORSPACE_COMPONENTS.get(colorspace, 4)
    if has_mask:
        # SMask 是同尺寸的灰度位图，同样要占一份内存。
        ncomp += 1
    if estimate_image_bytes(width, height, bpc, ncomp) > MAX_EMBEDDED_IMAGE_DECODED_BYTES:
        logger.warning(
            "PDF image xref=%s skipped: decoded size exceeds %d byte budget",
            xref,
            MAX_EMBEDDED_IMAGE_DECODED_BYTES,
        )
        return False
    return True


def shrink_factor(edge: int, target: Optional[int] = None) -> int:
    """``Pixmap.shrink(n)`` 是**除以 2**n**（不是除以 n）→ 因子按 2 的幂取。

    旧实现把「除数」当成 shrink 因子，2000×2000 的图被缩成 500×500
    （实际只该到 1000×1000）；长条图甚至会被缩成 1×1 全白。
    """
    limit = MAX_EMBEDDED_IMAGE_EDGE if target is None else target
    factor = 0
    span = edge
    while span > limit:
        span = (span + 1) // 2
        factor += 1
    return factor


def encode_jpeg_preview(pymupdf: Any, pix: Any, max_base64_bytes: int) -> Optional[bytes]:
    """把位图编码成 JPEG，装不下就逐级降质 + 再缩放，而不是整张丢弃。

    返回 JPEG 字节；实在装不下才返回 ``None``（调用方记为「省略」）。
    """
    for step in range(MAX_RESIZE_STEPS + 1):
        for quality in JPEG_QUALITY_LADDER:
            try:
                raw = pix.tobytes("jpg", jpg_quality=quality)
            except Exception:  # noqa: BLE001 — 单张图失败不影响其余
                logger.warning("PDF image encode failed at quality %d", quality)
                return None
            if base64_length(len(raw)) <= max_base64_bytes:
                return raw
        if step >= MAX_RESIZE_STEPS:
            break
        if pix.width < 8 or pix.height < 8:
            break
        pix.shrink(1)
    return None


def _composite_on_white(pymupdf: Any, rgba: Any) -> Optional[Any]:
    """把 RGBA 预览合成到白底（PDF 的 alpha 在独立 SMask 里）。

    没有 numpy 时返回 ``None`` —— 调用方降级为「不合成」，宁可保留
    原始底色，也不让整篇读取失败。
    """
    try:
        import numpy as np
    except Exception:  # noqa: BLE001 — numpy 缺失是可接受的降级
        return None
    width, height, ncomp = rgba.width, rgba.height, rgba.n
    if ncomp < 4:
        return None
    try:
        buf = np.frombuffer(rgba.samples, dtype=np.uint8).reshape(height, width, ncomp)
        alpha = buf[:, :, 3:4].astype(np.uint16)
        rgb = buf[:, :, :3].astype(np.uint16)
        blended = (rgb * alpha + 255 * (255 - alpha) + 127) // 255
        return pymupdf.Pixmap(
            pymupdf.csRGB, width, height, blended.astype(np.uint8).tobytes(), False
        )
    except Exception:  # noqa: BLE001 — 合成失败降级为不合成
        logger.warning("PDF image alpha compositing failed; keeping raw RGB")
        return None


def _apply_alpha(pymupdf: Any, doc: Any, pix: Any, mask_xref: int) -> Any:
    """把 SMask 的透明度合成到白底；没有 SMask 或形状不匹配就原样返回。"""
    if not mask_xref:
        return pix
    try:
        mask = pymupdf.Pixmap(doc, mask_xref)
    except Exception:  # noqa: BLE001 — SMask 解不开就按无 alpha 处理
        return pix
    if mask.width != pix.width or mask.height != pix.height:
        return pix
    try:
        rgba = pymupdf.Pixmap(pix, mask)
    except Exception:  # noqa: BLE001 — 组件数不匹配就按无 alpha 处理
        return pix
    composited = _composite_on_white(pymupdf, rgba)
    return composited if composited is not None else pix


def _mask_is_safe(doc: Any, mask_xref: int) -> bool:
    """SMask 自身也是一张位图 —— 它的过滤器与尺寸同样要过预检。"""
    filters = image_filters(doc, mask_xref)
    if not filter_chain_is_trusted(filters):
        logger.warning("PDF image SMask %s skipped: untrusted filter chain", mask_xref)
        return False
    width = _xref_int(doc, mask_xref, "Width") or 0
    height = _xref_int(doc, mask_xref, "Height") or 0
    bpc = _xref_int(doc, mask_xref, "BitsPerComponent") or 8
    colorspace = _xref_name(doc, mask_xref, "ColorSpace") or "DeviceGray"
    return image_precheck_ok(mask_xref, width, height, bpc, colorspace)


def _build_preview(
    pymupdf: Any,
    doc: Any,
    xref: int,
    mask_xref: int,
    max_image_bytes: int,
) -> Optional[_Preview]:
    """解码 → 白底合成 → 缩放 → JPEG 编码。返回 ``(raw, ext, w, h)``。"""
    try:
        pix = pymupdf.Pixmap(doc, xref)
    except Exception as exc:  # noqa: BLE001 — 单张图失败不影响其余
        logger.warning("PDF image xref=%s decode failed: %s", xref, exc)
        return None
    if pix.width <= 0 or pix.height <= 0:
        logger.warning("PDF image xref=%s skipped: empty pixmap", xref)
        return None
    if pix.width * pix.height > MAX_EMBEDDED_IMAGE_PIXELS:
        logger.warning(
            "PDF image xref=%s skipped: decoded pixmap exceeds pixel budget", xref
        )
        return None
    if mask_xref and _mask_is_safe(doc, mask_xref):
        pix = _apply_alpha(pymupdf, doc, pix, mask_xref)
    if pix.n != 3:
        try:
            pix = pymupdf.Pixmap(pymupdf.csRGB, pix)
        except Exception:  # noqa: BLE001 — 色彩空间转换失败就跳过这张
            logger.warning("PDF image xref=%s skipped: colorspace conversion failed", xref)
            return None
    factor = shrink_factor(max(pix.width, pix.height))
    if factor > 0 and (pix.width >> factor) >= 1 and (pix.height >> factor) >= 1:
        pix.shrink(factor)
    raw = encode_jpeg_preview(pymupdf, pix, max_image_bytes)
    if not raw:
        logger.warning("PDF image xref=%s skipped: encoded preview exceeds budget", xref)
        return None
    return raw, "jpg", pix.width, pix.height


def _parse_image_info(info: Any) -> Optional[_ImageInfo]:
    """``page.get_images(full=True)`` 元组 → (xref, w, h, bpc, cs, smask)。"""
    if not info or len(info) < 6:
        return None
    try:
        xref = int(info[0] or 0)
        width = int(info[2] or 0)
        height = int(info[3] or 0)
        bpc = int(info[4] or 8)
    except (TypeError, ValueError):
        return None
    if not xref:
        return None
    colorspace = str(info[5] or "")
    smask = 0
    if len(info) > 1:
        try:
            smask = int(info[1] or 0)
        except (TypeError, ValueError):
            smask = 0
    return xref, width, height, bpc, colorspace, smask


class ImageExtractionState:
    """跨页共享的图片提取状态。

    三个独立的上界 + 四个计数，保证「不可信 PDF」下的资源占用有硬顶：

    - ``budget``：剩余可**输出**的 base64 字节 —— 约束响应体大小；
    - ``cache_bytes``：xref 缓存占用的**原始**字节 —— 约束常驻内存；
    - ``skipped``：已判定放不下的 xref —— 避免后续页反复解码再拒绝；
    - ``reported`` / ``decoded`` / ``inspections``：返回张数、解码次数、
      枚举次数各自的封顶。
    """

    __slots__ = (
        "budget",
        "cache",
        "cache_bytes",
        "skipped",
        "reported",
        "decoded",
        "inspections",
    )

    def __init__(self, budget: int) -> None:
        self.budget = max(0, budget)
        self.cache: Dict[int, _Preview] = {}
        self.cache_bytes = 0
        self.skipped: Set[int] = set()
        self.reported = 0
        self.decoded = 0
        self.inspections = 0

    def can_inspect(self) -> bool:
        """还能继续枚举页面图片吗？"""
        return self.inspections < MAX_TOTAL_IMAGE_INSPECTIONS

    def can_decode(self) -> bool:
        """还能继续解码位图吗？"""
        return self.decoded < MAX_IMAGE_DECODES_PER_DOCUMENT

    def can_report(self) -> bool:
        """还能继续返回图片条目吗？"""
        return self.reported < MAX_TOTAL_EMBEDDED_IMAGES


def list_page_images(pymupdf: Any, page: Any, state: ImageExtractionState) -> List[Any]:
    """枚举一页的图片，受文档级枚举预算约束。

    ``include_images=False`` 时**根本不调用** —— 病理 PDF 的
    ``get_images()`` 单页可达 0.1s（2000 个 XObject 资源项），
    100 页就是 11s，而这条路径会被聊天附件 / LaTeX / Zotero / remote MCP
    全部命中。
    """
    if not state.can_inspect():
        return []
    try:
        infos = list(page.get_images(full=True))
    except Exception as exc:  # noqa: BLE001 — 图片表损坏时按无图处理
        logger.warning("PDF page image listing failed: %s", exc)
        return []
    state.inspections += len(infos)
    return infos


def extract_page_images(
    pymupdf: Any,
    doc: Any,
    infos: Sequence[Any],
    max_images: int,
    state: ImageExtractionState,
    *,
    embed_image_data: bool = False,
    max_image_bytes: int = MAX_EMBEDDED_IMAGE_BYTES,
) -> List[Dict[str, Any]]:
    """按页提取内嵌图片（metadata-only 或带像素的有界预览）。

    ``state.budget`` 按 **base64 编码后**的字节计，直接对应 JSON 响应
    体积；``state.cache`` 按 xref 复用已解码的预览，避免同一张图在多页
    重复出现时被反复解码（放大 CPU）。

    ``embed_image_data=False`` 时只返回图片元数据（宽高/格式/颜色空间），
    不带 ``data_url`` —— 供「知道有几张图、但不需要像素」的调用方使用。
    """
    images: List[Dict[str, Any]] = []
    if max_images <= 0:
        return images
    for order, info in enumerate(infos):
        if len(images) >= max_images:
            break
        if not state.can_report():
            # 文档级张数上限 —— 元数据条目同样计数（它们也占响应体积）。
            break
        parsed = _parse_image_info(info)
        if parsed is None:
            continue
        xref, width, height, bpc, colorspace, mask_xref = parsed
        if not embed_image_data:
            # metadata-only：**完全不解码**。不碰 Pixmap 就不会触发解压
            # 炸弹，响应体也只有几字节。
            state.reported += 1
            images.append(
                {
                    "index": order,
                    "width": width,
                    "height": height,
                    "bpc": bpc,
                    "colorspace": colorspace,
                }
            )
            continue
        if not state.can_decode():
            continue
        preview = state.cache.get(xref)
        if preview is None:
            if xref in state.skipped:
                continue
            # 计数的是**尝试**次数（不是成功数）—— 失败的解码同样消耗 CPU。
            state.decoded += 1
            preview = _decode_preview(pymupdf, doc, xref, mask_xref, max_image_bytes)
            if preview is None:
                state.skipped.add(xref)
                continue
            if state.cache_bytes + len(preview[0]) <= MAX_IMAGE_CACHE_BYTES:
                state.cache[xref] = preview
                state.cache_bytes += len(preview[0])
        raw, ext, out_w, out_h = preview
        encoded_len = base64_length(len(raw))
        if encoded_len > state.budget:
            # 预算只减不增 —— 这张图放不下，但**后面更小的图可能放得下**，
            # 所以继续而不是 break。
            state.skipped.add(xref)
            continue
        state.budget -= encoded_len
        state.reported += 1
        mime = "image/jpeg" if ext in ("jpg", "jpeg") else f"image/{ext}"
        images.append(
            {
                "index": order,
                "width": out_w,
                "height": out_h,
                "ext": ext,
                "size_bytes": len(raw),
                "data_url": (
                    f"data:{mime};base64," + base64.b64encode(raw).decode("ascii")
                ),
            }
        )
    return images


def _decode_preview(
    pymupdf: Any,
    doc: Any,
    xref: int,
    mask_xref: int,
    max_image_bytes: int,
) -> Optional[_Preview]:
    """解码前的过滤器/预算预检 —— 通过才真的去解码。"""
    filters = image_filters(doc, xref)
    if not filter_chain_is_trusted(filters):
        logger.warning(
            "PDF image xref=%s skipped: filter chain %s carries its own dimensions",
            xref,
            filters,
        )
        return None
    width = _xref_int(doc, xref, "Width") or 0
    height = _xref_int(doc, xref, "Height") or 0
    bpc = _xref_int(doc, xref, "BitsPerComponent") or 8
    colorspace = _xref_name(doc, xref, "ColorSpace") or "DeviceRGB"
    if not image_precheck_ok(
        xref, width, height, bpc, colorspace, has_mask=bool(mask_xref)
    ):
        return None
    return _build_preview(pymupdf, doc, xref, mask_xref, max_image_bytes)
