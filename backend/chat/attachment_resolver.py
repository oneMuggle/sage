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


# Task 2 才会装入, 本 Task stub 三个 digest 函数让 Task 1 测试通过
def _digest_ppt(file_path: str, workspace: str) -> str:
    """Stub. Task 2 will replace."""
    return ""

def _digest_word(file_path: str, workspace: str) -> str:
    """Stub. Task 2 will replace."""
    return ""

def _digest_excel(file_path: str, workspace: str) -> str:
    """Stub. Task 2 will replace."""
    return ""


logger = logging.getLogger(__name__)

_MENTION_RE = re.compile(r"(?:^|\s)@([^\s]+?)(?=\s|$)")

OFFICE_EXTS: FrozenSet[str] = frozenset({".pptx", ".docx", ".xlsx"})

# ext → kind (M1 用)
_EXT_TO_KIND = {
    ".pptx": "office-ppt",
    ".docx": "office-word",
    ".xlsx": "office-excel",
}


@dataclass
class Mention:
    raw: str           # @ 后的整段原文 (含 ext)
    path: str          # 与 raw 相同 (本轮不解析 host/relative)
    kind: Optional[str]  # 'office-ppt'/'office-word'/'office-excel' 或 None


@dataclass
class ResolvedBlock:
    source_ref: str    # 显示用的 basename (e.g. 'foo.pptx')
    digest_text: str   # 注入 LLM 的纯文本


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


def resolve_mentions(
    mentions: List[Mention],
    workspace: str,
) -> List[ResolvedBlock]:
    """对 kind=office-* 的 mention 调 _digest_* 出 digest; 其它跳过。

    失败降级: 单个 mention 抛 OfficeError 时静默 skip + log warning,
    不留 placeholder (避免用户在 LLM 看到残块)。
    """
    from backend.office.errors import OfficeError  # 延迟 import 避免循环

    blocks: List[ResolvedBlock] = []
    for m in mentions:
        if m.kind not in ("office-ppt", "office-word", "office-excel"):
            continue
        try:
            if m.kind == "office-ppt":
                digest = _digest_ppt(m.path, workspace)
            elif m.kind == "office-word":
                digest = _digest_word(m.path, workspace)
            else:  # office-excel
                digest = _digest_excel(m.path, workspace)
            blocks.append(
                ResolvedBlock(
                    source_ref=os.path.basename(m.path),
                    digest_text=digest,
                )
            )
        except OfficeError as exc:
            logger.warning(
                "office mention resolve failed: %s (%s)", m.path, exc,
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
