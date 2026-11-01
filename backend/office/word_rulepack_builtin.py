"""Built-in Word rule packs (M2a).

Only generic, mechanically checkable parameters are bundled. The GB/T 9704
pack cites the standard number as a source but intentionally does not copy
the standard text.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any, Dict, List, Tuple

from .word_rulepack_models import WordRulePack

_GB_SOURCE = "GB/T 9704-2012（通用版面参数摘要，不复制标准全文）"


def _rule(
    rule_id: str,
    title: str,
    kind: str,
    params: Dict[str, Any],
    *,
    category: str = "content",
    severity: str = "error",
    source: str = "",
    fixable: bool = False,
    fix_hint: str = "",
    description: str = "",
) -> Dict[str, Any]:
    return {
        "id": rule_id,
        "title": title,
        "description": description,
        "category": category,
        "severity": severity,
        "kind": kind,
        "params": params,
        "source": source,
        "fixable": fixable,
        "fix_hint": fix_hint,
    }


def _gb_t_9704_general() -> Dict[str, Any]:
    return {
        "id": "gb-t-9704-general",
        "name": "党政机关公文格式（GB/T 9704 通用参数）",
        "version": "1.0",
        "description": (
            "GB/T 9704-2012 中可直接机械校验的通用版面项：A4、纵向、"
            "页边距、页码、正文仿宋三号。字体名按常见实现取值，"
            "不同字库可自定义规则包调整。"
        ),
        "source": _GB_SOURCE,
        "rules": [
            _rule(
                "page/size",
                "页面为 A4",
                "page.size",
                {"size": "A4"},
                category="page",
                source=_GB_SOURCE,
                fixable=True,
                fix_hint="页面设置 → 纸张大小 A4（210×297mm）",
            ),
            _rule(
                "page/orientation",
                "页面为纵向",
                "page.orientation",
                {"orientation": "portrait"},
                category="page",
                source=_GB_SOURCE,
                fixable=True,
                fix_hint="页面设置 → 方向选择纵向",
            ),
            _rule(
                "page/margins",
                "页边距符合通用参数",
                "page.margins",
                {
                    "top_cm": 3.7,
                    "bottom_cm": 3.5,
                    "left_cm": 2.8,
                    "right_cm": 2.6,
                    "tolerance_cm": 0.1,
                },
                category="page",
                source=_GB_SOURCE,
                fixable=True,
                fix_hint="页边距改为上 3.7 / 下 3.5 / 左 2.8 / 右 2.6 cm（±1mm）",
            ),
            _rule(
                "page/page_number",
                "页脚包含页码",
                "page.page_number",
                {"required": True, "format": "decimal"},
                category="page",
                source=_GB_SOURCE,
                fixable=True,
                fix_hint="在页脚插入页码域（PAGE），格式为阿拉伯数字",
            ),
            _rule(
                "style/body_font",
                "正文为仿宋三号",
                "style.font",
                {
                    "style": "Normal",
                    "font_east_asia": "仿宋_GB2312",
                    "size_pt": 16.0,
                    "tolerance_pt": 0.5,
                },
                category="style",
                source=_GB_SOURCE,
                fixable=True,
                fix_hint="正文样式改为仿宋_GB2312 三号（16pt）",
            ),
        ],
    }


def _general_quality() -> Dict[str, Any]:
    return {
        "id": "general-quality",
        "name": "Word 通用质量检查",
        "version": "1.0",
        "description": (
            "与具体格式标准无关的通用审校：占位符残留、连续空行、"
            "标题编号、图/表题注与引用编号连续性。"
        ),
        "source": None,
        "rules": [
            _rule(
                "content/placeholder_residue",
                "无未解析占位符",
                "content.placeholder_residue",
                {},
                category="content",
                severity="error",
                fix_hint="解析或删除 {{}} / <<>> / [[ ]] / 【】 / 交叉引用占位符",
            ),
            _rule(
                "content/empty_paragraphs",
                "连续空段落不超限",
                "content.empty_paragraphs",
                {"max_consecutive": 2},
                category="content",
                severity="warning",
                fixable=True,
                fix_hint="删除多余空段落，用段落间距代替空行",
            ),
            _rule(
                "structure/heading_sequence",
                "标题编号连续",
                "structure.heading_sequence",
                {"levels": [1, 2, 3], "require_prefix": True, "skip_texts": ["参考文献"]},
                category="structure",
                severity="warning",
                fix_hint="按出现顺序重排标题编号为 1 / 1.1 / 1.1.1 连续递进",
            ),
            _rule(
                "content/caption_sequence",
                "图/表题注编号连续",
                "content.caption_sequence",
                {"labels": ["图", "表"]},
                category="content",
                severity="warning",
                fix_hint="重排图/表题注编号，使其从 1 连续递增",
            ),
            _rule(
                "content/citation_coverage",
                "引用编号无缺号",
                "content.citation_coverage",
                {},
                category="content",
                severity="warning",
                fix_hint="补齐缺失的引用标记，或核对文末参考文献表",
            ),
        ],
    }


@lru_cache(maxsize=1)
def builtin_rulepacks() -> Tuple[WordRulePack, ...]:
    """Return validated built-in packs (cached; callers should copy)."""
    payloads: List[Dict[str, Any]] = [_gb_t_9704_general(), _general_quality()]
    return tuple(WordRulePack.model_validate(payload) for payload in payloads)


__all__ = ["builtin_rulepacks"]
