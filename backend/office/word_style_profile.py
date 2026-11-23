"""规则包（WordRulePack）→ Word 样式画像（WordFormatSpec）转换。

把审校侧的规则（规则包/规范书，含从模板抽取出的 24–28 条规则）反向
编译成生成侧的样式画像，打通「从范本抽取样式 → 存为模板 → 生成/套用」
闭环。

映射约定（与 ``word_rule_extract_template`` 产出的 params 对齐）：

- ``page.size`` / ``page.orientation`` / ``page.margins`` /
  ``page.page_number`` → ``page`` / ``footer``；
- ``style.font``：``Normal`` → body、``Title`` → title、``Heading 1–5`` →
  headings.hN、题注类样式名（图题/表题/题注/Caption…）→ caption；
- ``style.paragraph``：正文段距/行距/缩进映射到 body，标题映射到
  headings.hN，题注只映射对齐。

安全护栏：数值按模型边界钳制（超界视为无效值 → unmapped，不静默截断）；
同一字段冲突时保留先出现的值并记 warning（规则顺序即优先级）。
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from .models import WordFormatSpec
from .word_rulepack_models import (
    WordRulePack,
    WordStyleProfileConversion,
    WordStyleUnmappedRule,
)

_CAPTION_STYLE_KEYWORDS = (
    "图题",
    "表题",
    "题注",
    "图注",
    "表注",
    "图标题",
    "表标题",
    "caption",
)
_COLOR_RE = re.compile(r"^#?[0-9A-Fa-f]{6}$")
_ALIGN_ALIASES = {
    "both": "justify",
    "left": "left",
    "center": "center",
    "right": "right",
    "justify": "justify",
}

#: 各目标支持的 font 类字段
_FONT_FIELDS = {
    "body": ("font_family", "ascii_font", "font_size_pt"),
    "title": ("font_family", "ascii_font", "font_size_pt", "bold", "color"),
    "caption": ("font_family", "ascii_font", "font_size_pt", "bold"),
}

#: 各目标支持的 paragraph 类字段
_PARAGRAPH_FIELDS = {
    "body": (
        "line_spacing",
        "line_spacing_pt",
        "first_line_indent_cm",
        "space_before_pt",
        "space_after_pt",
        "align",
    ),
    "title": ("space_before_pt", "space_after_pt", "align"),
    "caption": ("align",),
}


def _style_target(style_name: str) -> Optional[str]:  # noqa: PLR0911 — 逐分支早退
    """样式名 → 画像目标：body / title / caption / h1-h5；未知返回 None。"""
    name = (style_name or "").strip()
    if not name:
        return None
    lowered = name.casefold()
    if lowered == "normal":
        return "body"
    if lowered == "title":
        return "title"
    if lowered.startswith("heading "):
        suffix = name.split()[-1]
        if suffix.isdigit() and 1 <= int(suffix) <= 5:
            return f"h{int(suffix)}"
        return None
    if any(keyword in lowered for keyword in _CAPTION_STYLE_KEYWORDS):
        return "caption"
    return None


def _cap_kind(target_label: str) -> str:
    """h1-h5 与 title 共用 heading 能力集。"""
    return "title" if target_label.startswith("h") else target_label


def _number(value: Any, minimum: float, maximum: float) -> Optional[float]:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number < minimum or number > maximum:
        return None
    return number


def _alignment(value: Any) -> Optional[str]:
    return _ALIGN_ALIASES.get(str(value).strip().casefold())


def format_spec_from_rulepack(pack: WordRulePack) -> WordStyleProfileConversion:
    """把规则包转换为样式画像。

    返回 ``WordStyleProfileConversion``：``format_spec`` 可直接传给
    ``generate_docx`` / ``apply_style_to_document``；``unmapped`` 记录无法
    映射的规则（非样式规则、未知样式、不支持字段、非法值）及原因。
    """
    page: Dict[str, Any] = {}
    margins: Dict[str, float] = {}
    body: Dict[str, Any] = {}
    title: Dict[str, Any] = {}
    headings: Dict[str, Dict[str, Any]] = {
        f"h{level}": {} for level in range(1, 6)
    }
    caption: Dict[str, Any] = {}
    footer: Dict[str, Any] = {}
    applied: List[str] = []
    unmapped: List[WordStyleUnmappedRule] = []
    warnings: List[str] = []

    def put(target: Dict[str, Any], key: str, value: Any, rule_id: str) -> bool:
        """写入字段；冲突保留先者并告警。返回本次是否生效。"""
        if key in target and target[key] != value:
            warnings.append(
                f"冲突：规则 {rule_id} 的 {key}={value!r} 与已生效值 "
                f"{target[key]!r} 不一致，保留先生效值"
            )
            return False
        target[key] = value
        return True

    def unsupported(rule_id: str, kind: str, reason: str) -> None:
        unmapped.append(
            WordStyleUnmappedRule(rule_id=rule_id, kind=kind, reason=reason)
        )

    def target_for(label: str) -> Dict[str, Any]:
        if label.startswith("h"):
            return headings[label]
        if label == "body":
            return body
        if label == "title":
            return title
        return caption

    def map_font_params(
        params: Dict[str, Any], cap: str, target: Dict[str, Any], rule_id: str
    ) -> bool:
        mapped = False
        supported = _FONT_FIELDS[cap]
        if "font_east_asia" in params:
            value = str(params["font_east_asia"]).strip()
            if "font_family" not in supported:
                warnings.append(
                    f"unsupported_field/font_family：规则 {rule_id} 在 {cap} 上不支持中文字体，已忽略"
                )
            elif value:
                mapped = put(target, "font_family", value, rule_id) or mapped
        if "font_ascii" in params:
            value = str(params["font_ascii"]).strip()
            if "ascii_font" not in supported:
                warnings.append(
                    f"unsupported_field/ascii_font：规则 {rule_id} 在 {cap} 上不支持西文字体，已忽略"
                )
            elif value:
                mapped = put(target, "ascii_font", value, rule_id) or mapped
        if "size_pt" in params:
            value = _number(params["size_pt"], 1.0, 72.0)
            if value is None:
                warnings.append(
                    f"invalid_value：规则 {rule_id} 的字号 {params['size_pt']!r} 超出 1–72pt，已忽略"
                )
            elif "font_size_pt" in supported:
                mapped = put(target, "font_size_pt", value, rule_id) or mapped
        if "bold" in params:
            if "bold" in supported:
                mapped = (
                    put(target, "bold", bool(params["bold"]), rule_id) or mapped
                )
            else:
                warnings.append(
                    f"unsupported_field/bold：规则 {rule_id} 在 {cap} 上不支持加粗，已忽略"
                )
        if "color" in params:
            text = str(params["color"]).strip()
            if "color" not in supported:
                warnings.append(
                    f"unsupported_field/color：规则 {rule_id} 在 {cap} 上不支持字体颜色，已忽略"
                )
            elif not _COLOR_RE.match(text):
                warnings.append(
                    f"invalid_value：规则 {rule_id} 的颜色 {text!r} 不是 6 位 RGB，已忽略"
                )
            else:
                mapped = (
                    put(target, "color", text.lstrip("#").upper(), rule_id) or mapped
                )
        if "italic" in params:
            warnings.append(
                f"unsupported_field/italic：规则 {rule_id} 的样式级斜体暂不支持，已忽略"
            )
        return mapped

    def map_paragraph_params(
        params: Dict[str, Any], cap: str, target: Dict[str, Any], rule_id: str
    ) -> bool:
        mapped = False
        supported = _PARAGRAPH_FIELDS[cap]
        space_max = 48.0 if cap == "body" else 96.0
        candidates = (
            ("line_spacing", 1.0, 3.0),
            ("line_spacing_pt", 1.0, 200.0),
            ("first_line_indent_cm", 0.0, 5.0),
            ("space_before_pt", 0.0, space_max),
            ("space_after_pt", 0.0, space_max),
        )
        for field, minimum, maximum in candidates:
            if field not in params:
                continue
            if field not in supported:
                warnings.append(
                    f"unsupported_field/{field}：规则 {rule_id} 在 {cap} 上不支持该段落字段，已忽略"
                )
                continue
            value = _number(params[field], minimum, maximum)
            if value is None:
                warnings.append(
                    f"invalid_value：规则 {rule_id} 的 {field}={params[field]!r} 超出范围，已忽略"
                )
                continue
            mapped = put(target, field, value, rule_id) or mapped
        if "alignment" in params:
            value = _alignment(params["alignment"])
            if value is None:
                warnings.append(
                    f"invalid_value：规则 {rule_id} 的对齐 {params['alignment']!r} 不支持，已忽略"
                )
            elif "align" not in supported:
                warnings.append(
                    f"unsupported_field/align：规则 {rule_id} 在 {cap} 上不支持对齐，已忽略"
                )
            else:
                mapped = put(target, "align", value, rule_id) or mapped
        return mapped

    for rule in pack.rules:
        kind = rule.kind
        params = dict(rule.params or {})
        if kind == "page.size":
            raw = str(params.get("size", "")).strip().casefold()
            normalized = {"a4": "A4", "letter": "letter"}.get(raw)
            if normalized is None:
                unsupported(rule.id, kind, "invalid_value")
                continue
            put(page, "size", normalized, rule.id)
            applied.append(rule.id)
        elif kind == "page.orientation":
            raw = str(params.get("orientation", "")).strip().casefold()
            if raw not in ("portrait", "landscape"):
                unsupported(rule.id, kind, "invalid_value")
                continue
            put(page, "orientation", raw, rule.id)
            applied.append(rule.id)
        elif kind == "page.margins":
            mapped = False
            for edge in ("top", "bottom", "left", "right"):
                key = f"{edge}_cm"
                if key not in params:
                    continue
                value = _number(params[key], 0.0, 10.0)
                if value is None:
                    warnings.append(
                        f"invalid_value：规则 {rule.id} 的 {key}={params[key]!r} 超出 0–10cm，已忽略"
                    )
                    continue
                mapped = put(margins, edge, value, rule.id) or mapped
            if mapped:
                applied.append(rule.id)
            else:
                unsupported(rule.id, kind, "invalid_value")
        elif kind == "page.page_number":
            if not params.get("required", True):
                unsupported(rule.id, kind, "not_required")
                continue
            put(footer, "page_number", True, rule.id)
            put(footer, "align", "center", rule.id)
            applied.append(rule.id)
        elif kind in ("style.font", "style.paragraph"):
            style_name = str(params.get("style", ""))
            label = _style_target(style_name)
            if label is None:
                unsupported(rule.id, kind, "unsupported_style")
                continue
            cap = _cap_kind(label)
            target = target_for(label)
            if kind == "style.font":
                mapped = map_font_params(params, cap, target, rule.id)
            else:
                mapped = map_paragraph_params(params, cap, target, rule.id)
            if mapped:
                applied.append(rule.id)
            else:
                unsupported(rule.id, kind, "unsupported_field")
        else:
            unsupported(rule.id, kind, "not_style_rule")

    spec_data: Dict[str, Any] = {}
    page_data = dict(page)
    if margins:
        page_data["margins_cm"] = margins
    if page_data:
        spec_data["page"] = page_data
    if body:
        spec_data["body"] = body
    if title:
        spec_data["title"] = title
    heading_data = {key: value for key, value in headings.items() if value}
    if heading_data:
        spec_data["headings"] = heading_data
    if caption:
        spec_data["caption"] = caption
    if footer:
        spec_data["footer"] = footer

    try:
        format_spec = WordFormatSpec(**spec_data)
    except Exception as exc:  # pragma: no cover — 防御：理论上值已钳制
        warnings.append(f"format_spec 校验失败，返回空规范：{exc}")
        format_spec = WordFormatSpec()

    return WordStyleProfileConversion(
        rulepack_id=pack.id,
        format_spec=format_spec,
        applied_rule_ids=applied,
        unmapped=unmapped,
        warnings=warnings,
    )


__all__ = ["format_spec_from_rulepack"]
