"""Resolve DOCX style cascades: docDefaults → style basedOn → direct run formatting."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

_DEFAULT_FORMAT: Dict[str, Any] = {
    "font_ascii": None,
    "font_east_asia": None,
    "size_pt": None,
    "bold": False,
    "italic": False,
    "underline": False,
    "color": None,
}


# Phase 3.5：``docx.oxml.ns`` 所在的 ``docx.oxml`` 包在 import 时会拉进
# lxml(~76ms)。本模块只在真正解析 .docx 样式时才用得上 → 按需惰性导入。
def qn(tag: str) -> str:
    """把 ``w:p`` 形式的标签展开为 ``{namespace}p``。

    真正的实现在 ``docx.oxml.ns``。模块级 ``__getattr__`` 不参与函数体内的
    LOAD_GLOBAL，所以这里保留一个同名薄壳：首次调用时才导入并缓存，
    调用语义与 docx 原生 ``qn`` 完全一致。
    """
    from backend.core.lazy import load_attr

    return load_attr("docx.oxml.ns", "qn", globals(), alias="_docx_qn")(tag)


def _bool_value(element: Any) -> bool:
    value = element.get(qn("w:val"))
    return value not in ("0", "false", "off", "none")


def read_rpr(rpr: Any) -> Dict[str, Any]:
    """Read the supported properties from a ``w:rPr`` element."""
    if rpr is None:
        return {}
    result: Dict[str, Any] = {}
    fonts = rpr.find(qn("w:rFonts"))
    if fonts is not None:
        ascii_name = fonts.get(qn("w:ascii")) or fonts.get(qn("w:hAnsi"))
        east_asia = fonts.get(qn("w:eastAsia"))
        if ascii_name:
            result["font_ascii"] = ascii_name
        if east_asia:
            result["font_east_asia"] = east_asia
        theme = (
            fonts.get(qn("w:asciiTheme"))
            or fonts.get(qn("w:hAnsiTheme"))
            or fonts.get(qn("w:eastAsiaTheme"))
        )
        if theme:
            result["theme_font"] = theme
    size = rpr.find(qn("w:sz"))
    if size is not None:
        raw = size.get(qn("w:val"))
        if raw and raw.isdigit():
            result["size_pt"] = int(raw) / 2.0
    bold = rpr.find(qn("w:b"))
    if bold is not None:
        result["bold"] = _bool_value(bold)
    italic = rpr.find(qn("w:i"))
    if italic is not None:
        result["italic"] = _bool_value(italic)
    underline = rpr.find(qn("w:u"))
    if underline is not None:
        value = underline.get(qn("w:val"))
        result["underline"] = value not in (None, "none")
    color = rpr.find(qn("w:color"))
    if color is not None:
        value = color.get(qn("w:val"))
        if value and value.upper() != "AUTO":
            result["color"] = value.upper()
    return result


def _style_type(style: Any) -> str:
    enum = getattr(style, "type", None)
    name = getattr(enum, "name", None) or str(enum or "")
    return name.lower()


def _pt_to_emu(pt_value: Any) -> Optional[int]:
    """Convert python-docx Pt value to EMU (English Metric Units)."""
    if pt_value is None:
        return None
    try:
        return int(pt_value)
    except (TypeError, ValueError):
        return None


def _read_ppr(style: Any) -> Dict[str, Any]:
    """Read paragraph properties from a style object.

    Returns alignment, line_spacing, spacing (before/after), and indent values.
    """
    pf = getattr(style, "paragraph_format", None)
    if pf is None:
        return {}
    result: Dict[str, Any] = {}

    alignment = getattr(pf, "alignment", None)
    if alignment is not None:
        result["alignment"] = _enum_name(alignment).lower()

    line_spacing = getattr(pf, "line_spacing", None)
    line_spacing_rule = getattr(pf, "line_spacing_rule", None)
    if line_spacing is not None:
        rule_name = _enum_name(line_spacing_rule) if line_spacing_rule else ""
        if isinstance(line_spacing, (int, float)):  # noqa: UP038
            if "EXACT" in rule_name or "AT_LEAST" in rule_name:
                result["line_spacing_pt"] = round(line_spacing / 12700, 1)
            else:
                result["line_spacing"] = float(line_spacing)
        elif isinstance(line_spacing, str):
            result["line_spacing"] = float(line_spacing)

    space_before = _pt_to_emu(getattr(pf, "space_before", None))
    if space_before is not None:
        result["space_before_pt"] = round(space_before / 12700, 1)

    space_after = _pt_to_emu(getattr(pf, "space_after", None))
    if space_after is not None:
        result["space_after_pt"] = round(space_after / 12700, 1)

    first_line_indent = _pt_to_emu(getattr(pf, "first_line_indent", None))
    if first_line_indent is not None:
        result["first_line_indent_pt"] = round(first_line_indent / 12700, 2)

    left_indent = _pt_to_emu(getattr(pf, "left_indent", None))
    if left_indent is not None:
        result["left_indent_pt"] = round(left_indent / 12700, 2)

    return result


def _enum_name(value: Any) -> str:
    """Extract name from an enum or convert to string."""
    if value is None:
        return ""
    name = getattr(value, "name", None)
    if name:
        return name.upper()
    return str(value).upper()


class StyleResolver:
    """Resolve effective run formatting for a python-docx document."""

    def __init__(self, document: Any) -> None:
        self._styles: Dict[str, Dict[str, Any]] = {}
        styles_element = document.styles.element
        defaults_element = styles_element.find(qn("w:docDefaults"))
        default_rpr = None
        if defaults_element is not None:
            rpr_default = defaults_element.find(qn("w:rPrDefault"))
            if rpr_default is not None:
                default_rpr = rpr_default.find(qn("w:rPr"))
        self.defaults: Dict[str, Any] = dict(_DEFAULT_FORMAT)
        self.defaults.update(read_rpr(default_rpr))

        for style in document.styles:
            style_id = getattr(style, "style_id", None)
            if not style_id:
                continue
            try:
                base = getattr(style, "base_style", None)
                based_on = base.style_id if base else None
            except (KeyError, ValueError, AttributeError):
                based_on = None
            element = getattr(style, "element", None)
            rpr = element.find(qn("w:rPr")) if element is not None else None
            self._styles[style_id] = {
                "name": getattr(style, "name", None) or style_id,
                "type": _style_type(style),
                "based_on": based_on,
                "format": read_rpr(rpr),
                "paragraph_format": _read_ppr(style),
            }

    def chain(self, style_id: Optional[str]) -> List[str]:
        chain: List[str] = []
        seen = set()
        current = style_id
        while current and current not in seen and current in self._styles:
            chain.append(current)
            seen.add(current)
            current = self._styles[current]["based_on"]
        return list(reversed(chain))

    def _apply_chain(
        self, base: Dict[str, Any], style_id: Optional[str]
    ) -> Dict[str, Any]:
        for item in self.chain(style_id):
            base.update(self._styles[item]["format"])
        return base

    def resolve_style(self, style_id: Optional[str]) -> Dict[str, Any]:
        return self._apply_chain(dict(self.defaults), style_id)

    def resolve_run(
        self, run: Any, paragraph_style_id: Optional[str]
    ) -> Dict[str, Any]:
        result = self.resolve_style(paragraph_style_id)
        run_style = getattr(getattr(run, "style", None), "style_id", None)
        if run_style and run_style != paragraph_style_id:
            self._apply_chain(result, run_style)
        result.update(read_rpr(run._r.rPr))
        return result

    def styles(self) -> List[Dict[str, Any]]:
        items: List[Dict[str, Any]] = []
        for style_id, entry in self._styles.items():
            fmt = self.resolve_style(style_id)
            para_fmt = entry.get("paragraph_format", {})
            items.append(
                {
                    "style_id": style_id,
                    "name": entry["name"],
                    "type": entry["type"],
                    "based_on": entry["based_on"],
                    "font_ascii": fmt.get("font_ascii"),
                    "font_east_asia": fmt.get("font_east_asia"),
                    "size_pt": fmt.get("size_pt"),
                    "bold": bool(fmt.get("bold")),
                    "italic": bool(fmt.get("italic")),
                    "underline": bool(fmt.get("underline")),
                    "color": fmt.get("color"),
                    "alignment": para_fmt.get("alignment"),
                    "line_spacing": para_fmt.get("line_spacing"),
                    "line_spacing_pt": para_fmt.get("line_spacing_pt"),
                    "space_before_pt": para_fmt.get("space_before_pt"),
                    "space_after_pt": para_fmt.get("space_after_pt"),
                    "first_line_indent_pt": para_fmt.get("first_line_indent_pt"),
                    "left_indent_pt": para_fmt.get("left_indent_pt"),
                }
            )
        return items


__all__ = ["StyleResolver", "read_rpr"]
