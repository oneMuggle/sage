"""LaTeX template profile extraction (cls/sty + sample .tex → slots/style/macros)."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Dict, Iterable, Optional, Tuple

from backend.office.errors import (
    OfficeFileNotFoundError,
    OfficeParseError,
    OfficePathError,
    OfficeSizeLimitError,
)
from backend.office.path_safety import is_within

from .models import (
    LatexAnchor,
    LatexTemplateProfile,
    LatexTemplateSlot,
    LatexWarning,
)
from .parser import LatexLimits, parse_latex_project
from .scanner import (
    command_arg_spans,
    find_environment,
    line_col,
    parse_command,
    strip_comments,
)

_SLOT_COMMANDS: Dict[str, Tuple[str, bool, str]] = {
    "title": ("text", True, "文档标题"),
    "author": ("list", True, "作者（多个作者用 \\and 分隔）"),
    "affil": ("list", False, "作者单位"),
    "affiliation": ("list", False, "作者单位"),
    "institute": ("list", False, "机构"),
    "email": ("text", False, "联系邮箱"),
    "date": ("date", False, "日期"),
    "keywords": ("list", False, "关键词"),
}

_JOURNAL_COMMANDS = {
    "journal",
    "journalname",
    "articletype",
    "received",
    "accepted",
    "corres",
    "correspondingauthor",
    "doi",
    "volume",
    "issue",
    "pages",
    "copyright",
    "funding",
    "acknowledgements",
    "acknowledgment",
}

_ENV_SLOTS: Dict[str, Tuple[str, bool, str]] = {
    "abstract": ("rich_text", True, "摘要"),
    "keywords": ("list", False, "关键词"),
    "keyword": ("list", False, "关键词"),
    "acknowledgements": ("rich_text", False, "致谢"),
    "acknowledgments": ("rich_text", False, "致谢"),
}

_PLACEHOLDER_PATTERNS = (
    re.compile(r"<<([^<>\n]{1,120})>>"),
    re.compile(r"\[\[([^\[\]\n]{1,120})\]\]"),
    re.compile(r"【([^【】\n]{1,120})】"),
)

_COMMENT_PATTERN = re.compile(
    r"%\s*(?:TODO|FIXME|待填|待补充|write here)[:：]?\s*([^\n]{0,120})", re.I
)
_TODO_COMMAND = re.compile(r"\\todo\s*\{([^{}]{1,200})\}")

_MACRO_RE = re.compile(
    r"\\(newcommand|renewcommand|providecommand)\s*\{?\s*\\([A-Za-z@]+)\s*\}?"
    r"(?:\s*\[(\d+)\])?(?:\s*\[([^\]]*)\])?\s*\{",
    re.S,
)
_DEF_RE = re.compile(r"\\def\s*\\([A-Za-z@]+)\s*([^{]*)\{", re.S)
_GEOMETRY_RE = re.compile(r"\\geometry\s*\{([^{}]*)\}", re.S)
_LINESPREAD_RE = re.compile(r"\\linespread\s*\{([^{}]*)\}", re.S)
_BIBSTYLE_RE = re.compile(r"\\bibliographystyle\s*\{([^{}]*)\}", re.S)
_USEPACKAGE_RE = re.compile(
    r"\\(?:usepackage|RequirePackage)\s*(?:\[[^\]]*\])?\s*\{([^{}]*)\}", re.S
)
_DOCCLASS_RE = re.compile(r"\\documentclass\s*(?:\[([^\]]*)\])?\s*\{([^{}]*)\}", re.S)
_PROVIDES_RE = re.compile(r"\\Provides(?:Class|Package)\s*\{([^{}]*)\}", re.S)


def _plain(value: str) -> str:
    """Best-effort plain text for template metadata/current values."""
    text = value
    for _ in range(3):
        text = re.sub(
            r"\\(?:textbf|textit|emph|texttt|textsl|textsc|underline|text|mathrm|"
            r"mathbf|mathit|mathcal|mbox)\s*\{([^{}]*)\}",
            r"\1",
            text,
        )
    text = re.sub(r"\\(?:label|index|footnote)\s*\{[^{}]*\}", "", text)
    text = re.sub(r"\\[A-Za-z@]+\s*", "", text)
    text = text.replace("~", " ").replace("\\\\", " ")
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _slug(value: str, index: int) -> str:
    slug = re.sub(r"[^0-9A-Za-z_\u4e00-\u9fff]+", "_", value).strip("_")
    if not slug:
        slug = "slot"
    if slug[0].isdigit():
        slug = "s_" + slug
    return f"{slug}_{index}"


def _add_slot(profile: LatexTemplateProfile, slot: LatexTemplateSlot) -> None:
    for existing in profile.slots:
        if (
            existing.kind == slot.kind
            and existing.name == slot.name
            and existing.start == slot.start
        ):
            return
    profile.slots.append(slot)


def _anchor(file_path: Path, root: Path, text: str, pos: int) -> LatexAnchor:
    line, column = line_col(text, pos)
    try:
        rel = file_path.resolve().relative_to(root).as_posix()
    except ValueError:
        rel = file_path.name
    return LatexAnchor(rel, line, column)


def _scan_style_files(
    profile: LatexTemplateProfile,
    root: Path,
    style_files: Iterable[Path],
) -> None:
    seen = set()
    for path in style_files:
        try:
            resolved = path.resolve()
        except OSError:
            continue
        if resolved in seen or not is_within(root, resolved):
            continue
        seen.add(resolved)
        if not resolved.is_file():
            continue
        try:
            raw = resolved.read_text(encoding="utf-8", errors="replace")
        except OSError:
            profile.warnings.append(
                LatexWarning(
                    "style_read_error",
                    f"无法读取样式文件 {resolved.name}",
                    _anchor(resolved, root, "", 0),
                )
            )
            continue
        text = strip_comments(raw)
        match = _PROVIDES_RE.search(text)
        if match and not profile.document_class:
            profile.document_class = match.group(1).strip()
        for match in _USEPACKAGE_RE.finditer(text):
            for raw_name in match.group(1).split(","):
                name = raw_name.strip()
                if name and name not in profile.packages:
                    profile.packages.append(name)
        for match in _DOCCLASS_RE.finditer(text):
            opts = [
                item.strip()
                for item in (match.group(1) or "").split(",")
                if item.strip()
            ]
            if opts:
                profile.style.setdefault("class_options", opts)
        _scan_macros(text, profile)
        geometry = _GEOMETRY_RE.search(text)
        if geometry:
            profile.style.setdefault("geometry", geometry.group(1).strip())
        linespread = _LINESPREAD_RE.search(text)
        if linespread:
            profile.style.setdefault("linespread", linespread.group(1).strip())
        bibstyle = _BIBSTYLE_RE.search(text)
        if bibstyle:
            profile.style.setdefault("bibliography_style", bibstyle.group(1).strip())


def _scan_macros(text: str, profile: LatexTemplateProfile) -> None:
    for match in _MACRO_RE.finditer(text):
        name = match.group(2)
        nargs = int(match.group(3) or 0)
        optional_default = match.group(4)
        start = match.end()
        depth = 1
        i = start
        while i < len(text) and depth > 0:
            if text[i] == "\\":
                i += 2
                continue
            if text[i] == "{":
                depth += 1
            elif text[i] == "}":
                depth -= 1
            i += 1
        body = text[start : max(start, i - 1)]
        profile.macros.setdefault(
            name,
            {
                "nargs": nargs,
                "optional_default": optional_default,
                "body": body[:500],
            },
        )
    for match in _DEF_RE.finditer(text):
        name = match.group(1)
        profile.macros.setdefault(
            name,
            {"nargs": match.group(2).count("#"), "body": ""},
        )


def _scan_slots(
    profile: LatexTemplateProfile,
    clean: str,
    raw: str,
    file_path: Path,
    root: Path,
) -> None:
    pos = 0
    n = len(clean)
    while pos < n:
        idx = clean.find("\\", pos)
        if idx < 0:
            break
        cmd = parse_command(clean, idx)
        if cmd is None:
            pos = idx + 1
            continue
        spans = command_arg_spans(clean, cmd)
        if cmd.name in _SLOT_COMMANDS and spans:
            slot_type, required, description = _SLOT_COMMANDS[cmd.name]
            start, end = spans[0]
            _add_slot(
                profile,
                LatexTemplateSlot(
                    name=cmd.name,
                    kind="command_arg",
                    type=slot_type,
                    required=required,
                    description=description,
                    current_value=_plain(clean[start:end]),
                    command=cmd.name,
                    anchor=_anchor(file_path, root, clean, cmd.start),
                    start=start,
                    end=end,
                ),
            )
        elif cmd.name in _JOURNAL_COMMANDS and spans:
            start, end = spans[0]
            _add_slot(
                profile,
                LatexTemplateSlot(
                    name=cmd.name,
                    kind="command_arg",
                    type="text",
                    required=False,
                    description=f"期刊字段 \\{cmd.name}",
                    current_value=_plain(clean[start:end]),
                    command=cmd.name,
                    anchor=_anchor(file_path, root, clean, cmd.start),
                    start=start,
                    end=end,
                    confidence=0.7,
                ),
            )
        elif cmd.name == "begin" and cmd.args:
            env = cmd.args[0].strip()
            if env in _ENV_SLOTS:
                found = find_environment(clean, cmd.end, env)
                if found is not None:
                    content_start, content_end, _ = found
                    slot_type, required, description = _ENV_SLOTS[env]
                    _add_slot(
                        profile,
                        LatexTemplateSlot(
                            name=env,
                            kind="environment_body",
                            type=slot_type,
                            required=required,
                            description=description,
                            current_value=_plain(clean[content_start:content_end]),
                            environment=env,
                            anchor=_anchor(file_path, root, clean, cmd.start),
                            start=content_start,
                            end=content_end,
                        ),
                    )
        pos = cmd.end if cmd.end > idx else idx + 1

    for pattern in _PLACEHOLDER_PATTERNS:
        for index, match in enumerate(pattern.finditer(raw), start=1):
            label = match.group(1).strip()
            _add_slot(
                profile,
                LatexTemplateSlot(
                    name=f"placeholder_{_slug(label, index)}",
                    kind="placeholder",
                    type="text",
                    required=True,
                    description=f"模板占位符：{label}",
                    current_value=label,
                    placeholder=match.group(0),
                    anchor=_anchor(file_path, root, raw, match.start()),
                    start=match.start(),
                    end=match.end(),
                    confidence=0.9,
                ),
            )

    for index, match in enumerate(_COMMENT_PATTERN.finditer(raw), start=1):
        label = (match.group(1) or "comment").strip()
        _add_slot(
            profile,
            LatexTemplateSlot(
                name=f"comment_{_slug(label, index)}",
                kind="comment",
                type="text",
                required=False,
                description="注释中的待填提示",
                current_value=label,
                anchor=_anchor(file_path, root, raw, match.start()),
                start=match.start(),
                end=match.end(),
                confidence=0.5,
            ),
        )

    for index, match in enumerate(_TODO_COMMAND.finditer(raw), start=1):
        label = match.group(1).strip()
        _add_slot(
            profile,
            LatexTemplateSlot(
                name=f"todo_{_slug(label, index)}",
                kind="placeholder",
                type="text",
                required=True,
                description=f"\\todo 占位：{label}",
                current_value=label,
                placeholder=match.group(0),
                anchor=_anchor(file_path, root, raw, match.start()),
                start=match.start(),
                end=match.end(),
                confidence=0.8,
            ),
        )


def _scan_template_header(
    profile: LatexTemplateProfile,
    text: str,
) -> None:
    match = _DOCCLASS_RE.search(text)
    if match:
        profile.document_class = match.group(2).strip()
        profile.document_options = [
            item.strip()
            for item in (match.group(1) or "").split(",")
            if item.strip()
        ]
        for option in profile.document_options:
            if option in ("10pt", "11pt", "12pt"):
                profile.style["font_size"] = option
            if option == "twocolumn":
                profile.style["columns"] = "two"
    for match in _USEPACKAGE_RE.finditer(text):
        for raw_name in match.group(1).split(","):
            name = raw_name.strip()
            if name and name not in profile.packages:
                profile.packages.append(name)
    for package in ("natbib", "biblatex", "cite"):
        if package in profile.packages:
            profile.style["citation_package"] = package
            break
    _scan_macros(text, profile)
    geometry = _GEOMETRY_RE.search(text)
    if geometry:
        profile.style.setdefault("geometry", geometry.group(1).strip())
    linespread = _LINESPREAD_RE.search(text)
    if linespread:
        profile.style.setdefault("linespread", linespread.group(1).strip())
    bibstyle = _BIBSTYLE_RE.search(text)
    if bibstyle:
        profile.style.setdefault("bibliography_style", bibstyle.group(1).strip())


def analyze_latex_template(
    file_path: Path,
    *,
    root: Optional[Path] = None,
    limits: Optional[LatexLimits] = None,
) -> LatexTemplateProfile:
    """Extract a LaTeX template profile (slots/style/macros)."""
    limits = limits or LatexLimits()
    source = Path(file_path)
    root_path = Path(root).resolve() if root is not None else source.resolve().parent
    if not root_path.is_dir():
        raise OfficeParseError("LaTeX 项目根目录不存在")
    if not source.is_file():
        raise OfficeFileNotFoundError(source)
    if source.suffix.lower() not in (".tex", ".ltx"):
        raise OfficeParseError("仅支持 .tex/.ltx 模板")
    try:
        resolved = source.resolve()
    except OSError as exc:
        raise OfficeParseError("无法解析 LaTeX 模板路径") from exc
    if not is_within(root_path, resolved):
        raise OfficePathError("LaTeX 模板不在项目目录内", file_path=source)
    size = resolved.stat().st_size
    if size > limits.max_file_bytes:
        raise OfficeSizeLimitError(size, limits.max_file_bytes)
    raw = resolved.read_text(encoding="utf-8", errors="replace")
    clean = strip_comments(raw)

    profile = LatexTemplateProfile(source_path=str(resolved.relative_to(root_path)))
    style_files = list(resolved.parent.glob("*.cls")) + list(resolved.parent.glob("*.sty"))
    if resolved.parent != root_path:
        style_files += list(root_path.glob("*.cls")) + list(root_path.glob("*.sty"))
    _scan_style_files(profile, root_path, style_files)
    _scan_template_header(profile, clean)
    _scan_slots(profile, clean, raw, resolved, root_path)

    try:
        doc = parse_latex_project(resolved, root=root_path, limits=limits)
        profile.includes = list(doc.includes)
        profile.warnings.extend(doc.warnings)
        if not profile.metadata.title:
            profile.metadata = doc.metadata
    except Exception as exc:  # noqa: BLE001 — profile extraction must degrade
        profile.warnings.append(
            LatexWarning("template_parse_warning", f"模板正文解析失败: {exc}")
        )

    if not profile.document_class:
        profile.warnings.append(
            LatexWarning("missing_documentclass", "模板未声明 \\documentclass")
        )
    if not profile.slots:
        profile.warnings.append(
            LatexWarning(
                "no_slots",
                "未发现可填充槽位；可在模板中使用 \\title/\\author/摘要环境或 <<占位符>>",
            )
        )
    return profile


__all__ = ["analyze_latex_template"]
