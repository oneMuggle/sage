"""中文办公模板库 (Office parity batch 3 — Item 3.2).

Three responsibilities:

1. **BUILTIN_TEMPLATES** — 6 curated 中文办公 Word 模板 (周报/会议纪要/项目计划/
   日报/项目复盘/简历). Each entry carries static placeholder metadata
   (``{name, type, description}``) plus a lazy ``build()`` that composes a real
   .docx (python-docx) containing docxtpl ``{{ }}`` tags. Table placeholders use
   real docx tables whose template row cells hold plain cell-level ``{{var}}``
   tags — docxtpl fills those natively; deliberate design choice: **no
   ``{%tr for%}`` row loops** in builtin templates so a single string value per
   placeholder is enough to fill them (multiline values render as-is, matching
   the /word/fill-template contract).

   Note on declared vs. scanned types: for builtin templates the registry's
   placeholder types are curated metadata (e.g. 周报 ``highlights`` is declared
   RICH_TEXT because the UI should render a multiline editor); the scanner's
   ``|``-filter → RICH_TEXT / table-cell → TABLE conventions (see
   ``word_template._extract_placeholders_from_text``) drive *workspace* user
   templates, which are classified by scanning the actual .docx.

2. **list_templates(workspace_path)** — builtin registry + user templates found
   in ``<workspace>/office/templates/*.docx`` (each analyzed with the existing
   scanner; broken files are skipped with a logged warning, never fail the
   listing).

3. **instantiate_template(...)** — fill a builtin (by id) or workspace template
   (by filename, containment-checked within ``office/templates/``) through the
   exact ``word_template.fill_word_template`` machinery (ZIP-bomb guards,
   dangerous-Jinja scan, SandboxedEnvironment, ≤10MB InlineImage) and write the
   result into the managed layout ``<workspace>/office/word/<uuid>/<filename>``.
   Nothing is registered here — the route persists the row via
   ``_build_summary_for_generated`` like the other generate routes.

Security:
- builtin ids must match ``^[a-z0-9_]{1,64}$`` (unknown/invalid → error).
- workspace template filenames are validated (no separators / ``..`` / wrong
  extension) AND containment-checked via ``path_safety.resolve_within``.
- every data value (str) is capped at ``MAX_DATA_VALUE_CHARS``.

Python 3.8-compatible syntax (no PEP 604/585) per backend convention.
"""

from __future__ import annotations

import logging
import os
import re
import shutil
import tempfile
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from docx import Document

from .errors import OfficeError, OfficeFileNotFoundError, OfficePathError, OfficeTemplateFillError
from .models import (
    OfficeDocType,
    TemplateLibraryEntry,
    TemplateLibraryPlaceholder,
    TemplateLibraryResponse,
    TemplatePlaceholderType,
    WordTemplateFillRequest,
    WordTemplateFillResult,
)
from .path_safety import resolve_within, validate_supported_filename
from .storage import generate_document_dir, validate_workspace
from .word_template import analyze_word_template, fill_word_template

logger = logging.getLogger(__name__)

#: builtin 模板 id 严格格式（小写字母/数字/下划线，≤64 字符）。
TEMPLATE_ID_RE = re.compile(r"^[a-z0-9_]{1,64}$")

#: 单个 data 值的长度上限（防止超大字符串把渲染/存储拖垮）。
MAX_DATA_VALUE_CHARS = 20_000

#: workspace 用户模板目录（相对 workspace 根）。
WORKSPACE_TEMPLATES_SUBDIR = os.path.join("office", "templates")


# ──────────────────────────────────────────────────────────────────────
# Builtin registry
# ──────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class BuiltinPlaceholder:
    """Static placeholder metadata for one builtin template."""

    name: str
    type: TemplatePlaceholderType
    description: str = ""


@dataclass(frozen=True)
class BuiltinTemplate:
    """One builtin 中文办公模板.

    ``build`` composes (and caches) the real .docx on first use; it must not
    touch the workspace — the returned Path is a process-local cache file that
    ``instantiate_template`` copies into the managed document directory before
    filling.
    """

    id: str
    name: str
    description: str
    build: Callable[[], Path]
    placeholders: List[BuiltinPlaceholder] = field(default_factory=list)
    doc_type: OfficeDocType = OfficeDocType.WORD


# ── per-process cache dir + lazy build cache ─────────────────────────

_BUILTIN_CACHE_DIR: Optional[Path] = None
_BUILTIN_DOCX_CACHE: Dict[str, Path] = {}


def _builtin_cache_dir() -> Path:
    """Process-wide cache dir for generated builtin template .docx files.

    System temp (cleaned by the OS eventually); filenames carry the PID + a
    random suffix so two concurrent backend processes never race on the same
    file while one is being read by the fill step.
    """
    global _BUILTIN_CACHE_DIR
    if _BUILTIN_CACHE_DIR is None:
        base = Path(tempfile.gettempdir()) / "sage-office-template-cache"
        base.mkdir(parents=True, exist_ok=True)
        _BUILTIN_CACHE_DIR = base
    return _BUILTIN_CACHE_DIR


def _save_builtin_docx(template_id: str, doc: Document) -> Path:
    """Persist a freshly composed builtin template docx into the cache dir."""
    unique_name = f"{template_id}-{os.getpid()}-{uuid.uuid4().hex[:8]}.docx"
    target = _builtin_cache_dir() / unique_name
    doc.save(str(target))
    return target


def builtin_docx_path(spec: BuiltinTemplate) -> Path:
    """Return (building on first use) the cached .docx for a builtin template."""
    cached = _BUILTIN_DOCX_CACHE.get(spec.id)
    if cached is not None and cached.is_file():
        return cached
    path = spec.build()
    _BUILTIN_DOCX_CACHE[spec.id] = path
    return path


# ── docx composition helpers ─────────────────────────────────────────


def _field_paragraph(doc: Document, label: str, tag: str) -> None:
    """One '标签：{{tag}}' body paragraph."""
    doc.add_paragraph(f"{label}：{tag}")


def _section(doc: Document, title: str, tag: str) -> None:
    """A level-1 section heading followed by a body placeholder paragraph."""
    doc.add_heading(title, level=1)
    doc.add_paragraph(tag)


def _tagged_table(doc: Document, headers: List[str], row_tags: List[str]) -> None:
    """A real docx table: styled header row + one template row of {{var}} cells.

    Cell-level variables only (no ``{%tr for%}`` loops) — see module docstring.
    """
    table = doc.add_table(rows=2, cols=len(headers))
    table.style = "Table Grid"
    for col, header in enumerate(headers):
        table.cell(0, col).text = header
    for col, tag in enumerate(row_tags):
        table.cell(1, col).text = tag


# ── the six builtin builders ─────────────────────────────────────────


def _build_weekly_report() -> Path:
    doc = Document()
    doc.add_heading("{{title}}", level=0)
    _field_paragraph(doc, "作者", "{{author}}")
    _field_paragraph(doc, "周期", "{{week_range}}")
    _section(doc, "本周亮点", "{{highlights}}")
    _section(doc, "下周计划", "{{next_plan}}")
    _section(doc, "风险与问题", "{{risks}}")
    return _save_builtin_docx("weekly_report", doc)


def _build_meeting_minutes() -> Path:
    doc = Document()
    doc.add_heading("{{meeting_title}}", level=0)
    _field_paragraph(doc, "时间", "{{date}}")
    _field_paragraph(doc, "参会人", "{{attendees}}")
    _section(doc, "讨论内容", "")
    _tagged_table(doc, ["讨论内容"], ["{{discussion}}"])
    _section(doc, "行动项", "")
    _tagged_table(doc, ["行动项"], ["{{action_items}}"])
    return _save_builtin_docx("meeting_minutes", doc)


def _build_project_plan() -> Path:
    doc = Document()
    doc.add_heading("{{title}}", level=0)
    _field_paragraph(doc, "负责人", "{{owner}}")
    _field_paragraph(doc, "开始日期", "{{startDate}}")
    _field_paragraph(doc, "结束日期", "{{endDate}}")
    _field_paragraph(doc, "预算", "{{budget}}")
    _section(doc, "里程碑", "")
    _tagged_table(doc, ["里程碑"], ["{{milestones}}"])
    return _save_builtin_docx("project_plan", doc)


def _build_daily_report() -> Path:
    doc = Document()
    doc.add_heading("{{title}}", level=0)
    _field_paragraph(doc, "日期", "{{date}}")
    _field_paragraph(doc, "记录人", "{{author}}")
    _section(doc, "今日完成", "{{today_work}}")
    _section(doc, "明日计划", "{{tomorrow_plan}}")
    _section(doc, "问题与风险", "{{issues}}")
    return _save_builtin_docx("daily_report", doc)


def _build_retrospective() -> Path:
    doc = Document()
    doc.add_heading("{{project_name}} 项目复盘", level=0)
    _field_paragraph(doc, "复盘时间", "{{review_date}}")
    _section(doc, "做得好的", "{{wins}}")
    _section(doc, "待改进", "{{problems}}")
    _section(doc, "改进行动", "{{improvements}}")
    _section(doc, "关键指标", "")
    _tagged_table(doc, ["关键指标"], ["{{metrics}}"])
    return _save_builtin_docx("retrospective", doc)


def _build_resume() -> Path:
    doc = Document()
    doc.add_heading("{{name}}", level=0)
    _field_paragraph(doc, "电话", "{{phone}}")
    _field_paragraph(doc, "邮箱", "{{email}}")
    _section(doc, "教育背景", "{{education}}")
    _section(doc, "工作与项目经历", "")
    _tagged_table(doc, ["经历"], ["{{experiences}}"])
    return _save_builtin_docx("resume", doc)


BUILTIN_TEMPLATES: List[BuiltinTemplate] = [
    BuiltinTemplate(
        id="weekly_report",
        name="周报",
        description="按亮点 / 下周计划 / 风险三段式组织的周工作汇报。",
        placeholders=[
            BuiltinPlaceholder("title", TemplatePlaceholderType.TEXT, "周报标题"),
            BuiltinPlaceholder("author", TemplatePlaceholderType.TEXT, "作者姓名"),
            BuiltinPlaceholder(
                "week_range", TemplatePlaceholderType.TEXT, "覆盖周期，如 2026-09-01 ~ 2026-09-07"
            ),
            BuiltinPlaceholder("highlights", TemplatePlaceholderType.RICH_TEXT, "本周亮点，可多行"),
            BuiltinPlaceholder("next_plan", TemplatePlaceholderType.RICH_TEXT, "下周计划，可多行"),
            BuiltinPlaceholder("risks", TemplatePlaceholderType.RICH_TEXT, "风险与问题，可多行"),
        ],
        build=_build_weekly_report,
    ),
    BuiltinTemplate(
        id="meeting_minutes",
        name="会议纪要",
        description="含讨论内容表与行动项表的会议记录模板。",
        placeholders=[
            BuiltinPlaceholder("meeting_title", TemplatePlaceholderType.TEXT, "会议主题"),
            BuiltinPlaceholder("date", TemplatePlaceholderType.DATE, "会议日期"),
            BuiltinPlaceholder("attendees", TemplatePlaceholderType.TEXT, "参会人员"),
            BuiltinPlaceholder("discussion", TemplatePlaceholderType.TABLE, "讨论内容（表格单元格变量）"),
            BuiltinPlaceholder("action_items", TemplatePlaceholderType.TABLE, "行动项（表格单元格变量）"),
        ],
        build=_build_meeting_minutes,
    ),
    BuiltinTemplate(
        id="project_plan",
        name="项目计划",
        description="含起止日期、预算与里程碑表的项目计划模板。",
        placeholders=[
            BuiltinPlaceholder("title", TemplatePlaceholderType.TEXT, "项目名称"),
            BuiltinPlaceholder("owner", TemplatePlaceholderType.TEXT, "负责人"),
            BuiltinPlaceholder("startDate", TemplatePlaceholderType.DATE, "开始日期"),
            BuiltinPlaceholder("endDate", TemplatePlaceholderType.DATE, "结束日期"),
            BuiltinPlaceholder("budget", TemplatePlaceholderType.TEXT, "预算"),
            BuiltinPlaceholder("milestones", TemplatePlaceholderType.TABLE, "里程碑（表格单元格变量）"),
        ],
        build=_build_project_plan,
    ),
    BuiltinTemplate(
        id="daily_report",
        name="日报",
        description="今日完成 / 明日计划 / 问题风险三段式日报模板。",
        placeholders=[
            BuiltinPlaceholder("title", TemplatePlaceholderType.TEXT, "日报标题"),
            BuiltinPlaceholder("date", TemplatePlaceholderType.DATE, "日期"),
            BuiltinPlaceholder("author", TemplatePlaceholderType.TEXT, "记录人"),
            BuiltinPlaceholder("today_work", TemplatePlaceholderType.RICH_TEXT, "今日完成事项，可多行"),
            BuiltinPlaceholder("tomorrow_plan", TemplatePlaceholderType.TEXT, "明日计划"),
            BuiltinPlaceholder("issues", TemplatePlaceholderType.TEXT, "问题与风险"),
        ],
        build=_build_daily_report,
    ),
    BuiltinTemplate(
        id="retrospective",
        name="项目复盘",
        description="做得好 / 待改进 / 改进行动 + 关键指标表的项目复盘模板。",
        placeholders=[
            BuiltinPlaceholder("project_name", TemplatePlaceholderType.TEXT, "项目名称"),
            BuiltinPlaceholder("review_date", TemplatePlaceholderType.DATE, "复盘时间"),
            BuiltinPlaceholder("wins", TemplatePlaceholderType.RICH_TEXT, "做得好的方面，可多行"),
            BuiltinPlaceholder("problems", TemplatePlaceholderType.RICH_TEXT, "待改进的问题，可多行"),
            BuiltinPlaceholder("improvements", TemplatePlaceholderType.RICH_TEXT, "改进行动，可多行"),
            BuiltinPlaceholder("metrics", TemplatePlaceholderType.TABLE, "关键指标（表格单元格变量）"),
        ],
        build=_build_retrospective,
    ),
    BuiltinTemplate(
        id="resume",
        name="简历",
        description="个人信息 + 教育背景 + 经历表的中文简历模板。",
        placeholders=[
            BuiltinPlaceholder("name", TemplatePlaceholderType.TEXT, "姓名"),
            BuiltinPlaceholder("phone", TemplatePlaceholderType.TEXT, "联系电话"),
            BuiltinPlaceholder("email", TemplatePlaceholderType.TEXT, "电子邮箱"),
            BuiltinPlaceholder("education", TemplatePlaceholderType.TEXT, "教育背景"),
            BuiltinPlaceholder("experiences", TemplatePlaceholderType.TABLE, "工作与项目经历（表格单元格变量）"),
        ],
        build=_build_resume,
    ),
]

_BUILTIN_BY_ID: Dict[str, BuiltinTemplate] = {spec.id: spec for spec in BUILTIN_TEMPLATES}


# ──────────────────────────────────────────────────────────────────────
# list_templates
# ──────────────────────────────────────────────────────────────────────


def _entry_placeholders(
    placeholders: List[Any],
) -> List[TemplateLibraryPlaceholder]:
    """Deduplicate by name (first occurrence wins) and convert to the API model."""
    by_name: Dict[str, Any] = {}
    for placeholder in placeholders:
        by_name.setdefault(placeholder.name, placeholder)
    return [
        TemplateLibraryPlaceholder(
            name=placeholder.name,
            type=placeholder.type,
            description=getattr(placeholder, "description", "") or "",
        )
        for placeholder in by_name.values()
    ]


def _builtin_entries() -> List[TemplateLibraryEntry]:
    return [
        TemplateLibraryEntry(
            id=spec.id,
            name=spec.name,
            description=spec.description,
            doc_type=spec.doc_type,
            placeholders=_entry_placeholders(spec.placeholders),
            source="builtin",
        )
        for spec in BUILTIN_TEMPLATES
    ]


def _workspace_template_id(stem: str, used_ids: set) -> str:
    """Stable-ish 'ws_' id from a filename stem; uniqueness via numeric suffix."""
    sanitized = re.sub(r"[^a-z0-9_]+", "_", stem.lower()).strip("_")
    base = ("ws_" + (sanitized or "template"))[:64]
    candidate = base
    counter = 1
    while candidate in used_ids:
        suffix = f"_{counter}"
        candidate = base[: 64 - len(suffix)] + suffix
        counter += 1
    return candidate


def _scan_workspace_templates(workspace: Path) -> List[TemplateLibraryEntry]:
    """Analyze <workspace>/office/templates/*.docx; skip broken files."""
    templates_dir = workspace / WORKSPACE_TEMPLATES_SUBDIR
    if not templates_dir.is_dir():
        return []
    entries: List[TemplateLibraryEntry] = []
    used_ids: set = set()
    for path in sorted(templates_dir.glob("*.docx")):
        # Word 的 ~$ 锁文件不是模板；目录项也可能在扫描间隙变成非文件。
        if not path.is_file() or path.name.startswith("~$"):
            continue
        try:
            analysis = analyze_word_template(path, workspace_path=str(workspace))
        except OfficeError as exc:
            logger.warning(
                "Skipping broken workspace template %s: %s", path.name, exc
            )
            continue
        entry_id = _workspace_template_id(path.stem, used_ids)
        used_ids.add(entry_id)
        entries.append(
            TemplateLibraryEntry(
                id=entry_id,
                name=path.stem,
                description=f"工作区模板（office/templates/{path.name}）",
                doc_type=OfficeDocType.WORD,
                placeholders=_entry_placeholders(analysis.placeholders),
                source="workspace",
                filename=path.name,
            )
        )
    return entries


def list_templates(workspace_path: Optional[str] = None) -> TemplateLibraryResponse:
    """List builtin templates plus workspace user templates.

    ``workspace_path`` 缺省 / 不传时只返回 builtin；传入时校验 workspace
    （非法路径抛 OfficePathError）并扫描 ``office/templates/*.docx``。
    """
    templates = _builtin_entries()
    if workspace_path:
        workspace = validate_workspace(Path(workspace_path))
        templates.extend(_scan_workspace_templates(workspace))
    return TemplateLibraryResponse(templates=templates)


# ──────────────────────────────────────────────────────────────────────
# instantiate_template
# ──────────────────────────────────────────────────────────────────────


def _resolve_source_template(
    workspace: Path,
    template_id: Optional[str],
    workspace_template: Optional[str],
) -> Path:
    """Locate the source .docx for instantiation (builtin id OR workspace file)."""
    if template_id and workspace_template:
        raise OfficePathError(
            "template_id and workspace_template are mutually exclusive"
        )
    if template_id:
        if not TEMPLATE_ID_RE.match(template_id):
            raise OfficePathError(
                f"Invalid template id (must match {TEMPLATE_ID_RE.pattern}): {template_id!r}"
            )
        spec = _BUILTIN_BY_ID.get(template_id)
        if spec is None:
            raise OfficeFileNotFoundError(Path(template_id))
        return builtin_docx_path(spec)
    if workspace_template:
        # validate_supported_filename: rejects separators/'..' and enforces the
        # .docx extension (auto-appended when omitted); resolve_within then
        # containment-checks the resolved path inside office/templates/.
        safe_name = validate_supported_filename(workspace_template, OfficeDocType.WORD)
        templates_dir = workspace / WORKSPACE_TEMPLATES_SUBDIR
        candidate = resolve_within(templates_dir, templates_dir / safe_name)
        if not candidate.is_file():
            raise OfficeFileNotFoundError(candidate)
        return candidate
    raise OfficePathError("template_id or workspace_template is required")


def _validate_data_caps(data: Optional[Dict[str, Any]]) -> None:
    """Reject oversized string values (protects render + storage)."""
    if not data:
        return
    for key, value in data.items():
        if isinstance(value, str) and len(value) > MAX_DATA_VALUE_CHARS:
            raise OfficeTemplateFillError(
                f"Data value for '{key}' exceeds the {MAX_DATA_VALUE_CHARS}-character limit"
            )


def instantiate_template(
    workspace_path: str,
    template_id: Optional[str] = None,
    workspace_template: Optional[str] = None,
    filename: str = "",
    data: Optional[Dict[str, Any]] = None,
    images: Optional[Dict[str, str]] = None,
) -> WordTemplateFillResult:
    """Instantiate a library template into the managed Word layout.

    The source docx (builtin cache file or workspace template) is copied into
    a fresh ``<workspace>/office/word/<uuid>/`` directory and filled via
    :func:`word_template.fill_word_template` — the exact same safety machinery
    as ``POST /office/word/fill-template`` (ZIP guards, dangerous-Jinja scan,
    SandboxedEnvironment, ≤10MB images, output-filename checks), so no safety
    logic is duplicated here. On any failure the managed directory is removed
    again; on success the intermediate source copy is deleted, leaving only
    the filled document.

    Returns the full ``WordTemplateFillResult`` (output_path / filled_count /
    unfilled_placeholders) so the route can persist the row and echo the
    standard fill response.
    """
    workspace = validate_workspace(Path(workspace_path))
    source_template = _resolve_source_template(
        workspace, template_id, workspace_template
    )
    if not filename:
        raise OfficePathError("filename is required")
    output_name = validate_supported_filename(filename, OfficeDocType.WORD)
    _validate_data_caps(data)

    doc_id = uuid.uuid4().hex
    managed_dir = generate_document_dir(workspace, OfficeDocType.WORD, doc_id)
    source_copy = managed_dir / f"._source-{source_template.name}"
    try:
        try:
            shutil.copyfile(source_template, source_copy)
        except OSError as exc:
            raise OfficeTemplateFillError(
                f"Template source is unavailable: {exc}"
            ) from exc
        result = fill_word_template(
            WordTemplateFillRequest(
                workspace_path=str(workspace),
                template_path=str(source_copy),
                output_filename=output_name,
                data=dict(data or {}),
                images=images,
            )
        )
    except Exception:
        # 失败不留半成品：清掉整个新 managed 目录（只包含源拷贝/残留输出）。
        shutil.rmtree(managed_dir, ignore_errors=True)
        raise
    # 成功：删掉中间源拷贝，目录里只留最终文档。
    try:
        source_copy.unlink()
    except OSError as exc:  # pragma: no cover — Windows 句柄延迟等极端情况
        logger.warning("Failed to remove template source copy: %s", exc)
    return result
