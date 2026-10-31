"""LaTeX template filler: slot replacement + LaTeX escaping + post-validation."""

from __future__ import annotations

import re
import shutil
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
_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".pdf", ".eps", ".svg"}
_MAX_IMAGE_BYTES = 20 * 1024 * 1024


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


def _asset_dir_name(output_name: str) -> str:
    stem = re.sub(r"[^0-9A-Za-z._-]+", "_", Path(output_name).stem).strip("._")
    return f"{stem or 'output'}_assets"


def _sanitize_image_name(name: str) -> str:
    stem = re.sub(r"[^0-9A-Za-z._-]+", "_", Path(name).stem).strip("._") or "image"
    return f"{stem}{Path(name).suffix.lower()}"


def _resolve_image(value: Any, template_dir: Path, root: Path) -> Path:
    raw = str(value).strip()
    if not raw:
        raise OfficeTemplateFillError("图片槽位需要填写工作区内图片路径")
    candidate = Path(raw).expanduser()
    resolved: Optional[Path]
    if candidate.is_absolute():
        try:
            resolved = resolve_within(root, candidate)
        except OfficePathError as exc:
            raise OfficeTemplateFillError("图片不在工作区内") from exc
    else:
        resolved = None
        for base in (template_dir, root):
            try:
                check = resolve_within(root, base / candidate)
            except OfficePathError:
                continue
            if check.is_file():
                resolved = check
                break
        if resolved is None:
            raise OfficeTemplateFillError(f"图片不存在或不在工作区内: {raw}")
    if not resolved.is_file():
        raise OfficeTemplateFillError(f"图片不存在: {raw}")
    if resolved.suffix.lower() not in _IMAGE_SUFFIXES:
        raise OfficeTemplateFillError(f"不支持的图片格式: {resolved.suffix}")
    if resolved.stat().st_size > _MAX_IMAGE_BYTES:
        raise OfficeTemplateFillError(f"图片超过 20 MiB: {raw}")
    return resolved


def _copy_image(
    source: Path,
    assets_dir: Path,
    used: Dict[str, Optional[Path]],
) -> str:
    name = _sanitize_image_name(source.name)
    if used.get(name) == source:
        return name
    candidate = name
    index = 1
    while candidate in used:
        candidate = f"{Path(name).stem}-{index}{Path(name).suffix}"
        index += 1
    assets_dir.mkdir(parents=True, exist_ok=True)
    try:
        shutil.copyfile(str(source), str(assets_dir / candidate))
    except OSError as exc:
        raise OfficeTemplateFillError(f"复制图片失败: {source.name}") from exc
    used[candidate] = source
    return candidate


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

    output_name = _check_output_name(output_filename)
    try:
        target = resolve_within(root_path, resolved.parent / output_name)
    except OfficePathError as exc:
        raise OfficeTemplateFillError("输出路径不在工作区内") from exc
    if target == resolved:
        raise OfficeTemplateFillError("输出文件不能覆盖模板")
    if target.exists():
        raise OfficeTemplateFillError("输出文件已存在，拒绝覆盖")

    asset_prefix = _asset_dir_name(output_name)
    assets_dir = resolved.parent / asset_prefix
    used_images: Dict[str, Optional[Path]] = {}
    if assets_dir.is_dir():
        for existing in assets_dir.iterdir():
            if existing.is_file():
                used_images[existing.name] = None
    relative_output_dir = target.parent.relative_to(root_path)
    images_copied: List[str] = []

    replacements: List[Tuple[int, int, str]] = []
    filled = 0
    unfilled: List[str] = []
    for slot in profile.slots:
        if slot.name not in data:
            unfilled.append(slot.name)
            continue
        if slot.type == "image":
            source_image = _resolve_image(data[slot.name], resolved.parent, root_path)
            filename = _copy_image(source_image, assets_dir, used_images)
            value = f"{asset_prefix}/{filename}"
            rel_image = (relative_output_dir / asset_prefix / filename).as_posix()
            if rel_image not in images_copied:
                images_copied.append(rel_image)
        else:
            value = _coerce_value(slot, data[slot.name])
            if slot.kind == "comment":
                value = "% " + value
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
        "images_copied": images_copied,
        "unfilled_slots": unfilled,
        "validation": validation,
        "warnings": warnings,
    }


__all__ = ["escape_latex", "fill_latex_template"]
