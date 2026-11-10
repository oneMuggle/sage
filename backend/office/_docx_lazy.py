"""Phase 3.5：python-docx 惰性访问器。

python-docx（连带 lxml）在 import 时约 48ms，而 Word 相关模块会被 FastAPI
路由层在启动期整体导入。本 shim 提供一层可调用代理：名字在调用方模块的命名
空间里看起来就是 ``docx`` 里的符号，但第一次真正调用时才导入真正的 docx
并把真实对象缓存回 shim 自己的 globals()。

设计要点：
- 每个 wrapper 在首次调用时调用 ``backend.core.lazy.load_attr``，由
  ``load_attr`` 完成「目标模块导入 + 取属性 + 缓存」。
- ``alias`` 参数使用 ``_real_<name>`` 前缀，避免 shim 自身 ``globals()``
  里的 wrapper 函数（名字恰好等于 ``attr``）被 ``load_attr`` 误命中 →
  无限递归。
- 只对**可调用**符号提供 wrapper。``docx.enum.*`` 枚举与
  ``docx.shared.RGBColor`` 在调用点走属性访问，无法用函数代理 → 由调用
  方函数内部 ``from docx.enum.text import WD_ALIGN_PARAGRAPH`` 解析。
- 模块级需要**真实值**的常量（如 ``word_fix._PAGE_SIZES``、
  ``word_layout._ALIGN_MAP``、``word_lint._PAGE_FIELD_XPATH``）改为惰性
  函数，由 shim 暴露对应 helper。
"""

from __future__ import annotations

from typing import Any, Dict, Tuple

from backend.core.lazy import load_attr

# ---------------------------------------------------------------------------
# 可调用符号：Document / OxmlElement / qn / Cm / Pt / Inches / Mm
# ---------------------------------------------------------------------------


def Document(*args: Any, **kwargs: Any) -> Any:  # noqa: N802
    """惰性 ``docx.Document``：仅在第一次真正打开 .docx 时导入。"""
    return load_attr("docx", "Document", globals(), alias="_real_Document")(
        *args, **kwargs
    )


def OxmlElement(*args: Any, **kwargs: Any) -> Any:  # noqa: N802
    """惰性 ``docx.oxml.OxmlElement``。"""
    return load_attr(
        "docx.oxml", "OxmlElement", globals(), alias="_real_OxmlElement"
    )(*args, **kwargs)


def qn(tag: str) -> str:
    """惰性 ``docx.oxml.ns.qn``：``w:p`` → ``{...main}p``。"""
    return load_attr("docx.oxml.ns", "qn", globals(), alias="_real_qn")(tag)


def Cm(*args: Any, **kwargs: Any) -> Any:  # noqa: N802
    return load_attr("docx.shared", "Cm", globals(), alias="_real_Cm")(
        *args, **kwargs
    )


def Pt(*args: Any, **kwargs: Any) -> Any:  # noqa: N802
    return load_attr("docx.shared", "Pt", globals(), alias="_real_Pt")(
        *args, **kwargs
    )


def Inches(*args: Any, **kwargs: Any) -> Any:  # noqa: N802
    return load_attr("docx.shared", "Inches", globals(), alias="_real_Inches")(
        *args, **kwargs
    )


def Mm(*args: Any, **kwargs: Any) -> Any:  # noqa: N802
    return load_attr("docx.shared", "Mm", globals(), alias="_real_Mm")(
        *args, **kwargs
    )


# ---------------------------------------------------------------------------
# 模块级常量 helper
#
# 原本这些常量在模块加载时会立刻求值 docx 真实对象；现改为函数，
# 仅在第一次真正使用 .docx 功能时触发 docx 导入。
# ---------------------------------------------------------------------------


def page_field_xpath() -> str:
    """``.//{...main}fldSimple``——供 ``word_lint._check_header_footer`` 使用。"""
    return ".//" + qn("w:fldSimple")


def page_sizes() -> Dict[str, Tuple[Any, Any]]:
    """A4 / Letter 的 (width, height) ——供 ``word_fix`` 使用。"""
    return {
        "A4": (Cm(21.0), Cm(29.7)),
        "LETTER": (Inches(8.5), Inches(11.0)),
    }


def align_map() -> Dict[str, Any]:
    """文本对齐枚举映射（含 ``distribute``）——供 ``word_fix._ALIGNMENTS`` 使用。"""
    wd = load_attr(
        "docx.enum.text",
        "WD_ALIGN_PARAGRAPH",
        globals(),
        alias="_real_WD_ALIGN_PARAGRAPH_full",
    )
    return {
        "left": wd.LEFT,
        "center": wd.CENTER,
        "right": wd.RIGHT,
        "justify": wd.JUSTIFY,
        "distribute": wd.DISTRIBUTE,
    }


def align_map_ltr() -> Dict[str, Any]:
    """文本对齐枚举映射（不含 ``distribute``）——供 ``word_layout._ALIGN_MAP`` 使用。"""
    wd = load_attr(
        "docx.enum.text",
        "WD_ALIGN_PARAGRAPH",
        globals(),
        alias="_real_WD_ALIGN_PARAGRAPH_ltr",
    )
    return {
        "left": wd.LEFT,
        "center": wd.CENTER,
        "right": wd.RIGHT,
        "justify": wd.JUSTIFY,
    }
