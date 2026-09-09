"""中文办公模板库 (Office parity batch 3 — Item 3.2; round 3 N2 adds xlsx/ppt).

Three responsibilities:

1. **Builtin registry** — 10 curated 中文办公模板 across doc types:

   - ``BUILTIN_TEMPLATES`` (kept as-is, all ``doc_type=word``): 6 Word 模板
     (周报/会议纪要/项目计划/日报/项目复盘/简历). Each entry carries static
     placeholder metadata (``{name, type, description}``) plus a lazy
     ``build()`` that composes a real .docx (python-docx) containing docxtpl
     ``{{ }}`` tags. Table placeholders use real docx tables whose template row
     cells hold plain cell-level ``{{var}}`` tags — docxtpl fills those
     natively; deliberate design choice: **no ``{%tr for%}`` row loops** in
     builtin templates so a single string value per placeholder is enough to
     fill them (multiline values render as-is, matching the /word/fill-template
     contract).
   - ``BUILTIN_EXCEL_TEMPLATES`` / ``BUILTIN_PPT_TEMPLATES`` (round 3 N2):
     2 xlsx (预算表/库存台账) + 2 pptx (项目启动会/周例会) 模板. There is no
     docxtpl equivalent for xlsx/pptx, so their builders embed **literal
     ``{{var}}`` marker text** in cells / text frames; instantiation walks every
     string cell (openpyxl, formula cells excluded) / every text frame
     (python-pptx, including table cells and speaker notes) and replaces
     markers literally.

   ``ALL_BUILTIN_TEMPLATES`` is the combined registry used for listing and
   instantiation; ``BUILTIN_TEMPLATES`` stays the 6 Word entries so existing
   callers/tests that reason about the Word-only registry keep working.

   Note on declared vs. scanned types: for builtin templates the registry's
   placeholder types are curated metadata (e.g. 周报 ``highlights`` is declared
   RICH_TEXT because the UI should render a multiline editor); the scanner's
   ``|``-filter → RICH_TEXT / table-cell → TABLE conventions (see
   ``word_template._extract_placeholders_from_text``) drive *workspace* user
   templates, which are classified by scanning the actual .docx.

2. **list_templates(workspace_path)** — builtin registry + user templates found
   in ``<workspace>/office/templates/`` with extensions ``.docx``/``.xlsx``/
   ``.pptx`` (docx analyzed with the existing scanner; xlsx/pptx scanned for
   literal markers; broken files are skipped with a logged warning, never fail
   the listing).

3. **instantiate_template(...)** — fill a builtin (by id) or workspace template
   (by filename, containment-checked within ``office/templates/``):
   - word → the exact ``word_template.fill_word_template`` machinery
     (ZIP-bomb guards, dangerous-Jinja scan, SandboxedEnvironment, ≤10MB
     InlineImage) into ``<workspace>/office/word/<uuid>/<filename>``.
   - excel/ppt → generic marker-replace (see above) into the SAME managed
     layout, ``office/excel|ppt/<uuid>/<filename>``.
   Both return a ``WordTemplateFillResult``-compatible model so the existing
   ``POST /office/templates/instantiate`` route works unchanged.
   Nothing is registered here — the route persists the row via
   ``_build_summary_for_generated`` like the other generate routes.

Marker-replace semantics (excel/ppt):
- ``{{ inner }}`` marker names are stripped and ``|``-filters dropped
  (``{{a | upper}}`` fills from ``data["a"]``), mirroring the word scanner.
- replacement is literal: ``str(data.get(name, ''))`` (``None`` → empty).
- ``filled_count`` counts unique template marker names whose data key is
  present; ``unfilled_placeholders`` is the sorted list of the rest — exactly
  the /word/fill-template contract.
- openpyxl keeps formulas as formulas (cells whose value starts with ``=`` are
  never touched); openpyxl/python-pptx round-trips preserve common formatting
  but may drop exotic features, same caveat as the generate/edit paths.

Security:
- builtin ids must match ``^[a-z0-9_]{1,64}$`` (unknown/invalid → error).
- workspace template filenames are validated (no separators / ``..`` /
  extension must match the detected doc type) AND containment-checked via
  ``path_safety.resolve_within``.
- every data value (str) is capped at ``MAX_DATA_VALUE_CHARS``; xlsx/pptx
  source files are capped at ``MAX_TEMPLATE_SOURCE_BYTES``.

Python 3.8-compatible syntax (no PEP 604/585) per backend convention.
"""

from __future__ import annotations

import copy
import logging
import os
import re
import shutil
import tempfile
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

from docx import Document

from .errors import (
    OfficeError,
    OfficeFileNotFoundError,
    OfficePathError,
    OfficeSizeLimitError,
    OfficeTemplateFillError,
    OfficeTemplateParseError,
)
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
from .word_template import PLACEHOLDER_RE, analyze_word_template, fill_word_template

logger = logging.getLogger(__name__)

#: builtin 模板 id 严格格式（小写字母/数字/下划线，≤64 字符）。
TEMPLATE_ID_RE = re.compile(r"^[a-z0-9_]{1,64}$")

#: {{var}} 占位符标记（与 word_template.PLACEHOLDER_RE 完全同一正则，别名仅
#: 为了让 xlsx/ppt 路径的语义可读：literal marker replace）。
MARKER_RE = PLACEHOLDER_RE

#: 单个 data 值的长度上限（防止超大字符串把渲染/存储拖垮）。
MAX_DATA_VALUE_CHARS = 20_000

#: workspace xlsx/pptx 模板源文件大小上限（与 read 路由 50MB 缺省一致）。
MAX_TEMPLATE_SOURCE_BYTES = 50 * 1024 * 1024

#: workspace 用户模板目录（相对 workspace 根）。
WORKSPACE_TEMPLATES_SUBDIR = os.path.join("office", "templates")

#: workspace 模板扩展名 → doc_type（顺序即无扩展名时的猜测顺序：word 优先，
#: 保持既有「省略扩展名 = .docx」行为不变）。
_TEMPLATE_EXTENSION_DOC_TYPES: Dict[str, OfficeDocType] = {
    ".docx": OfficeDocType.WORD,
    ".xlsx": OfficeDocType.EXCEL,
    ".pptx": OfficeDocType.PPT,
}


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


def _save_builtin_file(template_id: str, document: Any, extension: str) -> Path:
    """Persist a freshly composed builtin template file into the cache dir.

    ``document`` is any object exposing ``save(target_path)`` (python-docx
    ``Document``, openpyxl ``Workbook``, python-pptx ``Presentation``).
    """
    unique_name = f"{template_id}-{os.getpid()}-{uuid.uuid4().hex[:8]}.{extension}"
    target = _builtin_cache_dir() / unique_name
    document.save(str(target))
    return target


def _save_builtin_docx(template_id: str, doc: Document) -> Path:
    """Persist a freshly composed builtin template docx into the cache dir."""
    return _save_builtin_file(template_id, doc, "docx")


def builtin_template_path(spec: BuiltinTemplate) -> Path:
    """Return (building on first use) the cached template file for a builtin."""
    cached = _BUILTIN_DOCX_CACHE.get(spec.id)
    if cached is not None and cached.is_file():
        return cached
    path = spec.build()
    _BUILTIN_DOCX_CACHE[spec.id] = path
    return path


#: Back-compat alias — the cache is doc-type agnostic since round 3 N2.
builtin_docx_path = builtin_template_path


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


# ──────────────────────────────────────────────────────────────────────
# Excel builtin builders (round 3 — N2)
#
# xlsx/pptx 没有 docxtpl 等价的渲染引擎，因此 builder 直接在单元格里写
# **字面量 {{var}} 标记文本**，实例化时由 `_replace_xlsx_markers` 全表扫描
# 替换（公式单元格除外）。样式走 openpyxl 原生 Font/PatternFill/
# number_format/freeze_panes。
# ──────────────────────────────────────────────────────────────────────


def _style_header_row(worksheet, row: int, columns: int) -> None:
    """表头行：蓝底白字加粗（与生成器 excel 输出的观感一致）。"""
    from openpyxl.styles import Font, PatternFill

    fill = PatternFill(fill_type="solid", start_color="4472C4", end_color="4472C4")
    for col in range(1, columns + 1):
        cell = worksheet.cell(row=row, column=col)
        cell.font = Font(color="FFFFFF", bold=True)
        cell.fill = fill


def _set_column_widths(worksheet, widths: List[float]) -> None:
    from openpyxl.utils import get_column_letter

    for index, width in enumerate(widths, start=1):
        worksheet.column_dimensions[get_column_letter(index)].width = width


def _build_budget_sheet() -> Path:
    from openpyxl import Workbook
    from openpyxl.styles import Font

    workbook = Workbook()

    # Sheet 概览：标题 / 负责人 / 周期 / 合计 字段标记。
    overview = workbook.active
    assert overview is not None
    overview.title = "概览"
    overview["A1"] = "{{title}}"
    overview["A1"].font = Font(bold=True, size=14)
    overview_fields = (
        (2, "负责人", "{{owner}}"),
        (3, "周期", "{{period}}"),
        (4, "预算合计", "{{total}}"),
    )
    for row, label, marker in overview_fields:
        label_cell = overview.cell(row=row, column=1, value=label)
        label_cell.font = Font(bold=True)
        overview.cell(row=row, column=2, value=marker)
    overview.freeze_panes = "A2"
    _set_column_widths(overview, [14.0, 30.0])

    # Sheet 明细：表头 + 3 行示例标记 + 一行真实 =SUM 公式（实例化时原样保留）。
    detail = workbook.create_sheet("明细")
    for col, header in enumerate(("项目", "类别", "金额", "备注"), start=1):
        detail.cell(row=1, column=col, value=header)
    _style_header_row(detail, 1, 4)
    for row, marker in ((2, "{{item1}}"), (3, "{{item2}}"), (4, "{{item3}}")):
        detail.cell(row=row, column=1, value=marker)
    total_label = detail.cell(row=5, column=1, value="合计")
    total_label.font = Font(bold=True)
    total_formula = detail.cell(row=5, column=3, value="=SUM(C2:C4)")
    total_formula.font = Font(bold=True)
    for row in range(2, 6):
        detail.cell(row=row, column=3).number_format = "#,##0.00"
    detail.freeze_panes = "A2"
    _set_column_widths(detail, [20.0, 12.0, 12.0, 28.0])
    return _save_builtin_file("budget_sheet", workbook, "xlsx")


def _build_inventory() -> Path:
    from openpyxl import Workbook
    from openpyxl.styles import Font

    workbook = Workbook()
    sheet = workbook.active
    assert sheet is not None
    sheet.title = "库存台账"

    # 标题行（含 {{warehouse}} 标记）+ 表头行；前两行一并冻结。
    title_cell = sheet.cell(row=1, column=1, value="{{warehouse}}库存台账")
    title_cell.font = Font(bold=True, size=14)
    headers = ("编号", "名称", "规格", "单位", "数量", "单价", "金额", "更新日期")
    for col, header in enumerate(headers, start=1):
        sheet.cell(row=2, column=col, value=header)
    _style_header_row(sheet, 2, len(headers))
    # 数字格式示例列：预置 12 行数量/单价/金额/日期格式，用户直接填数即可。
    sample_first_row, sample_last_row = 3, 14
    for row in range(sample_first_row, sample_last_row + 1):
        sheet.cell(row=row, column=5).number_format = "0"
        sheet.cell(row=row, column=6).number_format = "#,##0.00"
        sheet.cell(row=row, column=7).number_format = "#,##0.00"
        sheet.cell(row=row, column=8).number_format = "yyyy-mm-dd"
    sheet.freeze_panes = "A3"
    _set_column_widths(sheet, [12.0, 20.0, 16.0, 8.0, 10.0, 12.0, 12.0, 14.0])
    return _save_builtin_file("inventory", workbook, "xlsx")


# ──────────────────────────────────────────────────────────────────────
# PPT builtin builders (round 3 — N2)
#
# python-pptx 默认模板 + Blank 版式 + 文本框几何（与 ppt.generate_ppt 的
# 缺省路径一致的几何常量），文本框内写 {{var}} 标记，实例化时由
# `_replace_pptx_markers` 遍历所有 text frame（含表格单元格与备注）替换。
# ──────────────────────────────────────────────────────────────────────

#: 与 ppt._TITLE_BOX_GEOMETRY / _BODY_BOX_GEOMETRY 一致（EMU，缺省 4:3 画布）。
_PPT_TITLE_BOX_GEOMETRY = (914400, 274638, 9144000, 1143000)
_PPT_BODY_BOX_GEOMETRY = (914400, 1600200, 9144000, 4572000)


def _ppt_textbox(
    slide,
    geometry: Tuple[int, int, int, int],
    lines: List[str],
    *,
    font_size: int,
    bold: bool = False,
) -> None:
    """在 slide 上加一个文本框，每行一段（生成器/编辑层同款语义）。"""
    from pptx.util import Pt

    box = slide.shapes.add_textbox(*geometry)
    frame = box.text_frame
    frame.word_wrap = True
    for index, line in enumerate(lines):
        paragraph = frame.paragraphs[0] if index == 0 else frame.add_paragraph()
        paragraph.text = line
        for run in paragraph.runs:
            run.font.size = Pt(font_size)
            run.font.bold = bold


def _build_kickoff_deck() -> Path:
    from pptx import Presentation

    prs = Presentation()
    blank_layout = prs.slide_layouts[6]

    # Slide 1 标题页：项目 / 汇报人 / 日期。
    title_slide = prs.slides.add_slide(blank_layout)
    _ppt_textbox(
        title_slide,
        _PPT_TITLE_BOX_GEOMETRY,
        ["{{project}} 项目启动会"],
        font_size=32,
        bold=True,
    )
    _ppt_textbox(
        title_slide,
        (914400, 1828800, 9144000, 1371600),
        ["汇报人：{{presenter}}", "日期：{{date}}"],
        font_size=16,
    )

    # Slide 2 议程：{{agenda_items}} 多行标记（一行一条议程）。
    agenda_slide = prs.slides.add_slide(blank_layout)
    _ppt_textbox(agenda_slide, _PPT_TITLE_BOX_GEOMETRY, ["会议议程"], font_size=24, bold=True)
    _ppt_textbox(agenda_slide, _PPT_BODY_BOX_GEOMETRY, ["{{agenda_items}}"], font_size=16)

    # Slide 3 角色分工：{{roles}} 多行标记。
    roles_slide = prs.slides.add_slide(blank_layout)
    _ppt_textbox(roles_slide, _PPT_TITLE_BOX_GEOMETRY, ["项目角色与分工"], font_size=24, bold=True)
    _ppt_textbox(roles_slide, _PPT_BODY_BOX_GEOMETRY, ["{{roles}}"], font_size=16)
    return _save_builtin_file("kickoff_deck", prs, "pptx")


def _build_weekly_sync() -> Path:
    from pptx import Presentation

    prs = Presentation()
    blank_layout = prs.slide_layouts[6]

    week_slide = prs.slides.add_slide(blank_layout)
    _ppt_textbox(
        week_slide, _PPT_TITLE_BOX_GEOMETRY, ["周例会（{{week}}）"], font_size=28, bold=True
    )
    _ppt_textbox(
        week_slide, _PPT_BODY_BOX_GEOMETRY, ["本周进展：", "{{done}}"], font_size=16
    )

    next_slide = prs.slides.add_slide(blank_layout)
    _ppt_textbox(next_slide, _PPT_TITLE_BOX_GEOMETRY, ["下周计划"], font_size=24, bold=True)
    _ppt_textbox(next_slide, _PPT_BODY_BOX_GEOMETRY, ["{{next}}"], font_size=16)

    risks_slide = prs.slides.add_slide(blank_layout)
    _ppt_textbox(risks_slide, _PPT_TITLE_BOX_GEOMETRY, ["风险与求助"], font_size=24, bold=True)
    _ppt_textbox(risks_slide, _PPT_BODY_BOX_GEOMETRY, ["{{risks}}"], font_size=16)
    return _save_builtin_file("weekly_sync", prs, "pptx")


BUILTIN_EXCEL_TEMPLATES: List[BuiltinTemplate] = [
    BuiltinTemplate(
        id="budget_sheet",
        name="预算表",
        description="概览 + 明细双表预算模板，含真实 =SUM 合计公式与表头样式。",
        doc_type=OfficeDocType.EXCEL,
        placeholders=[
            BuiltinPlaceholder("title", TemplatePlaceholderType.TEXT, "预算表标题"),
            BuiltinPlaceholder("owner", TemplatePlaceholderType.TEXT, "负责人"),
            BuiltinPlaceholder("period", TemplatePlaceholderType.TEXT, "预算周期，如 2026 年 Q3"),
            BuiltinPlaceholder("total", TemplatePlaceholderType.TEXT, "预算合计金额"),
            BuiltinPlaceholder("item1", TemplatePlaceholderType.TEXT, "明细第 1 行项目名"),
            BuiltinPlaceholder("item2", TemplatePlaceholderType.TEXT, "明细第 2 行项目名"),
            BuiltinPlaceholder("item3", TemplatePlaceholderType.TEXT, "明细第 3 行项目名"),
        ],
        build=_build_budget_sheet,
    ),
    BuiltinTemplate(
        id="inventory",
        name="库存台账",
        description="含仓库标题、冻结表头与数量/单价/金额数字格式示例列的库存台账。",
        doc_type=OfficeDocType.EXCEL,
        placeholders=[
            BuiltinPlaceholder("warehouse", TemplatePlaceholderType.TEXT, "仓库/台账名称"),
        ],
        build=_build_inventory,
    ),
]

BUILTIN_PPT_TEMPLATES: List[BuiltinTemplate] = [
    BuiltinTemplate(
        id="kickoff_deck",
        name="项目启动会",
        description="标题页 + 议程 + 角色分工的三页项目启动会演示模板。",
        doc_type=OfficeDocType.PPT,
        placeholders=[
            BuiltinPlaceholder("project", TemplatePlaceholderType.TEXT, "项目名称"),
            BuiltinPlaceholder("presenter", TemplatePlaceholderType.TEXT, "汇报人"),
            BuiltinPlaceholder("date", TemplatePlaceholderType.DATE, "会议日期"),
            BuiltinPlaceholder("agenda_items", TemplatePlaceholderType.RICH_TEXT, "议程，一行一条"),
            BuiltinPlaceholder("roles", TemplatePlaceholderType.RICH_TEXT, "角色分工，可多行"),
        ],
        build=_build_kickoff_deck,
    ),
    BuiltinTemplate(
        id="weekly_sync",
        name="周例会",
        description="周次 + 本周进展 / 下周计划 / 风险求助的周例会演示模板。",
        doc_type=OfficeDocType.PPT,
        placeholders=[
            BuiltinPlaceholder("week", TemplatePlaceholderType.TEXT, "周次，如 W37"),
            BuiltinPlaceholder("done", TemplatePlaceholderType.RICH_TEXT, "本周进展，可多行"),
            BuiltinPlaceholder("next", TemplatePlaceholderType.RICH_TEXT, "下周计划，可多行"),
            BuiltinPlaceholder("risks", TemplatePlaceholderType.RICH_TEXT, "风险与求助，可多行"),
        ],
        build=_build_weekly_sync,
    ),
]

#: 所有 builtin 模板（word + excel + ppt）— 列表与实例化的完整注册表。
#: ``BUILTIN_TEMPLATES`` 特意保持为 6 个 Word 模板（既有公开常量，测试与
#: 调用方依赖其 Word-only 行为），跨类型查找请用 ``ALL_BUILTIN_TEMPLATES``。
ALL_BUILTIN_TEMPLATES: List[BuiltinTemplate] = (
    BUILTIN_TEMPLATES + BUILTIN_EXCEL_TEMPLATES + BUILTIN_PPT_TEMPLATES
)

_BUILTIN_BY_ID: Dict[str, BuiltinTemplate] = {spec.id: spec for spec in ALL_BUILTIN_TEMPLATES}



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
        for spec in ALL_BUILTIN_TEMPLATES
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


def _marker_key(inner: str) -> str:
    """``{{ inner }}`` 的数据键：去空白并去掉 ``|`` 过滤器（{{a | upper}} → a）。

    与 word 扫描器 ``_extract_placeholders_from_text`` 的命名约定一致，保证
    同一个模板占位符在 word / excel / ppt 三种类型下都以同一个键填充。
    """
    key = inner.strip()
    if "|" in key:
        key = key.split("|", 1)[0].strip()
    return key


def _marker_substitution(data: Dict[str, Any]):
    """构建 MARKER_RE 的替换函数：命中 data 的标记替换为字符串值。"""

    def substitute(match: re.Match) -> str:
        key = _marker_key(match.group(1))
        if key in data:
            value = data[key]
            return "" if value is None else str(value)
        return match.group(0)

    return substitute


def _scan_xlsx_marker_names(path: Path) -> List[str]:
    """按行序收集 xlsx 所有字符串单元格里的标记名（公式单元格跳过）。"""
    from openpyxl import load_workbook

    names: List[str] = []
    try:
        workbook = load_workbook(str(path), read_only=True, data_only=True)
        try:
            for worksheet in workbook.worksheets:
                for row in worksheet.iter_rows():
                    for cell in row:
                        value = cell.value
                        if not isinstance(value, str) or value.startswith("="):
                            continue
                        for match in MARKER_RE.finditer(value):
                            names.append(_marker_key(match.group(1)))
        finally:
            workbook.close()
    except OfficeError:
        raise
    except Exception as exc:
        raise OfficeTemplateParseError(
            "Failed to parse xlsx template", file_path=path
        ) from exc
    return names


def _scan_pptx_marker_names(path: Path) -> List[str]:
    """收集 pptx 所有 text frame（含表格单元格与备注）里的标记名。"""
    from pptx import Presentation

    names: List[str] = []
    try:
        prs = Presentation(str(path))
        for frame in _iter_ppt_text_frames(prs):
            for paragraph in frame.paragraphs:
                for match in MARKER_RE.finditer(paragraph.text):
                    names.append(_marker_key(match.group(1)))
    except OfficeError:
        raise
    except Exception as exc:
        raise OfficeTemplateParseError(
            "Failed to parse pptx template", file_path=path
        ) from exc
    return names


def _marker_library_placeholders(names: List[str]) -> List[TemplateLibraryPlaceholder]:
    """去重（保序）后的标记占位符元数据；xlsx/ppt 扫描到的标记一律 TEXT。"""
    unique: List[str] = []
    seen: Set[str] = set()
    for name in names:
        if name and name not in seen:
            seen.add(name)
            unique.append(name)
    return [
        TemplateLibraryPlaceholder(name=name, type=TemplatePlaceholderType.TEXT)
        for name in unique
    ]


def _scan_workspace_templates(workspace: Path) -> List[TemplateLibraryEntry]:
    """Scan <workspace>/office/templates/*.{docx,xlsx,pptx}; skip broken files."""
    templates_dir = workspace / WORKSPACE_TEMPLATES_SUBDIR
    if not templates_dir.is_dir():
        return []
    entries: List[TemplateLibraryEntry] = []
    used_ids: set = set()
    scanners = (
        ("*.docx", OfficeDocType.WORD),
        ("*.xlsx", OfficeDocType.EXCEL),
        ("*.pptx", OfficeDocType.PPT),
    )
    for pattern, doc_type in scanners:
        for path in sorted(templates_dir.glob(pattern)):
            # Office 的 ~$ 锁文件不是模板；目录项也可能在扫描间隙变成非文件。
            if not path.is_file() or path.name.startswith("~$"):
                continue
            try:
                placeholders = _analyze_workspace_template(path, doc_type, workspace)
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
                    doc_type=doc_type,
                    placeholders=placeholders,
                    source="workspace",
                    filename=path.name,
                )
            )
    return entries


def _analyze_workspace_template(
    path: Path, doc_type: OfficeDocType, workspace: Path
) -> List[TemplateLibraryPlaceholder]:
    """Extract library placeholder metadata for one workspace template file."""
    if doc_type is OfficeDocType.WORD:
        analysis = analyze_word_template(path, workspace_path=str(workspace))
        return _entry_placeholders(analysis.placeholders)
    if doc_type is OfficeDocType.EXCEL:
        return _marker_library_placeholders(_scan_xlsx_marker_names(path))
    return _marker_library_placeholders(_scan_pptx_marker_names(path))


def list_templates(workspace_path: Optional[str] = None) -> TemplateLibraryResponse:
    """List builtin templates plus workspace user templates.

    ``workspace_path`` 缺省 / 不传时只返回 builtin；传入时校验 workspace
    （非法路径抛 OfficePathError）并扫描 ``office/templates/`` 下的
    ``.docx``/``.xlsx``/``.pptx``。
    """
    templates = _builtin_entries()
    if workspace_path:
        workspace = validate_workspace(Path(workspace_path))
        templates.extend(_scan_workspace_templates(workspace))
    return TemplateLibraryResponse(templates=templates)


# ──────────────────────────────────────────────────────────────────────
# instantiate_template
# ──────────────────────────────────────────────────────────────────────


def _resolve_builtin_template(template_id: str) -> Tuple[Path, OfficeDocType]:
    """Locate the cached source file for a builtin template (by id)."""
    if not TEMPLATE_ID_RE.match(template_id):
        raise OfficePathError(
            f"Invalid template id (must match {TEMPLATE_ID_RE.pattern}): {template_id!r}"
        )
    spec = _BUILTIN_BY_ID.get(template_id)
    if spec is None:
        raise OfficeFileNotFoundError(Path(template_id))
    return builtin_template_path(spec), spec.doc_type


def _resolve_workspace_template(
    workspace: Path, workspace_template: str
) -> Tuple[Path, OfficeDocType]:
    """Locate a workspace template file and derive its doc type.

    Extension → doc type (``.docx``/``.xlsx``/``.pptx``); an unsupported
    extension is rejected. Without any extension the legacy convenience
    behavior applies — the canonical extensions are tried in word/excel/ppt
    order and the first existing file wins (missing everywhere →
    ``OfficeFileNotFoundError`` for the ``.docx`` candidate, matching the
    pre-N2 behavior).
    """
    templates_dir = workspace / WORKSPACE_TEMPLATES_SUBDIR
    lowered = workspace_template.lower()
    for extension, doc_type in _TEMPLATE_EXTENSION_DOC_TYPES.items():
        if not lowered.endswith(extension):
            continue
        # validate_supported_filename: rejects separators/'..' and enforces the
        # extension matches the doc type; resolve_within then containment-checks
        # the resolved path inside office/templates/.
        safe_name = validate_supported_filename(workspace_template, doc_type)
        candidate = resolve_within(templates_dir, templates_dir / safe_name)
        if not candidate.is_file():
            raise OfficeFileNotFoundError(candidate)
        return candidate, doc_type
    if "." in workspace_template:
        raise OfficePathError(
            "Unsupported workspace template extension (expected .docx/.xlsx/.pptx): "
            f"{workspace_template!r}"
        )
    for extension, doc_type in _TEMPLATE_EXTENSION_DOC_TYPES.items():
        candidate = templates_dir / (workspace_template + extension)
        if candidate.is_file():
            return resolve_within(templates_dir, candidate), doc_type
    raise OfficeFileNotFoundError(templates_dir / (workspace_template + ".docx"))


def _resolve_source_template(
    workspace: Path,
    template_id: Optional[str],
    workspace_template: Optional[str],
) -> Tuple[Path, OfficeDocType]:
    """Locate the source template file (builtin id OR workspace file).

    Returns the source path together with the template's doc type, which
    decides the instantiation strategy (docxtpl fill vs. marker replace) and
    the managed output layout.
    """
    if template_id and workspace_template:
        raise OfficePathError(
            "template_id and workspace_template are mutually exclusive"
        )
    if template_id:
        return _resolve_builtin_template(template_id)
    if workspace_template:
        return _resolve_workspace_template(workspace, workspace_template)
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


# ──────────────────────────────────────────────────────────────────────
# xlsx/pptx instantiation — generic {{marker}} replace (round 3 — N2)
# ──────────────────────────────────────────────────────────────────────


def _iter_ppt_shapes(shapes):
    """Depth-first walk over a shape tree (recursing into group shapes)."""
    from pptx.enum.shapes import MSO_SHAPE_TYPE

    for shape in shapes:
        yield shape
        if shape.shape_type == MSO_SHAPE_TYPE.GROUP:
            yield from _iter_ppt_shapes(shape.shapes)


def _iter_ppt_text_frames(prs):
    """Every text frame in the presentation: shape frames, table cells, notes."""
    for slide in prs.slides:
        for shape in _iter_ppt_shapes(slide.shapes):
            if shape.has_text_frame:
                yield shape.text_frame
            if shape.has_table:
                for row in shape.table.rows:
                    for cell in row.cells:
                        yield cell.text_frame
        if slide.has_notes_slide:
            yield slide.notes_slide.notes_text_frame


def _set_paragraph_text(paragraph, text: str) -> None:
    """Overwrite a paragraph's text, keeping the first run's formatting."""
    runs = paragraph.runs
    if not runs:
        paragraph.text = text
        return
    runs[0].text = text
    for run in runs[1:]:
        run._r.getparent().remove(run._r)


def _replace_in_paragraph(text_frame, index: int, paragraph, data: Dict[str, Any]) -> int:
    """Replace data-keyed {{markers}} in one paragraph.

    Multiline values are materialized as additional paragraphs cloned from the
    marker paragraph (deepcopy keeps its paragraph + run formatting) because a
    literal ``\\n`` inside a run is not rendered as a line break by PowerPoint.

    Returns the number of extra paragraphs inserted (0 when nothing was
    replaced) so the caller can keep walking the frame by live index.
    """
    runs = paragraph.runs
    if not runs:
        return 0
    combined = "".join(run.text for run in runs)
    if not MARKER_RE.search(combined):
        return 0
    filled_here = any(
        _marker_key(match.group(1)) in data for match in MARKER_RE.finditer(combined)
    )
    if not filled_here:
        return 0
    new_text = MARKER_RE.sub(_marker_substitution(data), combined)
    lines = new_text.split("\n")
    _set_paragraph_text(paragraph, lines[0])
    anchor = paragraph._p
    for _ in lines[1:]:
        clone = copy.deepcopy(paragraph._p)
        anchor.addnext(clone)
        anchor = clone
    fresh_paragraphs = text_frame.paragraphs
    for offset, line in enumerate(lines[1:], start=1):
        _set_paragraph_text(fresh_paragraphs[index + offset], line)
    return len(lines) - 1


def _replace_pptx_markers(source: Path, output: Path, data: Dict[str, Any]) -> Set[str]:
    """Fill {{markers}} across a presentation; return unique marker names found.

    The source file is opened read-only and saved to ``output`` — the workspace
    template itself is never modified.
    """
    from pptx import Presentation

    try:
        prs = Presentation(str(source))
        frames = list(_iter_ppt_text_frames(prs))
        # 先扫一遍源文件收集全部标记名（filled_count/unfilled 的口径与 word
        # 路径一致：基于模板里实际出现的唯一标记名，而非替换发生次数）。
        found: Set[str] = set()
        for frame in frames:
            for paragraph in frame.paragraphs:
                for match in MARKER_RE.finditer(paragraph.text):
                    found.add(_marker_key(match.group(1)))
        for frame in frames:
            # 按活索引逐段推进：多行值会克隆出新段落，快照索引会漂移。
            para_index = 0
            while para_index < len(frame.paragraphs):
                paragraph = frame.paragraphs[para_index]
                inserted = _replace_in_paragraph(frame, para_index, paragraph, data)
                para_index += 1 + inserted
        prs.save(str(output))
    except OfficeError:
        raise
    except Exception as exc:
        raise OfficeTemplateFillError(
            "Template fill failed", file_path=source
        ) from exc
    return found


def _replace_xlsx_markers(source: Path, output: Path, data: Dict[str, Any]) -> Set[str]:
    """Fill {{markers}} across a workbook; return unique marker names found.

    Formula cells (value starting with ``=``) are skipped so real formulas —
    e.g. the budget template's ``=SUM(C2:C4)`` — survive instantiation intact.
    Non-string cells are skipped naturally. openpyxl round-trips keep common
    formatting (styles / widths / freeze panes / number formats / formulas).
    """
    from openpyxl import load_workbook

    try:
        workbook = load_workbook(str(source))
        found: Set[str] = set()
        for worksheet in workbook.worksheets:
            for row in worksheet.iter_rows():
                for cell in row:
                    value = cell.value
                    if not isinstance(value, str) or value.startswith("="):
                        continue
                    for match in MARKER_RE.finditer(value):
                        found.add(_marker_key(match.group(1)))
        substitute = _marker_substitution(data)
        for worksheet in workbook.worksheets:
            for row in worksheet.iter_rows():
                for cell in row:
                    value = cell.value
                    if not isinstance(value, str) or value.startswith("="):
                        continue
                    if not MARKER_RE.search(value):
                        continue
                    cell.value = MARKER_RE.sub(substitute, value)
        workbook.save(str(output))
    except OfficeError:
        raise
    except Exception as exc:
        raise OfficeTemplateFillError(
            "Template fill failed", file_path=source
        ) from exc
    return found


def _instantiate_marker_template(
    workspace: Path,
    source_template: Path,
    doc_type: OfficeDocType,
    filename: str,
    data: Dict[str, Any],
) -> WordTemplateFillResult:
    """Instantiate an xlsx/pptx template via marker replace into the managed layout.

    Mirrors the word path's guarantees: the output lands in
    ``<workspace>/office/<doc_type>/<uuid>/<filename>`` (a fresh per-document
    directory), any failure removes the directory again, and the result is
    ``WordTemplateFillResult``-compatible so the existing instantiate route
    works unchanged.
    """
    output_name = validate_supported_filename(filename, doc_type)
    try:
        source_size = source_template.stat().st_size
    except OSError as exc:
        raise OfficeTemplateFillError(
            f"Template source is unavailable: {exc}", file_path=source_template
        ) from exc
    if source_size > MAX_TEMPLATE_SOURCE_BYTES:
        raise OfficeSizeLimitError(
            source_size, MAX_TEMPLATE_SOURCE_BYTES, file_path=source_template
        )

    doc_id = uuid.uuid4().hex
    managed_dir = generate_document_dir(workspace, doc_type, doc_id)
    output = managed_dir / output_name
    try:
        if doc_type is OfficeDocType.EXCEL:
            found = _replace_xlsx_markers(source_template, output, data)
        else:
            found = _replace_pptx_markers(source_template, output, data)
    except Exception:
        # 失败不留半成品：清掉整个新 managed 目录。
        shutil.rmtree(managed_dir, ignore_errors=True)
        raise
    unfilled = sorted(name for name in found if name not in data)
    return WordTemplateFillResult(
        output_path=str(output),
        filename=output_name,
        file_size_bytes=output.stat().st_size,
        filled_count=len(found) - len(unfilled),
        unfilled_placeholders=unfilled,
    )


def instantiate_template(
    workspace_path: str,
    template_id: Optional[str] = None,
    workspace_template: Optional[str] = None,
    filename: str = "",
    data: Optional[Dict[str, Any]] = None,
    images: Optional[Dict[str, str]] = None,
) -> WordTemplateFillResult:
    """Instantiate a library template into the managed layout for its doc type.

    word → the source docx (builtin cache file or workspace template) is copied
    into a fresh ``<workspace>/office/word/<uuid>/`` directory and filled via
    :func:`word_template.fill_word_template` — the exact same safety machinery
    as ``POST /office/word/fill-template`` (ZIP guards, dangerous-Jinja scan,
    SandboxedEnvironment, ≤10MB images, output-filename checks), so no safety
    logic is duplicated here.

    excel/ppt → the builtin (built lazily) or workspace file is opened
    read-only, every ``{{marker}}`` is replaced with its data value, and the
    result is saved into ``office/excel|ppt/<uuid>/<filename>`` (see
    :func:`_instantiate_marker_template`).

    On any failure the managed directory is removed again; on success the word
    path's intermediate source copy is deleted, leaving only the filled
    document. Returns the full ``WordTemplateFillResult`` (output_path /
    filled_count / unfilled_placeholders) so the route can persist the row and
    echo the standard fill response.
    """
    workspace = validate_workspace(Path(workspace_path))
    source_template, doc_type = _resolve_source_template(
        workspace, template_id, workspace_template
    )
    if not filename:
        raise OfficePathError("filename is required")
    _validate_data_caps(data)

    if doc_type is not OfficeDocType.WORD:
        return _instantiate_marker_template(
            workspace, source_template, doc_type, filename, dict(data or {})
        )

    output_name = validate_supported_filename(filename, OfficeDocType.WORD)
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
