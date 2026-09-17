"""Round A P6: Office 环境能力探测（本机转换器 / 可选依赖）。

探测四类能力供前端展示能力徽章与安装引导，替代"点了导出才发现没装
LibreOffice"的事后失败 toast：

- **pdf_converter**: LibreOffice（跨平台）或 Word COM（Windows + pywin32）
  任一可用即可导出/高保真预览 PDF；
- **image_optimize**: Pillow —— >8MB 图片插入时自动降采样压缩；
- **formula_eval**: formulas 引擎 —— xlsx 公式本地求值。

探测本身零副作用：只做 ``find_spec`` / 路径存在性检查，不 import 重模块、
不启动子进程。结果带 30s TTL 模块级缓存 —— 前端每次进 Office 页都会拉一
次，探测虽轻也没必要每次都扫全部候选路径。

Python 3.8-compatible syntax（typing.Optional，无 PEP 604），与
``backend/office`` 其余模块同口径，可回流 release/win7。
"""

from __future__ import annotations

import sys
import time
from importlib.util import find_spec
from typing import Optional, Tuple

from pydantic import BaseModel, ConfigDict, Field

from .export_pdf import _locate_soffice

__all__ = ["OfficeCapabilities", "probe_capabilities"]

#: 探测结果缓存时长（秒）。用户安装 LibreOffice 后最多 30s 内徽章刷新。
_CACHE_TTL_SECONDS = 30.0


class OfficeCapabilities(BaseModel):
    """GET /office/capabilities 响应。"""

    model_config = ConfigDict(extra="forbid")

    platform: str = Field(description="sys.platform（win32/darwin/linux）")
    soffice_available: bool = Field(description="LibreOffice soffice 是否可定位")
    soffice_path: Optional[str] = Field(
        default=None, description="定位到的 soffice 可执行文件路径；未找到为 None"
    )
    word_com_available: bool = Field(
        description="Word COM 通道是否可用（仅 Windows 且已安装 pywin32）"
    )
    pdf_export_available: bool = Field(
        description="是否存在任一 PDF 转换器（soffice 或 Word COM）"
    )
    pillow_available: bool = Field(description="Pillow 是否可导入（图片自动压缩）")
    formulas_available: bool = Field(description="formulas 引擎是否可导入（公式本地求值）")
    ocr_available: bool = Field(
        default=False,
        description="OCR 兜底是否可用（pytesseract 已装且 tesseract 在 PATH）",
    )


#: (探测时间戳, 结果)。探测无副作用，进程内共享一份即可。
_cache: Optional[Tuple[float, OfficeCapabilities]] = None


def _probe() -> OfficeCapabilities:
    soffice_path = _locate_soffice()
    # Word COM 只在 Windows 上有意义；pywin32 缺失时 export_pdf 的
    # COM 分支同样会跳过，这里保持同一判定口径（find_spec 不加载 COM）。
    word_com = sys.platform == "win32" and find_spec("win32com") is not None
    return OfficeCapabilities(
        platform=sys.platform,
        soffice_available=soffice_path is not None,
        soffice_path=soffice_path,
        word_com_available=word_com,
        pdf_export_available=soffice_path is not None or word_com,
        pillow_available=find_spec("PIL") is not None,
        formulas_available=find_spec("formulas") is not None,
        ocr_available=_ocr_available(),
    )


def _ocr_available() -> bool:
    """P4-A: OCR 依赖探测（懒加载，异常归为不可用）。"""
    try:
        from .ocr import ocr_available

        ok, _ = ocr_available()
        return ok
    except Exception:  # noqa: BLE001 — 探测失败即不可用
        return False


def probe_capabilities(force: bool = False) -> OfficeCapabilities:
    """探测（或返回 30s 内缓存的）Office 环境能力。

    Args:
        force: True 时跳过缓存强制重探（测试/用户点"重新检测"用）。
    """
    global _cache
    now = time.monotonic()
    if not force and _cache is not None and now - _cache[0] < _CACHE_TTL_SECONDS:
        return _cache[1]
    result = _probe()
    _cache = (now, result)
    return result
