"""LaTeX template filler: slot replacement + LaTeX escaping + post-validation."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from backend.office.errors import (
    OfficeFileNotFoundError,
    OfficeParseError,
    OfficePathError,
    OfficeTemplateFillError,
)
from backend.office.path_safety import resolve_within

from .models import LatexTemplateProfile, LatexTemplateSlot
from .parser import LatexLimits, parse_latex_project
from .template import analyze_latex_template
from .validator import validate_latex_source

_LIST_SLOTS = {"author", "affil", "affiliation", "institute", "keywords"}


def escape_latex(value: str) -> str:
    """Escape plain text for LaTeX text mode."""
    replacements = (
        ("\\", r"\textbackslash{}"),
        ("&", r"\&"),
        ("%", r"\%"),
        ("$", r"\$"),
        ("#", r"\#"),
        ("_", r"\_"),
        ("{", r"\{"),
        ("}", r"\}"),
        ("~", r"\textasciitilde{}"),
        ("^", r"\textasciicircum{}"),
    )
    out = value
    for old, new in replacements:
        out = out.replace(old, new)
    return out


def _coerce_value(slot: LatexTemplateSlot, value: Any) -> str:
    if isinstance(value, (list, tuple)):  # noqa: UP038 — py38 runtime isinstance union
        items = [escape_latex(str(item)) for item in value]
        separator = " \\and " if slot.name in _LIST_SLOTS else ", "
        return separator.join(items)
    return escape_latex(str(value))


def _check_output_name(output_filename: str) -> str:
    name = (output_filename or "").strip()
    if not name:
        raise OfficeTemplateFillError("output_filename 不能为空")
    if Path(name).is_absolute() or "/" in name or "\\" in name:
        raise OfficeTemplateFillError("output_filename 不能包含路径分隔符")
    if name in (".", ".."):
        raise OfficeTemplateFillError("output_filename 非法")
    return name


def _apply_replacements(
    source: str,
    replacements: List[Tuple[int, int, str]],
) -> str:
    rendered = source
    last_start = len(source) + 1
    for start, end, value in sorted(replacements, key=lambda item: item[0], reverse=True):
        if start < 0 or end < start or end > len(source):
            raise OfficeTemplateFillError("槽位位置超出模板范围")
        if end > last_start:
            raise OfficeTemplateFillError("槽位位置重叠，无法安全填充")
        rendered = rendered[:start] + value + rendered[end:]
        last_start = start
    return rendered


def fill_latex_template(
    template_path: Path,
    data: Dict[str, Any],
    output_filename: str,
    *,
    root: Optional[Path] = None,
    limits: Optional[LatexLimits] = None,
) -> Dict[str, Any]:
    """Fill a LaTeX template's slots and write a new .tex file.

    The original template is never overwritten. Required slots must be present;
    the rendered source is validated (braces/environment pairing) before write.
    """
    limits = limits or LatexLimits()
    template = Path(template_path)
    root_path = Path(root).resolve() if root is not None else template.resolve().parent
    profile: LatexTemplateProfile = analyze_latex_template(
        template, root=root_path, limits=limits
    )
    if not isinstance(data, dict):
        raise OfficeTemplateFillError("data 必须是对象")

    missing = [
        slot.name
        for slot in profile.slots
        if slot.required and slot.name not in data
    ]
    if missing:
        raise OfficeTemplateFillError(
            "缺少必填槽位: " + ", ".join(sorted(set(missing)))
        )

    try:
        resolved = template.resolve()
    except OSError as exc:
        raise OfficeParseError("无法解析模板路径") from exc
    if not resolved.is_file():
        raise OfficeFileNotFoundError(resolved)
    source = resolved.read_text(encoding="utf-8", errors="replace")

    replacements: List[Tuple[int, int, str]] = []
    filled = 0
    unfilled: List[str] = []
    for slot in profile.slots:
        if slot.name not in data:
            unfilled.append(slot.name)
            continue
        value = _coerce_value(slot, data[slot.name])
        if slot.kind == "comment":
            replacements.append((slot.start, slot.end, "% " + value))
        else:
            replacements.append((slot.start, slot.end, value))
        filled += 1

    rendered = _apply_replacements(source, replacements)
    validation = validate_latex_source(rendered)
    if not validation["ok"]:
        messages = [
            issue["message"]
            for issue in validation["issues"]
            if issue["severity"] == "error"
        ]
        raise OfficeTemplateFillError(
            "填充后校验失败: " + "; ".join(messages[:5])
        )

    output_name = _check_output_name(output_filename)
    try:
        target = resolve_within(root_path, resolved.parent / output_name)
    except OfficePathError as exc:
        raise OfficeTemplateFillError("输出路径不在工作区内") from exc
    if target == resolved:
        raise OfficeTemplateFillError("输出文件不能覆盖模板")
    if target.exists():
        raise OfficeTemplateFillError("输出文件已存在，拒绝覆盖")
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(rendered, encoding="utf-8")
    except OSError as exc:
        raise OfficeTemplateFillError(f"写入输出文件失败: {exc}") from exc

    try:
        doc = parse_latex_project(target, root=root_path, limits=limits)
        warnings = [warning.to_dict() for warning in doc.warnings]
    except Exception as exc:  # noqa: BLE001 — output is already written; report warning
        warnings = [
            {
                "code": "output_parse_warning",
                "message": f"输出文件已写入，但正文解析失败: {exc}",
            }
        ]

    return {
        "ok": True,
        "template_path": profile.source_path,
        "output_path": target.relative_to(root_path).as_posix(),
        "filename": output_name,
        "filled_count": filled,
        "unfilled_slots": unfilled,
        "validation": validation,
        "warnings": warnings,
    }


__all__ = ["escape_latex", "fill_latex_template"]
