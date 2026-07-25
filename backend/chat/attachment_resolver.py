"""@ mention → office digest → LLM context block 解析器。

M1: 单文档 `@foo.pptx` 等自动注入 pptx/docx/xlsx 摘要到 system prompt。
M2: 多文档按出现顺序拼接, 块首 `=== name ===` 分隔。

设计 (per spec §3.2):
- 纯函数模块, 无 FastAPI / DB 依赖
- 复用 `backend.office.{ppt,word,excel}` 的 read_ppt/read_docx/read_xlsx 纯函数
- 失败降级: 单个 mention 抛 OfficeError 时静默 skip + log warning (不污染整块)
- 与现有 office_ppt_read / office_word_read / office_excel_read IPC endpoint 不同:
  * 不触发 _persist_read_summary (即不写 DB)
  * 不做 size validation (chat 信任 digest 输出)

Win7 兼容: 无 walrus, 无 PEP 604 union, str 类型注解仅在必须时用 (Python 3.8 兼容)。
"""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import FrozenSet, List, Optional

# Task 2: 真实 digest 格式化器 (复用 office 纯函数, 不触发 FastAPI endpoint)
from backend.office.errors import OfficeError, OfficePathError, OfficeSizeLimitError
from backend.office.excel import read_xlsx
from backend.office.path_safety import resolve_within
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


def _digest_word(file_path: str, workspace: str) -> str:
    """Return per-paragraph first sentence."""
    result = read_docx(
        file_path=Path(file_path),
        workspace_path=workspace,
        generated_filename=os.path.basename(file_path),
    )
    lines: List[str] = []
    for para in result.paragraphs:
        text = para.text.strip()
        if not text:
            continue
        first = text.split(".", 1)[0].strip()
        # 即使整段无句号, 也加 '.' 后缀让 LLM 识别句子边界
        lines.append(first + ".")
    return "\n".join(lines)


def _digest_excel(file_path: str, workspace: str) -> str:
    """Return sheet names + first 5 rows per sheet as TSV."""
    result = read_xlsx(
        file_path=Path(file_path),
        workspace_path=workspace,
        generated_filename=os.path.basename(file_path),
    )
    sheets = result.sheets
    names = [s.name for s in sheets]
    lines: List[str] = [f"sheets: {', '.join(names)}"]
    for sheet in sheets:
        rows = sheet.rows[:5]
        lines.append(f"--- {sheet.name} (top {len(rows)} rows) ---")
        for row in rows:
            lines.append("\t".join(row))
    return "\n".join(lines)


logger = logging.getLogger(__name__)

_MENTION_RE = re.compile(r"(?:^|\s)@([^\s]+?)(?=\s|$)")

OFFICE_EXTS: FrozenSet[str] = frozenset({".pptx", ".docx", ".xlsx"})
MAX_ATTACHMENT_FILE_SIZE_BYTES = 50 * 1024 * 1024

# ext → kind (M1 用)
_EXT_TO_KIND = {
    ".pptx": "office-ppt",
    ".docx": "office-word",
    ".xlsx": "office-excel",
}


@dataclass
class Mention:
    raw: str  # @ 后的整段原文 (含 ext)
    path: str  # 与 raw 相同 (本轮不解析 host/relative)
    kind: Optional[str]  # 'office-ppt'/'office-word'/'office-excel' 或 None


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
    return _digest_excel(file_path, workspace)


def resolve_mentions(
    mentions: List[Mention],
    workspace: str,
) -> List[ResolvedBlock]:
    """Resolve Office mentions within ``workspace``; invalid mentions are skipped."""
    office_mentions = [
        mention
        for mention in mentions
        if mention.kind in ("office-ppt", "office-word", "office-excel")
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
