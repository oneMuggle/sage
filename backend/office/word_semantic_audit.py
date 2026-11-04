"""Deterministic semantic rule checks (M4a).

Date-format consistency, terminology glossary and required phrases.
Registered into :mod:`word_audit` via ``SEMANTIC_CHECKERS``; the context is
duck-typed (``emit`` / ``paragraphs``) to avoid a circular import.
"""

from __future__ import annotations

import re
from collections import Counter
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

from .doc_profile_models import WordTextAnchor
from .errors import OfficeParseError
from .word_rulepack_models import WordRuleSpec

_DATE_STYLES = {
    "cn": re.compile(r"\d{4}年\d{1,2}月\d{1,2}日"),
    "iso": re.compile(r"\d{4}-\d{1,2}-\d{1,2}"),
    "slash": re.compile(r"\d{4}/\d{1,2}/\d{1,2}"),
    "dot": re.compile(r"\d{4}\.\d{1,2}\.\d{1,2}"),
}
_DATE_STYLE_LABELS = {
    "cn": "YYYY年M月D日",
    "iso": "YYYY-MM-DD",
    "slash": "YYYY/M/D",
    "dot": "YYYY.M.D",
}


def _anchor_of(paragraph: Dict[str, Any]) -> WordTextAnchor:
    return WordTextAnchor.model_validate(paragraph["anchor"])


def _date_styles_in_text(text: str) -> Dict[str, List[str]]:
    found: Dict[str, List[str]] = {}
    for style, pattern in _DATE_STYLES.items():
        matches = pattern.findall(text)
        if matches:
            found[style] = matches
    return found


def check_date_format(ctx: Any, rule: WordRuleSpec) -> None:
    raw_allowed = rule.params.get("allowed")
    allowed: Optional[Set[str]] = None
    if raw_allowed is not None:
        if not isinstance(raw_allowed, list) or not raw_allowed:
            raise OfficeParseError(f"规则 {rule.id} 参数 allowed 必须是非空数组")
        allowed = {str(item).strip().lower() for item in raw_allowed}
        unknown = allowed - set(_DATE_STYLES)
        if unknown:
            raise OfficeParseError(f"规则 {rule.id} 存在未知日期格式: {sorted(unknown)}")
    per_paragraph: List[Tuple[Dict[str, Any], Dict[str, List[str]]]] = []
    totals: Counter = Counter()
    for paragraph in ctx.paragraphs:
        found = _date_styles_in_text(str(paragraph.get("text") or ""))
        if not found:
            continue
        per_paragraph.append((paragraph, found))
        for style, matches in found.items():
            totals[style] += len(matches)
    if not per_paragraph:
        return
    if allowed is None:
        dominant = totals.most_common(1)[0][0]
        allowed = {dominant}
    expected_label = ", ".join(
        _DATE_STYLE_LABELS.get(style, style) for style in sorted(allowed)
    )
    for paragraph, found in per_paragraph:
        for style, matches in found.items():
            if style in allowed:
                continue
            sample = matches[0]
            ctx.emit(
                rule,
                f"日期格式 {_DATE_STYLE_LABELS.get(style, style)} 与允许格式不一致: {sample}",
                expected=expected_label,
                actual=sample,
                anchor=_anchor_of(paragraph),
                scope="paragraph",
            )


def _terminology_pairs(rule: WordRuleSpec) -> List[Tuple[str, List[str]]]:
    raw_pairs = rule.params.get("pairs")
    if not isinstance(raw_pairs, list) or not raw_pairs:
        raise OfficeParseError(f"规则 {rule.id} 参数 pairs 必须是非空数组")
    pairs: List[Tuple[str, List[str]]] = []
    for item in raw_pairs:
        if isinstance(item, dict):
            preferred = str(item.get("preferred") or "").strip()
            variants = item.get("variants")
        elif isinstance(item, list) and len(item) == 2:
            preferred = str(item[0]).strip()
            variants = item[1]
        else:
            raise OfficeParseError(f"规则 {rule.id} 的 pairs 项必须是对象或二元数组")
        if not preferred or not isinstance(variants, list):
            raise OfficeParseError(f"规则 {rule.id} 的 preferred/variants 非法")
        cleaned = [
            str(variant).strip()
            for variant in variants
            if str(variant).strip() and str(variant).strip() != preferred
        ]
        if cleaned:
            pairs.append((preferred, cleaned))
    if not pairs:
        raise OfficeParseError(f"规则 {rule.id} 没有有效术语对")
    return pairs


def check_terminology(ctx: Any, rule: WordRuleSpec) -> None:
    pairs = _terminology_pairs(rule)
    for paragraph in ctx.paragraphs:
        text = str(paragraph.get("text") or "")
        if not text:
            continue
        for preferred, variants in pairs:
            hits = [variant for variant in variants if variant in text]
            if not hits:
                continue
            ctx.emit(
                rule,
                f"术语不一致: 使用 {', '.join(hits)}，建议统一为 {preferred}",
                expected=preferred,
                actual=", ".join(hits),
                anchor=_anchor_of(paragraph),
                scope="paragraph",
            )


def check_required_phrases(ctx: Any, rule: WordRuleSpec) -> None:
    phrases = rule.params.get("phrases")
    if not isinstance(phrases, list) or not phrases:
        raise OfficeParseError(f"规则 {rule.id} 参数 phrases 必须是非空数组")
    mode = str(rule.params.get("match", "contains")).strip().lower()
    if mode not in ("contains", "exact"):
        raise OfficeParseError(f"规则 {rule.id} 参数 match 只能是 contains/exact")
    texts = [str(paragraph.get("text") or "").strip() for paragraph in ctx.paragraphs]
    for raw_phrase in phrases:
        target = str(raw_phrase).strip()
        if not target:
            continue
        if mode == "exact":
            found = any(text == target for text in texts)
        else:
            found = any(target in text for text in texts)
        if not found:
            ctx.emit(
                rule,
                f"缺少必备表述: {target}",
                expected=target,
                actual="未找到",
                scope="document",
            )


SEMANTIC_CHECKERS: Dict[str, Callable[[Any, WordRuleSpec], None]] = {
    "content.date_format": check_date_format,
    "content.terminology": check_terminology,
    "content.required_phrases": check_required_phrases,
}


__all__ = ["SEMANTIC_CHECKERS"]
