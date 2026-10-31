"""Resolve DOCX style cascades: docDefaults → style basedOn → direct run formatting."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from docx.oxml.ns import qn

_DEFAULT_FORMAT: Dict[str, Any] = {
    "font_ascii": None,
    "font_east_asia": None,
    "size_pt": None,
    "bold": False,
    "italic": False,
    "underline": False,
    "color": None,
}


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
                }
            )
        return items


__all__ = ["StyleResolver", "read_rpr"]
