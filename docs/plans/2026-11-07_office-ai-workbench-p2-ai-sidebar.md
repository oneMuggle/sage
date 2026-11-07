# AI 文档工作台 P2 — AI 侧栏实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development 逐任务实施本计划。步骤用 `- [ ]` 复选框跟踪。
>
> 状态：待实施（M0–M7）
> 日期：2026-11-07
> 规格：`docs/plans/2026-11-06_office-ai-workbench-redesign.md` §3.3 / §3.6 / §3.7 / §4-P2
> 依赖：P1 已合并（main #2914 `fcedd5e3b` / win7 #2915 `ec8c4fc21`）
> 双分支策略：main 先做；完成后 cherry-pick 到 release/win7（前端 1:1；后端新端点需换 `pydantic_compat` 垫片）

**Goal:** 在 `/office` 页面落地 AI 侧栏 —— 选中文本浮出操作条（改写/润色、对话、指令式修改、审校建议）+ 跨 Tab 常驻对话侧栏 + 按 Tab 变化的快捷指令 + `OfficeEditPreviewDialog` 内 AI 按钮。

**Architecture:** 前端状态收敛到 `src/entities/office/officeWorkspaceStore.ts`（zustand）；侧栏组件在 `src/features/office/sidebar/`；侧栏以 fixed 右侧抽屉挂在 `src/pages/Office.tsx` 页面级（跨 Tab 常驻）。后端只新增 2 个 LLM 端点（rewrite / chat），审校与写回复用已有 `/office/ai/review` 与 `/office/ai/revise`。前端一律经 Electron IPC `invoke()`，不直连 HTTP。

**Tech Stack:** React + TypeScript、zustand、FastAPI、pytest、vitest、Electron IPC（`electron/commandRoutes/office.ts` + `electron/ipc-manifest.json`）。

## Global Constraints

- 分行数硬上限 `maxFileLines: 800`（`architecture-policy.json`）；`architecture-baseline.json` 是逐文件棘轮，未进基线的文件不得超过 800 行，已进基线的文件不得增长。
- 分层：`src/shared` → `src/entities` → `src/features` → `src/widgets` → `src/pages`。**features 不得 import pages**。
- 前端禁止直连 HTTP；所有后端调用走 `invoke('<command>', args)`，命令必须在 `electron/commandRoutes/office.ts` 声明，并重新生成 `electron/ipc-manifest.json`（`node scripts/export-ipc-manifest.mjs`）。
- 后端 Python 一律用 `/home/fz/anaconda3/envs/sage-backend/bin/python`；不得用系统 python。
- 后端错误一律 `HTTPException(status_code, detail={"code": ..., "message": ...})`；LLM 失败返回 502 `llm_error` / `llm_unavailable`，不得 500。
- 后端工作区隔离：所有入参 `workspace_path` 必须过 `validate_workspace(Path(...))`，文件路径过 `resolve_within`，`doc_id` 必须过 `_doc_in_workspace`。
- 不得记录或打印原始 `SAGE_LOCAL_AUTH_TOKEN`。
- 中文文案进 i18n 模块；zh/en 必须键集完全一致且非空。
- 写回文档只走 `office_ai_revise`（保留 pre-edit 快照 + Word 修订痕迹）。
- 段落锚点统一 `data-paragraph-index`，0 基，跳过空段落与表格内段落（对齐后端 `_extract_paragraphs`）。

---

### Task 1: 工作区状态 store（M0）

**Files:**
- Create: `src/entities/office/officeWorkspaceStore.ts`
- Create: `src/entities/office/__tests__/officeWorkspaceStore.test.ts`

**Interfaces:**
- Consumes: `OfficeDocumentSummary`、`AiReviewSeverity`（`src/shared/api/types.ts`、`src/shared/api/officeSpecTypes.ts`）
- Produces（后续任务依赖，签名必须逐字一致）:
  ```ts
  export type PreviewMode = 'fidelity' | 'structured'
  export type GenerateMode = 'idle' | 'nl' | 'refs' | 'template' | 'iterate'
  export type SuggestionStatus = 'pending' | 'applied' | 'skipped'
  export interface SelectionState {
    text: string
    anchorParaIndex: number | null
    focusParaIndex: number | null
    rawContext: string
  }
  export interface SuggestionCardData {
    id: string
    paraIndex: number
    severity: AiReviewSeverity
    originalText: string
    suggestedText: string
    ruleName?: string
    applied: SuggestionStatus
  }
  export interface ConversationMessage {
    id: string
    role: 'user' | 'assistant' | 'system'
    content: string
    attachments?: SuggestionCardData[]
    createdAt: number
  }
  export const useOfficeWorkspaceStore: UseBoundStore<StoreApi<OfficeWorkspaceState>>
  ```

- [ ] **Step 1: 写失败测试**

`src/entities/office/__tests__/officeWorkspaceStore.test.ts`

```ts
import { beforeEach, describe, expect, it } from 'vitest'
import type { OfficeDocumentSummary } from '../../../shared/api/types'
import { useOfficeWorkspaceStore } from '../officeWorkspaceStore'

const docA: OfficeDocumentSummary = {
  id: 'doc-a',
  doc_type: 'word',
  original_filename: 'a.docx',
  generated_filename: 'a.docx',
  status: 'ready',
  created_at: 0,
  updated_at: 0,
  metadata: {},
} as OfficeDocumentSummary

const docB: OfficeDocumentSummary = { ...docA, id: 'doc-b', original_filename: 'b.docx' } as OfficeDocumentSummary

const initialState = useOfficeWorkspaceStore.getState()

describe('officeWorkspaceStore', () => {
  beforeEach(() => {
    useOfficeWorkspaceStore.setState(initialState, true)
  })

  it('starts with an empty workspace', () => {
    const s = useOfficeWorkspaceStore.getState()
    expect(s.activeDocument).toBeNull()
    expect(s.previewMode).toBe('fidelity')
    expect(s.sidebarOpen).toBe(false)
    expect(s.conversation).toEqual([])
    expect(s.selection).toBeNull()
    expect(s.generateMode).toBe('idle')
    expect(s.generatedDoc).toBeNull()
    expect(s.activeRuleGroups).toEqual([])
  })

  it('resets conversation and selection when switching to a different document', () => {
    const s = useOfficeWorkspaceStore.getState()
    s.setActiveDocument(docA)
    s.appendMessage({ id: 'm1', role: 'user', content: 'hi', createdAt: 1 })
    s.setSelection({ text: 'x', anchorParaIndex: 0, focusParaIndex: 0, rawContext: 'x' })

    useOfficeWorkspaceStore.getState().setActiveDocument(docB)

    const next = useOfficeWorkspaceStore.getState()
    expect(next.activeDocument?.id).toBe('doc-b')
    expect(next.conversation).toEqual([])
    expect(next.selection).toBeNull()
  })

  it('keeps conversation when re-setting the same document', () => {
    const s = useOfficeWorkspaceStore.getState()
    s.setActiveDocument(docA)
    s.appendMessage({ id: 'm1', role: 'user', content: 'hi', createdAt: 1 })

    useOfficeWorkspaceStore.getState().setActiveDocument({ ...docA })

    expect(useOfficeWorkspaceStore.getState().conversation).toHaveLength(1)
  })

  it('appends and patches messages immutably', () => {
    const s = useOfficeWorkspaceStore.getState()
    s.appendMessage({ id: 'm1', role: 'user', content: 'hi', createdAt: 1 })
    const before = useOfficeWorkspaceStore.getState().conversation

    useOfficeWorkspaceStore.getState().updateMessage('m1', { content: 'hello' })

    const after = useOfficeWorkspaceStore.getState().conversation
    expect(after).not.toBe(before)
    expect(after[0].content).toBe('hello')
  })

  it('updates a suggestion status inside its message', () => {
    const s = useOfficeWorkspaceStore.getState()
    s.appendMessage({
      id: 'm1',
      role: 'assistant',
      content: 'audit',
      createdAt: 1,
      attachments: [
        {
          id: 's1',
          paraIndex: 2,
          severity: 'warning',
          originalText: 'a',
          suggestedText: 'b',
          applied: 'pending',
        },
      ],
    })

    useOfficeWorkspaceStore.getState().updateSuggestionStatus('m1', 's1', 'applied')

    expect(
      useOfficeWorkspaceStore.getState().conversation[0].attachments?.[0].applied,
    ).toBe('applied')
  })

  it('resets the whole workspace', () => {
    const s = useOfficeWorkspaceStore.getState()
    s.setActiveDocument(docA)
    s.setSidebarOpen(true)
    useOfficeWorkspaceStore.getState().resetWorkspace()

    const next = useOfficeWorkspaceStore.getState()
    expect(next.activeDocument).toBeNull()
    expect(next.sidebarOpen).toBe(false)
  })
})
```

- [ ] **Step 2: 运行测试确认失败**

Run: `npx vitest run src/entities/office/__tests__/officeWorkspaceStore.test.ts`
Expected: FAIL —— 无法解析 `../officeWorkspaceStore`。

- [ ] **Step 3: 实现 store**

`src/entities/office/officeWorkspaceStore.ts`

```ts
import { create } from 'zustand'
import type { OfficeDocumentSummary } from '../../shared/api/types'
import type { AiReviewSeverity } from '../../shared/api/officeSpecTypes'

export type PreviewMode = 'fidelity' | 'structured'
export type GenerateMode = 'idle' | 'nl' | 'refs' | 'template' | 'iterate'
export type SuggestionStatus = 'pending' | 'applied' | 'skipped'

export interface SelectionState {
  text: string
  anchorParaIndex: number | null
  focusParaIndex: number | null
  rawContext: string
}

export interface SuggestionCardData {
  id: string
  paraIndex: number
  severity: AiReviewSeverity
  originalText: string
  suggestedText: string
  ruleName?: string
  applied: SuggestionStatus
}

export interface ConversationMessage {
  id: string
  role: 'user' | 'assistant' | 'system'
  content: string
  attachments?: SuggestionCardData[]
  createdAt: number
}

export interface OfficeWorkspaceState {
  activeDocument: OfficeDocumentSummary | null
  previewMode: PreviewMode
  fidelityFailed: boolean
  sidebarOpen: boolean
  conversation: ConversationMessage[]
  selection: SelectionState | null
  generateMode: GenerateMode
  generatedDoc: OfficeDocumentSummary | null
  activeRuleGroups: string[]
  setActiveDocument: (doc: OfficeDocumentSummary | null) => void
  setPreviewMode: (mode: PreviewMode) => void
  setFidelityFailed: (failed: boolean) => void
  setSidebarOpen: (open: boolean) => void
  toggleSidebar: () => void
  appendMessage: (message: ConversationMessage) => void
  updateMessage: (id: string, patch: Partial<Omit<ConversationMessage, 'id'>>) => void
  clearConversation: () => void
  setSelection: (selection: SelectionState | null) => void
  setGenerateMode: (mode: GenerateMode) => void
  setGeneratedDoc: (doc: OfficeDocumentSummary | null) => void
  setActiveRuleGroups: (groups: string[]) => void
  updateSuggestionStatus: (messageId: string, suggestionId: string, status: SuggestionStatus) => void
  resetWorkspace: () => void
}

const EMPTY = {
  activeDocument: null,
  previewMode: 'fidelity' as PreviewMode,
  fidelityFailed: false,
  sidebarOpen: false,
  conversation: [] as ConversationMessage[],
  selection: null,
  generateMode: 'idle' as GenerateMode,
  generatedDoc: null,
  activeRuleGroups: [] as string[],
}

export const useOfficeWorkspaceStore = create<OfficeWorkspaceState>((set, get) => ({
  ...EMPTY,

  setActiveDocument: (doc) => {
    const currentId = get().activeDocument?.id ?? null
    const nextId = doc?.id ?? null
    if (currentId === nextId) {
      set({ activeDocument: doc })
      return
    }
    set({ activeDocument: doc, conversation: [], selection: null })
  },

  setPreviewMode: (previewMode) => set({ previewMode }),
  setFidelityFailed: (fidelityFailed) => set({ fidelityFailed }),
  setSidebarOpen: (sidebarOpen) => set({ sidebarOpen }),
  toggleSidebar: () => set((s) => ({ sidebarOpen: !s.sidebarOpen })),

  appendMessage: (message) =>
    set((s) => ({ conversation: [...s.conversation, message] })),

  updateMessage: (id, patch) =>
    set((s) => ({
      conversation: s.conversation.map((m) => (m.id === id ? { ...m, ...patch } : m)),
    })),

  clearConversation: () => set({ conversation: [] }),
  setSelection: (selection) => set({ selection }),
  setGenerateMode: (generateMode) => set({ generateMode }),
  setGeneratedDoc: (generatedDoc) => set({ generatedDoc }),
  setActiveRuleGroups: (activeRuleGroups) => set({ activeRuleGroups }),

  updateSuggestionStatus: (messageId, suggestionId, status) =>
    set((s) => ({
      conversation: s.conversation.map((m) =>
        m.id !== messageId || !m.attachments
          ? m
          : {
              ...m,
              attachments: m.attachments.map((a) =>
                a.id === suggestionId ? { ...a, applied: status } : a,
              ),
            },
      ),
    })),

  resetWorkspace: () => set({ ...EMPTY }),
}))
```

- [ ] **Step 4: 运行测试确认通过**

Run: `npx vitest run src/entities/office/__tests__/officeWorkspaceStore.test.ts`
Expected: PASS（6 个测试）。

- [ ] **Step 5: 类型检查**

Run: `npx tsc --noEmit`
Expected: 0 error。

- [ ] **Step 6: 提交**

```bash
git add src/entities/office/
git commit -m "feat(office): 新增 AI 工作台 zustand 状态 store（P2 M0）"
```

---

### Task 2: 选区捕获 + 段落锚点 + 浮出操作条（M1）

**Files:**
- Create: `src/features/office/sidebar/selectionAnchor.ts`
- Create: `src/features/office/sidebar/useSelectionCapture.ts`
- Create: `src/features/office/sidebar/FloatingActionBar.tsx`
- Create: `src/features/office/sidebar/__tests__/selectionAnchor.test.ts`
- Create: `src/features/office/sidebar/__tests__/FloatingActionBar.test.tsx`
- Modify: `src/features/office/DocxNativePreview.tsx`

**Interfaces:**
- Consumes: `SelectionState`、`useOfficeWorkspaceStore`（Task 1）
- Produces:
  ```ts
  export const PARAGRAPH_ATTRIBUTE = 'data-paragraph-index'
  export function annotateParagraphIndexes(root: HTMLElement): void
  export function findParagraphIndex(node: Node | null, root: HTMLElement): number | null
  export function collectDocumentParagraphs(root: HTMLElement): { index: number; text: string }[]
  export function normalizeSelection(root: HTMLElement, selection: Selection | null): SelectionState | null
  export function useSelectionCapture(rootRef: React.RefObject<HTMLElement>): void
  export type FloatingActionKind = 'rewrite' | 'chat' | 'edit' | 'audit'
  export function FloatingActionBar(props: FloatingActionBarProps): JSX.Element | null
  interface FloatingActionBarProps {
    anchorRect: { top: number; left: number; width: number } | null
    canApply: boolean
    onAction: (kind: FloatingActionKind) => void
    onDismiss: () => void
  }
  ```

- [ ] **Step 1: 写锚点工具失败测试**

`src/features/office/sidebar/__tests__/selectionAnchor.test.ts`

```ts
import { beforeEach, describe, expect, it } from 'vitest'
import {
  annotateParagraphIndexes,
  collectDocumentParagraphs,
  findParagraphIndex,
  normalizeSelection,
} from '../selectionAnchor'

function buildRoot(html: string): HTMLElement {
  const root = document.createElement('div')
  root.innerHTML = html
  document.body.appendChild(root)
  return root
}

describe('selectionAnchor', () => {
  beforeEach(() => {
    document.body.innerHTML = ''
  })

  it('injects 0-based indices skipping empty and table paragraphs', () => {
    const root = buildRoot(
      '<p>first</p><p>   </p><table><tr><td><p>cell</p></td></tr></table><p>second</p>',
    )

    annotateParagraphIndexes(root)

    const indexed = Array.from(root.querySelectorAll('[data-paragraph-index]')).map((el) => [
      el.textContent,
      el.getAttribute('data-paragraph-index'),
    ])
    expect(indexed).toEqual([
      ['first', '0'],
      ['second', '1'],
    ])
  })

  it('re-annotates idempotently', () => {
    const root = buildRoot('<p>a</p><p>b</p>')
    annotateParagraphIndexes(root)
    annotateParagraphIndexes(root)
    expect(root.querySelectorAll('[data-paragraph-index]')).toHaveLength(2)
  })

  it('finds the nearest paragraph index from a text node', () => {
    const root = buildRoot('<p>a</p><p>hello world</p>')
    annotateParagraphIndexes(root)
    const text = root.querySelectorAll('p')[1].firstChild

    expect(findParagraphIndex(text, root)).toBe(1)
  })

  it('returns null when the node is outside any paragraph', () => {
    const root = buildRoot('<div>loose</div>')
    expect(findParagraphIndex(root.querySelector('div'), root)).toBeNull()
  })

  it('collects paragraph texts in index order', () => {
    const root = buildRoot('<p>a</p><p>b</p>')
    annotateParagraphIndexes(root)

    expect(collectDocumentParagraphs(root)).toEqual([
      { index: 0, text: 'a' },
      { index: 1, text: 'b' },
    ])
  })

  it('returns null for a collapsed selection', () => {
    const root = buildRoot('<p>hello</p>')
    annotateParagraphIndexes(root)
    const range = document.createRange()
    range.setStart(root.querySelector('p')!.firstChild!, 2)
    range.collapse(true)
    const selection = window.getSelection()!
    selection.removeAllRanges()
    selection.addRange(range)

    expect(normalizeSelection(root, selection)).toBeNull()
  })

  it('captures text and both paragraph anchors', () => {
    const root = buildRoot('<p>hello</p><p>world</p>')
    annotateParagraphIndexes(root)
    const range = document.createRange()
    range.setStart(root.querySelectorAll('p')[0].firstChild!, 1)
    range.setEnd(root.querySelectorAll('p')[1].firstChild!, 3)
    const selection = window.getSelection()!
    selection.removeAllRanges()
    selection.addRange(range)

    const result = normalizeSelection(root, selection)

    expect(result?.text).toBe('ellowor')
    expect(result?.anchorParaIndex).toBe(0)
    expect(result?.focusParaIndex).toBe(1)
    expect(result?.rawContext).toBe('ellowor')
  })
})
```

- [ ] **Step 2: 运行确认失败**

Run: `npx vitest run src/features/office/sidebar/__tests__/selectionAnchor.test.ts`
Expected: FAIL（模块不存在）。

- [ ] **Step 3: 实现 `selectionAnchor.ts`**

```ts
import type { SelectionState } from '../../../entities/office/officeWorkspaceStore'

export const PARAGRAPH_ATTRIBUTE = 'data-paragraph-index'
const MAX_RAW_CONTEXT = 80

export function annotateParagraphIndexes(root: HTMLElement): void {
  let next = 0
  root.querySelectorAll<HTMLElement>('p').forEach((el) => {
    el.removeAttribute(PARAGRAPH_ATTRIBUTE)
    if (el.closest('table')) return
    const text = el.textContent?.trim() ?? ''
    if (!text) return
    el.setAttribute(PARAGRAPH_ATTRIBUTE, String(next))
    next += 1
  })
}

export function findParagraphIndex(node: Node | null, root: HTMLElement): number | null {
  let current: Node | null = node
  while (current && current !== root) {
    if (current instanceof HTMLElement) {
      const raw = current.getAttribute(PARAGRAPH_ATTRIBUTE)
      if (raw !== null) {
        const parsed = Number.parseInt(raw, 10)
        return Number.isNaN(parsed) ? null : parsed
      }
    }
    current = current.parentNode
  }
  return null
}

export function collectDocumentParagraphs(
  root: HTMLElement,
): { index: number; text: string }[] {
  const out: { index: number; text: string }[] = []
  root.querySelectorAll<HTMLElement>(`[${PARAGRAPH_ATTRIBUTE}]`).forEach((el) => {
    const index = Number.parseInt(el.getAttribute(PARAGRAPH_ATTRIBUTE) ?? '', 10)
    const text = el.textContent?.trim() ?? ''
    if (!Number.isNaN(index) && text) out.push({ index, text })
  })
  return out.sort((a, b) => a.index - b.index)
}

export function normalizeSelection(
  root: HTMLElement,
  selection: Selection | null,
): SelectionState | null {
  if (!selection || selection.rangeCount === 0 || selection.isCollapsed) return null
  const text = selection.toString()
  if (!text.trim()) return null
  if (!root.contains(selection.anchorNode) || !root.contains(selection.focusNode)) return null
  return {
    text,
    anchorParaIndex: findParagraphIndex(selection.anchorNode, root),
    focusParaIndex: findParagraphIndex(selection.focusNode, root),
    rawContext: text.replace(/\s+/g, ' ').trim().slice(0, MAX_RAW_CONTEXT),
  }
}
```

- [ ] **Step 4: 运行锚点测试**

Run: `npx vitest run src/features/office/sidebar/__tests__/selectionAnchor.test.ts`
Expected: PASS。

- [ ] **Step 5: 写浮出条失败测试**

`src/features/office/sidebar/__tests__/FloatingActionBar.test.tsx`

```tsx
import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { FloatingActionBar } from '../FloatingActionBar'

vi.mock('../../../shared/lib/i18n', () => ({
  useI18n: () => ({ t: (key: string) => key, locale: 'zh', setLocale: vi.fn() }),
}))

describe('FloatingActionBar', () => {
  it('renders nothing without an anchor rect', () => {
    const { container } = render(
      <FloatingActionBar anchorRect={null} canApply onAction={vi.fn()} onDismiss={vi.fn()} />,
    )
    expect(container).toBeEmptyDOMElement()
  })

  it('renders four capabilities and fires the chosen one', () => {
    const onAction = vi.fn()
    render(
      <FloatingActionBar
        anchorRect={{ top: 100, left: 40, width: 60 }}
        canApply
        onAction={onAction}
        onDismiss={vi.fn()}
      />,
    )

    fireEvent.click(screen.getByTestId('office-floating-action-audit'))
    expect(onAction).toHaveBeenCalledWith('audit')
  })

  it('disables apply-dependent actions when canApply is false', () => {
    render(
      <FloatingActionBar
        anchorRect={{ top: 100, left: 40, width: 60 }}
        canApply={false}
        onAction={vi.fn()}
        onDismiss={vi.fn()}
      />,
    )
    expect(screen.getByTestId('office-floating-action-edit')).toBeDisabled()
  })
})
```

- [ ] **Step 6: 实现 `FloatingActionBar.tsx`**

```tsx
import { useI18n } from '../../../shared/lib/i18n'

export type FloatingActionKind = 'rewrite' | 'chat' | 'edit' | 'audit'

export interface FloatingActionBarProps {
  anchorRect: { top: number; left: number; width: number } | null
  canApply: boolean
  onAction: (kind: FloatingActionKind) => void
  onDismiss: () => void
}

const ACTIONS: { kind: FloatingActionKind; labelKey: string; needsDocument: boolean }[] = [
  { kind: 'rewrite', labelKey: 'office.ai.selection.rewrite', needsDocument: false },
  { kind: 'chat', labelKey: 'office.ai.selection.chat', needsDocument: false },
  { kind: 'edit', labelKey: 'office.ai.selection.edit', needsDocument: true },
  { kind: 'audit', labelKey: 'office.ai.selection.audit', needsDocument: true },
]

export function FloatingActionBar({
  anchorRect,
  canApply,
  onAction,
  onDismiss,
}: FloatingActionBarProps): JSX.Element | null {
  const { t } = useI18n()
  if (!anchorRect) return null

  return (
    <div
      data-testid="office-floating-action-bar"
      role="toolbar"
      className="fixed z-40 flex items-center gap-1 rounded-lg border border-border bg-surface px-1 py-1 shadow-lg"
      style={{ top: Math.max(anchorRect.top - 44, 8), left: Math.max(anchorRect.left, 8) }}
      onMouseDown={(event) => event.preventDefault()}
    >
      {ACTIONS.map((action) => (
        <button
          key={action.kind}
          type="button"
          data-testid={`office-floating-action-${action.kind}`}
          disabled={action.needsDocument && !canApply}
          className="rounded px-2 py-1 text-xs hover:bg-surface-hover disabled:opacity-40"
          onClick={() => onAction(action.kind)}
        >
          {t(action.labelKey as never)}
        </button>
      ))}
      <button
        type="button"
        data-testid="office-floating-action-dismiss"
        className="rounded px-2 py-1 text-xs text-text-muted hover:bg-surface-hover"
        onClick={onDismiss}
      >
        {t('office.ai.selection.dismiss' as never)}
      </button>
    </div>
  )
}
```

> 说明：`t()` 的键类型是 `TranslationKey` 联合类型；实现时直接写字面量键（Task 3 会补齐 i18n 键），或先 `as never` 再在 Task 3 去掉断言。**Task 3 必须移除这里的 `as never` 断言**。

- [ ] **Step 7: 实现 `useSelectionCapture.ts`**

```ts
import { useEffect } from 'react'
import type { RefObject } from 'react'
import { useOfficeWorkspaceStore } from '../../../entities/office/officeWorkspaceStore'
import { normalizeSelection } from './selectionAnchor'

export function useSelectionCapture(rootRef: RefObject<HTMLElement>): void {
  const setSelection = useOfficeWorkspaceStore((s) => s.setSelection)

  useEffect(() => {
    const root = rootRef.current
    if (!root) return

    const handle = () => {
      const selection = window.getSelection()
      const normalized = normalizeSelection(root, selection)
      setSelection(normalized)
    }

    document.addEventListener('selectionchange', handle)
    return () => document.removeEventListener('selectionchange', handle)
  }, [rootRef, setSelection])
}
```

- [ ] **Step 8: 在 `DocxNativePreview` 注入段落索引**

在 `src/features/office/DocxNativePreview.tsx` 的 `sanitizeRenderedDocx(container)` 之后加一行：

```ts
annotateParagraphIndexes(container)
```

并在文件顶部加 `import { annotateParagraphIndexes } from './sidebar/selectionAnchor'`。

- [ ] **Step 9: 全量验证**

Run: `npx vitest run src/features/office/sidebar src/features/office/__tests__/OfficePreviewPanel.test.tsx && npx tsc --noEmit`
Expected: 全绿。若 `OfficePreviewPanel.test.tsx` 因 `DocxNativePreview` 需要 `document` 而失败，在该测试里 mock `../sidebar/selectionAnchor`。

- [ ] **Step 10: 提交**

```bash
git add src/features/office/sidebar src/features/office/DocxNativePreview.tsx
git commit -m "feat(office): 选区捕获 + 段落锚点注入 + 浮出操作条（P2 M1）"
```

---

### Task 3: i18n 文案模块 + AI 侧栏外壳（M2）

**Files:**
- Create: `src/shared/lib/i18n/officeAiSidebar.ts`
- Create: `src/shared/lib/i18n/__tests__/officeAiSidebar.test.ts`
- Modify: `src/shared/lib/i18n/translations.ts`
- Create: `src/features/office/sidebar/ConversationArea.tsx`
- Create: `src/features/office/sidebar/QuickActions.tsx`
- Create: `src/features/office/sidebar/CommandInput.tsx`
- Create: `src/features/office/sidebar/AiSidebar.tsx`
- Create: `src/features/office/sidebar/OfficeAiSidebarHost.tsx`
- Create: `src/features/office/sidebar/__tests__/QuickActions.test.tsx`
- Create: `src/features/office/sidebar/__tests__/CommandInput.test.tsx`
- Create: `src/features/office/sidebar/__tests__/AiSidebar.test.tsx`

**Interfaces:**
- Consumes: `useOfficeWorkspaceStore`（Task 1）、`FloatingActionBar`（Task 2）
- Produces:
  ```ts
  export type QuickActionTab = 'documents' | 'generate' | 'rules' | 'latex'
  export interface QuickCommand {
    id: string
    labelKey: string
    command: string
  }
  export function quickCommandsForTab(tab: QuickActionTab): QuickCommand[]
  export interface OfficeAiSidebarHostProps {
    activeTab: QuickActionTab
    onNavigateTab: (tab: QuickActionTab) => void
  }
  export function OfficeAiSidebarHost(props: OfficeAiSidebarHostProps): JSX.Element
  ```

- [ ] **Step 1: 写 i18n 失败测试**

`src/shared/lib/i18n/__tests__/officeAiSidebar.test.ts`

```ts
import { describe, expect, it } from 'vitest'
import { officeAiSidebarEn, officeAiSidebarZh } from '../officeAiSidebar'

describe('officeAiSidebar i18n', () => {
  it('has identical key sets in zh and en', () => {
    expect(Object.keys(officeAiSidebarZh).sort()).toEqual(Object.keys(officeAiSidebarEn).sort())
  })

  it('has no empty strings', () => {
    for (const [key, value] of Object.entries({ ...officeAiSidebarZh, ...officeAiSidebarEn })) {
      expect(value.trim(), key).not.toBe('')
    }
  })
})
```

- [ ] **Step 2: 实现 i18n 模块**

`src/shared/lib/i18n/officeAiSidebar.ts` —— 键集（zh 值为准，en 逐键对应）：

| key | zh | en |
|---|---|---|
| `office.ai.sidebar.title` | AI 助手 | AI Assistant |
| `office.ai.sidebar.open` | 打开 AI 助手 | Open AI assistant |
| `office.ai.sidebar.close` | 关闭 AI 助手 | Close AI assistant |
| `office.ai.sidebar.empty` | 选中文本或输入指令开始 | Select text or type a command to start |
| `office.ai.sidebar.no_document` | 未选择文档 | No document selected |
| `office.ai.sidebar.current_document` | 当前文档 | Current document |
| `office.ai.sidebar.placeholder` | 输入指令，/ 唤起命令 | Type an instruction, / for commands |
| `office.ai.sidebar.send` | 发送 | Send |
| `office.ai.sidebar.thinking` | 生成中… | Generating… |
| `office.ai.sidebar.copy` | 复制 | Copy |
| `office.ai.sidebar.copied` | 已复制 | Copied |
| `office.ai.sidebar.apply` | 应用到文档 | Apply to document |
| `office.ai.sidebar.apply_disabled` | 仅 Word 文档支持应用 | Only Word documents support applying |
| `office.ai.sidebar.discard` | 丢弃 | Discard |
| `office.ai.sidebar.retry` | 重试 | Retry |
| `office.ai.sidebar.apply_failed` | 应用失败：{message} | Apply failed: {message} |
| `office.ai.sidebar.request_failed` | 请求失败：{message} | Request failed: {message} |
| `office.ai.sidebar.apply_done` | 已写入修订痕迹 | Applied as tracked changes |
| `office.ai.selection.rewrite` | 改写润色 | Rewrite |
| `office.ai.selection.chat` | 就这段提问 | Ask about this |
| `office.ai.selection.edit` | 按指令修改 | Edit by instruction |
| `office.ai.selection.audit` | 审校建议 | Audit |
| `office.ai.selection.dismiss` | 取消 | Dismiss |
| `office.ai.quick.documents.audit` | 审校全文 | Audit document |
| `office.ai.quick.documents.rules` | 提取规则 | Extract rules |
| `office.ai.quick.documents.summary` | 生成摘要 | Summarize |
| `office.ai.quick.documents.translate` | 翻译 | Translate |
| `office.ai.quick.generate.expand` | 从摘要扩展 | Expand from summary |
| `office.ai.quick.generate.structure` | 优化结构 | Improve structure |
| `office.ai.quick.generate.details` | 补充细节 | Add detail |
| `office.ai.quick.generate.consistency` | 检查一致性 | Check consistency |
| `office.ai.quick.rules.extract` | 提取规则 | Extract rules |
| `office.ai.quick.rules.conflicts` | 检查冲突 | Check conflicts |
| `office.ai.quick.rules.merge` | 合并相似 | Merge similar rules |
| `office.ai.quick.latex.compile` | 编译检查 | Check build |
| `office.ai.quick.latex.citations` | 引用格式化 | Format citations |
| `office.ai.quick.latex.formulas` | 公式校对 | Proofread formulas |
| `office.ai.audit.title` | 审校建议 | Audit suggestions |
| `office.ai.audit.apply_all` | 应用全部可修复项 | Apply all fixable |
| `office.ai.audit.skip` | 跳过 | Skip |
| `office.ai.audit.applied` | 已应用 | Applied |
| `office.ai.audit.skipped` | 已跳过 | Skipped |
| `office.ai.audit.paragraph` | 第 {index} 段 | Paragraph {index} |
| `office.ai.edit.title` | 指令式修改 | Instruction edit |
| `office.ai.edit.hint` | 描述要怎么改，AI 会定位段落 | Describe the change; AI locates the paragraph |
| `office.ai.edit.no_match` | 没有找到需要修改的段落 | No paragraph matched the instruction |

文件结构：

```ts
/**
 * AI 文档工作台侧栏文案（P2）。
 *
 * 独立成模块：locales/{en,zh}/workspaceAndTools.ts 已在 architecture-baseline.json
 * 基线上（806/807 行），新文案放这里不让基线文件继续增长。
 */
export const officeAiSidebarZh = {
  'office.ai.sidebar.title': 'AI 助手',
  // …（上表全部键）
} as const

export const officeAiSidebarEn: Record<keyof typeof officeAiSidebarZh, string> = {
  'office.ai.sidebar.title': 'AI Assistant',
  // …（逐键对应）
}
```

- [ ] **Step 3: 合并进 `translations.ts`**

```ts
import { officeAiSidebarEn, officeAiSidebarZh } from './officeAiSidebar'
// …
export type TranslationKey =
  | CoreTranslationKey
  | keyof typeof chatReadingZh
  | keyof typeof officeAiSidebarZh

export const translations: Record<Locale, Record<TranslationKey, string>> = {
  zh: { ...zh, ...chatReadingZh, ...officeAiSidebarZh },
  en: { ...en, ...chatReadingEn, ...officeAiSidebarEn },
}
```

- [ ] **Step 4: 写快捷指令失败测试**

`src/features/office/sidebar/__tests__/QuickActions.test.tsx`

```tsx
import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { QuickActions, quickCommandsForTab } from '../QuickActions'

vi.mock('../../../../shared/lib/i18n', () => ({
  useI18n: () => ({ t: (key: string) => key, locale: 'zh', setLocale: vi.fn() }),
}))

describe('quickCommandsForTab', () => {
  it('returns the documents command set', () => {
    expect(quickCommandsForTab('documents').map((c) => c.command)).toEqual([
      '/audit',
      '/rules',
      '/summarize',
      '/translate',
    ])
  })

  it('returns the latex command set', () => {
    expect(quickCommandsForTab('latex').map((c) => c.command)).toEqual([
      '/compile',
      '/citations',
      '/formulas',
    ])
  })
})

describe('QuickActions', () => {
  it('renders one button per command and forwards clicks', () => {
    const onCommand = vi.fn()
    render(<QuickActions tab="rules" onCommand={onCommand} />)

    const buttons = screen.getAllByRole('button')
    expect(buttons).toHaveLength(3)
    fireEvent.click(buttons[0])
    expect(onCommand).toHaveBeenCalledWith('/rules')
  })
})
```

- [ ] **Step 5: 实现 `QuickActions.tsx`**

```tsx
import { useI18n } from '../../../shared/lib/i18n'

export type QuickActionTab = 'documents' | 'generate' | 'rules' | 'latex'

export interface QuickCommand {
  id: string
  labelKey: string
  command: string
}

const COMMANDS: Record<QuickActionTab, QuickCommand[]> = {
  documents: [
    { id: 'audit', labelKey: 'office.ai.quick.documents.audit', command: '/audit' },
    { id: 'rules', labelKey: 'office.ai.quick.documents.rules', command: '/rules' },
    { id: 'summary', labelKey: 'office.ai.quick.documents.summary', command: '/summarize' },
    { id: 'translate', labelKey: 'office.ai.quick.documents.translate', command: '/translate' },
  ],
  generate: [
    { id: 'expand', labelKey: 'office.ai.quick.generate.expand', command: '/expand' },
    { id: 'structure', labelKey: 'office.ai.quick.generate.structure', command: '/structure' },
    { id: 'details', labelKey: 'office.ai.quick.generate.details', command: '/details' },
    { id: 'consistency', labelKey: 'office.ai.quick.generate.consistency', command: '/consistency' },
  ],
  rules: [
    { id: 'extract', labelKey: 'office.ai.quick.rules.extract', command: '/rules' },
    { id: 'conflicts', labelKey: 'office.ai.quick.rules.conflicts', command: '/conflicts' },
    { id: 'merge', labelKey: 'office.ai.quick.rules.merge', command: '/merge' },
  ],
  latex: [
    { id: 'compile', labelKey: 'office.ai.quick.latex.compile', command: '/compile' },
    { id: 'citations', labelKey: 'office.ai.quick.latex.citations', command: '/citations' },
    { id: 'formulas', labelKey: 'office.ai.quick.latex.formulas', command: '/formulas' },
  ],
}

export function quickCommandsForTab(tab: QuickActionTab): QuickCommand[] {
  return COMMANDS[tab]
}

export interface QuickActionsProps {
  tab: QuickActionTab
  onCommand: (command: string) => void
}

export function QuickActions({ tab, onCommand }: QuickActionsProps): JSX.Element {
  const { t } = useI18n()
  return (
    <div data-testid="office-ai-quick-actions" className="flex flex-wrap gap-1.5">
      {quickCommandsForTab(tab).map((item) => (
        <button
          key={item.id}
          type="button"
          data-testid={`office-ai-quick-${item.id}`}
          className="rounded-full border border-border px-2.5 py-1 text-xs hover:bg-surface-hover"
          onClick={() => onCommand(item.command)}
        >
          {t(item.labelKey)}
        </button>
      ))}
    </div>
  )
}
```

- [ ] **Step 6: 写命令输入框测试**

`src/features/office/sidebar/__tests__/CommandInput.test.tsx`

```tsx
import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { CommandInput } from '../CommandInput'

vi.mock('../../../../shared/lib/i18n', () => ({
  useI18n: () => ({ t: (key: string) => key, locale: 'zh', setLocale: vi.fn() }),
}))

describe('CommandInput', () => {
  it('submits on Enter and clears the field', () => {
    const onSubmit = vi.fn()
    render(<CommandInput disabled={false} pending={false} onSubmit={onSubmit} />)

    const textarea = screen.getByTestId('office-ai-command-input')
    fireEvent.change(textarea, { target: { value: '/audit' } })
    fireEvent.keyDown(textarea, { key: 'Enter' })

    expect(onSubmit).toHaveBeenCalledWith('/audit')
    expect((textarea as HTMLTextAreaElement).value).toBe('')
  })

  it('inserts a newline on Shift+Enter without submitting', () => {
    const onSubmit = vi.fn()
    render(<CommandInput disabled={false} pending={false} onSubmit={onSubmit} />)

    const textarea = screen.getByTestId('office-ai-command-input')
    fireEvent.change(textarea, { target: { value: 'a' } })
    fireEvent.keyDown(textarea, { key: 'Enter', shiftKey: true })

    expect(onSubmit).not.toHaveBeenCalled()
  })

  it('does not submit blank input', () => {
    const onSubmit = vi.fn()
    render(<CommandInput disabled={false} pending={false} onSubmit={onSubmit} />)

    fireEvent.keyDown(screen.getByTestId('office-ai-command-input'), { key: 'Enter' })

    expect(onSubmit).not.toHaveBeenCalled()
  })
})
```

- [ ] **Step 7: 实现 `CommandInput.tsx`**

```tsx
import { useState } from 'react'
import { useI18n } from '../../../shared/lib/i18n'

export interface CommandInputProps {
  disabled: boolean
  pending: boolean
  onSubmit: (value: string) => void
}

export function CommandInput({ disabled, pending, onSubmit }: CommandInputProps): JSX.Element {
  const { t } = useI18n()
  const [value, setValue] = useState('')

  const submit = () => {
    const trimmed = value.trim()
    if (!trimmed || disabled || pending) return
    onSubmit(trimmed)
    setValue('')
  }

  return (
    <div className="flex items-end gap-2 border-t border-border p-2">
      <textarea
        data-testid="office-ai-command-input"
        aria-label={t('office.ai.sidebar.placeholder')}
        rows={2}
        value={value}
        disabled={disabled}
        placeholder={t('office.ai.sidebar.placeholder')}
        className="flex-1 resize-none rounded border border-border bg-surface px-2 py-1 text-sm"
        onChange={(event) => setValue(event.target.value)}
        onKeyDown={(event) => {
          if (event.key !== 'Enter' || event.shiftKey) return
          event.preventDefault()
          submit()
        }}
      />
      <button
        type="button"
        data-testid="office-ai-command-send"
        disabled={disabled || pending || !value.trim()}
        className="rounded bg-accent px-3 py-1.5 text-sm text-accent-foreground disabled:opacity-40"
        onClick={submit}
      >
        {pending ? t('office.ai.sidebar.thinking') : t('office.ai.sidebar.send')}
      </button>
    </div>
  )
}
```

- [ ] **Step 8: 实现 `ConversationArea.tsx`**

要求：
- props：`{ messages: ConversationMessage[]; pending: boolean; onApply: (messageId: string, suggestion: SuggestionCardData) => void; onSkip: (messageId: string, suggestionId: string) => void }`
- 空态显示 `office.ai.sidebar.empty`
- 每条消息渲染 `role` + 文本；`assistant` 消息底部有「复制」按钮
- `attachments` 渲染为建议列表：`office.ai.audit.paragraph`（`{index}` 用 `paraIndex+1`）+ 原文/建议文 + `[应用][跳过]`，`applied` 非 `pending` 时显示对应状态文案
- 新消息到达时 `useEffect` 滚到底部（`ref.scrollIntoView({ block: 'end' })`）
- `data-testid`：`office-ai-conversation`、`office-ai-suggestion-{id}`

- [ ] **Step 9: 实现 `AiSidebar.tsx` + `OfficeAiSidebarHost.tsx`**

`AiSidebar.tsx` props：

```ts
export interface AiSidebarProps {
  activeTab: QuickActionTab
  messages: ConversationMessage[]
  pending: boolean
  errorText: string | null
  disabled: boolean
  onCommand: (value: string) => void
  onApply: (messageId: string, suggestion: SuggestionCardData) => void
  onSkip: (messageId: string, suggestionId: string) => void
  onClose: () => void
  floatingBar: React.ReactNode
}
```

布局：`fixed right-0 top-0 z-30 h-full w-[360px] flex flex-col border-l border-border bg-surface shadow-xl`，头部标题 + 当前文档名 + 关闭按钮（`data-testid="office-ai-sidebar"`）。

`OfficeAiSidebarHost.tsx`：

```tsx
export interface OfficeAiSidebarHostProps {
  activeTab: QuickActionTab
  onNavigateTab: (tab: QuickActionTab) => void
}

export function OfficeAiSidebarHost({ activeTab, onNavigateTab }: OfficeAiSidebarHostProps): JSX.Element {
  const sidebarOpen = useOfficeWorkspaceStore((s) => s.sidebarOpen)
  const toggleSidebar = useOfficeWorkspaceStore((s) => s.toggleSidebar)
  // …pending / error 状态由 Task 5 的 useAiCapabilities 接入；本阶段先用本地空实现
  return (
    <>
      <button
        type="button"
        data-testid="office-ai-sidebar-toggle"
        aria-expanded={sidebarOpen}
        className="fixed right-4 bottom-4 z-30 rounded-full bg-accent px-4 py-2 text-sm text-accent-foreground shadow-lg"
        onClick={toggleSidebar}
      >
        {sidebarOpen ? t('office.ai.sidebar.close') : t('office.ai.sidebar.open')}
      </button>
      {sidebarOpen ? <AiSidebar … /> : null}
    </>
  )
}
```

> `onNavigateTab` 本期用于 `documents` tab 的 `/rules` 命令（跳到 rules tab）；Task 5 接线时使用。

- [ ] **Step 10: 写 `AiSidebar` 测试 + 全量验证**

`__tests__/AiSidebar.test.tsx` 断言：
- 空态显示 `office.ai.sidebar.empty`
- 传入 2 条消息时渲染 2 个 `office-ai-message`
- 点击 `office-ai-sidebar-close` 调用 `onClose`

Run: `npx vitest run src/shared/lib/i18n src/features/office/sidebar && npx tsc --noEmit`
Expected: 全绿；`tsc` 0 error（此时 `FloatingActionBar` 的 `as never` 断言必须已移除）。

- [ ] **Step 11: 提交**

```bash
git add src/shared/lib/i18n src/features/office/sidebar
git commit -m "feat(office): AI 侧栏外壳 + 对话区 + 快捷指令 + i18n 模块（P2 M2）"
```

---

### Task 4: 后端 AI 端点 + IPC 路由 + 前端 client（M3）

**Files:**
- Create: `backend/api/ai_routes.py`
- Create: `backend/tests/unit/test_ai_routes.py`
- Modify: `backend/api/office_routes.py`（底部 include 2 行）
- Modify: `architecture-baseline.json`（`backend/api/office_routes.py` 实测值）
- Modify: `electron/commandRoutes/office.ts`
- Modify: `electron/ipc-manifest.json`（脚本生成）
- Create: `src/shared/api/aiApi.ts`
- Create: `src/shared/api/__tests__/aiApi.test.ts`

**Interfaces:**
- Consumes: `build_llm_client_from_settings()`（`backend/orchestration/llm_factory.py:261`）、`validate_workspace` / `resolve_within` / `get_database`
- Produces:
  ```
  POST /api/v1/office/ai/rewrite
    body: { workspace_path, document_id, text, instruction,
            target_lang?, custom_instruction?, context_before?, context_after? }
    →   { ok: true, result: string, model: string | null }
  POST /api/v1/office/ai/chat
    body: { workspace_path, document_id, message, history: [{ role, content }], document_context? }
    →   { ok: true, reply: string, model: string | null }
  ```
  ```ts
  // src/shared/api/aiApi.ts
  export type AiRewriteInstruction =
    | 'rewrite' | 'polish' | 'expand' | 'condense'
    | 'translate' | 'explain' | 'summarize' | 'custom'
  export interface AiRewriteRequest {
    workspacePath: string
    documentId: string
    text: string
    instruction: AiRewriteInstruction
    targetLang?: string
    customInstruction?: string
    contextBefore?: string
    contextAfter?: string
  }
  export interface AiRewriteResult { ok: boolean; result: string; model: string | null }
  export interface AiChatHistoryItem { role: 'user' | 'assistant'; content: string }
  export interface AiChatRequest {
    workspacePath: string
    documentId: string
    message: string
    history: AiChatHistoryItem[]
    documentContext?: string
  }
  export interface AiChatResult { ok: boolean; reply: string; model: string | null }
  export const aiApi: {
    rewrite(req: AiRewriteRequest): Promise<AiRewriteResult>
    chat(req: AiChatRequest): Promise<AiChatResult>
  }
  ```

- [ ] **Step 1: 写后端失败测试**

`backend/tests/unit/test_ai_routes.py`

```python
"""P2 AI 侧栏端点契约测试。"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from backend.api.ai_routes import router as ai_router  # noqa: E402
from fastapi import FastAPI  # noqa: E402


@pytest.fixture()
def client(tmp_path: Path) -> TestClient:
    app = FastAPI()
    app.include_router(ai_router, prefix="/api/v1")
    return TestClient(app)


@pytest.fixture()
def workspace(tmp_path: Path) -> Path:
    ws = tmp_path / "ws"
    ws.mkdir()
    return ws


def _llm_client(text: str = "改写结果") -> MagicMock:
    client = MagicMock()
    client.complete = AsyncMock(return_value=text)
    return client


def test_rewrite_returns_llm_output(client: TestClient, workspace: Path) -> None:
    with patch(
        "backend.api.ai_routes.build_llm_client_from_settings",
        return_value=_llm_client("新的段落文本"),
    ):
        resp = client.post(
            "/api/v1/office/ai/rewrite",
            json={
                "workspace_path": str(workspace),
                "document_id": "doc-1",
                "text": "原始段落",
                "instruction": "polish",
            },
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body == {"ok": True, "result": "新的段落文本", "model": None}


def test_rewrite_rejects_unknown_instruction(client: TestClient, workspace: Path) -> None:
    resp = client.post(
        "/api/v1/office/ai/rewrite",
        json={
            "workspace_path": str(workspace),
            "document_id": "doc-1",
            "text": "x",
            "instruction": "destroy",
        },
    )
    assert resp.status_code == 422


def test_rewrite_rejects_custom_without_instruction(client: TestClient, workspace: Path) -> None:
    resp = client.post(
        "/api/v1/office/ai/rewrite",
        json={
            "workspace_path": str(workspace),
            "document_id": "doc-1",
            "text": "x",
            "instruction": "custom",
        },
    )
    assert resp.status_code == 422


def test_rewrite_returns_502_when_llm_missing(client: TestClient, workspace: Path) -> None:
    with patch("backend.api.ai_routes.build_llm_client_from_settings", return_value=None):
        resp = client.post(
            "/api/v1/office/ai/rewrite",
            json={
                "workspace_path": str(workspace),
                "document_id": "doc-1",
                "text": "x",
                "instruction": "rewrite",
            },
        )

    assert resp.status_code == 502
    assert resp.json()["detail"]["code"] == "llm_unavailable"


def test_rewrite_returns_502_when_llm_raises(client: TestClient, workspace: Path) -> None:
    failing = MagicMock()
    failing.complete = AsyncMock(side_effect=RuntimeError("boom"))
    with patch("backend.api.ai_routes.build_llm_client_from_settings", return_value=failing):
        resp = client.post(
            "/api/v1/office/ai/rewrite",
            json={
                "workspace_path": str(workspace),
                "document_id": "doc-1",
                "text": "x",
                "instruction": "rewrite",
            },
        )

    assert resp.status_code == 502
    assert resp.json()["detail"]["code"] == "llm_error"


def test_chat_forwards_history(client: TestClient, workspace: Path) -> None:
    llm = MagicMock()
    response = MagicMock()
    response.content = "回答"
    llm.chat = AsyncMock(return_value=response)

    with patch("backend.api.ai_routes.build_llm_client_from_settings", return_value=llm):
        resp = client.post(
            "/api/v1/office/ai/chat",
            json={
                "workspace_path": str(workspace),
                "document_id": "doc-1",
                "message": "这段什么意思？",
                "history": [{"role": "user", "content": "你好"}],
                "document_context": "第一段\n第二段",
            },
        )

    assert resp.status_code == 200
    assert resp.json() == {"ok": True, "reply": "回答", "model": None}

    sent = llm.chat.await_args.args[0]
    assert sent[0]["role"] == "system"
    assert "第一段" in sent[0]["content"]
    assert sent[1] == {"role": "user", "content": "你好"}
    assert sent[-1] == {"role": "user", "content": "这段什么意思？"}
```

- [ ] **Step 2: 运行确认失败**

Run: `/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/test_ai_routes.py -q`
Expected: FAIL（`backend.api.ai_routes` 不存在）。

- [ ] **Step 3: 实现 `backend/api/ai_routes.py`**

```python
# ruff: noqa: UP006, UP007, UP035 — release/win7 Python 3.8 兼容
"""P2 AI 侧栏端点：段落改写与文档对话。

只提供「纯文本进、纯文本出」的两个能力；审校与写回分别复用
``/office/ai/review`` 与 ``/office/ai/revise``，避免重复实现。

端点:

* ``POST /office/ai/rewrite`` — 单段/整篇的改写、润色、扩写、精简、翻译、摘要。
* ``POST /office/ai/chat``    — 带文档上下文的单轮对话（历史由前端维护）。
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import List, Literal, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from backend.data.database import get_database
from backend.office.storage import validate_workspace
from backend.orchestration.llm_factory import build_llm_client_from_settings

logger = logging.getLogger(__name__)

router = APIRouter(tags=["office"])

MAX_TEXT_CHARS = 8000
MAX_CONTEXT_CHARS = 4000
MAX_HISTORY_ITEMS = 20
MAX_HISTORY_CHARS = 4000

Instruction = Literal[
    "rewrite", "polish", "expand", "condense", "translate", "explain", "summarize", "custom"
]

_INSTRUCTION_TASKS = {
    "rewrite": "在不改变原意的前提下重写这段文字，使其更通顺、更专业。",
    "polish": "润色这段文字：修正语病与标点，保持原意与篇幅接近。",
    "expand": "在保持原意的前提下扩写这段文字，补充必要的解释与过渡。",
    "condense": "精简这段文字，保留全部关键信息，删除冗余表达。",
    "explain": "解释这段文字的含义与要点，输出简洁的解释而不是改写正文。",
    "summarize": "为这段文字生成摘要，只保留核心论点与结论。",
}


class RewriteRequest(BaseModel):
    """POST /office/ai/rewrite body."""

    model_config = ConfigDict(extra="forbid")

    workspace_path: str = Field(min_length=1)
    document_id: str = Field(min_length=1)
    text: str = Field(min_length=1, max_length=MAX_TEXT_CHARS)
    instruction: Instruction
    target_lang: Optional[str] = Field(default=None, max_length=40)
    custom_instruction: Optional[str] = Field(default=None, max_length=1000)
    context_before: Optional[str] = Field(default=None, max_length=MAX_CONTEXT_CHARS)
    context_after: Optional[str] = Field(default=None, max_length=MAX_CONTEXT_CHARS)


class RewriteResult(BaseModel):
    ok: bool = True
    result: str
    model: Optional[str] = None


class ChatHistoryItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=MAX_HISTORY_CHARS)


class ChatRequest(BaseModel):
    """POST /office/ai/chat body."""

    model_config = ConfigDict(extra="forbid")

    workspace_path: str = Field(min_length=1)
    document_id: str = Field(min_length=1)
    message: str = Field(min_length=1, max_length=MAX_TEXT_CHARS)
    history: List[ChatHistoryItem] = Field(default_factory=list, max_length=MAX_HISTORY_ITEMS)
    document_context: Optional[str] = Field(default=None, max_length=MAX_CONTEXT_CHARS)


class ChatResult(BaseModel):
    ok: bool = True
    reply: str
    model: Optional[str] = None


def _error(status_code: int, code: str, message: str) -> HTTPException:
    return HTTPException(status_code=status_code, detail={"code": code, "message": message})


def _validate_workspace(workspace_path: str) -> Path:
    try:
        return validate_workspace(Path(workspace_path))
    except Exception as exc:  # noqa: BLE001 — 统一映射为 404，避免泄露本地路径
        logger.warning("ai rewrite workspace rejected: %s", type(exc).__name__)
        raise _error(404, "workspace_not_found", "工作区不存在或不可访问") from exc


def _assert_document_in_workspace(document_id: str, workspace: Path) -> None:
    conn = get_database().get_connection()
    row = conn.execute(
        "SELECT id FROM office_documents WHERE id = ? AND workspace_path = ?",
        (document_id, str(workspace)),
    ).fetchone()
    if row is None:
        raise _error(404, "document_not_found", "文档不存在或不属于该工作区")


def _build_rewrite_prompt(req: RewriteRequest) -> str:
    if req.instruction == "custom":
        task = (req.custom_instruction or "").strip()
        if not task:
            raise _error(422, "missing_custom_instruction", "custom 指令必须提供 custom_instruction")
    else:
        task = _INSTRUCTION_TASKS[req.instruction]
    if req.instruction == "translate":
        target = (req.target_lang or "").strip() or "中文"
        task = f"把这段文字翻译为{target}，只输出译文。"

    parts = [task, "", "待处理文本：", "<<<", req.text, ">>>"]
    if req.context_before:
        parts += ["", "上一段（仅供理解，不要输出）：", "<<<", req.context_before, ">>>"]
    if req.context_after:
        parts += ["", "下一段（仅供理解，不要输出）：", "<<<", req.context_after, ">>>"]
    parts += ["", "只输出处理结果本身，不要解释、不要加引号或 Markdown 代码块。"]
    return "\n".join(parts)


def _build_chat_messages(req: ChatRequest) -> List[dict]:
    system = "你是文档写作助手，回答简洁、直接、可执行。不要编造文档中不存在的内容。"
    messages: List[dict] = [{"role": "system", "content": system}]
    if req.document_context:
        messages[0]["content"] = (
            system + "\n\n当前文档内容（按段落顺序，仅供参考）：\n" + req.document_context
        )
    for item in req.history[-MAX_HISTORY_ITEMS:]:
        messages.append({"role": item.role, "content": item.content})
    messages.append({"role": "user", "content": req.message})
    return messages


async def _complete(prompt: str) -> tuple:
    client = build_llm_client_from_settings()
    if client is None:
        raise _error(502, "llm_unavailable", "未配置可用的 LLM 模型")
    try:
        text = await client.complete(prompt)
    except Exception as exc:  # noqa: BLE001 — LLM 上游失败统一 502
        logger.warning("ai rewrite llm failed: %s", type(exc).__name__)
        raise _error(502, "llm_error", "LLM 调用失败，请稍后重试") from exc
    result = (text or "").strip()
    if not result:
        raise _error(502, "llm_empty", "LLM 返回了空结果")
    return result, getattr(client, "model", None)


@router.post("/rewrite", response_model=RewriteResult)
async def ai_rewrite_endpoint(req: RewriteRequest) -> RewriteResult:
    """按指令改写一段文本。不写文件、不改文档。"""
    workspace = _validate_workspace(req.workspace_path)
    _assert_document_in_workspace(req.document_id, workspace)
    prompt = _build_rewrite_prompt(req)
    result, model = await _complete(prompt)
    return RewriteResult(ok=True, result=result, model=model)


@router.post("/chat", response_model=ChatResult)
async def ai_chat_endpoint(req: ChatRequest) -> ChatResult:
    """带文档上下文的单轮问答。历史由前端维护并随请求下发。"""
    workspace = _validate_workspace(req.workspace_path)
    _assert_document_in_workspace(req.document_id, workspace)

    client = build_llm_client_from_settings()
    if client is None:
        raise _error(502, "llm_unavailable", "未配置可用的 LLM 模型")
    try:
        response = await client.chat(_build_chat_messages(req))
    except Exception as exc:  # noqa: BLE001
        logger.warning("ai chat llm failed: %s", type(exc).__name__)
        raise _error(502, "llm_error", "LLM 调用失败，请稍后重试") from exc
    reply = (getattr(response, "content", "") or "").strip()
    if not reply:
        raise _error(502, "llm_empty", "LLM 返回了空结果")
    return ChatResult(ok=True, reply=reply, model=getattr(response, "model", None))


__all__ = ["ChatRequest", "ChatResult", "RewriteRequest", "RewriteResult", "router"]
```

> **win7 适配点（Task 8 记录，不在 main 做）**：`ConfigDict` 与 `Field(max_length=...)` 在 pydantic 1.10 需换成 `backend.compat.win7.pydantic_compat` 垫片与 `_constrained_list`（参考 `AiReviseRequest.issues` 的既有写法）。

- [ ] **Step 4: 运行后端测试**

Run: `/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/test_ai_routes.py -q`
Expected: 7 passed。

- [ ] **Step 5: 挂载 router**

在 `backend/api/office_routes.py` 底部与现有 include 并排追加：

```python
from backend.api.ai_routes import router as _ai_router

router.include_router(_ai_router, prefix="/ai")
```

> `office_routes.router` 已有 `prefix="/office"`，最终路径为 `/api/v1/office/ai/rewrite` 与 `/api/v1/office/ai/chat`。

- [ ] **Step 6: 更新架构基线**

Run: `node scripts/architecture-check.mjs --json | grep -A3 office_routes`
把 `architecture-baseline.json` 里 `backend/api/office_routes.py` 的数值改成实测文件行数，然后重跑 `node scripts/architecture-check.mjs`，Expected: 0 违规。

- [ ] **Step 7: 写 IPC 路由**

在 `electron/commandRoutes/office.ts` 的 `office_ai_revise` 之后追加：

```ts
  // P2 (2026-11-07): AI 侧栏改写 / 对话。纯文本进出，不写文件。
  office_ai_rewrite: {
    method: 'POST',
    path: () => '/api/v1/office/ai/rewrite',
    body: (a) => ({
      workspace_path: a.workspacePath ?? a.workspace_path,
      document_id: a.documentId ?? a.document_id,
      text: a.text,
      instruction: a.instruction,
      ...((a.targetLang ?? a.target_lang) ? { target_lang: a.targetLang ?? a.target_lang } : {}),
      ...((a.customInstruction ?? a.custom_instruction)
        ? { custom_instruction: a.customInstruction ?? a.custom_instruction }
        : {}),
      ...((a.contextBefore ?? a.context_before)
        ? { context_before: a.contextBefore ?? a.context_before }
        : {}),
      ...((a.contextAfter ?? a.context_after)
        ? { context_after: a.contextAfter ?? a.context_after }
        : {}),
    }),
  },
  office_ai_chat: {
    method: 'POST',
    path: () => '/api/v1/office/ai/chat',
    body: (a) => ({
      workspace_path: a.workspacePath ?? a.workspace_path,
      document_id: a.documentId ?? a.document_id,
      message: a.message,
      history: Array.isArray(a.history) ? a.history : [],
      ...((a.documentContext ?? a.document_context)
        ? { document_context: a.documentContext ?? a.document_context }
        : {}),
    }),
  },
```

- [ ] **Step 8: 重新生成 IPC manifest**

Run: `node scripts/export-ipc-manifest.mjs`
Expected: `electron/ipc-manifest.json` 增加 2 条命令；随后 `node scripts/export-ipc-manifest.mjs --check` 通过。

- [ ] **Step 9: 写前端 client 失败测试**

`src/shared/api/__tests__/aiApi.test.ts`

```ts
import { beforeEach, describe, expect, it, vi } from 'vitest'

const invoke = vi.fn()
vi.mock('../desktopInvoke', () => ({ invoke }))

import { aiApi } from '../aiApi'

describe('aiApi', () => {
  beforeEach(() => invoke.mockReset())

  it('maps rewrite args to the IPC command', async () => {
    invoke.mockResolvedValue({ ok: true, result: 'r', model: 'm' })

    const result = await aiApi.rewrite({
      workspacePath: '/ws',
      documentId: 'doc-1',
      text: 'src',
      instruction: 'polish',
      targetLang: 'en',
    })

    expect(invoke).toHaveBeenCalledWith('office_ai_rewrite', {
      workspacePath: '/ws',
      documentId: 'doc-1',
      text: 'src',
      instruction: 'polish',
      targetLang: 'en',
    })
    expect(result.result).toBe('r')
  })

  it('maps chat args including history', async () => {
    invoke.mockResolvedValue({ ok: true, reply: 'a', model: null })

    await aiApi.chat({
      workspacePath: '/ws',
      documentId: 'doc-1',
      message: 'q',
      history: [{ role: 'user', content: 'hi' }],
      documentContext: 'ctx',
    })

    expect(invoke).toHaveBeenCalledWith('office_ai_chat', {
      workspacePath: '/ws',
      documentId: 'doc-1',
      message: 'q',
      history: [{ role: 'user', content: 'hi' }],
      documentContext: 'ctx',
    })
  })
})
```

- [ ] **Step 10: 实现 `src/shared/api/aiApi.ts`**

```ts
import { invoke } from './desktopInvoke'
import { handleApiError } from './errorUtils'

export type AiRewriteInstruction =
  | 'rewrite'
  | 'polish'
  | 'expand'
  | 'condense'
  | 'translate'
  | 'explain'
  | 'summarize'
  | 'custom'

export interface AiRewriteRequest {
  workspacePath: string
  documentId: string
  text: string
  instruction: AiRewriteInstruction
  targetLang?: string
  customInstruction?: string
  contextBefore?: string
  contextAfter?: string
}

export interface AiRewriteResult {
  ok: boolean
  result: string
  model: string | null
}

export interface AiChatHistoryItem {
  role: 'user' | 'assistant'
  content: string
}

export interface AiChatRequest {
  workspacePath: string
  documentId: string
  message: string
  history: AiChatHistoryItem[]
  documentContext?: string
}

export interface AiChatResult {
  ok: boolean
  reply: string
  model: string | null
}

export const aiApi = {
  async rewrite(req: AiRewriteRequest): Promise<AiRewriteResult> {
    try {
      return await invoke<AiRewriteResult>('office_ai_rewrite', req)
    } catch (error) {
      throw handleApiError(error)
    }
  },

  async chat(req: AiChatRequest): Promise<AiChatResult> {
    try {
      return await invoke<AiChatResult>('office_ai_chat', req)
    } catch (error) {
      throw handleApiError(error)
    }
  },
}
```

> 实现前先确认 `handleApiError` 的真实导入路径（与 `officeApi.ts` 顶部一致）。

- [ ] **Step 11: 全量验证**

Run:
```
/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/test_ai_routes.py backend/tests/unit/office -q
/home/fz/anaconda3/envs/sage-backend/bin/ruff check backend/api/ai_routes.py backend/tests/unit/test_ai_routes.py
npx vitest run src/shared/api/__tests__/aiApi.test.ts
npx tsc --noEmit
node scripts/architecture-check.mjs
node scripts/export-ipc-manifest.mjs --check
```
Expected: 全绿。

- [ ] **Step 12: 提交**

```bash
git add backend/api/ai_routes.py backend/api/office_routes.py backend/tests/unit/test_ai_routes.py \
        electron/commandRoutes/office.ts electron/ipc-manifest.json \
        src/shared/api/aiApi.ts src/shared/api/__tests__/aiApi.test.ts architecture-baseline.json
git commit -m "feat(office): 新增 AI 改写/对话后端端点与 IPC 路由（P2 M3）"
```

---

### Task 5: 改写/润色 + 对话闭环（M4）

**Files:**
- Create: `src/features/office/sidebar/useAiCapabilities.ts`
- Create: `src/features/office/sidebar/suggestionFactory.ts`
- Create: `src/features/office/sidebar/__tests__/suggestionFactory.test.ts`
- Create: `src/features/office/sidebar/__tests__/useAiCapabilities.test.tsx`
- Modify: `src/features/office/sidebar/AiSidebar.tsx`（接入 pending / error / apply）
- Modify: `src/features/office/sidebar/OfficeAiSidebarHost.tsx`（接入 hook + 浮出条）

**Interfaces:**
- Consumes: `aiApi`（Task 4）、`useOfficeWorkspaceStore`（Task 1）、`collectDocumentParagraphs`（Task 2）、`officeSpecApi.reviseAiIssues` / `runAiReview`（既有）
- Produces:
  ```ts
  export function suggestionFromRewrite(params: {
    paraIndex: number
    originalText: string
    suggestedText: string
    comment?: string
  }): SuggestionCardData
  export function toReviseIssue(suggestion: SuggestionCardData): AiReviewIssue
  export interface AiCapabilities {
    pending: boolean
    errorText: string | null
    runRewrite: (params: { instruction: AiRewriteInstruction; text: string; targetLang?: string; paraIndex?: number | null }) => Promise<void>
    runChat: (message: string) => Promise<void>
    applySuggestion: (messageId: string, suggestion: SuggestionCardData) => Promise<void>
    markSkipped: (messageId: string, suggestionId: string) => void
  }
  export function useAiCapabilities(deps: {
    rootRef: React.RefObject<HTMLElement>
    filePath: string | null
    onNavigateTab: (tab: QuickActionTab) => void
  }): AiCapabilities
  ```

- [ ] **Step 1: 写 `suggestionFactory` 失败测试**

```ts
import { describe, expect, it } from 'vitest'
import { suggestionFromRewrite, toReviseIssue } from '../suggestionFactory'

describe('suggestionFactory', () => {
  it('builds a pending suggestion card', () => {
    const card = suggestionFromRewrite({
      paraIndex: 3,
      originalText: 'old',
      suggestedText: 'new',
      comment: '更通顺',
    })
    expect(card.paraIndex).toBe(3)
    expect(card.severity).toBe('info')
    expect(card.applied).toBe('pending')
    expect(card.ruleName).toBe('更通顺')
  })

  it('maps a suggestion to an AiReviewIssue accepted by /office/ai/revise', () => {
    const issue = toReviseIssue(
      suggestionFromRewrite({ paraIndex: 3, originalText: 'old', suggestedText: 'new' }),
    )
    expect(issue.actual).toBe('old')
    expect(issue.expected).toBe('new')
    expect(issue.suggestion).toBe('new')
    expect(issue.fixable).toBe(true)
    expect(issue.location).toEqual({ paragraph_index: 3, paragraph_text: 'old' })
    expect(issue.source.kind).toBe('llm')
  })
})
```

- [ ] **Step 2: 实现 `suggestionFactory.ts`**

```ts
import type { AiReviewIssue } from '../../../shared/api/officeSpecTypes'
import type { SuggestionCardData } from '../../../entities/office/officeWorkspaceStore'

export function suggestionFromRewrite(params: {
  paraIndex: number
  originalText: string
  suggestedText: string
  comment?: string
}): SuggestionCardData {
  return {
    id: `sg-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
    paraIndex: params.paraIndex,
    severity: 'info',
    originalText: params.originalText,
    suggestedText: params.suggestedText,
    ...(params.comment ? { ruleName: params.comment } : {}),
    applied: 'pending',
  }
}

export function toReviseIssue(suggestion: SuggestionCardData): AiReviewIssue {
  return {
    id: suggestion.id,
    severity: suggestion.severity,
    category: 'ai_rewrite',
    message: suggestion.ruleName ?? 'AI 改写',
    suggestion: suggestion.suggestedText,
    rationale: '',
    expected: suggestion.suggestedText,
    actual: suggestion.originalText,
    fixable: true,
    location: { paragraph_index: suggestion.paraIndex, paragraph_text: suggestion.originalText },
    source: {
      kind: 'llm',
      spec_id: null,
      spec_name: null,
      rule_id: null,
      rule_pack_id: null,
    },
  }
}
```

- [ ] **Step 3: 写 `useAiCapabilities` 失败测试**

断言点（用 `@testing-library/react` 的 `renderHook`）：
- 未选中文档时 `runRewrite` 直接写入一条 `system` 错误消息，不调用 `aiApi.rewrite`
- 选中文档时 `runRewrite` 调用 `aiApi.rewrite`，把结果作为 `assistant` 消息追加，并带 1 张 `pending` 建议卡（`paraIndex` 来自入参）
- `aiApi.rewrite` 抛错时追加 `system` 消息且 `errorText` 被设置
- `runChat` 把 `history` 取自上一条 user/assistant 消息（最多 20 条），`documentContext` 来自 `collectDocumentParagraphs` 拼接

- [ ] **Step 4: 实现 `useAiCapabilities.ts`**

要点（必须逐条实现）：
1. 依赖 `useOfficeWorkspaceStore` 的 `activeDocument`、`appendMessage`、`updateSuggestionStatus`、`conversation`。
2. `runRewrite`：
   - 无 `activeDocument` → `appendMessage({ role: 'system', content: t('office.ai.sidebar.no_document') })`，返回。
   - 调 `aiApi.rewrite({ workspacePath: doc.workspace_path ?? '', documentId: doc.id, text, instruction, targetLang })`。
   - 成功：`appendMessage({ role: 'assistant', content: result.result, attachments: [suggestionFromRewrite({...})].filter(Boolean), createdAt: Date.now() })`；`paraIndex` 取入参，缺省 `-1` 表示整篇（此时**不生成**建议卡，只显示结果 + 复制按钮）。
   - 失败：`setErrorText(t('office.ai.sidebar.request_failed', { message }))` 并追加 `system` 消息。
3. `runChat`：构造 `history`（`conversation.filter(role!=='system').slice(-20).map(...)`），`documentContext` 用 `collectDocumentParagraphs(rootRef.current).map(p => p.text).join('\n').slice(0, 4000)`；把用户消息先追加，再追加回答。
4. `applySuggestion`：需要 `filePath`；缺 `filePath` 时错误提示 `office.ai.sidebar.apply_disabled`。调
   ```ts
   await officeSpecApi.reviseAiIssues({
     workspace_path: workspacePath,
     file_path: filePath,
     doc_id: activeDocument.id,
     issues: [toReviseIssue(suggestion)],
     add_comments: true,
   })
   ```
   成功后 `updateSuggestionStatus(messageId, suggestion.id, 'applied')` 并把 `t('office.ai.sidebar.apply_done')` 追加为 `system` 消息。
5. 所有状态更新必须走 store（immutable），不得本地 `useState` 复制 `conversation`。

- [ ] **Step 5: 接入侧栏与浮出条**

`OfficeAiSidebarHost.tsx` 改为：
- 接收 `rootRef`（画布根节点）、`filePath`（当前 Word 文档绝对路径，来自 `OfficePreviewPanel` → `Office.tsx`）
- 用 `useSelectionCapture(rootRef)`
- 用 `useAiCapabilities({ rootRef, filePath, onNavigateTab })`
- 渲染 `FloatingActionBar`：
  - `anchorRect` 由 `selection` 存在时的 `window.getSelection()?.getRangeAt(0).getBoundingClientRect()` 计算（`useMemo`，依赖 `selection`）
  - `canApply` = `activeDocument?.doc_type === 'word' && Boolean(filePath)`
  - `onAction('rewrite')` → `runRewrite({ instruction: 'polish', text: selection.text, paraIndex: selection.anchorParaIndex })`
  - `onAction('chat')` → 打开侧栏并把 `selection.rawContext` 预填进 `CommandInput`（通过 `initialValue` prop）
  - `onAction('edit')` / `onAction('audit')` → Task 6 实现；本期先 `runRewrite` / 打开侧栏占位并在注释标注 `Task 6`
  - `onDismiss()` → `setSelection(null)`
- 命令解析（`CommandInput.onSubmit`）：
  - `/audit` → Task 6；本期追加 system 消息占位
  - `/summarize` → `runRewrite({ instruction: 'summarize', text: 全文段落 })`
  - `/translate` → `runRewrite({ instruction: 'translate', targetLang: '中文', ... })`
  - `/rules` → `onNavigateTab('rules')`
  - 其他 `/` 前缀且未识别 → system 消息「未知命令」
  - 非 `/` 开头 → `runChat(value)`

- [ ] **Step 6: 全量验证**

Run: `npx vitest run src/features/office/sidebar && npx tsc --noEmit && npx eslint src/features/office/sidebar --max-warnings=0`
Expected: 全绿。

- [ ] **Step 7: 提交**

```bash
git add src/features/office/sidebar
git commit -m "feat(office): 侧栏改写与对话闭环（P2 M4）"
```

---

### Task 6: AI 审校建议 + 指令式修改（M5）

**Files:**
- Create: `src/features/office/sidebar/useAuditSuggestions.ts`
- Create: `src/features/office/sidebar/InstructionEditCard.tsx`
- Create: `src/features/office/sidebar/__tests__/useAuditSuggestions.test.tsx`
- Create: `src/features/office/sidebar/__tests__/InstructionEditCard.test.tsx`
- Modify: `src/features/office/sidebar/AiSidebar.tsx`（渲染 `InstructionEditCard`）
- Modify: `src/features/office/sidebar/OfficeAiSidebarHost.tsx`（接线 `audit` / `edit`）

**Interfaces:**
- Consumes: `officeSpecApi.runAiReview` / `reviseAiIssues`、`AiReviewIssue`、`SuggestionCardData`
- Produces:
  ```ts
  export interface AuditSuggestionsApi {
    running: boolean
    runAudit: (params: { filePath: string; workspacePath: string; docId: string }) => Promise<void>
    applyAll: (messageId: string) => Promise<void>
  }
  export function useAuditSuggestions(): AuditSuggestionsApi
  export interface InstructionEditCardProps {
    busy: boolean
    edits: SuggestionCardData[]
    onApply: (suggestion: SuggestionCardData) => void
    onSkip: (suggestionId: string) => void
  }
  export function InstructionEditCard(props: InstructionEditCardProps): JSX.Element
  ```

- [ ] **Step 1: 写审校 hook 失败测试**

断言点：
- `runAudit` 调 `officeSpecApi.runAiReview({ workspace_path, file_path, doc_id, use_llm: true })`
- 返回 `issues` 中 `fixable === false` 或 `!actual || !expected` 的项**不**进入建议卡
- 可修复项按 `location.paragraph_index` 映射为 `SuggestionCardData`（`msgId` 为返回消息的 id）
- 整个审校结果作为一条 `assistant` 消息追加，`attachments` 为建议卡数组
- `applyAll` 用 `reviseAiIssues` 一次性提交所有 `pending` 卡，成功后逐条置 `applied`

- [ ] **Step 2: 实现 `useAuditSuggestions.ts`**

关键实现：

```ts
const result = await officeSpecApi.runAiReview({
  workspace_path: workspacePath,
  file_path: filePath,
  doc_id: docId,
  use_llm: true,
})

const cards: SuggestionCardData[] = result.issues
  .filter((issue) => issue.fixable && issue.actual && (issue.expected || issue.suggestion))
  .map((issue) => ({
    id: issue.id,
    paraIndex: issue.location?.paragraph_index ?? -1,
    severity: issue.severity,
    originalText: issue.actual as string,
    suggestedText: (issue.expected || issue.suggestion) as string,
    ...(issue.message ? { ruleName: issue.message } : {}),
    applied: 'pending' as const,
  }))

appendMessage({
  id: newMessageId(),
  role: 'assistant',
  content: t('office.ai.audit.title'),
  attachments: cards,
  createdAt: Date.now(),
})
```

`applyAll(messageId)`：

```ts
const message = conversation.find((m) => m.id === messageId)
const pending = (message?.attachments ?? []).filter((c) => c.applied === 'pending')
if (!pending.length) return
await officeSpecApi.reviseAiIssues({
  workspace_path: workspacePath,
  file_path: filePath,
  doc_id: docId,
  issues: pending.map(toReviseIssue),
  add_comments: true,
})
pending.forEach((c) => updateSuggestionStatus(messageId, c.id, 'applied'))
```

- [ ] **Step 3: 写 `InstructionEditCard` 失败测试**

断言点：
- 渲染每条的段号（`paraIndex + 1`）、原文、建议文
- 点击「应用」调用 `onApply(card)`，点击「跳过」调用 `onSkip(card.id)`
- `busy` 为 true 时所有按钮 disabled

- [ ] **Step 4: 实现 `InstructionEditCard.tsx`**

布局：每条一个卡片，`<del>` 原文 + `<ins>` 建议文；底部 `[应用][跳过]`；`data-testid="office-ai-instruction-edit-{id}"`。

- [ ] **Step 5: 接线「指令式修改」**

`OfficeAiSidebarHost` 增加 `editInstruction` 流程：
1. 浮出条 `edit` → 打开侧栏，`CommandInput` 预填 `把这段改成：` + 选区文本
2. 用户提交后：以整篇段落为上下文调 `aiApi.rewrite({ instruction: 'custom', customInstruction: userInput, text: 段落原文, paraIndex: anchorParaIndex })`
3. 结果作为建议卡追加，`AiSidebar` 在 `attachments.length > 1` 或命令为 `/edit` 时用 `InstructionEditCard` 渲染
4. 无 `anchorParaIndex` 时追加 system 消息 `office.ai.edit.no_match`

- [ ] **Step 6: 接入「审校建议」**

浮出条 `audit` 与 `/audit` 命令 → `runAudit({ filePath, workspacePath, docId })`；
`AiSidebar` 建议列表顶部加 `[应用全部可修复项]`（`data-testid="office-ai-audit-apply-all"`）→ `applyAll(messageId)`。

> 非 Word 文档：`audit` 与 `edit` 按钮保持 disabled（`canApply === false`）。

- [ ] **Step 7: 全量验证**

Run: `npx vitest run src/features/office/sidebar && npx tsc --noEmit && npx eslint src/features/office/sidebar --max-warnings=0`
Expected: 全绿。

- [ ] **Step 8: 提交**

```bash
git add src/features/office/sidebar
git commit -m "feat(office): AI 审校建议与指令式修改（P2 M5）"
```

---

### Task 7: `OfficeEditPreviewDialog` AI 接入（M6）

**Files:**
- Create: `src/features/office/OfficeEditAiActions.tsx`
- Create: `src/features/office/__tests__/OfficeEditAiActions.test.tsx`
- Modify: `src/features/office/OfficeEditPreviewDialog.tsx`（仅接线，净增 ≤ 15 行）

**Interfaces:**
- Consumes: `aiApi.rewrite`（Task 4）
- Produces:
  ```ts
  export type OfficeEditAiInstruction = 'rewrite' | 'polish' | 'expand' | 'condense'
  export interface OfficeEditAiActionsProps {
    workspacePath: string
    documentId: string
    /** 读取当前编辑框内容的快照（用于构造请求） */
    getCurrentText: () => string
    /** 结果回填到编辑框 */
    onResult: (text: string) => void
    disabled?: boolean
  }
  export function OfficeEditAiActions(props: OfficeEditAiActionsProps): JSX.Element
  ```

- [ ] **Step 1: 写失败测试**

断言点：
- 渲染 4 个按钮（`office-edit-ai-rewrite|polish|expand|condense`）
- 点击「润色」时调 `aiApi.rewrite({ instruction: 'polish', text: getCurrentText(), ... })`
- 成功后调用 `onResult('新文本')`
- 失败时在组件内显示错误文案（`role="alert"`），不抛出
- `getCurrentText()` 返回空串时按钮 disabled

- [ ] **Step 2: 实现 `OfficeEditAiActions.tsx`**

- 单一 `busy` 状态，busy 时全部按钮 disabled 并显示 `office.ai.sidebar.thinking`
- 错误文案用 `office.ai.sidebar.request_failed`
- 不弹确认框；结果直接回填（对话框本身可撤销）
- `data-testid="office-edit-ai-actions"`

- [ ] **Step 3: 接入对话框**

在 `OfficeEditPreviewDialog.tsx` 的表单标题行下方插入：

```tsx
<OfficeEditAiActions
  workspacePath={workspacePath}
  documentId={documentId}
  getCurrentText={() => currentDocText}
  onResult={(text) => setCurrentDocText(text)}
/>
```

> 实际变量名以实现时的对话框 state 为准（实现者必须先读该文件确认编辑框 state 名称与 `workspacePath` / `documentId` 来源）。**只在命中已有 state 时接线，不新增副本 state。**

- [ ] **Step 4: 检查文件行数**

Run: `wc -l src/features/office/OfficeEditPreviewDialog.tsx src/features/office/OfficeEditAiActions.tsx`
Expected: 前者 < 800；后者 < 200。

- [ ] **Step 5: 全量验证**

Run: `npx vitest run src/features/office && npx tsc --noEmit && node scripts/architecture-check.mjs`
Expected: 全绿，架构 0 违规。

- [ ] **Step 6: 提交**

```bash
git add src/features/office/OfficeEditAiActions.tsx src/features/office/OfficeEditPreviewDialog.tsx \
        src/features/office/__tests__/OfficeEditAiActions.test.tsx
git commit -m "feat(office): 编辑预览对话框接入 AI 改写按钮组（P2 M6）"
```

---

### Task 8: 收尾 —— 页面接线、文档归档、门禁（M7）

**Files:**
- Modify: `src/pages/Office.tsx`（渲染 `OfficeAiSidebarHost`，传 `activeTab` / `rootRef` / `filePath`）
- Modify: `src/features/office/OfficePreviewPanel.tsx`（向上暴露画布 DOM 根 ref 与当前 Word 绝对路径）
- Create: `docs/technical/<NN>-office-ai-workbench.md` 的 P2 章节（编号按实测分配）
- Modify: `docs/user-manual/<NN>-document-workbench.md` 的 P2 章节
- Modify: `architecture-baseline.json`（按实测）
- Delete: `docs/plans/2026-11-07_office-ai-workbench-p2-ai-sidebar.md`（并入技术/用户手册后按规范删除）

- [ ] **Step 1: 页面接线**

`src/pages/Office.tsx` 根 `div` 内、Tab 内容之后渲染：

```tsx
<OfficeAiSidebarHost
  activeTab={activeTab}
  onNavigateTab={(tab) => setActiveTab(tab)}
  rootRef={canvasRootRef}
  filePath={activeWordPath}
/>
```

- `canvasRootRef` 由 `DocumentCanvas` 的容器 `ref` 提升到 `Office.tsx`（若现为内部 ref，则改用 `OfficeLayout` 传入的 `center` 包裹节点）
- `activeWordPath` 来自 `OfficePreviewPanel` 的 `onActiveWordResolved?: (path: string | null) => void` 回调（新增 optional prop，默认不传不改变既有行为）

- [ ] **Step 2: 端到端手测**

按 `.claude/skills/run-desktop/SKILL.md` 启动（Vite + Electron 正常模式），验证：
1. 打开 Word 文档 → 选中一段 → 浮出条出现
2. 点「改写润色」→ 侧栏出现结果 → 点「应用到文档」→ 文档出现修订痕迹
3. 侧栏输入 `/summarize` → 返回摘要
4. 侧栏输入任意问题 → 返回回答
5. 点「审校建议」→ 建议卡列表 → 「应用全部可修复项」成功
6. 切换到 generate / rules / latex tab → 侧栏常驻，快捷指令内容随 tab 变化
7. 打开 `OfficeEditPreviewDialog` → AI 按钮组可用，结果回填编辑框

- [ ] **Step 3: 文档**

- 技术手册：新增小节说明 6 个侧栏组件、store 形状、2 个后端端点契约、锚点约定（`data-paragraph-index` 0 基）、复用 `review`/`revise` 的理由、win7 移植注意（pydantic 垫片）
- 用户手册：新增小节说明四类浮出操作、侧栏命令表、按 Tab 的快捷指令表、「只有 Word 支持应用」

- [ ] **Step 4: 门禁全量**

```
npx tsc --noEmit
npx vitest run
npx eslint src --max-warnings=0
node scripts/architecture-check.mjs
node scripts/export-ipc-manifest.mjs --check
/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit backend/tests/integration -q
/home/fz/anaconda3/envs/sage-backend/bin/ruff check backend/
```
Expected: 全绿（后端允许的既有 6 个环境性失败除外，见 memory `sage-backend-preexisting-test-failures`）。

- [ ] **Step 5: 删除计划文档并提交**

```bash
git rm docs/plans/2026-11-07_office-ai-workbench-p2-ai-sidebar.md
git add -A
git commit -m "docs(office): P2 AI 侧栏归档至技术与用户手册（P2 M7）"
```

---

## 5. 不修改

- `src/features/journal/JournalPanel.tsx`（按设计文档保留 4 测试 + barrel 契约）
- `src/features/office/OfficeAiAssistantPanel.tsx`（保留；P3 收尾时评估是否下线）
- `backend/api/office_ai_review_routes.py`（复用，不改）
- `electron/preload.ts` / `src/shared/types/electron-api.d.ts`（命令声明式，无需改动）

## 6. 双分支策略

1. main 完成 P2（PR #TBD）
2. squash 合并 main
3. cherry-pick 到 `release/win7`（独立 PR）
   - 前端 1:1 移植
   - `backend/api/ai_routes.py`：`ConfigDict` / `Field(max_length=...)` 换 `backend.compat.win7.pydantic_compat` 垫片；`List[...] = Field(max_length=20)` 换 `_constrained_list`
   - `architecture-baseline.json` 按 win7 实测值独立维护（不得直接拷 main 数值）
   - `electron/ipc-manifest.json` 在 win7 重新生成
4. win7 验证矩阵：tsc + vitest + py38 pytest + ruff + `check_py38_compat.py` + architecture + IPC manifest

## 7. 验收

- [ ] 选中文本 → 浮出条出现 → 「改写润色」→ 结果展示 → 「应用到文档」写入 Word 修订痕迹
- [ ] 侧栏 `/summarize`、`/translate`、`/rules`、`/audit` 命令全通
- [ ] 审校建议可逐条应用/跳过，批量应用正确
- [ ] 指令式修改能定位段落并给出 diff
- [ ] `OfficeEditPreviewDialog` AI 按钮可用，结果回填编辑框
- [ ] 快捷指令按 Tab 切换内容正确
- [ ] 后端 2 个新端点有契约测试 + 502 降级测试
- [ ] main / win7 双分支 CI 全绿
- [ ] 技术 / 用户手册章节已归档，计划文档已删除
