"""@ mention → office digest → LLM context block 解析器。

M1: 单文档 `@foo.pptx` 等自动注入 pptx/docx/xlsx/pdf 摘要到 system prompt。
M2: 多文档按出现顺序拼接, 块首 `=== name ===` 分隔。

设计 (per spec §3.2):
- 纯函数模块, 无 FastAPI / DB 依赖
- 复用 `backend.office.{ppt,word,excel,pdf}` 的 read_ppt/read_docx/read_xlsx/read_pdf 纯函数
- digest 有每文件字节预算 (MAX_ATTACHMENT_DIGEST_BYTES): word 保 heading/表格全量
  截正文段, excel 自适应行数 + 数值列统计, pdf 按页预览, 超出部分显式标注截断
- 失败降级: 单个 mention 抛 OfficeError 时静默 skip + log warning (不污染整块)
- 与现有 office_ppt_read / office_word_read / office_excel_read IPC endpoint 不同:
  * 不触发 _persist_read_summary (即不写 DB)
  * 不做 size validation (chat 信任 digest 输出)

Win7 兼容: 无 walrus, 无 PEP 604 union, str 类型注解仅在必须时用 (Python 3.8 兼容)。
"""

from __future__ import annotations

import logging
import math
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import FrozenSet, List, Optional

# Task 2: 真实 digest 格式化器 (复用 office 纯函数, 不触发 FastAPI endpoint)
from backend.office.errors import OfficeError, OfficePathError, OfficeSizeLimitError
from backend.office.excel import read_xlsx
from backend.office.path_safety import resolve_within
from backend.office.pdf import read_pdf
from backend.office.ppt import read_ppt
from backend.office.storage import validate_workspace
from backend.office.word import read_docx


def _digest_ppt(file_path: str, workspace: str) -> str:
    """Return per-slide digest: '[title]\\n  - bullet' each."""
    result = read_ppt(
        file_path=Path(file_path),
        workspace_path=workspace,
        generated_filename=os.path.basename(file_path),
    )
    lines: List[str] = []
    for slide in result.slides:
        title = slide.title or "(untitled)"
        lines.append(f"[{title}]")
        for block in slide.text_blocks:
            lines.append(f"  - {block}")
    return "\n".join(lines)


def _render_word_paragraphs(paragraphs) -> List[str]:
    """段落流 → markdown 行: heading 映射 #/##/###, 列表映射 - / 1., 其余全段原样。

    编号列表的序号按连续出现次序重排 (python-docx 拿不到真实编号), 遇到
    非 List Number 段落即复位。
    """
    lines: List[str] = []
    number = 0
    for para in paragraphs:
        text = para.text.strip()
        if not text:
            continue
        style = para.style or ""
        if para.level > 0:
            lines.append("#" * min(para.level, 6) + " " + text)
            number = 0
        elif "List Number" in style:
            number += 1
            lines.append(f"{number}. {text}")
        elif "List" in style:  # List Bullet / List Paragraph 等
            lines.append(f"- {text}")
            number = 0
        else:
            lines.append(text)
            number = 0
    return lines


def _render_word_table(rows) -> List[str]:
    """表格 → GFM markdown 表 (首行作表头, 竖线转义, 单元格内换行压成空格)。"""
    if not rows:
        return []
    width = max(len(r) for r in rows)

    def _cell(value: str) -> str:
        return str(value).replace("\n", " ").replace("|", "\\|").strip()

    def _row_cells(row) -> List[str]:
        cells = [_cell(c) for c in row]
        cells.extend([""] * (width - len(cells)))  # 短行补空单元格对齐
        return cells

    lines = ["| " + " | ".join(_row_cells(rows[0])) + " |"]
    lines.append("| " + " | ".join(["---"] * width) + " |")
    for row in rows[1:]:
        lines.append("| " + " | ".join(_row_cells(row)) + " |")
    return lines


def _clamp_comment_text(text: str, limit: int = 60) -> str:
    """批注正文压成单行并截到 limit 字（超长以 … 收尾，总长仍 ≤ limit）。"""
    collapsed = " ".join(text.split())
    if len(collapsed) <= limit:
        return collapsed
    return collapsed[: limit - 1] + "…"


def _render_comment_overview(comments) -> List[str]:
    """批注概况块（round-2 R3-digest）: `comments: N 条` + 前 3 条明细行。

    明细行格式: `[作者: 锚点文本 → 批注 ≤60字]`。无批注 → 空列表
    （digest 末尾不输出任何批注行）。getattr 全程防御：read_docx 的
    result 是否已并入 comments 字段由并行批次决定，缺字段/缺属性时
    静默跳过，绝不影响正文 digest。
    """
    lines: List[str] = []
    total = len(comments)
    if not total:
        return lines
    lines.append(f"comments: {total} 条")
    for comment in comments[:3]:
        author = (getattr(comment, "author", None) or "-").strip() or "-"
        anchor = " ".join((getattr(comment, "anchor_text", "") or "").split())
        text = getattr(comment, "text", "") or ""
        lines.append(f"[{author}: {anchor} → {_clamp_comment_text(text)}]")
    return lines


def _digest_word(file_path: str, workspace: str) -> str:
    """Return structured markdown digest: heading 层级 + 全段文本 + 列表 + GFM 表格。

    Budget: heading 与表格始终全量保留, 正文段落累计超
    MAX_ATTACHMENT_DIGEST_BYTES 时从截断点起丢弃, 并以
    `[…已截断，共 N 段]` 标注被丢弃的正文段数。
    摘要末尾附批注概况 (round-2 R3-digest): 有批注时输出
    `comments: N 条` + 前 3 条 `[作者: 锚点 → 批注 ≤60字]`；
    无批注（或 read_docx 结果尚无 comments 字段）时不输出。
    """
    result = read_docx(
        file_path=Path(file_path),
        workspace_path=workspace,
        generated_filename=os.path.basename(file_path),
    )
    lines: List[str] = []
    dropped = 0
    truncated = False
    used = 0
    for line in _render_word_paragraphs(result.paragraphs):
        is_heading = line.startswith("#")
        cost = len(line.encode("utf-8")) + 1
        if not truncated and (is_heading or used + cost <= MAX_ATTACHMENT_DIGEST_BYTES):
            lines.append(line)
            used += cost
            continue
        # 超 budget: 正文行计入截断计数, heading 仍保留维持文档骨架
        truncated = True
        if is_heading:
            lines.append(line)
            used += cost
        else:
            dropped += 1
    if truncated and dropped:
        lines.append(f"[…已截断，共 {dropped} 段]")
    for table in result.tables:
        table_lines = _render_word_table(table.rows)
        if not table_lines:
            continue
        if lines:
            lines.append("")  # GFM 表格前的空行分隔
        lines.extend(table_lines)
    # 批注概况附在摘要末尾（正文/表格之后，不受 budget 截断影响——
    # 批注是独立维度的事实，正文再长也不该把它挤掉）。
    lines.extend(_render_comment_overview(getattr(result, "comments", None) or []))
    return "\n".join(lines)


def _fmt_num(value: float) -> str:
    """统计值展示: 整数值不带小数点, 浮点保留 4 位有效数字。"""
    if abs(value) < 1e15 and value == int(value):
        return str(int(value))
    return format(value, ".4g")


def _sheet_numeric_stats(rows) -> List[str]:
    """数值列统计 (纯 Python, 不引入 pandas): count/non_null/min/max/mean。

    仅当某列的全部非空单元格都能 float() 解析时才视为数值列; 含 nan/inf
    一律按文本列跳过。rows[0] 视为表头, 统计范围是数据行。
    """
    if len(rows) < 2:
        return []
    header, data = rows[0], rows[1:]
    width = max(len(r) for r in rows)
    lines: List[str] = []
    for col in range(width):
        values: List[float] = []
        non_null = 0
        numeric = True
        for row in data:
            cell = row[col].strip() if col < len(row) else ""
            if not cell:
                continue
            non_null += 1
            try:
                value = float(cell)
            except ValueError:
                numeric = False
                break
            if not math.isfinite(value):
                numeric = False
                break
            values.append(value)
        if not numeric or not values:
            continue
        name = header[col].strip() if col < len(header) else f"col{col + 1}"
        lines.append(
            f"stat {name}: count={len(values)}, non_null={non_null}, "
            f"min={_fmt_num(min(values))}, max={_fmt_num(max(values))}, "
            f"mean={_fmt_num(sum(values) / len(values))}"
        )
    return lines


def _digest_excel(file_path: str, workspace: str) -> str:
    """Return per-sheet digest: 行列数 + 表头 + 数值列统计 + 自适应行数 TSV。

    行数不再硬编码 5: 在 MAX_ATTACHMENT_DIGEST_BYTES 预算内能放多少数据行
    就放多少, 放不下的行数以 `[…已截断，共 N 行]` 标注。
    """
    result = read_xlsx(
        file_path=Path(file_path),
        workspace_path=workspace,
        generated_filename=os.path.basename(file_path),
    )
    sheets = result.sheets
    names = [s.name for s in sheets]
    overview = f"sheets: {', '.join(names)}"
    lines: List[str] = [overview]
    used = len(overview.encode("utf-8")) + 1
    for sheet in sheets:
        # 固定段: 分隔行 (含行列数) + 表头行 + 数值列统计, 全量保留
        fixed = [f"--- {sheet.name} ({sheet.max_row} rows x {sheet.max_col} cols) ---"]
        if sheet.rows:
            fixed.append("\t".join(sheet.rows[0]))
        fixed.extend(_sheet_numeric_stats(sheet.rows))
        lines.extend(fixed)
        used += sum(len(line.encode("utf-8")) + 1 for line in fixed)
        data_rows = sheet.rows[1:] if sheet.rows else []
        shown = 0
        for row in data_rows:
            tsv = "\t".join(row)
            cost = len(tsv.encode("utf-8")) + 1
            if used + cost > MAX_ATTACHMENT_DIGEST_BYTES:
                break
            lines.append(tsv)
            used += cost
        if shown < len(data_rows):
            lines.append(f"[…已截断，共 {len(data_rows) - shown} 行]")
    return "\n".join(lines)


def _digest_pdf(file_path: str, workspace: str) -> str:
    """Return page count + per-page first-chars preview (budget-aware)。

    每页压掉换行/连续空白后取前 _PDF_PAGE_PREVIEW_CHARS 字符; 整体超
    MAX_ATTACHMENT_DIGEST_BYTES 时停止装载, 以 `[…已截断，共 N 页]` 标注。
    """
    result = read_pdf(
        file_path=Path(file_path),
        workspace_path=workspace,
    )
    pages = result.pages
    overview = f"pages: {len(pages)}"
    lines: List[str] = [overview]
    used = len(overview.encode("utf-8")) + 1
    for shown, page in enumerate(pages):
        text = " ".join(page.text.split())
        if len(text) > _PDF_PAGE_PREVIEW_CHARS:
            text = text[:_PDF_PAGE_PREVIEW_CHARS]
        section = f"--- page {page.page_number} ---\n{text}"
        cost = len(section.encode("utf-8")) + 1
        if used + cost > MAX_ATTACHMENT_DIGEST_BYTES:
            lines.append(f"[…已截断，共 {len(pages) - shown} 页]")
            break
        lines.append(section)
        used += cost
    return "\n".join(lines)


logger = logging.getLogger(__name__)

_MENTION_RE = re.compile(r"(?:^|\s)@([^\s]+?)(?=\s|$)")

OFFICE_EXTS: FrozenSet[str] = frozenset({".pptx", ".docx", ".xlsx", ".pdf"})
MAX_ATTACHMENT_FILE_SIZE_BYTES = 50 * 1024 * 1024

# 单文件 digest 注入 LLM 前的软字节预算 (UTF-8 计)。与上面的磁盘 50MB 硬上限
# 语义不同: 这个管 digest 内容量, word/excel/pdf 各自按预算自适应截断。
MAX_ATTACHMENT_DIGEST_BYTES = 8 * 1024

# PDF 单页文本预览的字符上限 (整体仍受 MAX_ATTACHMENT_DIGEST_BYTES 约束)。
_PDF_PAGE_PREVIEW_CHARS = 2000

# ext → kind (M1 用)
_EXT_TO_KIND = {
    ".pptx": "office-ppt",
    ".docx": "office-word",
    ".xlsx": "office-excel",
    ".pdf": "office-pdf",
}


@dataclass
class Mention:
    raw: str  # @ 后的整段原文 (含 ext)
    path: str  # 与 raw 相同 (本轮不解析 host/relative)
    kind: Optional[str]  # 'office-ppt'/'office-word'/'office-excel'/'office-pdf' 或 None


@dataclass
class ResolvedBlock:
    source_ref: str  # 显示用的 basename (e.g. 'foo.pptx')
    digest_text: str  # 注入 LLM 的纯文本


def extract_mentions(text: str) -> List[Mention]:
    """从 text 里扫所有 @path, 按扩展名分类 kind.

    过滤: path 必须含 '/' 或 '.' (排除 @com 之类纯单词噪声)。
    去重: 同一 path 只保留首次出现 (preserve order)。
    """
    seen = set()
    result: List[Mention] = []
    for m in _MENTION_RE.finditer(text):
        raw = m.group(1)
        if "/" not in raw and "." not in raw:
            continue
        if raw in seen:
            continue
        seen.add(raw)
        ext = Path(raw).suffix.lower()
        kind = _EXT_TO_KIND.get(ext)  # None for non-office
        result.append(Mention(raw=raw, path=raw, kind=kind))
    return result


def _resolve_attachment_path(raw_path: str, workspace_root: Path) -> Path:
    """Resolve one mention inside a validated workspace and enforce the read limit."""
    candidate = Path(raw_path)
    if not candidate.is_absolute():
        candidate = workspace_root / candidate
    resolved = resolve_within(workspace_root, candidate)
    try:
        is_file = resolved.is_file()
    except OSError as exc:
        # T3.M4 closure: 沙箱里 stat 可能因权限/IO 失败, 链回 cause 让
        # logger.warning 看到根因 (不光是 'not a regular file')。
        raise OfficePathError(
            "Attachment path is not a regular file",
            file_path=resolved,
        ) from exc
    if not is_file:
        raise OfficePathError(
            "Attachment path is not a regular file",
            file_path=resolved,
        )
    try:
        actual_size = resolved.stat().st_size
    except OSError as exc:
        # T3.M4 closure: stat 失败时同样链回 cause, 便于诊断 size 上限误触发。
        raise OfficeSizeLimitError(
            actual_size=-1,
            max_size=MAX_ATTACHMENT_FILE_SIZE_BYTES,
            file_path=resolved,
        ) from exc
    if actual_size > MAX_ATTACHMENT_FILE_SIZE_BYTES:
        raise OfficeSizeLimitError(
            actual_size=actual_size,
            max_size=MAX_ATTACHMENT_FILE_SIZE_BYTES,
            file_path=resolved,
        )
    return resolved


def _digest_for_kind(kind: str, file_path: str, workspace: str) -> str:
    if kind == "office-ppt":
        return _digest_ppt(file_path, workspace)
    if kind == "office-word":
        return _digest_word(file_path, workspace)
    if kind == "office-pdf":
        return _digest_pdf(file_path, workspace)
    return _digest_excel(file_path, workspace)


def resolve_mentions(
    mentions: List[Mention],
    workspace: str,
) -> List[ResolvedBlock]:
    """Resolve Office mentions within ``workspace``; invalid mentions are skipped."""
    office_mentions = [
        mention
        for mention in mentions
        if mention.kind
        in ("office-ppt", "office-word", "office-excel", "office-pdf")
    ]
    if not office_mentions:
        return []
    if not workspace:
        logger.warning("office mention resolve skipped: workspace path is missing")
        return []

    try:
        workspace_root = validate_workspace(Path(workspace))
    except OfficeError as exc:
        logger.warning(
            "office mention workspace validation failed (%s)",
            type(exc).__name__,
        )
        return []

    blocks: List[ResolvedBlock] = []
    for mention in office_mentions:
        try:
            resolved_path = _resolve_attachment_path(mention.path, workspace_root)
            digest = _digest_for_kind(
                mention.kind or "",
                str(resolved_path),
                str(workspace_root),
            )
            blocks.append(
                ResolvedBlock(
                    source_ref=resolved_path.name,
                    digest_text=digest,
                )
            )
        except OfficeError as exc:
            logger.warning(
                "office mention resolve failed: %s (%s)",
                os.path.basename(mention.path),
                type(exc).__name__,
            )
    return blocks


def render_attachment_block(blocks: List[ResolvedBlock]) -> str:
    """拼接为单一字符串, 供 route 层嵌入 system prompt。

    格式:
        <attachments>
        === name1 ===
        digest1
        === name2 ===
        digest2
        </attachments>

    空 list → 返回空串 (让 route 层跳过注入)。
    """
    if not blocks:
        return ""
    parts = ["<attachments>"]
    for b in blocks:
        parts.append(f"=== {b.source_ref} ===")
        parts.append(b.digest_text)
    parts.append("</attachments>")
    return "\n".join(parts)


def process(text: str, workspace: str) -> str:
    """route 层一键调: 返回附件块字符串 (可能为空串)。"""
    mentions = extract_mentions(text)
    blocks = resolve_mentions(mentions, workspace)
    return render_attachment_block(blocks)
