# Sage Office M1–M2 Chat-Read — Design Spec

- **Date:** 2026-07-24
- **Branch(es):**
  - `fix/office-m1-m2-chat-read`（从 `release/win7` 切，先 spec + plan + TDD）
  - 与 `main` 同步走项目惯例：main 提 PR + win7 单 squash cherry-pick
- **Status:** 已实施（`@` Office 摘要注入子集）；完整 M1–M2 由 [`2026-07-25-office-m1-m2-completion-design.md`](./2026-07-25-office-m1-m2-completion-design.md) supersede
- **Author:** Claude（与用户共同 brainstorming 5 个问题达成）
- **Spec owner PR:** #210（main）/ #211（release/win7）

> 本文保留为已落地摘要注入链路的设计记录。session Workspace binding、`ChatOfficeRef`、Office list/read tools、统一 Workspace context 与跨进程 E2E 以 2026-07-25 完整收尾设计为准。

## 1. 背景与目标

### 1.1 M0 现状（已完成）

| M0 能力 | 说明 |
|---|---|
| 工作区入口检测 | `officeRoutes.py` 通过 `validate_workspace()` 校验路径 |
| 文档 CRUD | `storage.save_document / list_documents / delete_document`（SQLite） |
| 内容读取 | `office_ppt_read / office_word_read / office_excel_read` 返回结构化结果 |
| 文件生成 | `office_ppt_generate / office_word_generate / office_excel_generate` |
| Staging sweep | F5：`backend/data/office/` 与 DB 协同 orphan 清理（per PR #208+#209） |
| 路径沙盒 | `path_safety.py` 统一 doc-id 正则 + workspace containment |

Office 模块的"内容已可读"，但**chat 完全不引用 Office**——所有 chat 文本里 `@/path` 是字面量传给 LLM，不会被展开。

### 1.2 现状缺口（root cause）

| 层 | 现状 | 缺口 |
|---|---|---|
| 前端 `AtFileMenu` | 通过 `fileSearchClient.search()` 走 filesystem 搜索 | 不显示 office docs，user 不能 @ 它们 |
| 后端 `/chat/stream` | `ChatService.run_turn` 直接把 user `content` 送给 LLM | 没有 mention 提取，也没有文件内容注入 |
| `office_*_read` IPC | 已存在，返回完整解析结果 | 没有 digest（per-type 摘要）路径 |

三层叠加：user 在 chat 里无法感知 office 文档，文档是孤立模块。

### 1.3 目标

1. **M1**：用户输入 `@` 时，菜单合并显示工作区内的 office 文档（pptx/word/excel），选中后送入 LLM 时**按文档类型**自动注入**摘要**（不是全文）：
   - `.pptx`：每张 slide 的 title + bullet 列表
   - `.docx`：每段首句
   - `.xlsx`：所有 sheet 名 + 每 sheet 前 5 行 TSV
2. **M2**：同一 chat 消息里可 @ 多个 office 文档，backend 按 `@` 出现顺序拼接，块首加 `=== <name> ===` 分隔，M1 的单文档路径完全保留。
3. 非 office @路径（其它文本文件）维持当前字面量行为，不在本轮处理。
4. 双分支（`main` + `release/win7`）都修复；走项目惯例的 main 提 PR + win7 单 squash cherry-pick。
5. 覆盖率 ≥80%。

### 1.4 非目标

| 项 | 不做原因 |
|---|---|
| Tool-call 让 LLM 自取段 | tool-calling 架构增量超出 M1-M2 范围，列入 ideas |
| 跨 session / 跨消息 context cache | YAGNI；M1 验证后再评估 |
| 反向：从 chat 内容 save as office doc | 写入方向是新需求，需独立 brainstorm |
| 编辑 office doc 触发 chat diff | editor 整合超本轮范围 |
| 文档 attach 大小限制 | 现 storage 层 `max_size_bytes` 已生效，digest 已天然裁剪 |

## 2. 架构总览

### 2.1 数据流（user 视角）

```
用户在 ChatInput 输入：
  "帮我总结 @proposal.pptx 和 @notes.docx 的重点"

  ↓ ChatInput 提交 → IPC agent_chat_stream

backend /chat/stream 收到原始消息 text:
  ① ChatService.run_turn 入口处调用 attachment_resolver.process(text, workspace)
  ② extract_mentions(text) → ["proposal.pptx", "notes.docx"]
  ③ resolve_mentions() 对每个 path：
     - .pptx → office_ppt_read → digest_per_slide
     - .docx → office_word_read → digest_first_sentence_per_para
  ④ 拼接为附件块：
     <attachments>
     === proposal.pptx ===
     [slide 1] Title: ...
     [slide 2] Title: ...
     === notes.docx ===
     第一段首句。第二段首句。
     </attachments>
  ⑤ 注入到 LLM 输入 system prompt（不在 user message 内）

  ↓ LLM 看到：原始 user content + system prompt 内附件块
```

### 2.2 模块分层

| 层 | 模块 | 责任 |
|---|---|---|
| Frontend | `src/shared/api/fileSearchClient.ts` | merge filesystem + officeApi.listDocuments，统一返回 shape |
| Frontend | `src/features/chat/AtFileMenu.tsx` | 多 kind 渲染（kind icon 区分） |
| Frontend | `src/widgets/chat/ChatInput.tsx` | 不变，selection 照旧插入 `@{path}` |
| Frontend (IPC) | `src/shared/api/officeApi.ts` | `listDocuments` 已存在，可直接复用 |
| Backend | `backend/chat/__init__.py` (NEW) | 包标记，本轮唯一 module |
| Backend | `backend/chat/attachment_resolver.py` (NEW) | `extract_mentions` + `resolve_mentions` + 3 个 digest 格式化器 |
| Backend | `backend/api/legacy_routes.py` (`/chat/stream`) | 调用 `attachment_resolver.process()`，注入 system prompt 列表头 |
| Backend | `backend/api/hex_routes.py` (`/chat`) | 同上（hex mode 同步） |
| Backend | `backend/application/services/chat_service.py` | 可选：若 process 已发生在 routes 层，service 接受预注入消息即可 |

**关键决策**：附件注入发生在 **route 入口**（`/chat/stream` request handler），不在 service 内。原因：
- Service 层不知道 workspace 路径（只有 routes 拿得到 request body 的 `workspace_path` 字段）。
- digest 需要 IPC/office 调用（service 不应依赖 IPC 客户端）。
- 单点改造，hex/legacy 模式各调一处。

## 3. 详细设计

### 3.1 前端：`fileSearchClient.search()` 合并 office

#### 3.1.1 新返回类型

```typescript
// src/shared/api/fileSearchClient.ts
export type FileSearchKind = 'file' | 'office-ppt' | 'office-word' | 'office-excel';

export interface FileSearchResult {
  path: string;          // filesystem 路径 或 office doc id
  name: string;          // basename 用于显示
  size?: number;         // file size（office 来自 DB metadata）
  kind: FileSearchKind;  // 区分来源
}
```

#### 3.1.2 查询合并策略

```typescript
// pseudo-code
async search(query: string, opts): Promise<FileSearchResult[]> {
  const [fsResults, officeList] = await Promise.all([
    // 现有 filesystem search（不变）
    this._fsSearch(query, opts),
    // 新增：通过 officeApi.listDocuments 拉所有，再客户端 filter name
    // (workspace_path 由 ChatInput 上下文注入；本轮假设 current workspace 已知)
    this._officeList(),
  ]);

  const fsMapped = fsResults.map(r => ({...r, kind: inferKindByPath(r.path)}));
  // inferKindByPath: .pptx→office-ppt, .docx→office-word, .xlsx→office-excel
  const officeMapped = officeList.documents
    .filter(d => d.name.toLowerCase().includes(query.toLowerCase()))
    .map(d => ({
      path: d.file_path,
      name: d.name,
      size: d.file_size_bytes,
      kind: kindByDocType(d.doc_type),  // ppt|word|excel → office-ppt|word|excel
    }));

  // 去重：path 完全相等时优先 office kind
  return dedupeByPath([...officeMapped, ...fsMapped]);
}
```

**关键点**：
- Workspace 路径：复用现有 `useWorkspace()` / `currentWorkspace` 上下文注入。officeApi.listDocuments 已经接 `(workspacePath)`，前端 ChatInput 同一组件能拿到。
- 错误隔离：office 拉失败不阻塞 fs 结果（try/catch），降级显示 fs only。
- AbortSignal：沿用现有 `opts.signal`。

#### 3.1.3 AtFileMenu 渲染

```tsx
// AtFileMenu.tsx 渲染分支
{results.map((r, i) => (
  <li>
    <button>
      <span className="kind-icon">{r.kind === 'file' ? '📄' :
                                   r.kind === 'office-ppt' ? '📊' :
                                   r.kind === 'office-word' ? '📝' :
                                   r.kind === 'office-excel' ? '📈' : ''}</span>
      <span>{r.name}</span>
      <span className="path">{r.path}</span>
    </button>
  </li>
))}
```

选中后调 `onSelect(result.path)`——ChatInput 照旧插入 `@{path}`，**前端不感知 office vs file**。

### 3.2 Backend：`backend/chat/attachment_resolver.py`

#### 3.2.1 公共接口

```python
# backend/chat/attachment_resolver.py
from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import List, Optional

from backend.api.office_routes import (
    read_ppt_file, read_word_file, read_excel_file,
    OfficePathError, OfficeParseError,
)

_MENTION_RE = re.compile(r'(?:^|\s)@([^\s]+?)(?=\s|$)')

OFFICE_EXTS = {'.pptx', '.docx', '.xlsx'}

@dataclass
class Mention:
    raw: str           # @ 后到空格/末尾的整段
    path: str          # 推断的路径
    kind: Optional[str]  # 'office-ppt' | 'office-word' | 'office-excel' | None (file)


@dataclass
class ResolvedBlock:
    source_ref: str    # 用于日志/debug 的 doc name
    digest_text: str   # 注入 LLM 的纯文本


def extract_mentions(text: str) -> List[Mention]:
    """从 user 文本里扫所有 @path，按扩展名分类 kind."""
    seen = set()
    result = []
    for m in _MENTION_RE.finditer(text):
        raw = m.group(1)
        # 过滤相邻文本混入：仅 accept 含 '/' 或 '.' 的（过滤纯单词 noise）
        if '/' not in raw and '.' not in raw:
            continue
        if raw in seen:
            continue
        seen.add(raw)
        ext = os.path.splitext(raw)[1].lower()
        kind = {
            '.pptx': 'office-ppt',
            '.docx': 'office-word',
            '.xlsx': 'office-excel',
        }.get(ext)
        result.append(Mention(raw=raw, path=raw, kind=kind))
    return result


def resolve_mentions(
    mentions: List[Mention],
    workspace: str,
) -> List[ResolvedBlock]:
    """对 kind=office-* 的 mention 调 office read 出 digest；其它 mention 跳过。

    失败降级：office read 抛错时，本 mention 静默丢弃（不留 placeholder），
    但打印 warning 便于 debug——避免用户在 UI 里看到残缺 digest 块。
    """
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
            blocks.append(ResolvedBlock(source_ref=os.path.basename(m.path), digest_text=digest))
        except (OfficePathError, OfficeParseError) as exc:
            # 静默 skip + log warning（容错优先；用户看不到残块）
            import logging
            logging.getLogger(__name__).warning(
                "office mention resolve failed: %s (%s)", m.path, exc
            )
    return blocks


def render_attachment_block(blocks: List[ResolvedBlock]) -> str:
    """拼接为单一字符串，供 route 层嵌入 system prompt。"""
    if not blocks:
        return ''
    parts = ['<attachments>']
    for b in blocks:
        parts.append(f'=== {b.source_ref} ===')
        parts.append(b.digest_text)
    parts.append('</attachments>')
    return '\n'.join(parts)


def process(text: str, workspace: str) -> str:
    """route 层一键调：返回附件块字符串（可能为空串）。"""
    mentions = extract_mentions(text)
    blocks = resolve_mentions(mentions, workspace)
    return render_attachment_block(blocks)
```

#### 3.2.2 三个 digest 格式化器

```python
def _digest_ppt(file_path: str, workspace: str) -> str:
    result = read_ppt_file(
        workspace_path=workspace,
        file_path=file_path,
        max_size_bytes=50 * 1024 * 1024,  # 50MB 全文档上限
    )
    lines = []
    for slide in result['slides']:
        title = slide.get('title') or '(untitled)'
        bullets = slide.get('bullets') or []
        lines.append(f"[{title}]")
        for b in bullets:
            lines.append(f"  - {b.get('text', '')}")
    return '\n'.join(lines)


def _digest_word(file_path: str, workspace: str) -> str:
    result = read_word_file(
        workspace_path=workspace,
        file_path=file_path,
        max_size_bytes=50 * 1024 * 1024,
    )
    lines = []
    for para in result['paragraphs']:
        text = para.get('text', '').strip()
        if not text:
            continue
        first_sentence = text.split('.', 1)[0].strip() + '.'
        lines.append(first_sentence)
    return '\n'.join(lines)


def _digest_excel(file_path: str, workspace: str) -> str:
    result = read_excel_file(
        workspace_path=workspace,
        file_path=file_path,
        max_size_bytes=50 * 1024 * 1024,
    )
    lines = []
    sheets = result.get('sheets', [])
    sheet_names = [s.get('name') for s in sheets]
    lines.append(f"sheets: {', '.join(sheet_names)}")
    for sheet in sheets:
        name = sheet.get('name', '?')
        rows = sheet.get('rows', [])[:5]
        lines.append(f"--- {name} (top {len(rows)} rows) ---")
        for row in rows:
            cells = [str(c.get('value', '')) for c in row]
            lines.append('\t'.join(cells))
    return '\n'.join(lines)
```

**关键约束**：
- 不调用生成 routes（chat 注入只读）
- 复用现有的 `office_*_read` 函数（不发明新 IPC handler）
- digest 抛错静默降级（M1 决定；M3+ 可加 user-visible warning）
- `max_size_bytes=50MB` 沿用 office 路由默认上限；低于此的全文档读并裁剪

### 3.3 Backend 路由改造

#### 3.3.1 `/chat/stream`（legacy_routes.py）

```python
@router.post("/chat/stream")
async def create_chat_stream(req: ChatStreamRequest, ...):
    user_text = req.content
    workspace = req.workspace_path  # 已有字段

    # NEW: 附件注入
    attachment_block = attachment_resolver.process(user_text, workspace)
    injected_system = None
    if attachment_block:
        injected_system = (
            "The user has referenced the following attached documents. "
            "Treat them as primary context for the user's request.\n\n"
            f"{attachment_block}"
        )

    # 现有逻辑不变（如果已有 system_prompt 列表，则 append；否则新建）
    system_messages = list(req.system_messages or [])
    if injected_system:
        system_messages.append({"role": "system", "content": injected_system})

    # 把 system_messages 透传到 chat_service.run_turn（hex 模式同步处理）
    ...
```

#### 3.3.2 `/chat`（hex_routes.py）

同样在 req 入口处理；hex 模式 system_messages 字段定义略不同，但 attachment 注入位置一致（在 run_turn 调用前）。

### 3.4 Frontend ChatInput 不动

选择 `onSelect(result.path)` 后 `ChatInput.tsx:252` 仍然做 `value.slice(0, atQuery.startIdx) + '@' + path + ' ' + value.slice(atQuery.endIdx)`。Path 是 office 的 file_path（典型：`/path/to/workspace/office/ppt/<doc_id>/output.pptx`），含 `.pptx/.docx/.xlsx` 后缀，**正则可识别**。

LLM 看到原始文本里的 `@...pptx` 字面量；现在 backend 在送 LLM 前会附 system 块解释这些文档。

## 4. 测试设计

### 4.1 Backend unit tests

| Module | Test file | Coverage |
|---|---|---|
| `extract_mentions` | `backend/tests/unit/chat/test_attachment_resolver_extract.py` | regex 触发、扩展名分类、重复去重、无扩展跳过 |
| `resolve_mentions` | `backend/tests/unit/chat/test_attachment_resolver_resolve.py` | 每种 kind 调用对应 `_digest_*`，非 office 跳过 |
| `_digest_ppt / _digest_word / _digest_excel` | `backend/tests/unit/chat/test_digest_formatters.py` | 空 slide/paragraph/sheet 边界、5 行裁剪、首句裁剪 |
| `render_attachment_block` | `backend/tests/unit/chat/test_attachment_resolver_render.py` | 空 list 返回空串；单块/多块分隔符 |
| `process` 整合 | `backend/tests/unit/chat/test_attachment_resolver.py` | 端到端 fixture：text + workspace → attachment block string |

### 4.2 Backend integration tests

| 测试 | 文件 | 断言 |
|---|---|---|
| `/chat/stream` 注入 | `backend/tests/integration/test_chat_attachment_injection.py` | mock LLM；req 带 `@foo.pptx`；断言 LLM request 收到 system prompt 含 `<attachments>` + pptx digest |
| 多文档聚合 | 同上 | req 带 `@a.pptx @b.docx`；断言按 a→b 顺序拼接 + `=== <name> ===` 分隔 |
| 无 office 注入 | 同上 | req 不带 `@`；断言 system_messages **不含** attachment block |
| 失败降级 | 同上 | 不存在的 path `Ghost.pptx`；断言跳过该 mention，其它正常 |

### 4.3 Frontend unit tests

| Module | Test file | Coverage |
|---|---|---|
| `fileSearchClient.search` merge | `src/shared/api/__tests__/fileSearchClient.test.ts` | fs results + office results 合并；按 path 去重；office 拉失败降级 |
| `AtFileMenu` 多 kind 渲染 | `src/features/chat/__tests__/AtFileMenu.test.tsx` | office-ppt icon 显示；filesystem 文件保持原样 |
| 选中行为不变 | 同上 | 选中 office 项后 onSelect 收到 path，ChatInput 拼接为 `@{path} ` |

### 4.4 E2E (Playwright)

| 场景 | 用例 |
|---|---|
| 单 office doc | workspace 放 1 pptx；ChatInput 输入 `@` 弹出菜单含该 doc；选中；提交；verify LLM request payload 含 digest |
| 多 office doc | workspace 放 1 pptx + 1 docx；输入 `@` 菜单两项；依次选中；提交；verify LLM payload 含两个 digest，按顺序 |
| 非 office 文件 | workspace 放纯 .txt；ChatInput `@` 菜单可见；选中；提交；verify LLM payload 不注入附件块（pass-through 行为） |

E2E 直接复用现有 `electron/electron-smoke`（per PR #195 改造后稳定，10s→30s waitForFunction）。

### 4.5 覆盖率目标

- Backend new code: ≥85%（核心 resize、extract、digest 都是纯函数，无环境依赖）
- Backend `chat_service.py` / route 文件: 不变（保持现有覆盖率）
- Frontend `fileSearchClient.ts` / `AtFileMenu.tsx`: ≥80%

## 5. 文件清单

### 5.1 新增文件

| 路径 | 行数估计 | 描述 |
|---|---|---|
| `backend/chat/__init__.py` | 5 | 包标记 |
| `backend/chat/attachment_resolver.py` | 140 | core module（含 3 个 digest 函数） |
| `backend/tests/unit/chat/__init__.py` | 0 | test pkg |
| `backend/tests/unit/chat/test_attachment_resolver.py` | 60 | extract + resolve + render + process |
| `backend/tests/unit/chat/test_digest_formatters.py` | 120 | 3 个 digest 边界 |
| `backend/tests/integration/test_chat_attachment_injection.py` | 200 | 4 个端到端 |
| `docs/superpowers/specs/2026-07-24-office-m1-m2-chat-read-design.md` | - | 本 spec |
| `docs/superpowers/plans/2026-07-24-office-m1-m2-chat-read.md` | - | impl plan（TDD 步骤） |

### 5.2 修改文件

| 路径 | 改点 | 改动行数估计 |
|---|---|---|
| `src/shared/api/fileSearchClient.ts` | merge office list + 返回 `kind` 字段 | +60 / -10 |
| `src/features/chat/AtFileMenu.tsx` | 渲染时按 kind 选 icon + 兼容 kind 字段 | +30 / -5 |
| `src/shared/api/__tests__/fileSearchClient.test.ts` (新建/扩展) | merge 测试 | +120 |
| `src/features/chat/__tests__/AtFileMenu.test.tsx` (新建/扩展) | 多 kind 渲染 | +80 |
| `backend/api/legacy_routes.py` | `/chat/stream` 入口处调 `process` + 注入 system_messages | +20 / -2 |
| `backend/api/hex_routes.py` | `/chat` 入口处同上 | +20 / -2 |
| `e2e/.../*.spec.ts` | 3 个 Playwright 用例 | +150 |

总计：~750 行新增（含测试），~30 行修改。

## 6. 风险评估

| 风险 | 概率 | 缓解 |
|---|---|---|
| 路径 mention 正则误识别 | 中 | M1 测试覆盖正常 `@path`、连续 `@@`、`@.`、`@com` 等噪声 case |
| Digest 内容超过 LLM context 限制 | 低 | 3 种格式化器都做了首 N 裁剪；50MB 上限；M1 不引入 chunking 不做 |
| Backend service 已有 system prompt 处理逻辑冲突 | 中 | route 层先于 service 注入，service 系统提示字段透传；用集成测试断言 payload |
| win7 + pydantic v1 注解兼容问题 | 低（per PR #209 已解决 pattern） | 沿用 `Optional[X]` + `class Config: extra = "forbid"`；TDD 阶段先在 py38 环境跑一次 |
| officeApi.listDocuments 失败降级 | 低 | fileSearchClient.search 用 try/catch；office 不阻塞 fs 结果 |

## 7. 实施里程碑（TDD）

1. **Backend core**：`backend/chat/attachment_resolver.py` + 4 个 unit test 文件（RED→GREEN→IMPROVE）
2. **Backend integration**：`test_chat_attachment_injection.py` 端到端（RED→GREEN）
3. **Backend route**：`legacy_routes.py` + `hex_routes.py` 接入 attachment_resolver（RED→GREEN）
4. **Frontend merge**：`fileSearchClient.ts` 合并 + 测试（RED→GREEN）
5. **Frontend UI**：`AtFileMenu.tsx` kind icon 渲染 + 测试（RED→GREEN）
6. **E2E**：`e2e/.../*.spec.ts` 3 个 Playwright 用例（RED→GREEN）
7. **双分支 PR**：main 提 PR + win7 cherry-pick（含 py38+py310 diff review）

每步实施对应 plan 文件 `2026-07-24-office-m1-m2-chat-read.md`。

## 8. 决策记录

| ID | 决策 | 备选 |
|---|---|---|
| 2026-07-24-01 | M1 包含文件内容注入 pipeline（一并新建 backend 模块），不仅 search merge | 仅 search merge；前端读 office 后自行发送 |
| 2026-07-24-02 | 注入位置在 route 入口（不在 service） | service 层；IPC handler |
| 2026-07-24-03 | Digest 策略：pptx title+bullets、docx 首句、xlsx sheet 名+前 5 行 | 全量原文；仅 summary |
| 2026-07-24-04 | `@` 路径检测：正则 + path 含 `/` 或 `.` 过滤纯单词 | 全字面 split |
| 2026-07-24-05 | M2 = 多文档按出现顺序拼接，单 `=== name ===` 分隔 | 编号分隔符；仅 markers |
| 2026-07-24-06 | Office 拉取失败降级：静默 skip + log warning | user-visible error；placeholder 保留空块 |
| 2026-07-24-07 | 路径消毒：mentions 直接作为 office path；office path_safety 重检（per F2） | regex 重命名 |
