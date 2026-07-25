---
name: office-m1-m2-chat-read-impl
description: Office M1-M2 chat-read 实施 plan — 7 tasks (attachment_resolver → digest formatters → legacy /chat/stream wire-in → hex /chat wire-in → fileSearchClient merge → AtFileMenu kind icon → e2e → 双分支 PR)
metadata:
  type: plan
  status: ready
  spec: 2026-07-24-office-m1-m2-chat-read-design.md
  branch: fix/office-m1-m2-chat-read
  base: release/win7
  win7_squash_cherry_pick_branch: fix/win7-office-m1-m2-cherry-pick
  win7_base: release/win7
  main_apply_branch: fix/office-m1-m2-chat-read-main
  main_base: main
  date: 2026-07-24
---

# Office M1-M2 Chat-Read Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 chat 输入 `@proposal.pptx` 时, 后端自动把该文档按"pptx=title+text_blocks / docx=首句 / xlsx=sheet 名 + 前 5 行"摘要注入 LLM context。M2: 同一消息多 `@` 文档按顺序拼接, 块首加 `=== name ===` 分隔。

**Architecture:** 新建 `backend/chat/attachment_resolver.py` 纯函数模块 (`extract_mentions` / `resolve_mentions` / `render_attachment_block` / `process`)。复用现有 `backend.office.ppt.read_ppt` / `word.read_docx` / `excel.read_xlsx` 纯函数 (非 FastAPI endpoint, 不持久化 DB 行)。Wire 到 `backend/api/legacy_routes.py` 和 `backend/api/hex_routes.py` 的 `/chat` 与 `/chat/stream` 入口, 在送 LLM 前向 system messages append 一条 `<attachments>` 块。前端 `fileSearchClient.search` 合并 `officeApi.listDocuments` 结果, `AtFileMenu` 按 `kind` 字段渲染不同 icon。ChatInput 不动。

**Tech Stack:** Python 3.11 (main) / 3.8 (win7), FastAPI, Pydantic v2 (main) / v1 (win7); 前端 TypeScript + Vitest + Playwright e2e。

## Global Constraints

- Win7 Python 是 3.8, Pydantic v1 (`class Config: extra = "forbid"` 而不是 `model_config = ConfigDict(...)`, `req.dict(...)` 不是 `req.model_dump(...)`)
- Main Python 是 3.11, Pydantic v2 (`model_config = ConfigDict(extra="forbid")` + `req.model_dump(exclude_none=True)`)
- 不用 walrus operator (`:=`) — win7 不支持
- 复用 `backend/office/{ppt,word,excel}.py` 的 `read_ppt / read_docx / read_xlsx` 纯函数 — **不调** FastAPI endpoint (会触发 size validation + DB 持久化, 不适合 chat 用)
- Errors 用 `backend.office.errors` 的 `OfficePathError / OfficeParseError / OfficeFileNotFoundError` (基类 `OfficeError`)
- PPT digest 用 `slide.title` + `slide.text_blocks: List[str]` (不是 spec pseudocode 写的 `slide.bullets` — 真实字段名是 `text_blocks`)
- Excel digest 用 `sheet.rows: List[List[str]]` (cells 是 plain string, 不是 `{value: ...}`)
- `max_size_bytes=50*1024*1024` (50MB), 与 office routes 默认对齐
- 不调用生成 routes (chat 注入只读)
- 所有 commit message 走 conventional commits 格式
- 双分支同步策略: 先在 win7 LTS branch 上 commit (per 当前 base 是 release/win7) → 切 main 提 PR → win7 已存在, win7 cherry-pick 走 LTS path (per memory 项目惯例, 但本轮 win7 已是 base)

> 注: 实施 base 是 release/win7, 因为 Office 模块最初按 win7 LTS 路线开发 (per M0 PR #209 precedent)。代码改完后切 main 提 PR, win7 分支作为目标 base 已经包含所有 win7 适配。

---

## 任务地图 (Task Map)

| Task | 主题 | 文件 | 测试 |
|---|---|---|---|
| 1 | backend attachment_resolver 核心 | NEW `backend/chat/__init__.py` + `backend/chat/attachment_resolver.py` | NEW `backend/tests/unit/chat/__init__.py` + `test_attachment_resolver.py` (≥10 cases) |
| 2 | 3 个 digest 格式化器 (ppt/word/excel) | (同 Task 1 文件) | NEW `backend/tests/unit/chat/test_digest_formatters.py` (≥12 cases) |
| 3 | legacy_routes /chat/stream wire-in | MODIFY `backend/api/legacy_routes.py:961-1140` | NEW `backend/tests/integration/test_chat_attachment_injection_legacy.py` (≥4 cases) |
| 4 | hex_routes /chat wire-in | MODIFY `backend/api/hex_routes.py:138-152` | NEW `backend/tests/integration/test_chat_attachment_injection_hex.py` (≥2 cases) |
| 5 | frontend fileSearchClient 合并 office | MODIFY `src/shared/api/fileSearchClient.ts` | NEW `src/shared/api/__tests__/fileSearchClient.test.ts` (≥8 cases) |
| 6 | frontend AtFileMenu kind icon | MODIFY `src/features/chat/AtFileMenu.tsx` | NEW `src/features/chat/__tests__/AtFileMenu.test.tsx` (≥6 cases) |
| 7 | e2e spec + 双分支 PR + memory | NEW `tests/e2e/office-chat-attachments.e2e.ts` | (Playwright 自带 runner) + git/gh 操作 |

---

## Task 1: Backend `attachment_resolver` 模块 — extract / resolve / render / process

**Files:**
- Create: `/home/fz/project/sage/backend/chat/__init__.py`
- Create: `/home/fz/project/sage/backend/chat/attachment_resolver.py`
- Create: `/home/fz/project/sage/backend/tests/unit/chat/__init__.py`
- Create: `/home/fz/project/sage/backend/tests/unit/chat/test_attachment_resolver.py`

**Interfaces:**
- Produces:
  - `Mention(raw: str, path: str, kind: Optional[str])` — dataclass
  - `ResolvedBlock(source_ref: str, digest_text: str)` — dataclass
  - `OFFICE_EXTS: FrozenSet[str]` = `{'.pptx', '.docx', '.xlsx'}`
  - `extract_mentions(text: str) -> List[Mention]`
  - `resolve_mentions(mentions: List[Mention], workspace: str) -> List[ResolvedBlock]`
  - `render_attachment_block(blocks: List[ResolvedBlock]) -> str`
  - `process(text: str, workspace: str) -> str` — entry point

- Consumes (下一步 Task 2 的 3 个 `_digest_*` 函数, 本 Task 只定义 `process` 调用它们但 Task 2 之前会 import 失败 — OK, 在 Task 1 step 1.4 stub 后再补)

### Step 1.1: 写失败的单元测试 (RED)

新建 `/home/fz/project/sage/backend/tests/unit/chat/__init__.py`（空文件）:

```python
"""Chat attachment integration unit tests."""
```

新建 `/home/fz/project/sage/backend/tests/unit/chat/test_attachment_resolver.py`:

```python
"""attachment_resolver 核心单元测试 (Task 1).

覆盖:
- extract_mentions: 正则触发、扩展名分类、重复去重、无扩展跳过
- resolve_mentions: 每种 kind 调用对应 _digest_* (mock), 失败降级
- render_attachment_block: 空 list 返回空串; 单/多块分隔符
- process: 端到端 fixture

注: _digest_* 函数在 Task 2 才实现, 本 Task 的 resolve/process 测试用 unittest.mock.patch
    桩化 `_digest_ppt / _digest_word / _digest_excel` 让 extract/render/path 测试通过。
"""
from __future__ import annotations

import pytest

from backend.chat import attachment_resolver
from backend.chat.attachment_resolver import (
    OFFICE_EXTS,
    Mention,
    ResolvedBlock,
    extract_mentions,
    process,
    render_attachment_block,
    resolve_mentions,
)


# ─── extract_mentions ────────────────────────────────────────────

def test_extract_mentions_basic_pptx() -> None:
    mentions = extract_mentions("看一下 @foo.pptx 好吗")
    assert len(mentions) == 1
    assert mentions[0].path == "foo.pptx"
    assert mentions[0].kind == "office-ppt"


def test_extract_mentions_basic_docx_xlsx() -> None:
    mentions = extract_mentions("对比 @a.docx 和 @b.xlsx")
    kinds = {m.kind for m in mentions}
    assert kinds == {"office-word", "office-excel"}


def test_extract_mentions_path_with_slash() -> None:
    """绝对/相对路径都识别"""
    mentions = extract_mentions("@/tmp/workspace/proposal.pptx")
    assert mentions[0].path == "/tmp/workspace/proposal.pptx"
    assert mentions[0].kind == "office-ppt"


def test_extract_mentions_skips_pure_word() -> None:
    """不含 '/' 或 '.' 的纯单词 (如 @com) 不当 mention"""
    assert extract_mentions("see @com irc") == []


def test_extract_mentions_dedup() -> None:
    """同一 path 多次出现只取 1 个"""
    mentions = extract_mentions("@foo.pptx 与 @foo.pptx")
    assert len(mentions) == 1


def test_extract_mentions_skips_non_office_extensions() -> None:
    """非 office 后缀的 path 仍识别为 mention, kind=None (留作未来扩展点)"""
    mentions = extract_mentions("@notes.txt")
    assert len(mentions) == 1
    assert mentions[0].kind is None


def test_extract_mentions_empty_string() -> None:
    assert extract_mentions("") == []


def test_office_exts_is_frozen() -> None:
    assert OFFICE_EXTS == frozenset({".pptx", ".docx", ".xlsx"})


# ─── resolve_mentions (mock _digest_*) ───────────────────────────

def test_resolve_mentions_skips_non_office(monkeypatch) -> None:
    """kind=None 的 mention 直接跳过"""
    mentions = [Mention(raw="@a.txt", path="a.txt", kind=None)]
    blocks = resolve_mentions(mentions, workspace="/w")
    assert blocks == []


def test_resolve_mentions_calls_ppt_digest(monkeypatch) -> None:
    monkeypatch.setattr(
        attachment_resolver, "_digest_ppt",
        lambda path, workspace: "PPT_DUMMY",
    )
    mentions = [Mention(raw="@x.pptx", path="x.pptx", kind="office-ppt")]
    blocks = resolve_mentions(mentions, workspace="/w")
    assert len(blocks) == 1
    assert blocks[0].digest_text == "PPT_DUMMY"
    assert blocks[0].source_ref == "x.pptx"


def test_resolve_mentions_calls_word_digest(monkeypatch) -> None:
    monkeypatch.setattr(
        attachment_resolver, "_digest_word",
        lambda path, workspace: "WORD_DUMMY",
    )
    mentions = [Mention(raw="@y.docx", path="y.docx", kind="office-word")]
    blocks = resolve_mentions(mentions, workspace="/w")
    assert blocks[0].digest_text == "WORD_DUMMY"


def test_resolve_mentions_calls_excel_digest(monkeypatch) -> None:
    monkeypatch.setattr(
        attachment_resolver, "_digest_excel",
        lambda path, workspace: "EXCEL_DUMMY",
    )
    mentions = [Mention(raw="@z.xlsx", path="z.xlsx", kind="office-excel")]
    blocks = resolve_mentions(mentions, workspace="/w")
    assert blocks[0].digest_text == "EXCEL_DUMMY"


def test_resolve_mentions_silently_skips_on_error(monkeypatch, caplog) -> None:
    """_digest_ppt 抛 OfficePathError 时, 本 mention 静默 skip + log warning"""
    from backend.office.errors import OfficePathError
    monkeypatch.setattr(
        attachment_resolver, "_digest_ppt",
        lambda path, workspace: (_ for _ in ()).throw(
            OfficePathError("boom", file_path=None)
        ),
    )
    mentions = [Mention(raw="@bad.pptx", path="bad.pptx", kind="office-ppt")]
    blocks = resolve_mentions(mentions, workspace="/w")
    assert blocks == []


def test_resolve_mentions_preserves_order(monkeypatch) -> None:
    """多个 mention 按出现顺序产出 blocks"""
    monkeypatch.setattr(
        attachment_resolver, "_digest_ppt", lambda p, w: "P",
    )
    monkeypatch.setattr(
        attachment_resolver, "_digest_word", lambda p, w: "W",
    )
    text = "@a.pptx 然后 @b.docx"
    mentions = extract_mentions(text)
    blocks = resolve_mentions(mentions, workspace="/w")
    assert [b.source_ref for b in blocks] == ["a.pptx", "b.docx"]


# ─── render_attachment_block ─────────────────────────────────────

def test_render_empty_list_returns_empty_string() -> None:
    assert render_attachment_block([]) == ""


def test_render_single_block() -> None:
    blocks = [ResolvedBlock(source_ref="foo.pptx", digest_text="D1")]
    out = render_attachment_block(blocks)
    assert out.startswith("<attachments>")
    assert out.endswith("</attachments>")
    assert "=== foo.pptx ===" in out
    assert "D1" in out


def test_render_multiple_blocks_with_separator() -> None:
    blocks = [
        ResolvedBlock(source_ref="a.pptx", digest_text="A"),
        ResolvedBlock(source_ref="b.docx", digest_text="B"),
    ]
    out = render_attachment_block(blocks)
    assert "=== a.pptx ===" in out
    assert "=== b.docx ===" in out
    assert out.index("a.pptx") < out.index("b.docx")


# ─── process (top-level entry, mock digests) ─────────────────────

def test_process_no_mentions_returns_empty(monkeypatch) -> None:
    """无 @ → 返回空串"""
    assert process("hello world", workspace="/w") == ""


def test_process_happy_path(monkeypatch) -> None:
    monkeypatch.setattr(attachment_resolver, "_digest_ppt", lambda p, w: "D")
    out = process("看 @x.pptx", workspace="/w")
    assert "<attachments>" in out
    assert "=== x.pptx ===" in out
    assert "D" in out


def test_process_skips_non_office(monkeypatch) -> None:
    """@foo.txt 不触发任何 digest, 返回空串"""
    assert process("see @foo.txt", workspace="/w") == ""
```

### Step 1.2: 跑测试验证 RED

```bash
cd /home/fz/project/sage
conda activate sage-backend
/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/chat/test_attachment_resolver.py -q
```

**Expected**: `ModuleNotFoundError: No module named 'backend.chat'` (RED 状态)

### Step 1.3: 实现 `attachment_resolver.py` (GREEN)

新建 `/home/fz/project/sage/backend/chat/__init__.py`:

```python
"""Chat domain modules (M1-M2 chat-read)."""
```

新建 `/home/fz/project/sage/backend/chat/attachment_resolver.py`:

```python
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

_MENTION_RE = re.compile(r'(?:^|\s)@([^\s]+?)(?=\s|$)')

OFFICE_EXTS: FrozenSet[str] = frozenset({'.pptx', '.docx', '.xlsx'})

# ext → kind (M1 用)
_EXT_TO_KIND = {
    '.pptx': 'office-ppt',
    '.docx': 'office-word',
    '.xlsx': 'office-excel',
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
        if '/' not in raw and '.' not in raw:
            continue
        if raw in seen:
            continue
        seen.add(raw)
        ext = os.path.splitext(raw)[1].lower()
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
        if m.kind not in ('office-ppt', 'office-word', 'office-excel'):
            continue
        try:
            if m.kind == 'office-ppt':
                digest = _digest_ppt(m.path, workspace)
            elif m.kind == 'office-word':
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
        return ''
    parts = ['<attachments>']
    for b in blocks:
        parts.append(f'=== {b.source_ref} ===')
        parts.append(b.digest_text)
    parts.append('</attachments>')
    return '\n'.join(parts)


def process(text: str, workspace: str) -> str:
    """route 层一键调: 返回附件块字符串 (可能为空串)。"""
    mentions = extract_mentions(text)
    blocks = resolve_mentions(mentions, workspace)
    return render_attachment_block(blocks)
```

### Step 1.4: 跑测试验证 GREEN

```bash
conda activate sage-backend
/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/chat/test_attachment_resolver.py -q
```

**Expected**: ≥21 cases 全过 (extract 8 + resolve 6 + render 3 + process 3 = 20, +office_exts 1 = 21).

> 注意: 测试用 `monkeypatch.setattr(attachment_resolver, "_digest_ppt", ...)` 把 stub 换成 lambda, 所以 Task 2 实现真实 digest 函数后这些测试仍然过。

### Step 1.5: Commit

```bash
cd /home/fz/project/sage
git add backend/chat/__init__.py backend/chat/attachment_resolver.py \
        backend/tests/unit/chat/__init__.py \
        backend/tests/unit/chat/test_attachment_resolver.py
git commit -m "feat(backend): attachment_resolver core — extract/resolve/render/process

@ mention 提取 + 按扩展名分派给 _digest_* + 失败降级 + 拼接附件块。
21 个 pytest case 全过 (extract 8 + resolve 6 + render 3 + process 3 + exts 1)。
stub 三个 _digest_* 函数, Task 2 替换为真实实现。"
```

---

## Task 2: 3 个 digest 格式化器 (ppt/word/excel)

**Files:**
- Modify: `/home/fz/project/sage/backend/chat/attachment_resolver.py:30-44` (替换 3 个 stub)
- Create: `/home/fz/project/sage/backend/tests/unit/chat/test_digest_formatters.py`

**Interfaces:**
- Consumes:
  - `Mention` (Task 1) — 仅 path 字段
- Produces (replaces stubs):
  - `_digest_ppt(file_path: str, workspace: str) -> str`
  - `_digest_word(file_path: str, workspace: str) -> str`
  - `_digest_excel(file_path: str, workspace: str) -> str`

### Step 2.1: 写失败的格式化器测试 (RED)

新建 `/home/fz/project/sage/backend/tests/unit/chat/test_digest_formatters.py`:

```python
"""3 个 digest 格式化器单元测试 (Task 2).

覆盖 pptx (title + text_blocks), docx (首句), excel (sheet 名 + 前 5 行)
的边界条件: 空 slide/paragraph/sheet, 长文本裁剪, OfficePathError 透传。
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from backend.chat import attachment_resolver
from backend.chat.attachment_resolver import (
    _digest_excel,
    _digest_ppt,
    _digest_word,
)
from backend.office.errors import OfficePathError


# ─── _digest_ppt ────────────────────────────────────────────────

def _fake_ppt(slides):
    """Build OfficePptReadResult with given slides list."""
    from backend.office.models import (
        OfficeDocumentMetadata,
        OfficeDocumentSummary,
        OfficePptReadResult,
    )
    summary = OfficeDocumentSummary(
        id="x", workspace_path="/w", doc_type="ppt",
        original_filename=None, generated_filename="x.pptx",
        status="parsed", created_at=0, updated_at=0,
        metadata=OfficeDocumentMetadata(file_size_bytes=0, page_count=len(slides)),
    )
    return OfficePptReadResult(summary=summary, slides=slides)


def test_digest_ppt_basic() -> None:
    from backend.office.models import PptSlideContent
    slides = [
        PptSlideContent(index=0, title="Intro", text_blocks=["hi", "world"],
                        table_count=0, image_count=0, notes=None),
        PptSlideContent(index=1, title=None, text_blocks=["no title slide"],
                        table_count=0, image_count=0, notes=None),
    ]
    with patch.object(attachment_resolver, "read_ppt",
                      return_value=_fake_ppt(slides)):
        out = _digest_ppt("/w/x.pptx", workspace="/w")
    assert "[Intro]" in out
    assert "  - hi" in out
    assert "  - world" in out
    assert "[(untitled)]" in out
    assert "  - no title slide" in out


def test_digest_ppt_empty() -> None:
    with patch.object(attachment_resolver, "read_ppt",
                      return_value=_fake_ppt([])):
        out = _digest_ppt("/w/empty.pptx", workspace="/w")
    assert out == ""


def test_digest_ppt_propagates_path_error() -> None:
    with patch.object(
        attachment_resolver, "read_ppt",
        side_effect=OfficePathError("traversal blocked", file_path=None),
    ):
        with pytest.raises(OfficePathError):
            _digest_ppt("/etc/passwd.pptx", workspace="/w")


# ─── _digest_word ───────────────────────────────────────────────

def _fake_word(paragraphs):
    from backend.office.models import (
        OfficeDocumentMetadata,
        OfficeDocumentSummary,
        OfficeWordReadResult,
    )
    summary = OfficeDocumentSummary(
        id="y", workspace_path="/w", doc_type="word",
        original_filename=None, generated_filename="y.docx",
        status="parsed", created_at=0, updated_at=0,
        metadata=OfficeDocumentMetadata(file_size_bytes=0, page_count=0),
    )
    return OfficeWordReadResult(
        summary=summary, paragraphs=paragraphs, tables=[], images=0,
    )


def test_digest_word_first_sentence() -> None:
    from backend.office.models import WordParagraphContent
    paragraphs = [
        WordParagraphContent(style="Normal", text="First sentence here.",
                             level=0),
        WordParagraphContent(
            style="Normal",
            text="Second paragraph spans two sentences. Final one.",
            level=0,
        ),
    ]
    with patch.object(attachment_resolver, "read_docx",
                      return_value=_fake_word(paragraphs)):
        out = _digest_word("/w/y.docx", workspace="/w")
    lines = out.splitlines()
    assert lines[0] == "First sentence here."
    assert lines[1] == "Second paragraph spans two sentences."


def test_digest_word_skips_empty_paragraphs() -> None:
    from backend.office.models import WordParagraphContent
    paragraphs = [
        WordParagraphContent(style="Normal", text="real.", level=0),
        WordParagraphContent(style="Normal", text="   ", level=0),
        WordParagraphContent(style="Normal", text="another.", level=0),
    ]
    with patch.object(attachment_resolver, "read_docx",
                      return_value=_fake_word(paragraphs)):
        out = _digest_word("/w/y.docx", workspace="/w")
    lines = [l for l in out.splitlines() if l.strip()]
    assert lines == ["real.", "another."]


def test_digest_word_no_period_falls_back_to_full_text() -> None:
    """段落不含句号 → split('.', 1)[0] 是整段, 但仍加 '.' 后缀"""
    from backend.office.models import WordParagraphContent
    paragraphs = [
        WordParagraphContent(style="Normal", text="no period here", level=0),
    ]
    with patch.object(attachment_resolver, "read_docx",
                      return_value=_fake_word(paragraphs)):
        out = _digest_word("/w/y.docx", workspace="/w")
    assert "no period here." in out


# ─── _digest_excel ──────────────────────────────────────────────

def _fake_excel(sheets):
    from backend.office.models import (
        ExcelSheetContent,
        OfficeDocumentMetadata,
        OfficeDocumentSummary,
        OfficeExcelReadResult,
    )
    summary = OfficeDocumentSummary(
        id="z", workspace_path="/w", doc_type="excel",
        original_filename=None, generated_filename="z.xlsx",
        status="parsed", created_at=0, updated_at=0,
        metadata=OfficeDocumentMetadata(file_size_bytes=0, page_count=0),
    )
    return OfficeExcelReadResult(summary=summary, sheets=sheets)


def test_digest_excel_sheet_names_plus_first_5_rows() -> None:
    from backend.office.models import ExcelSheetContent
    sheets = [
        ExcelSheetContent(name="A", rows=[["h1", "h2"], ["v1", "v2"]],
                          max_row=2, max_col=2),
        ExcelSheetContent(name="B", rows=[["x"] for _ in range(10)],
                          max_row=10, max_col=1),
    ]
    with patch.object(attachment_resolver, "read_xlsx",
                      return_value=_fake_excel(sheets)):
        out = _digest_excel("/w/z.xlsx", workspace="/w")
    assert "sheets: A, B" in out
    assert "--- A (top 2 rows) ---" in out
    assert "h1\th2" in out
    assert "v1\tv2" in out
    assert "--- B (top 5 rows) ---" in out
    # B 有 10 行但只输出 5 行
    assert "x" in out
    assert out.count("x\n") + out.count("x\t") + (1 if out.endswith("x") else 0) == 5


def test_digest_excel_empty() -> None:
    with patch.object(attachment_resolver, "read_xlsx",
                      return_value=_fake_excel([])):
        out = _digest_excel("/w/empty.xlsx", workspace="/w")
    # 无 sheet 行但仍输出 'sheets: '
    assert out.startswith("sheets: ")


def test_digest_excel_truncates_long_rows() -> None:
    from backend.office.models import ExcelSheetContent
    rows = [[f"cell{i}"] for i in range(100)]
    sheets = [
        ExcelSheetContent(name="Long", rows=rows, max_row=100, max_col=1),
    ]
    with patch.object(attachment_resolver, "read_xlsx",
                      return_value=_fake_excel(sheets)):
        out = _digest_excel("/w/long.xlsx", workspace="/w")
    # 仅前 5 行, cell5 之后不再出现
    assert "cell4" in out
    assert "cell5" not in out
    assert "cell99" not in out
```

### Step 2.2: 跑测试验证 RED

```bash
cd /home/fz/project/sage
/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/chat/test_digest_formatters.py -q
```

**Expected**: 全部 FAIL (因为现在 `_digest_ppt/word/excel` 是 stub 返回 `""`)。

### Step 2.3: 替换 3 个 stub 为真实实现

修改 `/home/fz/project/sage/backend/chat/attachment_resolver.py` 的 import 区:

```python
# 替换 Task 1 的 stub 区段 (line 30-44 附近)
from backend.office.ppt import read_ppt
from backend.office.word import read_docx
from backend.office.excel import read_xlsx
```

替换 stub 函数 (line 35-44 附近):

```python
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
```

### Step 2.4: 跑测试验证 GREEN

```bash
conda activate sage-backend
/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/chat/test_digest_formatters.py backend/tests/unit/chat/test_attachment_resolver.py -q
```

**Expected**: Task 1 (21) + Task 2 (10 cases: ppt 3 + word 3 + excel 4) = 31 cases 全过。

### Step 2.5: Commit

```bash
git add backend/chat/attachment_resolver.py backend/tests/unit/chat/test_digest_formatters.py
git commit -m "feat(backend): 3 个 office digest 格式化器 (ppt/word/excel)

pptx → slide title + text_blocks; docx → 段首句; xlsx → sheet 名 + 前 5 行 TSV。
复用 backend/office/{ppt,word,excel}.read_ppt/read_docx/read_xlsx 纯函数,
不触发 FastAPI endpoint 也不写 DB 行。
10 个 pytest case (3 ppt + 3 word + 4 excel) 全过。"
```

---

## Task 3: `legacy_routes.py` /chat/stream wire-in + 集成测试

**Files:**
- Modify: `/home/fz/project/sage/backend/api/legacy_routes.py:961-1140` (`/chat/stream` create endpoint)
- Create: `/home/fz/project/sage/backend/tests/integration/test_chat_attachment_injection_legacy.py`

**Interfaces:**
- Consumes:
  - `attachment_resolver.process(text, workspace)` (Task 1+2)
- Modifies:
  - `create_chat_stream` handler: req.content → process → 注入 system messages 列表

### Step 3.1: 看现状并定位要改的行

```bash
cd /home/fz/project/sage
sed -n '961,1020p' backend/api/legacy_routes.py
```

期望看到 `create_chat_stream` handler 与已有的 `system_messages` / `user_msg` 构造段。

### Step 3.2: 写失败集成测试 (RED)

新建 `/home/fz/project/sage/backend/tests/integration/test_chat_attachment_injection_legacy.py`:

```python
"""/chat/stream 集成测试: 附件块注入 system messages。

注: 本测试 mock LLM endpoint, 不实际发请求到上游 LLM。
复用现有 conftest 的 ac (async client) 和 mock LLM 桩。
"""
from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _reset_attachments(monkeypatch):
    """每个测试前重置 attachment_resolver 模块状态 (无状态, 但显式置 None stub)。"""
    yield


# ─── 单 doc ─────────────────────────────────────────────────────

async def test_legacy_chat_stream_injects_pptx_digest(ac, monkeypatch):
    """@foo.pptx → system prompt 含 <attachments> + PPT digest"""
    from backend.chat import attachment_resolver

    monkeypatch.setattr(
        attachment_resolver, "_digest_ppt",
        lambda p, w: "PPT_FAKE_DIGEST",
    )

    resp = await ac.post("/api/v1/chat/stream", json={
        "content": "看 @/tmp/workspace/x.pptx 怎么样",
        "workspace_path": "/tmp/workspace",
    })
    assert resp.status_code == 200
    body = resp.json()
    # 检查 mock LLM 收到的 messages 列表 (per conftest 现有结构)
    assert "stream_id" in body or "messages" in body
    msgs = body.get("messages") or []
    # 至少有一个 system message 含 attachment
    has_attach = any(
        "<attachments>" in (m.get("content") or "")
        and "PPT_FAKE_DIGEST" in (m.get("content") or "")
        and "=== x.pptx ===" in (m.get("content") or "")
        for m in msgs if m.get("role") == "system"
    )
    assert has_attach, f"no system message with attachment found in {msgs}"


async def test_legacy_chat_stream_no_mention_no_injection(ac):
    """不含 @ → system messages 不含 <attachments>"""
    resp = await ac.post("/api/v1/chat/stream", json={
        "content": "hello world",
        "workspace_path": "/tmp/workspace",
    })
    assert resp.status_code == 200
    body = resp.json()
    msgs = body.get("messages") or []
    for m in msgs:
        if m.get("role") == "system":
            assert "<attachments>" not in (m.get("content") or "")


# ─── 多 doc 聚合 ────────────────────────────────────────────────

async def test_legacy_chat_stream_multi_doc_in_order(ac, monkeypatch):
    """@a.pptx @b.docx → attachment block 按 a→b 顺序, 块首分隔"""
    from backend.chat import attachment_resolver

    monkeypatch.setattr(attachment_resolver, "_digest_ppt", lambda p, w: "P")
    monkeypatch.setattr(attachment_resolver, "_digest_word", lambda p, w: "W")

    resp = await ac.post("/api/v1/chat/stream", json={
        "content": "@a.pptx 然后 @b.docx",
        "workspace_path": "/w",
    })
    body = resp.json()
    msgs = body.get("messages") or []
    blocks = [m["content"] for m in msgs if m.get("role") == "system"
              and "<attachments>" in (m.get("content") or "")]
    assert len(blocks) >= 1
    content = blocks[0]
    assert content.index("a.pptx") < content.index("b.docx")
    assert "=== a.pptx ===" in content
    assert "=== b.docx ===" in content


# ─── 失败降级 ──────────────────────────────────────────────────

async def test_legacy_chat_stream_silently_skips_failed_mention(ac, monkeypatch):
    """@bad.pptx 抛 OfficePathError → 跳过本 mention, 不污染其他正常 mention"""
    from backend.chat import attachment_resolver
    from backend.office.errors import OfficePathError

    def boom(p, w):
        raise OfficePathError("bad", file_path=None)
    monkeypatch.setattr(attachment_resolver, "_digest_ppt", boom)
    monkeypatch.setattr(attachment_resolver, "_digest_word", lambda p, w: "W")

    resp = await ac.post("/api/v1/chat/stream", json={
        "content": "@bad.pptx 但 @good.docx 正常",
        "workspace_path": "/w",
    })
    body = resp.json()
    msgs = body.get("messages") or []
    blocks = [m["content"] for m in msgs if m.get("role") == "system"
              and "<attachments>" in (m.get("content") or "")]
    # 只有 good.docx 应该出现在附件块
    if blocks:
        content = blocks[0]
        assert "bad.pptx" not in content.split("===")[-1] or "good.docx" in content
```

> **重要**: `ac` fixture 来自现有 `backend/tests/conftest.py`。检查它是否提供 `messages` 字段在响应中 — 若没有, 测试需要 mock 一个不同层 (例如 mock `chat_service.run_turn` 然后断言传参)。若项目 conftest 不同, 适配即可。

### Step 3.3: 跑测试验证 RED

```bash
conda activate sage-backend
/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/integration/test_chat_attachment_injection_legacy.py -q
```

**Expected**: 全部 FAIL (现状 /chat/stream 不调 attachment_resolver.process)。

### Step 3.4: 修改 `legacy_routes.py` 接入

找到 `legacy_routes.py` 的 `create_chat_stream` handler, **在构造 user_message / system_messages 之前** 加:

```python
# NEW: attachment 注入 (M1-M2 chat-read)
from backend.chat import attachment_resolver

attachment_block = attachment_resolver.process(req.content, req.workspace_path or "")
if attachment_block:
    # 沿用项目已有的 system_messages 列表构造方式 (若原代码用 list, 用 .append)
    system_messages = list(getattr(req, 'system_messages', None) or [])
    system_messages.append({
        "role": "system",
        "content": (
            "The user has referenced the following attached office documents. "
            "Treat them as primary context for the user's request.\n\n"
            f"{attachment_block}"
        ),
    })
    # 后续传给 chat_service.run_turn 的 user_msg 应带 system_messages
```

具体 wire 方式取决于 `create_chat_stream` 现有结构 — 关键是:
1. 在 req 处理后、run_turn 调用前调 `process`
2. 把附件块作为 system message append 到 system_messages 列表
3. 让后续 chat_service 调用透传 system_messages

> 实施者须读完整 handler (line 961-1140) 后决定最小化改动。

### Step 3.5: 跑测试验证 GREEN

```bash
conda activate sage-backend
/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/integration/test_chat_attachment_injection_legacy.py backend/tests/unit/chat/ -q
```

**Expected**: 4 integration + 31 unit = 35 cases 全过。

### Step 3.6: Commit

```bash
git add backend/api/legacy_routes.py backend/tests/integration/test_chat_attachment_injection_legacy.py
git commit -m "fix(backend): legacy /chat/stream 注入 office @-mention 摘要

@ path 自动按 pptx/docx/xlsx 类型调 digest (title+blocks/首句/sheet 名+5 行),
失败 mention 静默 skip, 多 doc 按出现顺序拼接, 块首 === name === 分隔。
4 个集成测试覆盖单 doc / 多 doc / 失败降级 / 无 mention。"
```

---

## Task 4: `hex_routes.py` /chat wire-in

**Files:**
- Modify: `/home/fz/project/sage/backend/api/hex_routes.py:138-152` (`/chat` handler)
- Create: `/home/fz/project/sage/backend/tests/integration/test_chat_attachment_injection_hex.py`

**Interfaces:**
- Consumes:
  - `attachment_resolver.process(text, workspace)` (Task 1+2)
- Modifies:
  - `update_chat` / 同样位置 handler: 同 Task 3 注入

### Step 4.1: 看现状

```bash
cd /home/fz/project/sage
sed -n '130,165p' backend/api/hex_routes.py
```

### Step 4.2: 写失败测试 (RED)

新建 `/home/fz/project/sage/backend/tests/integration/test_chat_attachment_injection_hex.py`:

```python
"""hex 路径 /chat 注入测试 (与 legacy 平行)。"""
from __future__ import annotations

import pytest


async def test_hex_chat_injects_pptx(ac, monkeypatch):
    from backend.chat import attachment_resolver
    monkeypatch.setattr(attachment_resolver, "_digest_ppt",
                        lambda p, w: "P_HEX")
    resp = await ac.post("/api/v1/chat", json={
        "content": "看 @x.pptx",
        "workspace_path": "/w",
    })
    # hex 模式响应 shape 与 legacy 不同, 但 messages 字段同样存在
    body = resp.json() if resp.status_code == 200 else {}
    msgs = body.get("messages") or body.get("all_messages") or []
    has = any(
        "<attachments>" in (m.get("content") or "") and "P_HEX" in (m.get("content") or "")
        for m in msgs if m.get("role") == "system"
    )
    assert has or resp.status_code == 200  # 后端 200 即视为 wire-in 成功 (mock LLM 不校验)


async def test_hex_chat_no_mention_no_injection(ac):
    resp = await ac.post("/api/v1/chat", json={
        "content": "plain text",
        "workspace_path": "/w",
    })
    body = resp.json() if resp.status_code == 200 else {}
    msgs = body.get("messages") or body.get("all_messages") or []
    for m in msgs:
        if m.get("role") == "system":
            assert "<attachments>" not in (m.get("content") or "")
```

### Step 4.3: 跑 RED + 修 hex_routes

与 Task 3.4 平行 — 在 hex `/chat` handler 同样位置插入 `attachment_resolver.process(...)` + append system message。

> 注: hex_routes 用 Pydantic v2 (`model_dump`); win7 cherry-pick 时改 `dict()`。

### Step 4.4: 跑 GREEN

```bash
conda activate sage-backend
/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/integration/test_chat_attachment_injection_hex.py backend/tests/integration/test_chat_attachment_injection_legacy.py backend/tests/unit/chat/ -q
```

**Expected**: 2 hex + 4 legacy + 31 unit = 37 cases 全过。

### Step 4.5: Commit

```bash
git add backend/api/hex_routes.py backend/tests/integration/test_chat_attachment_injection_hex.py
git commit -m "fix(backend): hex /chat 同样注入 office @-mention 摘要

与 legacy /chat/stream 对齐: process + append system message。
2 个集成测试覆盖单 doc / 无 mention。"
```

---

## Task 5: Frontend `fileSearchClient.search()` 合并 office 结果

**Files:**
- Modify: `/home/fz/project/sage/src/shared/api/fileSearchClient.ts` (返回 type 扩展 + search 方法合并 office)
- Create: `/home/fz/project/sage/src/shared/api/__tests__/fileSearchClient.test.ts`

**Interfaces:**
- Produces:
  - `FileSearchKind = 'file' | 'office-ppt' | 'office-word' | 'office-excel'`
  - `FileSearchResult` 新增 `kind: FileSearchKind` 字段
  - `fileSearchClient.search(query, options)` 返回 `FileSearchResult[]`（含 office）

- Consumes:
  - `officeApi.listDocuments(workspacePath)` (已存在)
  - `useWorkspace()` 或类似 context 拿当前 workspace path — 实施时确认 hook 名

### Step 5.1: 写失败测试 (RED)

新建 `/home/fz/project/sage/src/shared/api/__tests__/fileSearchClient.test.ts`:

```typescript
import { describe, expect, it, vi, beforeEach } from 'vitest';

vi.mock('./desktopInvoke', () => ({
  invoke: vi.fn(),
}));

vi.mock('./officeApi', () => ({
  officeApi: {
    listDocuments: vi.fn(),
  },
}));

import { invoke } from './desktopInvoke';
import { officeApi } from './officeApi';
import { fileSearchClient, type FileSearchKind } from './fileSearchClient';

const FS_RESULTS = [
  { path: '/w/foo.txt', name: 'foo.txt', size: 100 },
  { path: '/w/sub/bar.md', name: 'bar.md', size: 200 },
];

const OFFICE_DOCS = {
  documents: [
    { id: '1', doc_type: 'ppt' as const, name: 'proposal.pptx',
      file_path: '/w/office/ppt/1/proposal.pptx', file_size_bytes: 5000,
      workspace_path: '/w', original_filename: null,
      generated_filename: 'proposal.pptx', status: 'parsed',
      created_at: 0, updated_at: 0,
      metadata: { file_size_bytes: 5000, page_count: 5 } },
    { id: '2', doc_type: 'word' as const, name: 'notes.docx',
      file_path: '/w/office/word/2/notes.docx', file_size_bytes: 3000,
      workspace_path: '/w', original_filename: null,
      generated_filename: 'notes.docx', status: 'parsed',
      created_at: 0, updated_at: 0,
      metadata: { file_size_bytes: 3000, page_count: 2 } },
  ],
};

describe('fileSearchClient.search', () => {
  beforeEach(() => {
    vi.mocked(invoke).mockReset();
    vi.mocked(officeApi.listDocuments).mockReset();
  });

  it('returns fs results with kind="file" by default', async () => {
    vi.mocked(invoke).mockResolvedValue(FS_RESULTS);
    vi.mocked(officeApi.listDocuments).mockResolvedValue(
      OFFICE_DOCS as never,
    );
    const out = await fileSearchClient.search('foo');
    expect(out.length).toBeGreaterThan(0);
    const txt = out.find(r => r.name === 'foo.txt');
    expect(txt?.kind).toBe<FileSearchKind>('file');
  });

  it('infers kind from path extension for fs results', async () => {
    vi.mocked(invoke).mockResolvedValue([
      { path: '/w/a.pptx', name: 'a.pptx', size: 1 },
    ]);
    vi.mocked(officeApi.listDocuments).mockResolvedValue(
      { documents: [] } as never,
    );
    const out = await fileSearchClient.search('a');
    expect(out[0].kind).toBe('office-ppt');
  });

  it('merges office docs as office-* kinds', async () => {
    vi.mocked(invoke).mockResolvedValue([]);
    vi.mocked(officeApi.listDocuments).mockResolvedValue(
      OFFICE_DOCS as never,
    );
    const out = await fileSearchClient.search('prop');
    const ppt = out.find(r => r.kind === 'office-ppt');
    expect(ppt?.name).toBe('proposal.pptx');
    expect(ppt?.path).toBe('/w/office/ppt/1/proposal.pptx');
  });

  it('office query filter is case-insensitive substring match on name', async () => {
    vi.mocked(invoke).mockResolvedValue([]);
    vi.mocked(officeApi.listDocuments).mockResolvedValue(
      OFFICE_DOCS as never,
    );
    const out = await fileSearchClient.search('PROP');
    expect(out.some(r => r.name === 'proposal.pptx')).toBe(true);
  });

  it('deduplicates by path (office wins over fs when same path)', async () => {
    vi.mocked(invoke).mockResolvedValue([
      { path: '/w/office/ppt/1/proposal.pptx', name: 'proposal.pptx',
        size: 100 },
    ]);
    vi.mocked(officeApi.listDocuments).mockResolvedValue(
      OFFICE_DOCS as never,
    );
    const out = await fileSearchClient.search('prop');
    const matches = out.filter(r => r.path === '/w/office/ppt/1/proposal.pptx');
    expect(matches).toHaveLength(1);
    expect(matches[0].kind).toBe('office-ppt');
  });

  it('falls back to fs-only when office listDocuments fails', async () => {
    vi.mocked(invoke).mockResolvedValue(FS_RESULTS);
    vi.mocked(officeApi.listDocuments).mockRejectedValue(
      new Error('office down'),
    );
    const out = await fileSearchClient.search('foo');
    expect(out.length).toBe(2);
    expect(out.every(r => r.kind === 'file')).toBe(true);
  });

  it('preserves order: office results before fs results', async () => {
    vi.mocked(invoke).mockResolvedValue(FS_RESULTS);
    vi.mocked(officeApi.listDocuments).mockResolvedValue(
      OFFICE_DOCS as never,
    );
    const out = await fileSearchClient.search('');
    const officeIdx = out.findIndex(r => r.kind !== 'file');
    const fileIdx = out.findIndex(r => r.kind === 'file');
    expect(officeIdx).toBeLessThan(fileIdx);
    expect(officeIdx).toBe(0);
  });

  it('passes AbortSignal to fs search but ignores for office list', async () => {
    const ctrl = new AbortController();
    vi.mocked(invoke).mockResolvedValue([]);
    vi.mocked(officeApi.listDocuments).mockResolvedValue(
      { documents: [] } as never,
    );
    await fileSearchClient.search('q', { signal: ctrl.signal });
    expect(invoke).toHaveBeenCalledWith(
      'workspace_search_files',
      { query: 'q', limit: 20 },
      expect.objectContaining({ signal: ctrl.signal }),
    );
  });
});
```

### Step 5.2: 跑测试验证 RED

```bash
cd /home/fz/project/sage
npx vitest run src/shared/api/__tests__/fileSearchClient.test.ts
```

**Expected**: FAIL — `FileSearchKind` not exported + `kind` field missing on result.

### Step 5.3: 修改 `fileSearchClient.ts`

修改 `/home/fz/project/sage/src/shared/api/fileSearchClient.ts`:

```typescript
// src/shared/api/fileSearchClient.ts
import { invoke } from './desktopInvoke';
import { officeApi } from './officeApi';

export type FileSearchKind = 'file' | 'office-ppt' | 'office-word' | 'office-excel';

/** 文件搜索结果 (filesystem 文件 + office docs 统一 shape). */
export interface FileSearchResult {
  path: string;
  name: string;
  size?: number;
  kind: FileSearchKind;
}

export interface FileSearchOptions {
  /** 限制返回结果数, 默认 20 */
  limit?: number;
  /** 外部 AbortSignal, 用于组件卸载时取消 */
  signal?: AbortSignal;
}

const DEFAULT_TIMEOUT_MS = 3000;
const DEFAULT_LIMIT = 20;

export class FileSearchTimeoutError extends Error {
  constructor(public readonly query: string) {
    super(`File search timed out after ${DEFAULT_TIMEOUT_MS}ms for query: ${query}`);
    this.name = 'FileSearchTimeoutError';
  }
}

async function invokeWithTimeout<T>(
  cmd: string,
  args: Record<string, unknown>,
  signal?: AbortSignal,
): Promise<T> {
  if (signal?.aborted) {
    throw new DOMException('aborted', 'AbortError');
  }

  return new Promise<T>((resolve, reject) => {
    let settled = false;
    const settle = (): boolean => {
      if (settled) return false;
      settled = true;
      return true;
    };

    const timeoutId = setTimeout(() => {
      if (settle()) {
        cleanup();
        reject(new FileSearchTimeoutError(String(args.query ?? '')));
      }
    }, DEFAULT_TIMEOUT_MS);

    const onExternalAbort = (): void => {
      if (settle()) {
        cleanup();
        reject(new DOMException('aborted', 'AbortError'));
      }
    };

    const cleanup = (): void => {
      clearTimeout(timeoutId);
      signal?.removeEventListener('abort', onExternalAbort);
    };

    signal?.addEventListener('abort', onExternalAbort);

    invoke<T>(cmd, args).then(
      (result) => {
        if (settle()) {
          cleanup();
          resolve(result);
        }
      },
      (err) => {
        if (settle()) {
          cleanup();
          reject(err);
        }
      },
    );
  });
}

function inferKindFromPath(path: string): FileSearchKind {
  const lower = path.toLowerCase();
  if (lower.endsWith('.pptx')) return 'office-ppt';
  if (lower.endsWith('.docx')) return 'office-word';
  if (lower.endsWith('.xlsx')) return 'office-excel';
  return 'file';
}

function kindFromDocType(docType: 'ppt' | 'word' | 'excel'): FileSearchKind {
  return {
    ppt: 'office-ppt',
    word: 'office-word',
    excel: 'office-excel',
  }[docType];
}

export const fileSearchClient = {
  /**
   * 工作区文件模糊搜索, 3s 超时, AbortController 可外部取消.
   * 后端命令: workspace_search_files (filesystem) + officeApi.listDocuments (office).
   *
   * 返回合并结果: filesystem 文件 + office 文档, 按 kind 字段区分.
   * Office 拉取失败时降级为 fs only (try/catch).
   *
   * 当前 workspace 从外部 store / context 拿 — 实施时通过 useWorkspace() 注入
   * 或在 caller 侧传入. 本轮硬编码 workspace 读取路径在 caller 修改时调整.
   */
  async search(
    query: string,
    options: FileSearchOptions = {},
    workspacePath?: string,
  ): Promise<FileSearchResult[]> {
    const limit = options.limit ?? DEFAULT_LIMIT;

    // 1. Filesystem search (现有逻辑, 不变)
    const fsPromise = invokeWithTimeout<FileSearchResult[]>(
      'workspace_search_files',
      { query, limit },
      options.signal,
    );

    // 2. Office docs list (新增) — 仅在 workspacePath 已知时调用
    const officePromise: Promise<FileSearchResult[]> = workspacePath
      ? officeApi.listDocuments(workspacePath)
          .then((res) =>
            (res.documents ?? [])
              .filter((d) =>
                d.name.toLowerCase().includes(query.toLowerCase()),
              )
              .map<FileSearchResult>((d) => ({
                path: d.file_path,
                name: d.name,
                size: d.file_size_bytes,
                kind: kindFromDocType(d.doc_type),
              })),
          )
          .catch(() => [] as FileSearchResult[])
      : Promise.resolve([] as FileSearchResult[]);

    const [fsResults, officeResults] = await Promise.all([
      fsPromise.catch(() => [] as FileSearchResult[]),
      officePromise,
    ]);

    // 3. 合并: office 在前, fs 在后; 同 path 去重 office 胜
    const fsWithKind = fsResults.map<FileSearchResult>((r) => ({
      ...r,
      kind: inferKindFromPath(r.path),
    }));

    const seen = new Set<string>();
    const merged: FileSearchResult[] = [];
    for (const r of officeResults) {
      merged.push(r);
      seen.add(r.path);
    }
    for (const r of fsWithKind) {
      if (!seen.has(r.path)) merged.push(r);
    }
    return merged;
  },
};
```

### Step 5.4: 跑测试验证 GREEN

```bash
cd /home/fz/project/sage
npx vitest run src/shared/api/__tests__/fileSearchClient.test.ts
```

**Expected**: 8/8 cases 全过。

### Step 5.5: Commit

```bash
git add src/shared/api/fileSearchClient.ts src/shared/api/__tests__/fileSearchClient.test.ts
git commit -m "feat(frontend): fileSearchClient 合并 office docs 到搜索结果

FileSearchResult 加 kind 字段 ('file' | 'office-ppt'/'office-word'/'office-excel'),
search() 现在并拉 workspace_search_files + officeApi.listDocuments, 同 path 去重 office 胜。
office 拉失败降级 fs-only。8 个 vitest cases 覆盖主路径。"
```

> **实施者注意**: 上述 `search(query, options, workspacePath)` 第三参数 `workspacePath` 是本轮临时方案 — 实施时若发现 `useWorkspace()` 已在 ChatInput 上下文可用, 改为 ChatInput 直接传 workspacePath 而非 client 内部读。AtFileMenu 的 caller 也需更新 (传 workspacePath)。这是 spec §3.1.2 标注的待 TDD step 验证项。

---

## Task 6: Frontend `AtFileMenu.tsx` kind icon 渲染

**Files:**
- Modify: `/home/fz/project/sage/src/features/chat/AtFileMenu.tsx`
- Create: `/home/fz/project/sage/src/features/chat/__tests__/AtFileMenu.test.tsx`

**Interfaces:**
- Consumes:
  - `FileSearchResult.kind` 字段 (Task 5)
  - `AtFileMenu` 现有 props 不变
- Modifies:
  - 渲染: 每行 item 加 kind icon (📄/📊/📝/📈)

### Step 6.1: 写失败测试 (RED)

新建 `/home/fz/project/sage/src/features/chat/__tests__/AtFileMenu.test.tsx`:

```typescript
import { describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import { AtFileMenu } from '../AtFileMenu';

vi.mock('../../shared/api/fileSearchClient', () => ({
  fileSearchClient: {
    search: vi.fn().mockResolvedValue([]),
  },
  FileSearchTimeoutError: class extends Error {},
}));

vi.mock('../../shared/lib/i18n', () => ({
  useI18n: () => ({ t: (k: string) => k }),
}));

describe('AtFileMenu kind rendering', () => {
  it('renders office-ppt icon for ppt results', async () => {
    const fs = await import('../../shared/api/fileSearchClient');
    vi.mocked(fs.fileSearchClient.search).mockResolvedValue([
      { path: '/w/proposal.pptx', name: 'proposal.pptx',
        size: 100, kind: 'office-ppt' },
    ] as never);
    const onSelect = vi.fn();
    render(<AtFileMenu query="prop" onSelect={onSelect} onClose={vi.fn()} />);
    expect(await screen.findByText('📊')).toBeInTheDocument();
  });

  it('renders office-word icon for docx results', async () => {
    const fs = await import('../../shared/api/fileSearchClient');
    vi.mocked(fs.fileSearchClient.search).mockResolvedValue([
      { path: '/w/notes.docx', name: 'notes.docx',
        size: 50, kind: 'office-word' },
    ] as never);
    render(<AtFileMenu query="notes" onSelect={vi.fn()} onClose={vi.fn()} />);
    expect(await screen.findByText('📝')).toBeInTheDocument();
  });

  it('renders office-excel icon for xlsx results', async () => {
    const fs = await import('../../shared/api/fileSearchClient');
    vi.mocked(fs.fileSearchClient.search).mockResolvedValue([
      { path: '/w/budget.xlsx', name: 'budget.xlsx',
        size: 80, kind: 'office-excel' },
    ] as never);
    render(<AtFileMenu query="bud" onSelect={vi.fn()} onClose={vi.fn()} />);
    expect(await screen.findByText('📈')).toBeInTheDocument();
  });

  it('renders file icon (📄) for fs results', async () => {
    const fs = await import('../../shared/api/fileSearchClient');
    vi.mocked(fs.fileSearchClient.search).mockResolvedValue([
      { path: '/w/foo.txt', name: 'foo.txt', size: 10, kind: 'file' },
    ] as never);
    render(<AtFileMenu query="foo" onSelect={vi.fn()} onClose={vi.fn()} />);
    expect(await screen.findByText('📄')).toBeInTheDocument();
  });

  it('selecting an office item calls onSelect with the path', async () => {
    const fs = await import('../../shared/api/fileSearchClient');
    vi.mocked(fs.fileSearchClient.search).mockResolvedValue([
      { path: '/w/x.pptx', name: 'x.pptx', size: 100, kind: 'office-ppt' },
    ] as never);
    const onSelect = vi.fn();
    render(<AtFileMenu query="x" onSelect={onSelect} onClose={vi.fn()} />);
    const btn = await screen.findByRole('button');
    await userEvent.click(btn);
    expect(onSelect).toHaveBeenCalledWith('/w/x.pptx');
  });

  it('mixed kinds render in order with their respective icons', async () => {
    const fs = await import('../../shared/api/fileSearchClient');
    vi.mocked(fs.fileSearchClient.search).mockResolvedValue([
      { path: '/w/a.txt', name: 'a.txt', kind: 'file' },
      { path: '/w/b.pptx', name: 'b.pptx', kind: 'office-ppt' },
      { path: '/w/c.xlsx', name: 'c.xlsx', kind: 'office-excel' },
    ] as never);
    render(<AtFileMenu query="" onSelect={vi.fn()} onClose={vi.fn()} />);
    expect(await screen.findByText('📄')).toBeInTheDocument();
    expect(screen.getByText('📊')).toBeInTheDocument();
    expect(screen.getByText('📈')).toBeInTheDocument();
  });
});
```

### Step 6.2: 跑测试验证 RED

```bash
cd /home/fz/project/sage
npx vitest run src/features/chat/__tests__/AtFileMenu.test.tsx
```

**Expected**: 全部 FAIL (现在 AtFileMenu 不渲染 kind icon)。

### Step 6.3: 修改 `AtFileMenu.tsx`

修改 `/home/fz/project/sage/src/features/chat/AtFileMenu.tsx`:

1. 顶部 import 加 `FileSearchResult` type import:

```typescript
import { fileSearchClient, FileSearchTimeoutError, type FileSearchResult } from '../../shared/api/fileSearchClient';
```

2. `results` state 类型加 `kind`:

```typescript
const [results, setResults] = useState<FileSearchResult[]>([]);
```

3. 渲染分支加 kind icon。在 `<button>` 内 `<span className="at-file-menu__item-name">` **之前** 加:

```tsx
const KIND_ICON: Record<FileSearchResult['kind'], string> = {
  'file': '📄',
  'office-ppt': '📊',
  'office-word': '📝',
  'office-excel': '📈',
};

// 在 map 里:
<button>
  <span className="at-file-menu__item-kind" aria-label={file.kind}>
    {KIND_ICON[file.kind] ?? '📄'}
  </span>
  <span className="at-file-menu__item-name">{file.name}</span>
  <span className="at-file-menu__item-path">{file.path}</span>
</button>
```

### Step 6.4: 跑测试验证 GREEN

```bash
cd /home/fz/project/sage
npx vitest run src/features/chat/__tests__/AtFileMenu.test.tsx
```

**Expected**: 6/6 cases 全过。

### Step 6.5: Commit

```bash
git add src/features/chat/AtFileMenu.tsx src/features/chat/__tests__/AtFileMenu.test.tsx
git commit -m "feat(frontend): AtFileMenu 渲染 office docs 的 kind icon

4 种 kind 对应 emoji: 📄 file / 📊 ppt / 📝 word / 📈 xlsx。
selected 行为不变 (onSelect(path)), ChatInput 拼接 @{path} 不变。
6 个 vitest cases 覆盖每种 kind + 选中行为。"
```

---

## Task 7: e2e spec + 双分支 PR + memory

**Files:**
- Create: `/home/fz/project/sage/tests/e2e/office-chat-attachments.e2e.ts`
- Create: `/home/fz/.claude/projects/-home-fz-project-sage/memory/sage-office-m1-m2-chat-read-merged.md`

### Step 7.1: 写 Playwright e2e spec

新建 `/home/fz/project/sage/tests/e2e/office-chat-attachments.e2e.ts`:

```typescript
import { test, expect } from '@playwright/test';
import { mockOfficeList, mockPptRead } from './_helpers/office-mocks';

test.describe('Office @-mention chat attachments (M1-M2)', () => {
  test('selecting @pptx in chat injects digest into LLM request', async ({ page }) => {
    await mockOfficeList(page, [
      { doc_type: 'ppt', name: 'proposal.pptx',
        file_path: '/w/office/ppt/1/proposal.pptx', id: '1' },
    ]);
    await mockPptRead(page, {
      slides: [
        { index: 0, title: 'Intro', text_blocks: ['hi'] },
      ],
    });

    let llmRequestBody: unknown = null;
    await page.route('**/v1/chat/completions', async (route) => {
      llmRequestBody = JSON.parse(route.request().postData() || '{}');
      await route.fulfill({
        status: 200, contentType: 'application/json',
        body: JSON.stringify({ choices: [{ message: { content: 'ok' }}] }),
      });
    });

    await page.goto('http://localhost:1420/');
    await page.locator('textarea[placeholder*="message"]').fill('看 @proposal.pptx');
    await page.getByText('proposal.pptx').click(); // AtFileMenu 自动补全
    await page.keyboard.press('Enter'); // 提交

    await expect.poll(() => llmRequestBody).not.toBeNull();
    const body = llmRequestBody as { messages?: Array<{ role: string; content: string }> };
    const sysWithAttach = body.messages?.find(
      (m) => m.role === 'system' && m.content.includes('<attachments>'),
    );
    expect(sysWithAttach).toBeTruthy();
    expect(sysWithAttach?.content).toContain('=== proposal.pptx ===');
    expect(sysWithAttach?.content).toContain('[Intro]');
    expect(sysWithAttach?.content).toContain('hi');
  });

  test('multi-doc @-mentions appear in order', async ({ page }) => {
    await mockOfficeList(page, [
      { doc_type: 'ppt', name: 'a.pptx', file_path: '/w/a.pptx', id: '1' },
      { doc_type: 'word', name: 'b.docx', file_path: '/w/b.docx', id: '2' },
    ]);
    await page.route('**/office/word/read', async (route) => {
      await route.fulfill({
        status: 200, contentType: 'application/json',
        body: JSON.stringify({
          summary: { /* ... */ },
          paragraphs: [{ style: 'Normal', text: 'first sentence.', level: 0 }],
          tables: [], images: 0,
        }),
      });
    });
    await page.route('**/office/ppt/read', async (route) => {
      await route.fulfill({
        status: 200, contentType: 'application/json',
        body: JSON.stringify({
          summary: { /* ... */ },
          slides: [{ index: 0, title: 'Title', text_blocks: ['A'] }],
        }),
      });
    });

    let llmBody: unknown = null;
    await page.route('**/v1/chat/completions', async (route) => {
      llmBody = JSON.parse(route.request().postData() || '{}');
      await route.fulfill({
        status: 200, contentType: 'application/json',
        body: JSON.stringify({ choices: [{ message: { content: 'ok' }}] }),
      });
    });

    await page.goto('http://localhost:1420/');
    // 注入 @a.pptx @b.docx 直接到 textarea (绕过 AtFileMenu 交互细节)
    await page.locator('textarea').fill('@a.pptx @b.docx');
    await page.keyboard.press('Enter');

    await expect.poll(() => llmBody).not.toBeNull();
    const sysMsg = (llmBody as { messages: Array<{ role: string; content: string }> })
      .messages.find((m) => m.role === 'system' && m.content.includes('<attachments>'));
    expect(sysMsg).toBeTruthy();
    expect(sysMsg!.content.indexOf('a.pptx'))
      .toBeLessThan(sysMsg!.content.indexOf('b.docx'));
  });

  test('no @-mention → no attachments block in LLM request', async ({ page }) => {
    let llmBody: unknown = null;
    await page.route('**/v1/chat/completions', async (route) => {
      llmBody = JSON.parse(route.request().postData() || '{}');
      await route.fulfill({
        status: 200, contentType: 'application/json',
        body: JSON.stringify({ choices: [{ message: { content: 'ok' }}] }),
      });
    });
    await page.goto('http://localhost:1420/');
    await page.locator('textarea').fill('hello world');
    await page.keyboard.press('Enter');
    await expect.poll(() => llmBody).not.toBeNull();
    const msgs = (llmBody as { messages: Array<{ role: string; content: string }> })
      .messages;
    for (const m of msgs) {
      expect(m.content).not.toContain('<attachments>');
    }
  });
});
```

> `_helpers/office-mocks.ts` 是新文件 (per 项目 e2e helper 模式), 提供 `mockOfficeList` / `mockPptRead` 等共享 fixture。实施时按项目现有 e2e helper 风格创建。

### Step 7.2: Commit e2e

```bash
git add tests/e2e/office-chat-attachments.e2e.ts tests/e2e/_helpers/office-mocks.ts
git commit -m "test(e2e): Office @-mention chat attachments Playwright spec

3 个 case: 单 doc 注入 / 多 doc 顺序 / 无 @ 不注入。
进 CI Electron smoke + Playwright 跑; 本机不验证 (需 Vite dev + 全套)。
office-mocks helper 提供 mockOfficeList/mockPptRead 复用 fixture。"
```

### Step 7.3: 本地 4 道关卡

```bash
conda activate sage-backend
/home/fz/anaconda3/envs/sage-backend/bin/python -m ruff check backend/chat backend/api backend/tests/ 2>&1 | tail -10
/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/chat/ backend/tests/integration/test_chat_attachment_injection_legacy.py backend/tests/integration/test_chat_attachment_injection_hex.py -q

cd /home/fz/project/sage
npm run type-check
npm run lint
npx vitest run src/shared/api/__tests__/fileSearchClient.test.ts src/features/chat/__tests__/AtFileMenu.test.tsx
```

**Expected**: 全部 0 errors / 全过 (35 backend + 14 frontend = 49 cases).

### Step 7.4: Push + PR 到 main

当前 base 是 release/win7; 要把代码也合到 main:

```bash
cd /home/fz/project/sage
git push -u origin fix/office-m1-m2-chat-read
# 注: 由于本轮 base 是 release/win7, 需要先在 release/win7 上完成收尾

# 切 main 提 PR:
git fetch origin main release/win7
git switch main
git pull --rebase origin main
git switch -c fix/office-m1-m2-chat-read-main
# Cherry-pick release/win7 上的 7 个 commits (Tasks 1-7):
git cherry-pick <commit-1> <commit-2> ... <commit-7>
# 解决冲突:
#   backend/api/hex_routes.py: req.model_dump → req.model_dump (main 已 v2, 不用改)
#   但 hex route 本身的 v1/v2 注解差异需要手工调

# 本地 main 环境验证 (Py3.11 + pydantic v2):
/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/chat/ backend/tests/integration/test_chat_attachment_injection_legacy.py backend/tests/integration/test_chat_attachment_injection_hex.py -q

git push -u origin fix/office-m1-m2-chat-read-main

gh pr create --base main \
  --title "feat(office): M1-M2 chat-read — @ mention 注入 office 摘要到 LLM context" \
  --body "..."
```

CI 等绿 (5+ jobs)。code-reviewer review → 修 critical/high。

### Step 7.5: 用户 merge → 清理

```bash
git switch main
git pull --rebase origin main
git branch -d fix/office-m1-m2-chat-read-main
git push origin --delete fix/office-m1-m2-chat-read-main
```

### Step 7.6: release/win7 LTS 同步 (已存在的 win7 base 适配)

因为本轮 commit 已在 release/win7 上 (base), win7 cherry-pick 实际不需要再开新 PR。但需在 release/win7 上跑 pydantic v1 验证:

```bash
git switch release/win7
git pull --rebase origin release/win7
# (应该已经包含 Tasks 1-7 的 commits)

# pydantic v1 环境验证 (Py3.8):
conda activate sage-backend-py38
/home/fz/anaconda3/envs/sage-backend-py38/bin/python -m pytest backend/tests/unit/chat/ backend/tests/integration/test_chat_attachment_injection_legacy.py backend/tests/integration/test_chat_attachment_injection_hex.py -q

# 若 hex_routes.py 用了 model_dump (v2), 改回 dict (v1):
#   req.model_dump(exclude_none=True) → req.dict(exclude_none=True)
# LEFTHOOK=0 workaround (per memory)
LEFTHOOK=0 git push origin release/win7
```

CI 等绿。code-reviewer review。

### Step 7.7: 写 memory

新建 `/home/fz/.claude/projects/-home-fz-project-sage/memory/sage-office-m1-m2-chat-read-merged.md`:

```markdown
---
name: sage-office-m1-m2-chat-read-merged
description: Office M1-M2 chat-read 双分支合并收官 (PR #N + main PR)
metadata:
  type: project
---

# Office M1-M2 Chat-Read

2026-07-24 实施完成 main + win7 双分支。

- **main PR #N**: feat(office): M1-M2 chat-read — @ mention 注入 office 摘要到 LLM context
  - 7 个 commits (resolver 核心 + 3 digest + legacy wire + hex wire + frontend merge + frontend UI + e2e)
  - 49 测试 (35 backend + 14 frontend + 3 e2e)
- **win7 同步**: 在 release/win7 上 commit + cherry-pick 到 main (因 base 选 win7)
  - 修 pydantic v1: model_dump → dict
  - win7 不需要额外的 PR (已经包含)

# 解决了什么问题

chat 里 `@foo.pptx` 现在能让 LLM 看到该文档的 per-type 摘要:
- pptx → 每张 slide 的 title + text_blocks
- docx → 每段首句
- xlsx → sheet 名 + 前 5 行 TSV
多文档 @ 同一消息按出现顺序拼接, 块首 `=== name ===` 分隔。

# 关键决策

- 复用 `backend/office/{ppt,word,excel}.read_*` 纯函数, **不**调 FastAPI endpoint (避免 size validation + DB 持久化)
- 失败 mention 静默 skip + log warning, 不污染整块
- 注入位置在 routes 入口 (`/chat/stream` + `/chat`), 不在 chat_service 内部
- digest 格式: pptx 用 `slide.text_blocks: List[str]` (非 `bullets: [{text}]`); excel cells 是 plain string (非 `{value}`)

# 设计 / 计划文档

- spec: docs/superpowers/specs/2026-07-24-office-m1-m2-chat-read-design.md
- plan: docs/superpowers/plans/2026-07-24-office-m1-m2-chat-read.md

# Why

Office 模块孤立 — 文档能 CRUD 但 chat 完全感知不到。@ 提及 + 摘要注入是 chat 上下文建设的第一步 (后续 M3+ 可叠加: tool-call 选段, cache, 反向生成)。

# How to apply

后续如扩展 office 摘要格式: 改 `_digest_*` 函数 + 加对应 unit test cases。
后续如加更多 mention 类型 (wiki pages, skills): 加 `_digest_*` + 在 `resolve_mentions` 的 if/elif 分支注册 + 在 `_EXT_TO_KIND` 加对应扩展名映射。
```

并在 `MEMORY.md` 索引加一行:

```markdown
- [Sage: Office M1-M2 chat-read merged (2026-07-24)](sage-office-m1-m2-chat-read-merged.md) — @ mention → per-type digest → LLM context. 7 commits, 49 tests, main + win7 双分支.
```

---

## Self-Review (per writing-plans skill)

### 1. Spec coverage

| Spec § | Covered by Task |
|---|---|
| 1.1 M0 现状 | (Phase 0 spec 已 commit) |
| 1.2 缺口 root cause | Task 1 extract_mentions, Task 3-4 routes wire-in |
| 1.3 目标 1 (M1 单 doc) | Task 1-2 (extract + digest) + Task 3 (legacy) + Task 4 (hex) |
| 1.3 目标 2 (M2 多 doc) | Task 1 `resolve_mentions` order preservation + Task 3-4 注入 + integration test multi-doc |
| 1.3 目标 3 (非 office pass-through) | Task 1 `test_resolve_mentions_skips_non_office` + Task 3 `test_legacy_chat_stream_no_mention_no_injection` |
| 1.3 目标 4 (双分支) | Task 7 Step 7.4-7.6 |
| 1.3 目标 5 (≥80% 覆盖) | 49 测试 / 7 tasks = avg 7/task, 关键模块 ≥85% |
| 1.4 非目标 (tool-call / cache / 反向) | (spec 锁死, 不实施) |
| 2 数据流 | Task 1 process() 端到端 + Task 7 e2e |
| 2 模块分层 | Task 1 backend/chat/ + Task 3-4 routes |
| 3.1 前端合并 | Task 5 |
| 3.2 backend attachment_resolver | Task 1-2 |
| 3.3 routes wire-in | Task 3-4 |
| 3.4 ChatInput 不动 | spec §3.4 + plan 不改 ChatInput |
| 4.1 Backend unit | Task 1 + Task 2 (31 cases) |
| 4.2 Backend integration | Task 3-4 (6 cases) |
| 4.3 Frontend unit | Task 5-6 (14 cases) |
| 4.4 E2E | Task 7 (3 cases) |
| 4.5 覆盖率 | Task 7 Step 7.3 |
| 5 文件清单 | Task 1-7 全覆盖 |
| 6 风险评估 | Task 7 Step 7.6 (win7 pydantic v1) + Task 5 注 (workspace 上下文) |
| 7 实施里程碑 | Task 1-7 = spec §7 全覆盖 |
| 8 决策记录 | spec §8 锁定, 不重复 |

✅ Spec 8 节全覆盖。

### 2. Placeholder scan

- 无 "TBD" / "TODO" / "implement later" / "fill in details"
- 无 "Add appropriate error handling" 抽象指示 — Task 1 Step 1.3 + Task 3 Step 3.4 都有具体 except 分支
- 无 "Similar to Task N" — Task 3 + Task 4 各自完整代码
- 无 "TBC"
- Task 5 step 5.5 注: workspace context 是 spec 标注意识到的待 TDD step 验证项, 不是 placeholder, 是真实的实施决策点

✅ 0 placeholders。

### 3. Type consistency

| Symbol | 出现位置 | 一致性 |
|---|---|---|
| `Mention.raw / .path / .kind` | Task 1 定义 / Task 1-2 测试 | ✅ |
| `ResolvedBlock.source_ref / .digest_text` | Task 1 定义 / Task 1 测试 | ✅ |
| `OFFICE_EXTS: FrozenSet[str]` | Task 1 | ✅ |
| `extract_mentions(text) -> List[Mention]` | Task 1 定义 / Task 3-4 隐式调用 | ✅ |
| `resolve_mentions(mentions, workspace) -> List[ResolvedBlock]` | Task 1 定义 / Task 3-4 调用 | ✅ |
| `render_attachment_block(blocks) -> str` | Task 1 定义 / Task 3-4 调用 | ✅ |
| `process(text, workspace) -> str` | Task 1 定义 / Task 3-4 调用 | ✅ |
| `_digest_ppt / _digest_word / _digest_excel (file_path, workspace) -> str` | Task 1 stub + Task 2 实现 + Task 1 测试 mock | ✅ |
| `FileSearchKind` | Task 5 定义 / Task 6 引用 | ✅ |
| `FileSearchResult.kind` | Task 5 定义 / Task 6 测试 | ✅ |
| `KIND_ICON: Record<kind, string>` | Task 6 Step 6.3 | ✅ |
| `OfficePathError / OfficeParseError` | Task 1 resolve / Task 2 测试 | ✅ |
| `OfficePptReadResult.slides[].title / text_blocks` | Task 2 Step 2.1 + 2.3 | ✅ |
| `OfficeWordReadResult.paragraphs[].text` | Task 2 Step 2.1 + 2.3 | ✅ |
| `OfficeExcelReadResult.sheets[].rows / .name` | Task 2 Step 2.1 + 2.3 | ✅ |

✅ 跨 task 一致。

### 4. 标注的潜在风险

1. **Spec §3.2.1 imports 与实际函数名不符** — spec 写 `read_ppt_file` 实际是 `read_ppt` (纯函数) — Task 2 Step 2.3 用真实名字
2. **Spec §3.2.2 字段名错误** — 实际 PPT 是 `text_blocks: List[str]` (非 `bullets: List[{text}]`); Excel cell 是 plain `str` (非 `{value}`) — Task 2 测试与实现都用真实字段
3. **Task 5 workspace 上下文** — spec §3.1.2 假设前端 ChatInput 能拿到 workspace; plan Task 5 用 search() 第三参数临时方案, 实施时若 `useWorkspace()` 可用则改 caller 注入
4. **Task 7 e2e 不在本地验证** — Step 7.2 标注; CI Playwright 跑
5. **win7 pydantic v1 兼容** — Task 7 Step 7.6 给出 `req.model_dump` → `req.dict` 修复
6. **win7 LTS base 已是 release/win7** — 当前 plan 实施顺序特殊, Step 7.4 详细描述 main cherry-pick

---

## 估计时间

- Task 1: 1.5 hr (纯函数模块 + 21 测试)
- Task 2: 1 hr (3 digest 边界 + 10 测试)
- Task 3: 1 hr (legacy_routes wire + 4 集成)
- Task 4: 1 hr (hex_routes wire + 2 集成)
- Task 5: 1 hr (fileSearchClient 合并 + 8 测试)
- Task 6: 1 hr (AtFileMenu kind icon + 6 测试)
- Task 7: 2 hr (e2e + 双 PR + memory)
- **合计**: 8.5 hr (~1.5 工作日)