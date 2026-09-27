"""Lightweight converter discovery, not a conversion-health guarantee.

Word COM requires pywin32 plus registered, existing Word executable, and
supports DOCX only. LibreOffice supports DOCX/XLSX/PPTX. No converter is
started by these checks; OCR retains its existing separate discovery path.
Results are cached for 30 seconds. Python 3.8-compatible.
"""

from __future__ import annotations

import os
import re
import sys
import time
from importlib.util import find_spec
from pathlib import Path
from typing import List, Literal, Optional, Tuple

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
        description="是否发现 pywin32、Word COM 注册及可执行文件（未验证运行）"
    )
    pdf_export_available: bool = Field(
        description="是否存在任一 PDF 转换器（soffice 或 Word COM）"
    )
    pdf_export_formats: List[Literal["docx", "xlsx", "pptx"]] = Field(
        default_factory=list, description="发现转换器的源格式；不代表实际转换健康已通过"
    )
    conversion_probe_status: Literal["detected", "unavailable"] = Field(
        default="unavailable", description="仅静态发现，不启动转换器，不声称已验证运行"
    )
    pillow_available: bool = Field(description="Pillow 是否可导入（图片自动压缩）")
    formulas_available: bool = Field(description="formulas 引擎是否可导入（公式本地求值）")
    ocr_available: bool = Field(
        default=False,
        description="OCR 兜底是否可用（pytesseract 已装且 tesseract 在 PATH）",
    )
    ocr_languages: Optional[list] = Field(
        default=None,
        description="tesseract 已安装的语言包清单（如 ['chi_sim', 'eng']）；不可用为 None",
    )


#: (探测时间戳, 结果)。探测无副作用，进程内共享一份即可。
_cache: Optional[Tuple[float, OfficeCapabilities]] = None


def _word_registered() -> bool:
    """Registry/file discovery only; never Dispatch Word during a capability GET."""
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, r"Word.Application\CLSID") as key:
            clsid = winreg.QueryValueEx(key, None)[0]
        with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, "CLSID\\" + clsid + r"\LocalServer32") as key:
            command = os.path.expandvars(winreg.QueryValueEx(key, None)[0]).strip()
        match = re.match(r'^"([^"\n]+\.exe)"(?:\s|$)|^(.+?\.exe)(?:\s|$)', command, re.IGNORECASE)
        return bool(match and Path(match.group(1) or match.group(2)).is_file())
    except (ImportError, OSError, TypeError, ValueError):
        return False


def _probe() -> OfficeCapabilities:
    soffice_path = _locate_soffice()
    word_com = (
        sys.platform == "win32"
        and find_spec("win32com") is not None
        and _word_registered()
    )
    formats = ["docx", "xlsx", "pptx"] if soffice_path is not None else (["docx"] if word_com else [])
    return OfficeCapabilities(
        platform=sys.platform,
        soffice_available=soffice_path is not None,
        soffice_path=soffice_path,
        word_com_available=word_com,
        pdf_export_available=bool(formats),
        pdf_export_formats=formats,
        conversion_probe_status="detected" if formats else "unavailable",
        pillow_available=find_spec("PIL") is not None,
        formulas_available=find_spec("formulas") is not None,
        ocr_available=_ocr_available(),
        ocr_languages=_ocr_languages(),
    )


def _ocr_available() -> bool:
    """P4-A: OCR 依赖探测（懒加载，异常归为不可用）。"""
    try:
        from .ocr import ocr_available

        ok, _ = ocr_available()
        return ok
    except Exception:  # noqa: BLE001 — 探测失败即不可用
        return False


def _ocr_languages() -> Optional[list]:
    """P4-B: 已装语言包枚举（懒加载，异常归为 None）。"""
    try:
        from .ocr import ocr_languages

        return ocr_languages()
    except Exception:  # noqa: BLE001 — 枚举失败即 None
        return None


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
