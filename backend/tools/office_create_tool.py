"""Office create tool for the LLM tool loop.

``office_create`` lets the LLM generate a Word / Excel / PPT document to an
arbitrary (trusted) target directory -- e.g. the user's Desktop. Unlike the
existing ``office_list`` / ``office_read`` (which need an @-mention to bind a
``ToolExecutionContext``), ``requires_tool_context = False`` so the tool is
always visible and a plain question ("create a word doc on my desktop") can
trigger it directly.

Writing outside the session workspace is gated by two complementary layers:
(1) ``path_boundary_validator`` in the M1 ``PermissionEnforcer`` (see
permissions.py) upgrades a cross-workspace write to approval in the legacy
agent chain; (2) ``BaseTool._enforce_workspace`` in ``execute()`` rejects the
write outright when ``policy.workspace_root`` is bound (the hex chain).

Plan 3.4 self-check readback: on success the result carries
``content["self_check"]`` — a compact read-back of the produced file
(paragraph/table/image counts, sheet names + row/col counts, slide count)
so the model can immediately verify intent. Read-back is best-effort: a
failure degrades to ``{ok: False, error}`` without failing the tool result.
"""

from __future__ import annotations

import json as _json
import sqlite3
from pathlib import Path
from typing import Any, Dict, Optional

from backend.data.database import get_database
from backend.domain.risk import RiskClass
from backend.office.excel import generate_xlsx, read_xlsx
from backend.office.markdown_to_paragraphs import parse_markdown_to_paragraphs
from backend.office.models import (
    OfficeDocType,
    OfficeExcelGenerateRequest,
    OfficePptGenerateRequest,
    OfficeWordGenerateRequest,
)
from backend.office.path_safety import OfficePathError, validate_supported_filename
from backend.office.ppt import generate_ppt, read_ppt
from backend.office.session_workspace import (
    get_active_workspace,
    get_document_in_workspace,
)
from backend.office.storage import document_path
from backend.office.tool_service import OfficeToolService
from backend.office.word import generate_docx, read_docx
from backend.tools.base import BaseTool, ToolResult, ToolSchema
from backend.tools.context import current_tool_context
from backend.tools.file_tool import _record_artifact_safely

#: doc_type 参数合法取值（与 models.OfficeDocType 对齐）
_VALID_DOC_TYPES = tuple(t.value for t in OfficeDocType)


def _check_content(content: Any) -> Optional[ToolResult]:
    """校验 content：非空 dict 或非空字符串（字符串由 ``_normalize_content``
    包装为 word 段落）。拆开 isinstance 避免 UP038（union 语法 3.10+）。"""
    if content is None:
        return ToolResult(success=False, error="content_required")
    if isinstance(content, str):
        if not content.strip():
            return ToolResult(success=False, error="content_required")
        return None
    if not isinstance(content, dict) or not content:
        return ToolResult(success=False, error="content_required")
    return None


# ──────────────────────────────────────────────────────────────────────
# Self-check readback（plan 3.4 tractable subset）
#
# 生成/编辑成功后用 office readers 回读产物，把紧凑事实（段落/表格/图片
# 计数、sheet 名与行列数、页数等）作为 ``content["self_check"]`` 附到
# 工具结果，让 LLM 在下一轮立即核对意图（页数/段数是否相符），无需再
# 手动调 office_read —— 闭合「写入 → 验证」反馈环。
#
# 回读是 best-effort：任何失败折叠为 ``{ok: False, error}``，主结果保持
# success（镜像 snapshot 的 best-effort 语义）；error 只带异常类名不带
# 消息，避免把绝对路径回显进 LLM 上下文。
# ──────────────────────────────────────────────────────────────────────

#: excel 摘要最多列出的 sheet 数（超出部分只计 sheet_count）
_SELF_CHECK_SHEET_CAP = 5
#: 首段文本 / 首页标题的截断长度（self_check 摘要恒 < 1KB 的字节预算）
_SELF_CHECK_TEXT_CAP = 80


def _requests_formula_strings(value: Any) -> bool:
    """递归检测请求内容里是否有以 ``=`` 开头的字符串（excel 公式请求）。

    入参只会是工具参数（JSON 形态：dict/list/str/标量），无需处理 tuple
    （避免 UP038 tuple-isinstance 与 SIM101 合并规则两头堵）。
    """
    if isinstance(value, str):
        return value.startswith("=")
    if isinstance(value, dict):
        return any(_requests_formula_strings(v) for v in value.values())
    if isinstance(value, list):
        return any(_requests_formula_strings(v) for v in value)
    return False


def _word_self_check_summary(path: Path) -> Dict[str, Any]:
    parsed = read_docx(path, workspace_path="")
    first_text = ""
    for para in parsed.paragraphs:
        if para.text.strip():
            first_text = para.text.strip()[:_SELF_CHECK_TEXT_CAP]
            break
    return {
        "paragraph_count": len(parsed.paragraphs),
        "table_count": len(parsed.tables),
        "image_count": parsed.images,
        "first_paragraph": first_text,
    }


def _excel_self_check_summary(path: Path, *, requested: Any) -> Dict[str, Any]:
    want_formulas = _requests_formula_strings(requested)
    parsed = read_xlsx(path, workspace_path="", include_formulas=want_formulas)
    summary: Dict[str, Any] = {
        "sheet_count": len(parsed.sheets),
        "sheets": [
            {"name": sheet.name, "rows": sheet.max_row, "cols": sheet.max_col}
            for sheet in parsed.sheets[:_SELF_CHECK_SHEET_CAP]
        ],
    }
    if want_formulas:
        summary["formula_cell_count"] = sum(
            len(sheet.formulas or []) for sheet in parsed.sheets
        )
    return summary


def _ppt_self_check_summary(path: Path) -> Dict[str, Any]:
    parsed = read_ppt(path, workspace_path="")
    first_title: Optional[str] = None
    if parsed.slides:
        first_title = parsed.slides[0].title
        if first_title is not None:
            first_title = first_title[:_SELF_CHECK_TEXT_CAP]
    return {"slide_count": len(parsed.slides), "first_slide_title": first_title}


def build_self_check(
    doc_type: str,
    path: Path,
    *,
    requested: Any = None,
    page_count: Optional[int] = None,
) -> Dict[str, Any]:
    """成功写入后回读产物的紧凑摘要（office_create / office_update 共用）。

    Args:
        doc_type: ``OfficeDocType`` 取值（word/excel/ppt/pdf）。
        path: 生成/编辑后的文件路径。
        requested: 原始请求内容（create 的 content / update 的 ops），
            仅用于探测 excel 公式请求（是否存在 ``=`` 开头字符串）。
        page_count: pdf 专用——生成结果自带的页数（reportlab 落地时已知，
            不为回读单独拉起 pymupdf 重依赖）；缺失则回读失败。

    Returns:
        ``{"ok": True, "summary": {...}}``，summary 按 doc_type：
        word → paragraph_count / table_count / image_count / first_paragraph
        （首个非空段，≤80 字符）；excel → sheet_count / sheets[{name, rows,
        cols}]（cap 5）/ formula_cell_count（请求含公式时）；ppt →
        slide_count / first_slide_title；pdf → page_count。
        回读失败 → ``{"ok": False, "error": "readback_failed: <ExcType>"}``
        （只带异常类名，防绝对路径泄漏）。本函数绝不抛出、绝不令主结果
        失败；summary 恒 < 1KB。
    """
    try:
        if doc_type == OfficeDocType.WORD.value:
            summary = _word_self_check_summary(path)
        elif doc_type == OfficeDocType.EXCEL.value:
            summary = _excel_self_check_summary(path, requested=requested)
        elif doc_type == OfficeDocType.PPT.value:
            summary = _ppt_self_check_summary(path)
        elif doc_type == OfficeDocType.PDF.value:
            if page_count is None:
                raise ValueError("page_count not provided by generate result")
            summary: Dict[str, Any] = {"page_count": page_count}
        else:
            raise ValueError(f"unsupported doc_type: {doc_type}")
    except Exception as exc:  # noqa: BLE001 — best-effort 回读，失败不阻断主结果
        return {"ok": False, "error": f"readback_failed: {type(exc).__name__}"}
    return {"ok": True, "summary": summary}


def managed_self_check(
    conn: sqlite3.Connection,
    workspace_path: str,
    doc_id: str,
    doc_type: str,
) -> Optional[Dict[str, Any]]:
    """受管文档（doc_id / binding 模式）的 self_check 回读。

    与 ``OfficeToolService._resolve_doc`` 同构地解析 on-disk 路径
    （``get_document_in_workspace`` 按 ``(id, workspace_path, 未归档)``
    收窄），命中后走 :func:`build_self_check`。doc 未知 / 归档 / 跨工作区 /
    DB 异常 → ``None``（调用方保持原 content，不附加 self_check 键）。
    """
    try:
        doc = get_document_in_workspace(conn, doc_id, workspace_path)
    except Exception:  # noqa: BLE001 — DB 层异常按「无法回读」折叠
        return None
    if doc is None:
        return None
    return build_self_check(doc_type, document_path(doc))


class OfficeCreateTool(BaseTool):
    """Generate an Office document (word/excel/ppt) to a target directory."""

    requires_tool_context = False
    risk = RiskClass.WRITE_LOCAL

    def _build_schema(self) -> ToolSchema:
        return ToolSchema(
            name="office_create",
            description=(
                "Create a new Office document (Word/Excel/PPT) and write it to "
                "a target directory. Use when the user asks to create / generate "
                "a .docx/.xlsx/.pptx file (e.g. on their Desktop). `content` is "
                "an object whose shape depends on `doc_type`: word → "
                "{title, paragraphs:[{text, heading?, font_size?, bold?, "
                "italic?, color?, align?}], tables:[{headers, rows[]}], "
                "images?:[{source, width_inches?, height_inches?}]}, excel → "
                "{sheets:[{name, headers[], rows[], column_widths?}], "
                "charts?:[{sheet?, type, anchor, data_ref, title?}]}, ppt → "
                "{slides:[{title, bullets[], notes?, layout?, image?}]}."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "doc_type": {
                        "type": "string",
                        "enum": list(_VALID_DOC_TYPES),
                        "description": (
                            "Document type (case-insensitive: word/Word/WORD "
                            "are all accepted)."
                        ),
                    },
                    "output_dir": {
                        "type": "string",
                        "description": (
                            "Target directory — ABSOLUTE path or ~-prefixed "
                            "(e.g. /home/user/Desktop or ~/Desktop). Do NOT use "
                            "a bare relative name like '桌面'. Created if missing."
                        ),
                    },
                    "filename": {
                        "type": "string",
                        "description": (
                            "Output filename. Extension is appended if missing "
                            "(.docx/.xlsx/.pptx); a wrong extension is rejected."
                        ),
                    },
                    "font_family": {
                        "type": "string",
                        "description": (
                            "中文字体名（如'宋体'/'微软雅黑'/'等线'）。"
                            "不传则默认宋体。"
                        ),
                    },
                    "content": {
                        "type": "object",
                        "description": (
                            "Structured content as a JSON object, keyed by "
                            "doc_type: word → {title, paragraphs:[{text, "
                            "heading?, font_size?, bold?, italic?, color?, "
                            "align?}], tables:[{headers, rows[]}], images?:"
                            "[{source, width_inches?, height_inches?}]}; "
                            "excel → {sheets:[{name, headers[], rows[], "
                            "column_widths?}], charts?:[{sheet?, type, anchor, "
                            "data_ref, title?}]}; ppt → {slides:[{title, "
                            "bullets[], notes?, layout?, image?}]}. A plain "
                            "string is also accepted for word (treated as body "
                            "text). excel 与 ppt 必须传对象（分别含 sheets / "
                            "slides），只有 word 接受纯字符串。"
                        ),
                        "properties": {
                            "title": {
                                "type": "string",
                                "description": "word 文档标题。",
                            },
                            "paragraphs": {
                                "type": "array",
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "text": {"type": "string"},
                                        "heading": {
                                            "type": ["string", "null"],
                                            "description": "'h1'/'h2'/'h3' 或 null",
                                        },
                                        "font_size": {
                                            "type": "number",
                                            "description": "段落字号（磅），如 12",
                                        },
                                        "bold": {"type": "boolean"},
                                        "italic": {"type": "boolean"},
                                        "color": {
                                            "type": "string",
                                            "description": "字体颜色 6 位 RGB hex（如 'FF0000'）",
                                        },
                                        "align": {
                                            "type": "string",
                                            "enum": ["left", "center", "right", "justify"],
                                        },
                                    },
                                    "required": ["text"],
                                },
                                "description": "word 段落列表（可选段落级样式）。",
                            },
                            "images": {
                                "type": "array",
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "source": {
                                            "type": "string",
                                            "description": (
                                                "图片来源：工作区图片路径或 "
                                                "data:image/... base64（≤10MB）"
                                            ),
                                        },
                                        "width_inches": {"type": "number"},
                                        "height_inches": {"type": "number"},
                                    },
                                    "required": ["source"],
                                },
                                "description": (
                                    "word 插图列表，按顺序追加在正文之后（批次2）。"
                                ),
                            },
                            "tables": {
                                "type": "array",
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "headers": {
                                            "type": "array",
                                            "items": {"type": "string"},
                                        },
                                        "rows": {
                                            "type": "array",
                                            "items": {
                                                "type": "array",
                                                "items": {"type": "string"},
                                            },
                                        },
                                    },
                                },
                                "description": "word 表格列表。",
                            },
                            "sheets": {
                                "type": "array",
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "name": {"type": "string"},
                                        "headers": {
                                            "type": "array",
                                            "items": {"type": "string"},
                                        },
                                        "rows": {
                                            "type": "array",
                                            "items": {
                                                "type": "array",
                                                "items": {"type": "string"},
                                            },
                                        },
                                        "column_widths": {
                                            "type": "array",
                                            "items": {"type": "number"},
                                            "description": (
                                                "各列列宽（index 0 = A 列），如 [20, 12, 30]"
                                            ),
                                        },
                                    },
                                },
                                "description": "excel 工作表列表。",
                            },
                            "charts": {
                                "type": "array",
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "sheet": {
                                            "type": "string",
                                            "description": "目标 sheet 名，缺省第一个 sheet",
                                        },
                                        "type": {
                                            "type": "string",
                                            "enum": ["line", "bar", "pie"],
                                        },
                                        "anchor": {
                                            "type": "string",
                                            "description": "左上角锚点单元格，如 'A10'",
                                        },
                                        "data_ref": {
                                            "type": "object",
                                            "properties": {
                                                "min_col": {"type": "integer"},
                                                "min_row": {"type": "integer"},
                                                "max_col": {"type": "integer"},
                                                "max_row": {"type": "integer"},
                                            },
                                            "required": [
                                                "min_col",
                                                "min_row",
                                                "max_col",
                                                "max_row",
                                            ],
                                            "description": "图表数据矩形（1-based，含端点）",
                                        },
                                        "titles_from_data": {"type": "boolean"},
                                        "from_rows": {"type": "boolean"},
                                        "title": {"type": "string"},
                                    },
                                    "required": ["type", "anchor", "data_ref"],
                                },
                                "description": (
                                    "excel 原生图表列表（Excel 打开可见、可再编辑；批次2）。"
                                ),
                            },
                            "slides": {
                                "type": "array",
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "title": {"type": "string"},
                                        "bullets": {
                                            "type": "array",
                                            "items": {"type": "string"},
                                        },
                                        "notes": {"type": "string"},
                                        "layout": {
                                            "type": "string",
                                            "enum": ["title", "title_content", "blank"],
                                            "description": (
                                                "版式；不传时用 Blank + 文本框（默认行为）"
                                            ),
                                        },
                                        "image": {
                                            "type": "object",
                                            "properties": {
                                                "source": {
                                                    "type": "string",
                                                    "description": (
                                                        "图片路径或 data:image/... base64（≤10MB）"
                                                    ),
                                                },
                                                "width_inches": {"type": "number"},
                                                "height_inches": {"type": "number"},
                                            },
                                            "required": ["source"],
                                            "description": "该页插图（批次2）",
                                        },
                                    },
                                    "required": ["title"],
                                },
                                "description": "ppt 幻灯片列表。",
                            },
                        },
                    },
                },
                "required": ["doc_type", "output_dir", "filename", "content"],
            },
        )

    def execute(
        self,
        doc_type: Optional[str] = None,
        output_dir: Optional[str] = None,
        filename: Optional[str] = None,
        content: Optional[Dict[str, Any]] = None,
        font_family: Optional[str] = None,
        **kwargs: Any,
    ) -> ToolResult:
        # doc_type 大小写容错（T6 实测模型传 "Word"）：归一化后再校验。
        if isinstance(doc_type, str):
            doc_type = doc_type.lower()
        error = self._check_params(doc_type, output_dir, filename, content)
        if error is not None:
            return error

        # ---- T7.5: binding-aware delegation -----------------------------
        # When the agent loop is running under a session-workspace binding
        # (``@workspace foo`` in the chat) we MUST route through
        # ``OfficeToolService.create`` so the doc is registered in
        # ``office_documents`` -- otherwise list/read can't see it (the
        # round-trip bug T7.5 fixes).
        delegated = self._try_delegate_to_bound_service(
            doc_type=doc_type, filename=filename, content=content
        )
        if delegated is not None:
            return delegated

        doc_type_enum = OfficeDocType(doc_type)
        target_dir = Path(output_dir).expanduser().resolve()
        error = self._check_path(output_dir, filename, doc_type_enum, target_dir)
        if error is not None:
            return error
        content = self._normalize_content(doc_type_enum, filename, content)
        if content is None:
            return ToolResult(success=False, error="content_required")
        return self._generate_document(
            doc_type_enum, filename, content, target_dir,
            font_family=font_family,
        )

    @staticmethod
    def _try_delegate_to_bound_service(
        *,
        doc_type: str,
        filename: str,
        content: Any,
    ) -> Optional[ToolResult]:
        """Route to OfficeToolService.create when an active binding exists.

        Returns:
            * ``None`` when there is no live binding (caller falls through
              to the legacy ``output_dir`` flow).
            * A :class:`ToolResult` carrying the service's ``{document_id,
              doc_type, filename}`` payload when delegation succeeds.
            * A failure :class:`ToolResult` if the service returns an
              error (e.g. stale generation, generation failure).
        """
        ctx = current_tool_context()
        if ctx is None or not ctx.session_id:
            return None
        try:
            db = get_database()
            conn = db.get_connection()
        except Exception:
            # No DB configured (e.g. legacy caller) -> fall through to
            # legacy ``output_dir`` path so plain "create on Desktop"
            # requests still work.
            return None
        binding = get_active_workspace(
            conn, ctx.session_id, expected_generation=ctx.binding_generation
        )
        if binding is None:
            return None

        service = OfficeToolService()
        result = service.create(
            conn,
            ctx.session_id,
            ctx.binding_generation,
            doc_type=doc_type,
            filename=filename,
            content=content,
        )
        if not result.get("success"):
            err = result.get("error") or {}
            return ToolResult(
                success=False,
                error=str(err.get("code") or "create_failed"),
            )
        # plan 3.4 自校验回读：受管文档同样回读摘要（解析失败→不加键，
        # 保持原 handle trio 形状不变）。self_check 只含计数事实，不含
        # workspace_path，维持「不回显受管绝对路径」不变式。
        content = dict(result["content"])
        doc_id = content.get("document_id")
        doc_type_value = content.get("doc_type")
        if isinstance(doc_id, str) and isinstance(doc_type_value, str):
            self_check = managed_self_check(
                conn, binding.workspace_path, doc_id, doc_type_value
            )
            if self_check is not None:
                content["self_check"] = self_check
        return ToolResult(success=True, content=content)

    @staticmethod
    def _normalize_content(
        doc_type_enum: OfficeDocType,
        filename: str,
        content: Any,
    ) -> Optional[Dict[str, Any]]:
        """把 LLM 的 content 输入归一化为结构化 dict。

        四层兜底（仅 WORD；excel/ppt 保持严格）：
        1. dict → 直接返回（结构化输入路径）
        2. str + json.loads 成功 + 是 dict → 返回解析结果（修"内容显示不全"bug）
        3. str + json.loads 失败 + markdown 有结构（多段 / heading / style）→ 解析
        4. str 但 markdown 无结构 → 纯文本单段落（兜底，保持原有行为）
        """
        if isinstance(content, dict):
            return content
        if not isinstance(content, str) or not content.strip():
            return None

        if doc_type_enum is not OfficeDocType.WORD:
            # excel/ppt 仍要求 dict，不做 markdown 猜测
            return None

        # ── 第 2 层：尝试 JSON 解析 ──
        try:
            parsed = _json.loads(content)
            if isinstance(parsed, dict):
                return parsed
        except (ValueError, _json.JSONDecodeError):
            pass

        # ── 第 3 层：markdown 解析（仅当有结构时才采用 markdown 形式） ──
        parsed_md = parse_markdown_to_paragraphs(content.strip())
        if parsed_md and (
            len(parsed_md) > 1
            or any(p.get("heading") or p.get("style") for p in parsed_md)
        ):
            title = Path(filename).stem or "文档"
            return {"title": title, "paragraphs": parsed_md}

        # ── 第 4 层：纯文本兜底（单段无结构 → 保持原有用法） ──
        title = Path(filename).stem or "文档"
        return {"title": title, "paragraphs": [{"text": content.strip()}]}

    @staticmethod
    def _check_params(
        doc_type: Optional[str],
        output_dir: Optional[str],
        filename: Optional[str],
        content: Optional[Dict[str, Any]],
    ) -> Optional[ToolResult]:
        """fail-fast 参数校验；返回错误 ToolResult 或 None（通过）。"""
        if doc_type not in _VALID_DOC_TYPES:
            return ToolResult(success=False, error=f"unsupported_doc_type: {doc_type}")
        if not isinstance(output_dir, str) or not output_dir.strip():
            return ToolResult(success=False, error="output_dir_required")
        # 相对路径（非绝对、非 ~ 开头）拒绝——避免静默 resolve 到 cwd 而非
        # 用户真实目录（T6 实测 LLM 传 "Desktop" 落到 <cwd>/Desktop）。
        if not Path(output_dir).is_absolute() and not output_dir.startswith("~"):
            return ToolResult(
                success=False,
                error=(
                    "output_dir_relative: 请用绝对路径或以 ~ 开头"
                    f"（如 ~/Desktop），而非 {output_dir!r}"
                ),
            )
        if not isinstance(filename, str) or not filename.strip():
            return ToolResult(success=False, error="filename_required")
        return _check_content(content)

    def _check_path(
        self,
        output_dir: str,
        filename: str,
        doc_type_enum: OfficeDocType,
        target_dir: Path,
    ) -> Optional[ToolResult]:
        """工作区边界 + 路径守卫；返回错误 ToolResult 或 None（通过）。

        - 工作区边界：``policy.workspace_root`` 绑定（hex 链）时拒绝越界写入；
          未绑定（legacy 链）时 ``_enforce_workspace`` 返回 None，零行为变化。
        - 目录必须是目录；目标文件已存在则拒绝（不覆盖）。
        """
        blocked = self._enforce_workspace(output_dir)
        if blocked is not None:
            return blocked
        if target_dir.exists() and not target_dir.is_dir():
            return ToolResult(success=False, error="output_dir_not_directory")
        try:
            safe_name = validate_supported_filename(filename, doc_type_enum)
        except OfficePathError as exc:
            return ToolResult(success=False, error=str(exc))
        target_file = target_dir / safe_name
        if target_file.exists():
            return ToolResult(
                success=False,
                error=f"file_exists: {target_file} 已存在，请更换文件名",
            )
        return None

    def _generate_document(
        self,
        doc_type_enum: OfficeDocType,
        filename: str,
        content: Dict[str, Any],
        target_dir: Path,
        font_family: Optional[str] = None,
    ) -> ToolResult:
        """构造生成请求并执行（复用生成器 + Pydantic 校验），返回结果。"""
        payload: Dict[str, Any] = dict(content)
        payload["workspace_path"] = ""
        payload["filename"] = filename
        try:
            if doc_type_enum is OfficeDocType.WORD:
                req = OfficeWordGenerateRequest(**payload)
                if font_family:
                    req = req.model_copy(update={"font_family": font_family})
                output = generate_docx(req, output_dir=str(target_dir))
            elif doc_type_enum is OfficeDocType.EXCEL:
                req = OfficeExcelGenerateRequest(**payload)
                output = generate_xlsx(req, output_dir=str(target_dir))
            else:
                req = OfficePptGenerateRequest(**payload)
                output = generate_ppt(req, output_dir=str(target_dir))
        except Exception as exc:
            return ToolResult(success=False, error=f"generate_failed: {exc}")

        stat = output.stat()

        # --- 记录 Artifacts（无 tool_context 时静默跳过，不阻断结果） ------
        # ``_record_artifact_safely`` 内部已吞掉一切异常，无需再包一层。
        _record_artifact_safely(str(output), stat.st_size)

        # --- plan 3.4 自校验回读：紧凑摘要附到结果（best-effort） --------
        result_content: Dict[str, Any] = {
            "path": str(output),
            "filename": output.name,
            "bytes": stat.st_size,
        }
        result_content["self_check"] = build_self_check(
            doc_type_enum.value, output, requested=content
        )
        return ToolResult(success=True, content=result_content)


__all__ = ["OfficeCreateTool"]
