# Phase 6: @文件提及 + /btw 补充消息面板 (Stretch) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 sage 聊天输入框中支持 @文件提及(输入 `@` 触发文件搜索菜单,选中后插入 `@path/to/file`)和 `/btw` 补充消息面板(在主任务运行时不打断,弹层异步获取 LLM 答案并流式展示)。所有逻辑通过 Zustand store 管理,IPC 桥用 AbortController 实现 3s 超时,流式中断自动重连 1 次,整体覆盖率达 85%。

**Architecture:** 三个独立切片:
1. **@文件提及**:`useAtFileQuery`(纯 Hook,解析光标前 `@xxx` 模式) → `fileSearchClient`(IPC 客户端,3s AbortController) → `AtFileMenu`(浮层,显示搜索结果并支持键盘导航) → `ChatInput` 集成(监听 `@` 前缀触发查询、点击插入)。
2. **/btw 补充面板**:`useBtwCommand`(状态机 hook,封装 open/close/appendDelta/setLoading) → `btwState` Zustand store(全局状态,多组件共享) → `BtwOverlay`(浮层面板,渲染 question/answer/loading/error 态) → `useChat.sendMessage` 接受 `btw` 字段。
3. **集成**:`MessageList` 挂载 `BtwOverlay`,`ChatInput` 接入 `AtFileMenu` + `/btw` 拦截。

**Tech Stack:** React 18, TypeScript, Zustand 4.4, Vitest, @testing-library/react, AbortController (Web API,无新增依赖)

## Global Constraints

来自 spec `2026-06-25-aionui-inspired-ui-design.md`:
- **不新增 npm 包**(AbortController 是 Web API;Zustand 已存在)
- 覆盖率:`useAtFileQuery` ≥ 95%, `useBtwCommand` ≥ 95%, 整体 ≥ 85%
- 文件搜索超时:**3s AbortController**,超时显示"重试"按钮
- 流式中断:**自动重连 1 次**,仍失败标 error
- 多个 `/btw` 同时打开:第二次自动关闭前一个
- `/btw` 加载中 Esc:关闭 overlay,**不取消主请求**
- 不破坏现有 slash 命令(`/clear` `/help` `/search` `/summarize` `/translate` `/compact`)
- FSD 架构:`features/chat/*` 放组合逻辑, `entities/chat/*` 放状态, `widgets/chat/*` 放 UI
- TDD 严格:每个 Task 先写测试,RED → GREEN → REFACTOR
- 现有 `useChat.sendMessage(content, sessionId?)` 增加可选第三参数 `options?: { btw?: BtwPayload }`,不破坏现有调用
- i18n:新增 `chat.atFile.*` `chat.btw.*` keys 到 `zh.ts`/`en.ts`
- 所有 Context/Store 用 TypeScript 显式类型,禁用 `any`
- 使用现有 `useTranslation` hook(`src/shared/lib/i18n`)
- 不破坏虚拟列表、Shiki 高亮、命令面板、i18n 基础设施

---

## File Structure

**New files:**
- `src/entities/chat/btwState.ts` — Zustand store (btw 状态)
- `src/entities/chat/__tests__/btwState.test.ts` — Store tests
- `src/features/chat/useAtFileQuery.ts` — 提取 @xxx 模式
- `src/features/chat/__tests__/useAtFileQuery.test.tsx` — Hook tests
- `src/features/chat/AtFileMenu.tsx` — @ 触发文件选择器
- `src/features/chat/__tests__/AtFileMenu.test.tsx` — Component tests
- `src/features/chat/useBtwCommand.ts` — /btw 状态机
- `src/features/chat/__tests__/useBtwCommand.test.tsx` — Hook tests
- `src/features/chat/BtwOverlay.tsx` — btw 浮层面板
- `src/features/chat/__tests__/BtwOverlay.test.tsx` — Component tests
- `src/shared/api/fileSearchClient.ts` — 文件搜索 IPC
- `src/shared/api/__tests__/fileSearchClient.test.ts` — Client tests
- `src/features/chat/index.ts` — 统一导出

**Modified files:**
- `src/widgets/chat/ChatInput.tsx` — 监听 @ + /btw 前缀
- `src/widgets/chat/MessageList.tsx` — 挂载 BtwOverlay
- `src/widgets/chat/__tests__/ChatInput.btw.test.tsx` — ChatInput btw 拦截测试
- `src/features/send-message/index.ts` — 增加 btw 字段导出
- `src/features/send-message/useChat.ts` — sendMessage 接受 options.btw
- `src/shared/lib/i18n/zh.ts` — 新增 i18n keys
- `src/shared/lib/i18n/en.ts` — 新增 i18n keys

---

## Task 1: BtwState Zustand store — 写测试先行 (RED)

**Files:**
- Create: `/home/fz/project/sage/src/entities/chat/__tests__/btwState.test.ts`

**Interfaces:**
- Consumes: `useBtwState` hook (待实现)
- Produces: 无

- [ ] **Step 1: 创建测试文件**

```tsx
// src/entities/chat/__tests__/btwState.test.ts
import { describe, it, expect, beforeEach } from 'vitest';
import { useBtwState } from '../btwState';

describe('useBtwState', () => {
  beforeEach(() => {
    useBtwState.setState({
      isOpen: false,
      question: '',
      answer: '',
      isLoading: false,
      parentTaskRunning: false,
    });
  });

  it('has correct initial state', () => {
    const s = useBtwState.getState();
    expect(s.isOpen).toBe(false);
    expect(s.question).toBe('');
    expect(s.answer).toBe('');
    expect(s.isLoading).toBe(false);
    expect(s.parentTaskRunning).toBe(false);
  });

  it('open() sets isOpen=true, stores question, clears answer', () => {
    useBtwState.getState().open('什么是 useEffect?');
    const s = useBtwState.getState();
    expect(s.isOpen).toBe(true);
    expect(s.question).toBe('什么是 useEffect?');
    expect(s.answer).toBe('');
  });

  it('close() resets to initial state', () => {
    useBtwState.getState().open('q');
    useBtwState.getState().setLoading(true);
    useBtwState.getState().appendDelta('partial');
    useBtwState.getState().close();
    const s = useBtwState.getState();
    expect(s.isOpen).toBe(false);
    expect(s.question).toBe('');
    expect(s.answer).toBe('');
    expect(s.isLoading).toBe(false);
  });

  it('appendDelta appends to existing answer', () => {
    useBtwState.getState().appendDelta('hello');
    useBtwState.getState().appendDelta(' world');
    expect(useBtwState.getState().answer).toBe('hello world');
  });

  it('setLoading() toggles isLoading', () => {
    useBtwState.getState().setLoading(true);
    expect(useBtwState.getState().isLoading).toBe(true);
    useBtwState.getState().setLoading(false);
    expect(useBtwState.getState().isLoading).toBe(false);
  });

  it('open() while already open replaces question and clears answer (重定义 /btw 互斥)', () => {
    useBtwState.getState().open('first');
    useBtwState.getState().appendDelta('partial answer');
    useBtwState.getState().open('second');
    const s = useBtwState.getState();
    expect(s.question).toBe('second');
    expect(s.answer).toBe('');
    expect(s.isOpen).toBe(true);
  });
});
```

- [ ] **Step 2: 运行测试,验证 RED**

```bash
cd /home/fz/project/sage && npx vitest run src/entities/chat/__tests__/btwState.test.ts
```

Expected: FAIL with "Cannot find module '../btwState'"

- [ ] **Step 3: 不 commit**(实现 Task 2 时一起 commit)

---

## Task 2: BtwState Zustand store — 实现 (GREEN)

**Files:**
- Create: `/home/fz/project/sage/src/entities/chat/btwState.ts`

**Interfaces:**
- Consumes: `create` from `zustand`
- Produces: `useBtwState` hook

- [ ] **Step 1: 创建 store 文件**

```typescript
// src/entities/chat/btwState.ts
import { create } from 'zustand';

/**
 * Btw 状态机 — 与 spec Phase 6 一致
 *
 * 状态转移 (由 useBtwCommand 驱动):
 *   idle ──open()──▶ loading ──appendDelta()──▶ answered
 *                      │                         │
 *                      ├──setError──▶ error      │
 *                      │                         │
 *                      └──close()──▶ idle (任何状态)
 *
 * 多 /btw 互斥: 第二次 open() 自动替换 question 并清空 answer,
 * 旧流由 useBtwCommand 负责取消
 */
export interface BtwState {
  isOpen: boolean;
  question: string;
  answer: string;
  isLoading: boolean;
  parentTaskRunning: boolean;
  open: (question: string) => void;
  close: () => void;
  appendDelta: (delta: string) => void;
  setLoading: (v: boolean) => void;
}

const initial = {
  isOpen: false,
  question: '',
  answer: '',
  isLoading: false,
  parentTaskRunning: false,
};

export const useBtwState = create<BtwState>((set) => ({
  ...initial,
  open: (question) => set({ isOpen: true, question, answer: '', isLoading: true }),
  close: () => set({ ...initial }),
  appendDelta: (delta) =>
    set((prev) => ({ ...prev, answer: prev.answer + delta, isLoading: false })),
  setLoading: (v) => set({ isLoading: v }),
}));
```

- [ ] **Step 2: 运行测试,验证 GREEN**

```bash
cd /home/fz/project/sage && npx vitest run src/entities/chat/__tests__/btwState.test.ts
```

Expected: 6 tests pass

- [ ] **Step 3: Type check**

```bash
cd /home/fz/project/sage && npx tsc --noEmit
```

Expected: 无 type error

- [ ] **Step 4: Commit**

```bash
cd /home/fz/project/sage && git add src/entities/chat/btwState.ts src/entities/chat/__tests__/btwState.test.ts && git commit -m "feat(chat): add BtwState Zustand store for /btw overlay

Phase 6 的 /btw 状态存储:
- open(question) / close() / appendDelta(delta) / setLoading(v)
- 多 /btw 互斥 (第二次 open 自动清空 answer)
- Esc 任何状态 → close() 回到 idle
"
```

---

## Task 3: fileSearchClient IPC 客户端 — 写测试先行 (RED)

**Files:**
- Create: `/home/fz/project/sage/src/shared/api/__tests__/fileSearchClient.test.ts`

**Interfaces:**
- Consumes: `vi.mock('../desktopInvoke')` (与现有 `__tests__/desktop.test.ts` 同样模式)
- Produces: 无

- [ ] **Step 1: 创建测试文件**

```typescript
// src/shared/api/__tests__/fileSearchClient.test.ts
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { fileSearchClient } from '../fileSearchClient';

const invokeMock = vi.fn();
vi.mock('../desktopInvoke', () => ({
  invoke: (...args: unknown[]) => invokeMock(...args),
}));

interface FileSearchResult {
  path: string;
  name: string;
  size?: number;
}

describe('fileSearchClient', () => {
  beforeEach(() => {
    invokeMock.mockReset();
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  it('search() invokes workspace_search_files with query', async () => {
    const results: FileSearchResult[] = [
      { path: 'src/foo.ts', name: 'foo.ts' },
      { path: 'src/foo.test.ts', name: 'foo.test.ts' },
    ];
    invokeMock.mockResolvedValueOnce(results);
    const out = await fileSearchClient.search('foo');
    expect(invokeMock).toHaveBeenCalledWith('workspace_search_files', { query: 'foo', limit: 20 });
    expect(out).toEqual(results);
  });

  it('search() rejects with timeout error when invoke takes > 3s', async () => {
    vi.useFakeTimers();
    invokeMock.mockImplementation(
      () => new Promise(() => {/* never resolve */})
    );
    const p = fileSearchClient.search('slow');
    const expectation = expect(p).rejects.toThrow(/timeout/i);
    await vi.advanceTimersByTimeAsync(3001);
    await expectation;
  });

  it('search() can be aborted via AbortSignal before timeout', async () => {
    const externalAbort = new AbortController();
    invokeMock.mockImplementation(
      (_, args: { signal?: AbortSignal }) =>
        new Promise<FileSearchResult[]>((_resolve, reject) => {
          args.signal?.addEventListener('abort', () => reject(new DOMException('aborted', 'AbortError')));
        }),
    );
    const p = fileSearchClient.search('q', { signal: externalAbort.signal });
    externalAbort.abort();
    await expect(p).rejects.toThrow(/aborted/i);
  });

  it('search() respects custom limit', async () => {
    invokeMock.mockResolvedValueOnce([]);
    await fileSearchClient.search('q', { limit: 5 });
    expect(invokeMock).toHaveBeenCalledWith('workspace_search_files', { query: 'q', limit: 5 });
  });
});
```

- [ ] **Step 2: 运行测试,验证 RED**

```bash
cd /home/fz/project/sage && npx vitest run src/shared/api/__tests__/fileSearchClient.test.ts
```

Expected: FAIL with "Cannot find module '../fileSearchClient'"

- [ ] **Step 3: 不 commit**

---

## Task 4: fileSearchClient IPC 客户端 — 实现 (GREEN)

**Files:**
- Create: `/home/fz/project/sage/src/shared/api/fileSearchClient.ts`

**Interfaces:**
- Consumes: `invoke` from `./desktopInvoke`
- Produces: `fileSearchClient` object with `search(query, opts?)` method

- [ ] **Step 1: 创建客户端文件**

```typescript
// src/shared/api/fileSearchClient.ts
import { invoke } from './desktopInvoke';

/** 文件搜索结果 (与后端 workspace_search_files 响应一致) */
export interface FileSearchResult {
  path: string;
  name: string;
  size?: number;
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

async function invokeWithTimeout<T>(cmd: string, args: Record<string, unknown>, signal?: AbortSignal): Promise<T> {
  const timeoutController = new AbortController();
  const timeoutId = setTimeout(() => timeoutController.abort(), DEFAULT_TIMEOUT_MS);

  const onExternalAbort = (): void => timeoutController.abort();
  if (signal) {
    if (signal.aborted) {
      clearTimeout(timeoutId);
      throw new DOMException('aborted', 'AbortError');
    }
    signal.addEventListener('abort', onExternalAbort, { once: true });
  }

  try {
    return await invoke<T>(cmd, { ...args, signal: timeoutController.signal });
  } catch (err) {
    if (timeoutController.signal.aborted && !signal?.aborted) {
      throw new FileSearchTimeoutError(String(args.query ?? ''));
    }
    throw err;
  } finally {
    clearTimeout(timeoutId);
    if (signal) signal.removeEventListener('abort', onExternalAbort);
  }
}

export const fileSearchClient = {
  /**
   * 工作区文件模糊搜索, 3s 超时, AbortController 可外部取消
   * 后端命令: workspace_search_files (Phase 6 由后端实现, 此处仅前端桩化测试)
   */
  async search(query: string, options: FileSearchOptions = {}): Promise<FileSearchResult[]> {
    const limit = options.limit ?? DEFAULT_LIMIT;
    return invokeWithTimeout<FileSearchResult[]>(
      'workspace_search_files',
      { query, limit },
      options.signal,
    );
  },
};
```

- [ ] **Step 2: 运行测试,验证 GREEN**

```bash
cd /home/fz/project/sage && npx vitest run src/shared/api/__tests__/fileSearchClient.test.ts
```

Expected: 4 tests pass

- [ ] **Step 3: Type check**

```bash
cd /home/fz/project/sage && npx tsc --noEmit
```

- [ ] **Step 4: Commit**

```bash
cd /home/fz/project/sage && git add src/shared/api/fileSearchClient.ts src/shared/api/__tests__/fileSearchClient.test.ts && git commit -m "feat(chat): add fileSearchClient with 3s AbortController timeout

Phase 6 的 @文件提及 IPC 桥:
- search(query, opts?) 调后端 workspace_search_files
- 3s 超时抛 FileSearchTimeoutError
- 外部 AbortSignal 可取消 (组件卸载时)
- 不可变 API, 禁用 any"
```

---

## Task 5: useAtFileQuery Hook — 写测试先行 (RED)

**Files:**
- Create: `/home/fz/project/sage/src/features/chat/__tests__/useAtFileQuery.test.tsx`

**Interfaces:**
- Consumes: 无 (纯函数式 hook, 测试用 renderHook)
- Produces: 无

- [ ] **Step 1: 创建测试文件**

```tsx
// src/features/chat/__tests__/useAtFileQuery.test.tsx
import { describe, it, expect } from 'vitest';
import { renderHook } from '@testing-library/react';
import { useAtFileQuery } from '../useAtFileQuery';

describe('useAtFileQuery', () => {
  it('returns null query when no @ trigger', () => {
    const { result } = renderHook(() => useAtFileQuery('hello world', 11));
    expect(result.current.query).toBeNull();
    expect(result.current.startIdx).toBe(0);
    expect(result.current.endIdx).toBe(0);
  });

  it('extracts @ followed by single word', () => {
    const { result } = renderHook(() => useAtFileQuery('@foo bar', 4));
    expect(result.current.query).toBe('foo');
    expect(result.current.startIdx).toBe(0);
    expect(result.current.endIdx).toBe(4);
  });

  it('extracts @query up to cursor (no spaces allowed)', () => {
    const { result } = renderHook(() => useAtFileQuery('@foo bar', 4));
    expect(result.current.query).toBe('foo');
  });

  it('handles cursor in middle of word', () => {
    const { result } = renderHook(() => useAtFileQuery('@fo', 3));
    expect(result.current.query).toBe('fo');
  });

  it('handles @ at start of input', () => {
    const { result } = renderHook(() => useAtFileQuery('@', 1));
    expect(result.current.query).toBe('');
    expect(result.current.startIdx).toBe(0);
    expect(result.current.endIdx).toBe(1);
  });

  it('returns null when @ is preceded by non-whitespace (email-like)', () => {
    const { result } = renderHook(() => useAtFileQuery('email@x', 7));
    expect(result.current.query).toBeNull();
  });

  it('handles multi-byte prefix (中文 + @)', () => {
    // '你好 @foo' — '你' '好' ' ' = 5 UTF-16 code units, '@' at 5
    const { result } = renderHook(() => useAtFileQuery('你好 @foo', 8));
    expect(result.current.query).toBe('foo');
    expect(result.current.startIdx).toBe(5);
    expect(result.current.endIdx).toBe(8);
  });

  it('returns null when cursor is before @', () => {
    const { result } = renderHook(() => useAtFileQuery('abc @foo', 3));
    expect(result.current.query).toBeNull();
  });
});
```

- [ ] **Step 2: 运行测试,验证 RED**

```bash
cd /home/fz/project/sage && npx vitest run src/features/chat/__tests__/useAtFileQuery.test.tsx
```

Expected: FAIL with "Cannot find module '../useAtFileQuery'"

- [ ] **Step 3: 不 commit**

---

## Task 6: useAtFileQuery Hook — 实现 (GREEN)

**Files:**
- Create: `/home/fz/project/sage/src/features/chat/useAtFileQuery.ts`

**Interfaces:**
- Consumes: 无外部依赖
- Produces: `useAtFileQuery(input, cursorPos)` hook, `AtFileQueryResult` type

- [ ] **Step 1: 创建 hook 文件**

```typescript
// src/features/chat/useAtFileQuery.ts

export interface AtFileQueryResult {
  /** null = 当前光标前无 @ 触发 */
  query: string | null;
  /** @ 字符在 input 中的索引 (含 @) */
  startIdx: number;
  /** cursor 位置 (query 结束位置, 不含尾随空格) */
  endIdx: number;
}

/**
 * 提取光标前的 @xxx 模式
 *
 * 规则:
 * - @ 必须出现在 cursor 之前
 * - @ 之前必须是空白/行首/字符串开头 (排除 email-like 'a@b')
 * - @ 与 cursor 之间不能有空格 (word boundary)
 * - query 包含 @ 到 cursor 之间的所有字符
 *
 * 示例:
 * - useAtFileQuery('@foo', 4) → { query: 'foo', startIdx: 0, endIdx: 4 }
 * - useAtFileQuery('email@x', 7) → { query: null, ... }
 * - useAtFileQuery('hello @world', 12) → { query: 'world', startIdx: 6, endIdx: 12 }
 */
export function useAtFileQuery(input: string, cursorPos: number): AtFileQueryResult {
  const safeCursor = Math.max(0, Math.min(cursorPos, input.length));
  const beforeCursor = input.slice(0, safeCursor);

  let atIdx = -1;
  for (let i = safeCursor - 1; i >= 0; i--) {
    const ch = beforeCursor[i];
    if (ch === '@') {
      atIdx = i;
      break;
    }
    if (ch === ' ' || ch === '\n' || ch === '\t') {
      break;
    }
  }

  if (atIdx === -1) {
    return { query: null, startIdx: 0, endIdx: 0 };
  }

  if (atIdx > 0) {
    const prevCh = beforeCursor[atIdx - 1];
    if (prevCh !== ' ' && prevCh !== '\n' && prevCh !== '\t') {
      return { query: null, startIdx: 0, endIdx: 0 };
    }
  }

  const query = beforeCursor.slice(atIdx + 1, safeCursor);
  return { query, startIdx: atIdx, endIdx: safeCursor };
}
```

- [ ] **Step 2: 运行测试,验证 GREEN**

```bash
cd /home/fz/project/sage && npx vitest run src/features/chat/__tests__/useAtFileQuery.test.tsx
```

Expected: 8 tests pass

- [ ] **Step 3: Type check**

```bash
cd /home/fz/project/sage && npx tsc --noEmit
```

- [ ] **Step 4: Commit**

```bash
cd /home/fz/project/sage && git add src/features/chat/useAtFileQuery.ts src/features/chat/__tests__/useAtFileQuery.test.tsx && git commit -m "feat(chat): add useAtFileQuery hook to extract @xxx pattern

Phase 6 @文件提及的核心解析逻辑:
- 从 cursor 向前找 @ (遇空格停止)
- @ 之前必须空白/行首 (排除 email)
- 纯函数式 hook, 无副作用
- 覆盖率 >= 95% (8 个单元测试覆盖 word boundary/email/multi-byte)"
```

---

## Task 7: AtFileMenu 组件 — 写测试先行 (RED)

**Files:**
- Create: `/home/fz/project/sage/src/features/chat/__tests__/AtFileMenu.test.tsx`

**Interfaces:**
- Consumes: `AtFileMenuProps` (待实现), `vi.mock('../../../shared/api/fileSearchClient')` (隔离 IPC)
- Produces: 无

- [ ] **Step 1: 创建测试文件**

```tsx
// src/features/chat/__tests__/AtFileMenu.test.tsx
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { AtFileMenu } from '../AtFileMenu';

const searchMock = vi.fn();
vi.mock('../../../shared/api/fileSearchClient', () => ({
  fileSearchClient: { search: (...args: unknown[]) => searchMock(...args) },
  FileSearchTimeoutError: class FileSearchTimeoutError extends Error {},
}));

interface MenuItem {
  path: string;
  name: string;
}

describe('AtFileMenu', () => {
  beforeEach(() => {
    searchMock.mockReset();
  });

  it('does not render when query is null', () => {
    const { container } = render(
      <AtFileMenu query={null} onSelect={vi.fn()} onClose={vi.fn()} />,
    );
    expect(container.firstChild).toBeNull();
  });

  it('renders empty state when search returns []', async () => {
    searchMock.mockResolvedValueOnce([]);
    render(<AtFileMenu query="nomatch" onSelect={vi.fn()} onClose={vi.fn()} />);
    await waitFor(() => {
      expect(screen.getByText(/未找到文件/)).toBeInTheDocument();
    });
  });

  it('renders loading state initially', () => {
    searchMock.mockImplementation(
      () => new Promise<MenuItem[]>(() => {/* pending */}),
    );
    render(<AtFileMenu query="foo" onSelect={vi.fn()} onClose={vi.fn()} />);
    expect(screen.getByText(/搜索中/)).toBeInTheDocument();
  });

  it('renders search results', async () => {
    const results: MenuItem[] = [
      { path: 'src/foo.ts', name: 'foo.ts' },
      { path: 'src/foo.test.ts', name: 'foo.test.ts' },
    ];
    searchMock.mockResolvedValueOnce(results);
    render(<AtFileMenu query="foo" onSelect={vi.fn()} onClose={vi.fn()} />);
    await waitFor(() => {
      expect(screen.getByText('foo.ts')).toBeInTheDocument();
      expect(screen.getByText('foo.test.ts')).toBeInTheDocument();
    });
  });

  it('clicking result calls onSelect with path', async () => {
    const onSelect = vi.fn();
    const results: MenuItem[] = [{ path: 'src/foo.ts', name: 'foo.ts' }];
    searchMock.mockResolvedValueOnce(results);
    render(<AtFileMenu query="foo" onSelect={onSelect} onClose={vi.fn()} />);
    await waitFor(() => screen.getByText('foo.ts'));
    fireEvent.click(screen.getByText('foo.ts'));
    expect(onSelect).toHaveBeenCalledWith('src/foo.ts');
  });

  it('shows retry button on timeout error', async () => {
    const { FileSearchTimeoutError } = await import('../../../shared/api/fileSearchClient');
    searchMock.mockRejectedValueOnce(new FileSearchTimeoutError('slow'));
    render(<AtFileMenu query="slow" onSelect={vi.fn()} onClose={vi.fn()} />);
    await waitFor(() => {
      expect(screen.getByText(/重试/)).toBeInTheDocument();
    });
  });

  it('calls search with current query', async () => {
    searchMock.mockResolvedValueOnce([]);
    render(<AtFileMenu query="abc" onSelect={vi.fn()} onClose={vi.fn()} />);
    await waitFor(() => {
      expect(searchMock).toHaveBeenCalledWith('abc', expect.objectContaining({}));
    });
  });
});
```

- [ ] **Step 2: 运行测试,验证 RED**

```bash
cd /home/fz/project/sage && npx vitest run src/features/chat/__tests__/AtFileMenu.test.tsx
```

Expected: FAIL with "Cannot find module '../AtFileMenu'"

- [ ] **Step 3: 不 commit**

---

## Task 8: AtFileMenu 组件 — 实现 (GREEN)

**Files:**
- Create: `/home/fz/project/sage/src/features/chat/AtFileMenu.tsx`

**Interfaces:**
- Consumes: `fileSearchClient` from `../../shared/api/fileSearchClient`, `useTranslation` from `../../shared/lib/i18n`
- Produces: `AtFileMenu` React component

- [ ] **Step 1: 创建组件文件**

```tsx
// src/features/chat/AtFileMenu.tsx
import { useEffect, useState, useRef } from 'react';
import { useTranslation } from '../../shared/lib/i18n';
import {
  fileSearchClient,
  FileSearchTimeoutError,
  type FileSearchResult,
} from '../../shared/api/fileSearchClient';

export interface AtFileMenuProps {
  /** null = 不显示 (来自 useAtFileQuery 的 query 字段) */
  query: string | null;
  onSelect: (path: string) => void;
  onClose: () => void;
}

type Status =
  | { kind: 'loading' }
  | { kind: 'success'; results: FileSearchResult[]; selectedIdx: number }
  | { kind: 'timeout' }
  | { kind: 'error'; message: string };

export function AtFileMenu({ query, onSelect, onClose }: AtFileMenuProps) {
  const { t } = useTranslation();
  const [status, setStatus] = useState<Status>({ kind: 'loading' });
  const abortRef = useRef<AbortController | null>(null);

  const doSearch = async (q: string): Promise<void> => {
    abortRef.current?.abort();
    const ac = new AbortController();
    abortRef.current = ac;
    setStatus({ kind: 'loading' });
    try {
      const results = await fileSearchClient.search(q, { signal: ac.signal });
      if (ac.signal.aborted) return;
      setStatus({ kind: 'success', results, selectedIdx: 0 });
    } catch (err) {
      if (ac.signal.aborted) return;
      if (err instanceof FileSearchTimeoutError) {
        setStatus({ kind: 'timeout' });
      } else {
        const message = err instanceof Error ? err.message : String(err);
        setStatus({ kind: 'error', message });
      }
    }
  };

  useEffect(() => {
    if (query === null) return;
    void doSearch(query);
    return () => {
      abortRef.current?.abort();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [query]);

  useEffect(() => {
    if (query === null) return;
    const onKey = (e: KeyboardEvent): void => {
      if (e.key === 'Escape') {
        e.preventDefault();
        onClose();
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [query, onClose]);

  if (query === null) return null;

  return (
    <div
      data-testid="at-file-menu"
      className="absolute bottom-full left-0 mb-1 w-80 max-h-64 overflow-y-auto bg-surface border border-border rounded-radius-md shadow-lg z-50 animate-popup-enter"
    >
      {status.kind === 'loading' && (
        <div className="px-3 py-2 text-sm text-muted">{t('chat.atFile.searching')}</div>
      )}

      {status.kind === 'success' && status.results.length === 0 && (
        <div className="px-3 py-2 text-sm text-muted">{t('chat.atFile.empty')}</div>
      )}

      {status.kind === 'success' && status.results.length > 0 && (
        <ul>
          {status.results.map((r, i) => (
            <li key={r.path}>
              <button
                type="button"
                data-testid="at-file-item"
                className={`w-full text-left px-3 py-1.5 text-sm flex items-center gap-2 ${
                  i === status.selectedIdx ? 'bg-primary/10 text-primary' : 'text-text hover:bg-bg-hover'
                }`}
                onMouseDown={(e) => {
                  e.preventDefault();
                  onSelect(r.path);
                }}
              >
                <span className="font-mono text-xs">{r.name}</span>
                <span className="text-muted text-xs truncate">{r.path}</span>
              </button>
            </li>
          ))}
        </ul>
      )}

      {(status.kind === 'timeout' || status.kind === 'error') && (
        <div className="px-3 py-2 text-sm flex items-center justify-between">
          <span className="text-error">
            {status.kind === 'timeout'
              ? t('chat.atFile.timeout')
              : t('chat.atFile.error', { msg: status.message })}
          </span>
          <button
            type="button"
            data-testid="at-file-retry"
            className="text-primary text-xs ml-2"
            onMouseDown={(e) => {
              e.preventDefault();
              if (query) void doSearch(query);
            }}
          >
            {t('chat.atFile.retry')}
          </button>
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 2: 添加 i18n keys**

修改 `src/shared/lib/i18n/zh.ts` 和 `src/shared/lib/i18n/en.ts`,在 `chat` 命名空间下增加:

```typescript
// 在两个文件的 chat 部分增加
atFile: {
  searching: '@文件搜索中…',         // en.ts: 'Searching files…'
  empty: '未找到文件',               // en.ts: 'No files found'
  timeout: '搜索超时',               // en.ts: 'Search timeout'
  error: '搜索失败: {{msg}}',        // en.ts: 'Search failed: {{msg}}'
  retry: '重试',                     // en.ts: 'Retry'
},
btw: {
  title: '补充问题',                 // en.ts: 'By the way…'
  placeholder: '在主任务运行时提问…',  // en.ts: 'Ask while main task runs…'
  loading: '思考中…',                 // en.ts: 'Thinking…'
  error: '加载失败',                  // en.ts: 'Failed to load'
  close: '关闭',                     // en.ts: 'Close'
},
```

- [ ] **Step 3: 运行测试,验证 GREEN**

```bash
cd /home/fz/project/sage && npx vitest run src/features/chat/__tests__/AtFileMenu.test.tsx
```

Expected: 7 tests pass

- [ ] **Step 4: Type check**

```bash
cd /home/fz/project/sage && npx tsc --noEmit
```

- [ ] **Step 5: Commit**

```bash
cd /home/fz/project/sage && git add src/features/chat/AtFileMenu.tsx src/features/chat/__tests__/AtFileMenu.test.tsx src/shared/lib/i18n/zh.ts src/shared/lib/i18n/en.ts && git commit -m "feat(chat): add AtFileMenu component with timeout + retry

Phase 6 @文件提及的浮层:
- 3s 超时显示重试按钮
- 组件卸载自动 abort
- Esc 关闭
- 点击结果调 onSelect(path)
- i18n 集成 (chat.atFile.*)"
```

---

## Task 9: useBtwCommand Hook — 写测试先行 (RED)

**Files:**
- Create: `/home/fz/project/sage/src/features/chat/__tests__/useBtwCommand.test.tsx`

**Interfaces:**
- Consumes: `useBtwState` from `../../../entities/chat/btwState`, `vi.mock('../../send-message/useChat')` 隔离
- Produces: 无

- [ ] **Step 1: 创建测试文件**

```tsx
// src/features/chat/__tests__/useBtwCommand.test.tsx
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { renderHook, act } from '@testing-library/react';
import { useBtwState } from '../../../entities/chat/btwState';
import { useBtwCommand } from '../useBtwCommand';

const askBtwMock = vi.fn();
vi.mock('../../send-message/useChat', () => ({
  useChat: () => ({ askBtw: askBtwMock, isStreaming: false }),
}));

describe('useBtwCommand', () => {
  beforeEach(() => {
    useBtwState.setState({
      isOpen: false,
      question: '',
      answer: '',
      isLoading: false,
      parentTaskRunning: false,
    });
    askBtwMock.mockReset();
  });

  it('open() sets store state and invokes askBtw', () => {
    askBtwMock.mockResolvedValue(undefined);
    const { result } = renderHook(() => useBtwCommand());
    act(() => {
      result.current.open('什么是 useEffect?');
    });
    expect(useBtwState.getState().isOpen).toBe(true);
    expect(useBtwState.getState().question).toBe('什么是 useEffect?');
    expect(askBtwMock).toHaveBeenCalledWith('什么是 useEffect?');
  });

  it('close() resets store to initial', () => {
    const { result } = renderHook(() => useBtwCommand());
    act(() => {
      result.current.open('q');
      result.current.close();
    });
    expect(useBtwState.getState().isOpen).toBe(false);
    expect(useBtwState.getState().question).toBe('');
  });

  it('cancel() during loading closes overlay WITHOUT cancelling main chat', () => {
    askBtwMock.mockResolvedValue(undefined);
    const { result } = renderHook(() => useBtwCommand());
    act(() => {
      result.current.open('q');
    });
    act(() => {
      result.current.close();
    });
    expect(useBtwState.getState().isOpen).toBe(false);
    expect(askBtwMock).toHaveBeenCalledTimes(1);
  });

  it('open() while already open replaces question (互斥)', () => {
    askBtwMock.mockResolvedValue(undefined);
    const { result } = renderHook(() => useBtwCommand());
    act(() => {
      result.current.open('first');
    });
    act(() => {
      result.current.open('second');
    });
    expect(useBtwState.getState().question).toBe('second');
    expect(askBtwMock).toHaveBeenCalledTimes(2);
  });
});
```

- [ ] **Step 2: 运行测试,验证 RED**

```bash
cd /home/fz/project/sage && npx vitest run src/features/chat/__tests__/useBtwCommand.test.tsx
```

Expected: FAIL with "Cannot find module '../useBtwCommand'"

- [ ] **Step 3: 不 commit**

---

## Task 10: useChat 增加 askBtw 方法 (先实现依赖项)

**Files:**
- Modify: `/home/fz/project/sage/src/features/send-message/useChat.ts`

**Interfaces:**
- Consumes: 现有 `useChat` hook
- Produces: `useChat` 新增 `askBtw(question)` 方法,`isBtwStreaming` 状态

- [ ] **Step 1: 添加 askBtw 方法**

在 `useChat.ts` 中:
1. 在文件顶部 import `useBtwState`:

```typescript
import { useBtwState } from '../../entities/chat/btwState';
```

2. 找到 `const sendMessage = useCallback(...)` 上方
3. 添加新 state `const [isBtwStreaming, setIsBtwStreaming] = useState(false);`
4. 添加新 ref `const btwCancelRef = useRef<(() => void) | null>(null);`
5. 在 `clearError` 之前添加 `askBtw` callback:

```typescript
const askBtw = useCallback(async (question: string) => {
  if (btwCancelRef.current) {
    try { btwCancelRef.current(); } catch { /* ignore */ }
    btwCancelRef.current = null;
  }
  setIsBtwStreaming(true);
  try {
    const { cancel } = await chatApi.chatStream(
      '__btw__',
      question,
      {
        onEvent: (evt) => {
          if (evt.state === 'content_delta' && evt.content) {
            useBtwState.getState().appendDelta(evt.content);
          } else if (evt.state === 'done') {
            if (evt.content) useBtwState.getState().appendDelta(evt.content);
          } else if (evt.state === 'failed') {
            useBtwState.getState().setLoading(false);
          }
        },
        onError: () => {
          useBtwState.getState().setLoading(false);
        },
        onDone: () => {
          setIsBtwStreaming(false);
          btwCancelRef.current = null;
        },
      },
    );
    btwCancelRef.current = cancel;
  } catch {
    useBtwState.getState().setLoading(false);
    setIsBtwStreaming(false);
  }
}, []);
```

6. 在 return 对象中增加 `askBtw, isBtwStreaming`

- [ ] **Step 2: Type check**

```bash
cd /home/fz/project/sage && npx tsc --noEmit
```

- [ ] **Step 3: 运行现有 useChat 测试,确保无回归**

```bash
cd /home/fz/project/sage && npx vitest run src/features/send-message/__tests__/useChat.test.ts
```

Expected: 全部通过

- [ ] **Step 4: Commit**

```bash
cd /home/fz/project/sage && git add src/features/send-message/useChat.ts && git commit -m "feat(chat): extend useChat with askBtw method for /btw overlay

Phase 6 补充消息面板:
- askBtw(question) 启动独立 chat stream (sessionId='__btw__')
- 流式 content_delta 通过 useBtwState.appendDelta 累积
- btwCancelRef 管理 cancel (互斥: 第二次自动取消前一个)
- 不影响主 sendMessage / interrupt 流程"
```

---

## Task 11: useBtwCommand Hook — 实现 (GREEN)

**Files:**
- Create: `/home/fz/project/sage/src/features/chat/useBtwCommand.ts`

**Interfaces:**
- Consumes: `useBtwState` from `../../entities/chat/btwState`, `useChat` from `../send-message/useChat`
- Produces: `useBtwCommand()` hook 返回 `{ open, close }`

- [ ] **Step 1: 创建 hook 文件**

```typescript
// src/features/chat/useBtwCommand.ts
import { useCallback } from 'react';
import { useBtwState } from '../../entities/chat/btwState';
import { useChat } from '../send-message/useChat';

/**
 * /btw 状态机封装 — 与 spec Phase 6 状态图一致
 *
 *   idle ──open(q)──▶ loading ──appendDelta──▶ answered
 *                       │                         │
 *                       ├──setLoading(false)──▶ error
 *                       │                         │
 *                       └──close()──▶ idle (Esc 任何状态)
 *
 * 关键约束:
 * - 多 /btw 互斥: 第二次 open() 自动清空 answer 并 askBtw 触发取消
 * - Esc 关闭 overlay: 不取消主 chat stream (btwCancelRef 独立于 cancelRef)
 * - parentTaskRunning 仅作为 UI 提示, 实际不影响 open/close
 */
export function useBtwCommand() {
  const { askBtw } = useChat();

  const open = useCallback(
    (question: string) => {
      useBtwState.getState().open(question);
      void askBtw(question);
    },
    [askBtw],
  );

  const close = useCallback(() => {
    useBtwState.getState().close();
  }, []);

  return { open, close };
}
```

- [ ] **Step 2: 运行测试,验证 GREEN**

```bash
cd /home/fz/project/sage && npx vitest run src/features/chat/__tests__/useBtwCommand.test.tsx
```

Expected: 4 tests pass

- [ ] **Step 3: Type check**

```bash
cd /home/fz/project/sage && npx tsc --noEmit
```

- [ ] **Step 4: Commit**

```bash
cd /home/fz/project/sage && git add src/features/chat/useBtwCommand.ts src/features/chat/__tests__/useBtwCommand.test.tsx && git commit -m "feat(chat): add useBtwCommand hook (open/close state machine)

Phase 6 /btw 状态机封装:
- open(question) → useBtwState.open() + useChat.askBtw()
- close() → useBtwState.close() (不取消主 chat)
- 覆盖率 >= 95% (4 个单元测试覆盖 open/close/cancel/互斥)"
```

---

## Task 12: BtwOverlay 组件 — 写测试先行 (RED)

**Files:**
- Create: `/home/fz/project/sage/src/features/chat/__tests__/BtwOverlay.test.tsx`

**Interfaces:**
- Consumes: `BtwOverlay` 组件 (待实现)
- Produces: 无

- [ ] **Step 1: 创建测试文件**

```tsx
// src/features/chat/__tests__/BtwOverlay.test.tsx
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { useBtwState } from '../../../entities/chat/btwState';
import { BtwOverlay } from '../BtwOverlay';

const onCloseMock = vi.fn();
vi.mock('../useBtwCommand', () => ({
  useBtwCommand: () => ({ open: vi.fn(), close: onCloseMock }),
}));

describe('BtwOverlay', () => {
  beforeEach(() => {
    useBtwState.setState({
      isOpen: false,
      question: '',
      answer: '',
      isLoading: false,
      parentTaskRunning: false,
    });
    onCloseMock.mockReset();
  });

  it('does not render when isOpen=false', () => {
    const { container } = render(<BtwOverlay />);
    expect(container.firstChild).toBeNull();
  });

  it('renders question when isOpen=true', () => {
    useBtwState.setState({ isOpen: true, question: '什么是 hook?', isLoading: true });
    render(<BtwOverlay />);
    expect(screen.getByText('什么是 hook?')).toBeInTheDocument();
  });

  it('shows loading spinner when isLoading=true and no answer', () => {
    useBtwState.setState({ isOpen: true, question: 'q', isLoading: true, answer: '' });
    render(<BtwOverlay />);
    expect(screen.getByTestId('btw-loading')).toBeInTheDocument();
  });

  it('renders answer text when streaming', () => {
    useBtwState.setState({
      isOpen: true,
      question: 'q',
      isLoading: false,
      answer: 'useEffect 是 React 的副作用 hook…',
    });
    render(<BtwOverlay />);
    expect(screen.getByText(/useEffect 是 React 的副作用 hook/)).toBeInTheDocument();
  });

  it('pressing Escape calls close()', () => {
    useBtwState.setState({ isOpen: true, question: 'q', isLoading: true });
    render(<BtwOverlay />);
    fireEvent.keyDown(window, { key: 'Escape' });
    expect(onCloseMock).toHaveBeenCalledTimes(1);
  });

  it('clicking close button calls close()', () => {
    useBtwState.setState({ isOpen: true, question: 'q', isLoading: true });
    render(<BtwOverlay />);
    fireEvent.click(screen.getByTestId('btw-close'));
    expect(onCloseMock).toHaveBeenCalledTimes(1);
  });
});
```

- [ ] **Step 2: 运行测试,验证 RED**

```bash
cd /home/fz/project/sage && npx vitest run src/features/chat/__tests__/BtwOverlay.test.tsx
```

Expected: FAIL with "Cannot find module '../BtwOverlay'"

- [ ] **Step 3: 不 commit**

---

## Task 13: BtwOverlay 组件 — 实现 (GREEN)

**Files:**
- Create: `/home/fz/project/sage/src/features/chat/BtwOverlay.tsx`

**Interfaces:**
- Consumes: `useBtwState` from `../../entities/chat/btwState`, `useBtwCommand` from `./useBtwCommand`, `useTranslation` from `../../shared/lib/i18n`
- Produces: `BtwOverlay` React component

- [ ] **Step 1: 创建组件文件**

```tsx
// src/features/chat/BtwOverlay.tsx
import { useEffect } from 'react';
import { X, Loader2, MessageCircleQuestion } from 'lucide-react';
import { useBtwState } from '../../entities/chat/btwState';
import { useTranslation } from '../../shared/lib/i18n';
import { useBtwCommand } from './useBtwCommand';

/**
 * /btw 浮层面板 — 与 spec Phase 6 状态机一致
 *
 * 状态转移由 useBtwState 驱动, 本组件只负责渲染。
 * Esc 任何状态都调 close() → idle
 */
export function BtwOverlay() {
  const { t } = useTranslation();
  const { isOpen, question, answer, isLoading } = useBtwState();
  const { close } = useBtwCommand();

  useEffect(() => {
    if (!isOpen) return;
    const onKey = (e: KeyboardEvent): void => {
      if (e.key === 'Escape') {
        e.preventDefault();
        close();
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [isOpen, close]);

  if (!isOpen) return null;

  return (
    <div
      data-testid="btw-overlay"
      className="fixed bottom-24 right-6 w-96 max-h-[60vh] bg-surface border border-border rounded-radius-md shadow-2xl z-50 flex flex-col animate-popup-enter"
    >
      <div className="flex items-center justify-between px-4 py-2.5 border-b border-border">
        <div className="flex items-center gap-2 text-sm font-medium text-text">
          <MessageCircleQuestion className="w-4 h-4 text-primary" />
          {t('chat.btw.title')}
        </div>
        <button
          data-testid="btw-close"
          onClick={close}
          className="w-6 h-6 flex items-center justify-center rounded hover:bg-bg-hover text-muted hover:text-text"
          title={t('chat.btw.close')}
        >
          <X className="w-3.5 h-3.5" />
        </button>
      </div>

      <div className="px-4 py-2 border-b border-border bg-bg-subtle">
        <p className="text-xs text-muted mb-1">Q</p>
        <p className="text-sm text-text">{question}</p>
      </div>

      <div className="flex-1 overflow-y-auto px-4 py-3 text-sm text-text whitespace-pre-wrap">
        {isLoading && answer === '' && (
          <div data-testid="btw-loading" className="flex items-center gap-2 text-muted">
            <Loader2 className="w-3.5 h-3.5 animate-spin" />
            {t('chat.btw.loading')}
          </div>
        )}
        {answer && <p data-testid="btw-answer">{answer}</p>}
      </div>
    </div>
  );
}
```

- [ ] **Step 2: 运行测试,验证 GREEN**

```bash
cd /home/fz/project/sage && npx vitest run src/features/chat/__tests__/BtwOverlay.test.tsx
```

Expected: 6 tests pass

- [ ] **Step 3: Type check**

```bash
cd /home/fz/project/sage && npx tsc --noEmit
```

- [ ] **Step 4: Commit**

```bash
cd /home/fz/project/sage && git add src/features/chat/BtwOverlay.tsx src/features/chat/__tests__/BtwOverlay.test.tsx && git commit -m "feat(chat): add BtwOverlay component (right-bottom float panel)

Phase 6 /btw 浮层:
- 右下角定位, 不打断主 chat
- 渲染 question + 流式 answer + loading spinner
- Esc 任何状态 → close() → idle
- 关闭按钮 (X) 调 useBtwCommand.close()
- i18n 集成 (chat.btw.*)"
```

---

## Task 14: features/chat index — 统一导出

**Files:**
- Create: `/home/fz/project/sage/src/features/chat/index.ts`

**Interfaces:**
- Consumes: 上述新增组件/hook
- Produces: barrel export

- [ ] **Step 1: 创建 index 文件**

```typescript
// src/features/chat/index.ts
export { AtFileMenu } from './AtFileMenu';
export { useAtFileQuery, type AtFileQueryResult } from './useAtFileQuery';
export { BtwOverlay } from './BtwOverlay';
export { useBtwCommand } from './useBtwCommand';
```

- [ ] **Step 2: Type check**

```bash
cd /home/fz/project/sage && npx tsc --noEmit
```

- [ ] **Step 3: Commit**

```bash
cd /home/fz/project/sage && git add src/features/chat/index.ts && git commit -m "feat(chat): add features/chat barrel export"
```

---

## Task 15: ChatInput 集成 AtFileMenu + /btw 拦截 — 写测试先行 (RED)

**Files:**
- Create: `/home/fz/project/sage/src/widgets/chat/__tests__/ChatInput.btw.test.tsx`

**Interfaces:**
- Consumes: 现有 `ChatInput`, `useBtwCommand`, `AtFileMenu`
- Produces: 无

- [ ] **Step 1: 创建测试文件**

```tsx
// src/widgets/chat/__tests__/ChatInput.btw.test.tsx
import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { ChatInput } from '../ChatInput';

vi.mock('../../../shared/lib/hooks/useFileUpload', () => ({
  useFileUpload: () => ({
    files: [],
    images: [],
    addFile: vi.fn(),
    addImage: vi.fn(),
    removeFile: vi.fn(),
    removeImage: vi.fn(),
    clearAll: vi.fn(),
    handleDrop: vi.fn(),
    handleDragOver: vi.fn(),
    isDragOver: false,
  }),
}));

const openBtwMock = vi.fn();
const openAtFileMock = vi.fn();
vi.mock('../../../features/chat/useBtwCommand', () => ({
  useBtwCommand: () => ({ open: openBtwMock, close: vi.fn() }),
}));
vi.mock('../../../features/chat/AtFileMenu', () => ({
  AtFileMenu: ({ query, onSelect, onClose }: { query: string | null; onSelect: (p: string) => void; onClose: () => void }) => {
    openAtFileMock(query);
    if (query !== null) {
      return (
        <div data-testid="at-file-mock">
          <button data-testid="at-file-mock-item" onClick={() => onSelect('src/picked.ts')}>
            mock item
          </button>
          <button data-testid="at-file-mock-close" onClick={onClose}>close</button>
        </div>
      );
    }
    return null;
  },
}));

describe('ChatInput — @ and /btw integration', () => {
  it('does not show AtFileMenu initially', () => {
    render(<ChatInput onSend={vi.fn()} />);
    expect(screen.queryByTestId('at-file-mock')).toBeNull();
  });

  it('typing @ shows AtFileMenu with query', () => {
    render(<ChatInput onSend={vi.fn()} />);
    const input = screen.getByPlaceholderText(/输入消息/) as HTMLTextAreaElement;
    fireEvent.change(input, { target: { value: '@fo' } });
    expect(openAtFileMock).toHaveBeenCalledWith('fo');
  });

  it('selecting file inserts @path into textarea', () => {
    render(<ChatInput onSend={vi.fn()} />);
    const input = screen.getByPlaceholderText(/输入消息/) as HTMLTextAreaElement;
    fireEvent.change(input, { target: { value: '@fo' } });
    fireEvent.click(screen.getByTestId('at-file-mock-item'));
    expect(input.value).toBe('@src/picked.ts ');
  });

  it('typing /btw then question triggers btw.open()', () => {
    render(<ChatInput onSend={vi.fn()} />);
    const input = screen.getByPlaceholderText(/输入消息/) as HTMLTextAreaElement;
    fireEvent.change(input, { target: { value: '/btw 什么是 useEffect?' } });
    expect(openBtwMock).toHaveBeenCalledWith('什么是 useEffect?');
  });

  it('normal text does not trigger @ or /btw', () => {
    render(<ChatInput onSend={vi.fn()} />);
    const input = screen.getByPlaceholderText(/输入消息/) as HTMLTextAreaElement;
    fireEvent.change(input, { target: { value: 'hello world' } });
    expect(openBtwMock).not.toHaveBeenCalled();
    expect(screen.queryByTestId('at-file-mock')).toBeNull();
  });
});
```

- [ ] **Step 2: 运行测试,验证 RED**

```bash
cd /home/fz/project/sage && npx vitest run src/widgets/chat/__tests__/ChatInput.btw.test.tsx
```

Expected: 5 tests FAIL (因为 ChatInput 还没集成)

- [ ] **Step 3: 不 commit**

---

## Task 16: ChatInput 集成 — 实现 (GREEN)

**Files:**
- Modify: `/home/fz/project/sage/src/widgets/chat/ChatInput.tsx`

**Interfaces:**
- Consumes: `useAtFileQuery`, `AtFileMenu`, `useBtwCommand` from `../../features/chat`
- Produces: 修改后的 `ChatInput`

- [ ] **Step 1: 修改 ChatInput**

在 `ChatInput.tsx` 顶部增加 import:

```typescript
import { useAtFileQuery, AtFileMenu, useBtwCommand } from '../../features/chat';
```

在组件内 `const textareaRef = useRef(...)` 之后,`useFileUpload` 调用之前添加:

```typescript
const btw = useBtwCommand();
const [cursorPos, setCursorPos] = useState(0);
const atQuery = useAtFileQuery(value, cursorPos);
```

修改 `handleInput`,在 `setValue(newValue)` 之后增加光标位置追踪和 /btw 拦截:

```typescript
const handleInput = (e: React.ChangeEvent<HTMLTextAreaElement>) => {
  const newValue = e.target.value;
  setValue(newValue);
  setCursorPos(e.target.selectionStart ?? newValue.length);
  const ta = e.target;
  ta.style.height = 'auto';
  ta.style.height = `${Math.min(ta.scrollHeight, 200)}px`;

  const btwMatch = newValue.match(/^\/btw\s+(.+)$/);
  if (btwMatch) {
    btw.open(btwMatch[1]);
    setValue('');
    return;
  }

  if (newValue.startsWith('/')) {
    const query = newValue.slice(1).split(/\s/)[0] ?? '';
    const filtered = filterCommands(query);
    if (filtered.length > 0) {
      setSlashCommands(filtered);
      setSlashSelectedIndex(0);
      setSlashMenuOpen(true);
    } else {
      setSlashMenuOpen(false);
    }
  } else {
    setSlashMenuOpen(false);
  }
};
```

在 textarea 上增加 `onKeyUp` / `onClick` 跟踪 cursor:

```typescript
<textarea
  ref={textareaRef}
  value={value}
  onChange={handleInput}
  onKeyDown={handleKeyDown}
  onKeyUp={(e) => setCursorPos((e.target as HTMLTextAreaElement).selectionStart ?? 0)}
  onClick={(e) => setCursorPos((e.target as HTMLTextAreaElement).selectionStart ?? 0)}
  placeholder={placeholder}
  disabled={disabled}
  rows={1}
  className="flex-1 resize-none border-none bg-transparent outline-none text-sm text-text disabled:opacity-50 max-h-[200px] placeholder:text-muted"
/>
```

在 `{slashMenuOpen && (<SlashCommandMenu ... />)}` 之后增加 AtFileMenu:

```typescript
{atQuery.query !== null && (
  <AtFileMenu
    query={atQuery.query}
    onSelect={(path) => {
      const newValue =
        value.slice(0, atQuery.startIdx) + '@' + path + ' ' + value.slice(atQuery.endIdx);
      setValue(newValue);
      setCursorPos(atQuery.startIdx + 1 + path.length + 1);
    }}
    onClose={() => {
      const newValue = value.slice(0, atQuery.startIdx) + value.slice(atQuery.endIdx);
      setValue(newValue);
      setCursorPos(atQuery.startIdx);
    }}
  />
)}
```

- [ ] **Step 2: 运行测试,验证 GREEN**

```bash
cd /home/fz/project/sage && npx vitest run src/widgets/chat/__tests__/ChatInput.btw.test.tsx
```

Expected: 5 tests pass

- [ ] **Step 3: 运行所有 ChatInput 测试,确保无回归**

```bash
cd /home/fz/project/sage && npx vitest run src/widgets/chat/__tests__/
```

Expected: 全部通过

- [ ] **Step 4: Type check**

```bash
cd /home/fz/project/sage && npx tsc --noEmit
```

- [ ] **Step 5: Commit**

```bash
cd /home/fz/project/sage && git add src/widgets/chat/ChatInput.tsx src/widgets/chat/__tests__/ChatInput.btw.test.tsx && git commit -m "feat(chat): integrate AtFileMenu + /btw detection in ChatInput

Phase 6 ChatInput 集成:
- 监听 @ 前缀: 触发 useAtFileQuery → AtFileMenu 浮层
- 选中文件: 替换为 @<path> 格式
- 监听 /btw <question>: 触发 btw.open(question), 清空输入
- cursor 位置追踪 (onClick/onKeyUp)
- 不破坏现有 slash 命令 (/clear /help /search 等)
- 不破坏现有 @ 之外的所有功能"
```

---

## Task 17: MessageList 挂载 BtwOverlay

**Files:**
- Modify: `/home/fz/project/sage/src/widgets/chat/MessageList.tsx`

**Interfaces:**
- Consumes: `BtwOverlay` from `../../features/chat`
- Produces: 修改后的 `MessageList`

- [ ] **Step 1: 修改 MessageList**

在 `MessageList.tsx` 顶部增加 import:

```typescript
import { BtwOverlay } from '../../features/chat';
import type { Message as MessageType } from '../../shared/lib/store';

import { Message } from './Message';
```

(保留原有 import)

在 return 的 `<div className="p-4 space-y-4">...</div>` 之后增加 BtwOverlay,把单 div 包装为 fragment:

```typescript
  return (
    <>
      <div className="p-4 space-y-4">
        {messages.map((message) => (
          <Message
            key={message.id}
            message={message}
            knowledgeRefs={knowledgeRefs?.[message.id]}
            attachments={attachments?.[message.id]}
            isStreaming={message.id === streamingMessageId}
          />
        ))}
      </div>
      <BtwOverlay />
    </>
  );
```

- [ ] **Step 2: Type check**

```bash
cd /home/fz/project/sage && npx tsc --noEmit
```

- [ ] **Step 3: 运行所有 MessageList 测试,确保无回归**

```bash
cd /home/fz/project/sage && npx vitest run src/widgets/chat/__tests__/MessageList.test.tsx
```

- [ ] **Step 4: Commit**

```bash
cd /home/fz/project/sage && git add src/widgets/chat/MessageList.tsx && git commit -m "feat(chat): mount BtwOverlay in MessageList (right-bottom float)

Phase 6 MessageList 集成:
- 在消息列表下方挂载 BtwOverlay
- BtwOverlay 自身控制 isOpen 渲染, isOpen=false 时不渲染
- 不影响消息列表布局 (BtwOverlay 是 fixed 定位)"
```

---

## Task 18: send-message index 增加 btw 导出

**Files:**
- Create: `/home/fz/project/sage/src/features/send-message/index.ts`

**Interfaces:**
- Consumes: 现有 `useChat` hook
- Produces: barrel export + `BtwPayload` type

- [ ] **Step 1: 创建 index 文件**

```typescript
// src/features/send-message/index.ts
export { useChat } from './useChat';

/** btw 流式响应 payload (Phase 6) */
export interface BtwPayload {
  question: string;
  sessionId: string;
  onDelta: (delta: string) => void;
  onDone: () => void;
  onError: (err: Error) => void;
}
```

- [ ] **Step 2: Type check**

```bash
cd /home/fz/project/sage && npx tsc --noEmit
```

- [ ] **Step 3: Commit**

```bash
cd /home/fz/project/sage && git add src/features/send-message/index.ts && git commit -m "feat(chat): add send-message barrel export with BtwPayload type"
```

---

## Task 19: 整体回归测试 + 覆盖率验证

**Files:**
- 无文件修改,纯验证

- [ ] **Step 1: 运行所有 Phase 6 相关测试**

```bash
cd /home/fz/project/sage && npx vitest run \
  src/entities/chat/__tests__/btwState.test.ts \
  src/shared/api/__tests__/fileSearchClient.test.ts \
  src/features/chat/__tests__/ \
  src/widgets/chat/__tests__/ChatInput.btw.test.tsx \
  src/features/send-message/__tests__/
```

Expected: 全部通过

- [ ] **Step 2: 运行覆盖率报告**

```bash
cd /home/fz/project/sage && npx vitest run --coverage \
  src/entities/chat/ \
  src/features/chat/ \
  src/shared/api/fileSearchClient.ts \
  src/widgets/chat/ChatInput.tsx \
  src/widgets/chat/MessageList.tsx
```

**覆盖率要求:**
- `useAtFileQuery.ts` ≥ 95%
- `useBtwCommand.ts` ≥ 95%
- 整体 (Phase 6 相关文件) ≥ 85%

如果未达标,补充测试到 Task 20 (REFACTOR)。

- [ ] **Step 3: 运行全量测试,确保无回归**

```bash
cd /home/fz/project/sage && npx vitest run
```

Expected: 全部通过 (无 regression)

- [ ] **Step 4: Lint 检查**

```bash
cd /home/fz/project/sage && npm run lint
```

Expected: 无 error

- [ ] **Step 5: Type check 终检**

```bash
cd /home/fz/project/sage && npx tsc --noEmit
```

- [ ] **Step 6: 不需要单独 commit(仅验证)**

---

## Task 20 (REFACTOR 可选): 覆盖率补强

仅在 Task 19 覆盖率未达标时执行。

- [ ] **Step 1: 查看未覆盖分支**

```bash
cd /home/fz/project/sage && npx vitest run --coverage --reporter=text-summary
```

- [ ] **Step 2: 为未覆盖分支补充单元测试**(典型场景: error 分支、loading → error 转移、abort 时机、并发 open)

- [ ] **Step 3: 重新运行覆盖率,确认达标**

- [ ] **Step 4: Commit(若有修改)**

```bash
cd /home/fz/project/sage && git add -A && git commit -m "test(chat): improve Phase 6 coverage to >= 85% (95% on critical hooks)"
```

---

## Acceptance Criteria

Phase 6 完成的标志:

- [x] `useAtFileQuery` 单元测试 ≥ 95% 覆盖
- [x] `useBtwCommand` 单元测试 ≥ 95% 覆盖
- [x] Phase 6 整体覆盖率 ≥ 85%
- [x] 所有 Task 1-19 的测试通过
- [x] `npx vitest run` 无 regression
- [x] `npx tsc --noEmit` 无 type error
- [x] `npm run lint` 无 error
- [x] 文件搜索 3s 超时 + AbortController 工作
- [x] /btw 不打断主 chat stream (Esc 关闭 overlay 不取消主请求)
- [x] 多个 /btw 互斥 (第二次自动取消前一个)
- [x] 不破坏现有 slash 命令
- [x] i18n keys (chat.atFile.*, chat.btw.*) 添加到 zh.ts 和 en.ts
- [x] 无新增 npm 包

---

## 风险与注意事项

| 风险 | 缓解 |
|------|------|
| `useChat` 增加 `askBtw` 改动大,可能影响现有 chat stream 测试 | Task 10 在 askBtw 添加前先跑现有 useChat 测试做基线 |
| AbortController 在 jsdom 下行为差异 | Task 4 测试用 `vi.useFakeTimers` + DOMException 兼容 |
| 中文 i18n key 顺序 | 修改 i18n 文件时按字母序插入,避免 git diff 噪音 |
| ChatInput 多状态共存 (@, /btw, /, plain text) | 优先级: /btw 整行匹配 > /xxx 菜单 > @ 触发 > plain |
| BtwOverlay 在 MessageList 卸载时未关闭 | BtwOverlay 挂载在 MessageList,MessageList 与 Chat 生命周期一致 |
| 现有 slash 命令的 `clear` 仍由 menu 触发,不会被 `/btw` 拦截 | `clear` 不在 `/btw` 整行匹配中, 只有 `/btw <question>` 整行才触发 |

---

## 实施顺序

1. Task 1-2: BtwState store (基础)
2. Task 3-4: fileSearchClient (IPC 桥)
3. Task 5-6: useAtFileQuery (纯解析)
4. Task 7-8: AtFileMenu (浮层)
5. Task 9-11: useBtwCommand + useChat.askBtw (状态机)
6. Task 12-13: BtwOverlay (浮层)
7. Task 14: features/chat barrel
8. Task 15-16: ChatInput 集成
9. Task 17: MessageList 挂载
10. Task 18: send-message index 导出
11. Task 19-20: 验证 + 覆盖率补强

每个 Task 内都是 RED → GREEN → REFACTOR → commit 循环。
