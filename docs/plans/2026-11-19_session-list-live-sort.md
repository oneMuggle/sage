# 会话列表实时排序（运行即置顶 + 新会话即时入列）实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 会话开始运行时立即出现在侧栏会话列表顶部（pinned 组之后），新建会话在创建成功时立即入列，不再等流结束后才刷新重排。

**Architecture:** 后端已在 `SessionRepository.list()` 里实现 `is_pinned DESC → run_status IN ('running','suspended') DESC → updated_at DESC` 排序，并在 run 开始时把 `run_status='running'` 落库；缺的只是①运行开始时的刷新信号，②新会话创建路径写入前端 store。方案：后端在 running 落库后向本流向推送 `session_updated / run_started` 事件；前端收到后原地标记 running 并按与 SQL 一致的比较器重排；发送动作同时做本地乐观置顶兜底；新会话创建（含项目绑定路径）通过新增的 store `addSession` 即时入列；流结束的既有 `loadSessions()` 全量对账保持不变。

**Tech Stack:** React 18 + Zustand（前端 store）、TypeScript、Vitest、FastAPI（legacy `/api/v1/chat/stream` NDJSON producer）、pytest + httpx ASGITransport。

**Spec:** 本计划自包含（背景分析来自 2026-11-19 的根因排查，见「背景与目标」）。

## 背景与目标

现象：
1. 运行中的会话不会自动排序到会话列表的最新位置，流结束后才重排。
2. 新开的会话（尤其在新会话页选中过项目时）不显示在会话列表中。

根因：
- 侧栏列表是 Zustand store 的快照，唯一自动刷新点是流结束时的 `loadSessions()`（`src/features/send-message/useChat.ts`）与其他少量显式动作；run 开始没有任何刷新信号，后端也不推送运行态事件（`session_updated` 只有 `title_updated` 一种）。
- `store.createSession()` 会把新会话 prepend 进 `sessions`，但 `projectApi.createSession()`（Welcome 页选中项目时、`@` 草稿会话）只建库不写 store，也没有后续 `loadSessions`。

目标（minimal diff）：
- 发送消息的瞬间（乐观）+ 后端 `run_started` 事件到达时（权威）都将该会话标记 running 并按后端排序规则移到 pinned 组之后最前。
- 项目绑定路径创建的新会话在提交时立即入列。
- 流结束的全量刷新继续承担最终对账（标题、终态徽章、最终顺序）。

## 涉及的文件与模块

| 文件 | 动作 |
|---|---|
| `src/shared/lib/sessionOrder.ts` | 新增：与 SQL 一致的会话比较器/排序函数 |
| `src/shared/lib/__tests__/sessionOrder.test.ts` | 新增：比较器单测 |
| `src/shared/lib/store.ts` | 修改：新增 `addSession` / `markSessionRunning`；`createSession` 改用一致排序插入 |
| `src/shared/lib/__tests__/store.test.ts` | 修改：store 动作测试 |
| `src/features/send-message/useChat.ts` | 修改：发送时乐观置顶；`session_updated` 增加 `run_started` 分支 |
| `src/features/send-message/__tests__/useChat.sessionUpdatedIncremental.test.ts` | 修改：`run_started` 分支测试 |
| `src/pages/Welcome.tsx` | 修改：项目绑定创建/草稿复用后 `addSession` 入列 |
| `src/pages/__tests__/Welcome.test.tsx` | 修改：项目路径入列测试 |
| `backend/api/legacy_routes.py` | 修改：running 落库后推送 `session_updated / run_started` |
| `backend/tests/integration/test_chat_stream_run_started.py` | 新增：事件链路集成测试 |
| `docs/technical/110-session-list-scroll-archive.md` | 修改：补充实时排序章节 |

## 技术方案

1. **统一排序比较器**（`sessionOrder.ts`），字段顺序严格对齐 `backend/data/session_repo.py::SessionRepository.list()`：
   `is_pinned DESC → 活跃(running/suspended) DESC → updated_at DESC`。稳定排序（ES2019 起 `Array.sort` 保证稳定）。
2. **store 新增两个动作**：
   - `markSessionRunning(id)`：`run_status='running'`、`last_message_at=Date.now()`、`last_error=null`，然后按比较器整体重排（新数组，不原地 mutate）。
   - `addSession(session)`：id 已存在则 no-op；否则并入后按比较器重排（与后端一致：新会话在 pinned 组之后）。
   - `createSession` 的 prepend 改为同样的排序插入，消除"本地顺序与后端顺序暂时不一致"的窗口。
3. **前端两处触发**：
   - `useChat.sendMessage` 在 `markStreamActive` 后调用 `markSessionRunning(sid)`（乐观、立即可见）。
   - `useChat` 的 `session_updated` handler 新增 `evt.subtype === 'run_started'` 分支 → `markSessionRunning(sid)`（不再落入全量 `loadSessions()`，省一次 HTTP）。
4. **后端事件**：`legacy_routes.py` 中 `update_run_status(..., 'running')` 返回 true（行存在）后，`await entry.queue.put({"type": "session_updated", "subtype": "run_started", "session_id": ...})`，fail-open。
5. **Welcome 入列**：`projectApi.createSession` 的返回对象缓存进 `draftSessionRef`（新增 `session` 字段）；`handleSubmit` 中无论新建还是复用草稿，只要拿到了 `Session` 对象就调用 `addSession`。无项目的 `store.createSession()` 路径保持不变（已入列）。

## 实施步骤

- [x] Task 1：新增排序比较器 `sessionOrder.ts` + 单测
- [x] Task 2：store 新增 `addSession` / `markSessionRunning`，`createSession` 排序插入 + 单测
- [x] Task 3：`useChat` 乐观置顶 + `run_started` 事件分支 + 测试
- [x] Task 4：Welcome 项目路径即时入列 + 测试
- [x] Task 5：后端 `run_started` 事件 + 集成测试
- [x] Task 6：文档更新 + 全量验证

## Global Constraints

- 前端测试：`npx vitest run <path>`（Node 经 nvm，若 PATH 不含 node 用 `/home/fz/.nvm/versions/node/v25.9.0/bin/node`）。
- 后端测试必须用 conda 环境：`/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest ...`。
- 后端 lint：`/home/fz/anaconda3/envs/sage-backend/bin/python -m ruff check backend/...`（双引号、中文注释不受 ERA001 限制的既有豁免沿用）。
- 前端 lint/格式化：`npx eslint <files>`、`npx prettier --check <files>`；仓库有架构棘轮（`architecture-baseline.json`），本计划不应新增文件层面的行数违规——新增前端模块需在同一次提交中运行 `npm run check:architecture`（若存在）确认。
- commit 采用 Conventional Commits：`feat(sidebar): ...` / `fix(sidebar): ...`。
- 不改动 `backend/requirements.txt`；不引入新依赖。
- 本分支基于 main（pydantic 2.x / Python 3.10），完成后再按项目流程 cherry-pick 到 `release/win7` 并做 py38 兼容验证（本计划不含 win7 落地）。

---

### Task 1: 会话排序比较器 `sessionOrder.ts`

**Files:**
- Create: `src/shared/lib/sessionOrder.ts`
- Test: `src/shared/lib/__tests__/sessionOrder.test.ts`

**Interfaces:**
- Produces:
  - `isSessionActive(session: Pick<Session, 'run_status'>): boolean`
  - `compareSessions(a: Session, b: Session): number`
  - `sortSessions(sessions: Session[]): Session[]`（返回新数组）

- [ ] **Step 1: 写失败测试**

```ts
// src/shared/lib/__tests__/sessionOrder.test.ts
import { describe, expect, it } from 'vitest';

import { compareSessions, isSessionActive, sortSessions } from '../sessionOrder';
import type { Session } from '../store';

function makeSession(overrides: Partial<Session> & { id: string }): Session {
  return {
    title: overrides.id,
    created_at: 0,
    updated_at: 0,
    last_message_at: null,
    message_count: 0,
    is_pinned: false,
    ...overrides,
  };
}

describe('compareSessions（与后端 SQL 排序一致）', () => {
  it('pinned 永远在最前，即使 updated_at 更旧', () => {
    const pinned = makeSession({ id: 'pinned', is_pinned: true, updated_at: 1 });
    const fresh = makeSession({ id: 'fresh', updated_at: 9_999 });
    expect(sortSessions([fresh, pinned]).map((s) => s.id)).toEqual(['pinned', 'fresh']);
  });

  it('非 pinned 中 running/suspended 排在 idle 之前', () => {
    const running = makeSession({ id: 'running', run_status: 'running', updated_at: 1 });
    const suspended = makeSession({ id: 'suspended', run_status: 'suspended', updated_at: 2 });
    const idle = makeSession({ id: 'idle', run_status: 'idle', updated_at: 9_999 });
    const unknown = makeSession({ id: 'unknown', updated_at: 8_888 });
    expect(sortSessions([idle, unknown, running, suspended]).map((s) => s.id)).toEqual([
      'suspended',
      'running',
      'idle',
      'unknown',
    ]);
  });

  it('同组内按 updated_at DESC', () => {
    const older = makeSession({ id: 'older', updated_at: 1 });
    const newer = makeSession({ id: 'newer', updated_at: 2 });
    expect(compareSessions(newer, older)).toBeLessThan(0);
    expect(compareSessions(older, newer)).toBeGreaterThan(0);
  });

  it('isSessionActive 只认 running/suspended', () => {
    expect(isSessionActive({ run_status: 'running' })).toBe(true);
    expect(isSessionActive({ run_status: 'suspended' })).toBe(true);
    expect(isSessionActive({ run_status: 'failed' })).toBe(false);
    expect(isSessionActive({})).toBe(false);
  });

  it('sortSessions 不修改入参数组', () => {
    const a = makeSession({ id: 'a', updated_at: 1 });
    const b = makeSession({ id: 'b', updated_at: 2 });
    const input = [a, b];
    sortSessions(input);
    expect(input.map((s) => s.id)).toEqual(['a', 'b']);
  });
});
```

- [ ] **Step 2: 运行确认失败**

Run: `npx vitest run src/shared/lib/__tests__/sessionOrder.test.ts`
Expected: FAIL（模块不存在）

- [ ] **Step 3: 最小实现**

```ts
// src/shared/lib/sessionOrder.ts
import type { Session } from './store';

/** 与后端 `SessionRepository.list()` 的活跃判定一致。 */
const ACTIVE_RUN_STATUSES = new Set(['running', 'suspended']);

export function isSessionActive(session: Pick<Session, 'run_status'>): boolean {
  return typeof session.run_status === 'string' && ACTIVE_RUN_STATUSES.has(session.run_status);
}

/**
 * 会话列表比较器，字段顺序严格对齐后端 SQL：
 *   `is_pinned DESC, run_status IN ('running','suspended') DESC, updated_at DESC`
 * 本地只在乐观更新（运行开始/新会话入列）时使用；常规顺序仍以服务端返回为准。
 */
export function compareSessions(a: Session, b: Session): number {
  if (a.is_pinned !== b.is_pinned) return a.is_pinned ? -1 : 1;
  const activeA = isSessionActive(a) ? 1 : 0;
  const activeB = isSessionActive(b) ? 1 : 0;
  if (activeA !== activeB) return activeB - activeA;
  return b.updated_at - a.updated_at;
}

/** 稳定排序并返回新数组（不原地修改）。 */
export function sortSessions(sessions: Session[]): Session[] {
  return [...sessions].sort(compareSessions);
}
```

- [ ] **Step 4: 运行确认通过**

Run: `npx vitest run src/shared/lib/__tests__/sessionOrder.test.ts`
Expected: PASS（5 tests）

- [ ] **Step 5: Commit**

```bash
git add src/shared/lib/sessionOrder.ts src/shared/lib/__tests__/sessionOrder.test.ts
git commit -m "feat(sidebar): add session order comparator mirroring backend SQL sort"
```

---

### Task 2: store 新增 `addSession` / `markSessionRunning`

**Files:**
- Modify: `src/shared/lib/store.ts`（StoreState 接口 ~L171、实现 ~L315；`updateSession` 附近）
- Test: `src/shared/lib/__tests__/store.test.ts`

**Interfaces:**
- Consumes: Task 1 的 `sortSessions(sessions: Session[]): Session[]`
- Produces:
  - `addSession(session: Session): void` —— id 已存在时 no-op
  - `markSessionRunning(id: string): void` —— 会话不存在时 no-op
  - `createSession` 行为不变（返回 `Promise<string>`），但插入位置改为排序插入

- [ ] **Step 1: 写失败测试（追加到 store.test.ts）**

```ts
describe('store 会话实时排序 (2026-11-19)', () => {
  function seed(sessions: Session[]): void {
    useStore.setState({ sessions });
  }

  it('markSessionRunning 标记 running 并置顶到 pinned 组之后', () => {
    seed([
      { id: 'pinned', title: 'pinned', created_at: 0, updated_at: 1, last_message_at: null, message_count: 0, is_pinned: true },
      { id: 'newest', title: 'newest', created_at: 0, updated_at: 9_000, last_message_at: null, message_count: 0, is_pinned: false },
      { id: 'started', title: 'started', created_at: 0, updated_at: 100, last_message_at: null, message_count: 0, is_pinned: false, run_status: 'failed', last_error: 'boom' },
    ]);
    useStore.getState().markSessionRunning('started');
    const sessions = useStore.getState().sessions;
    expect(sessions.map((s) => s.id)).toEqual(['pinned', 'started', 'newest']);
    const started = sessions.find((s) => s.id === 'started');
    expect(started?.run_status).toBe('running');
    expect(started?.last_error).toBeNull();
    expect(started?.last_message_at).toBeGreaterThan(0);
  });

  it('markSessionRunning 会话不在列表时 no-op', () => {
    seed([]);
    useStore.getState().markSessionRunning('missing');
    expect(useStore.getState().sessions).toEqual([]);
  });

  it('addSession 去重且按排序规则插入', () => {
    seed([
      { id: 'pinned', title: 'pinned', created_at: 0, updated_at: 1, last_message_at: null, message_count: 0, is_pinned: true },
      { id: 'existing', title: 'existing', created_at: 0, updated_at: 5_000, last_message_at: null, message_count: 0, is_pinned: false },
    ]);
    const fresh: Session = { id: 'fresh', title: '新对话', created_at: 0, updated_at: 10_000, last_message_at: null, message_count: 0, is_pinned: false };
    useStore.getState().addSession(fresh);
    expect(useStore.getState().sessions.map((s) => s.id)).toEqual(['pinned', 'fresh', 'existing']);
    useStore.getState().addSession(fresh);
    expect(useStore.getState().sessions.map((s) => s.id)).toEqual(['pinned', 'fresh', 'existing']);
  });
});
```

注意：`store.test.ts` 顶部需确认已从 `../store` 导入 `useStore` 与 `Session` 类型；若只有 `useStore`，把 `Session` 一并加入 `import type`。

- [ ] **Step 2: 运行确认失败**

Run: `npx vitest run src/shared/lib/__tests__/store.test.ts`
Expected: FAIL（`addSession` / `markSessionRunning` 不存在）

- [ ] **Step 3: 实现**

在 `store.ts` 顶部导入：

```ts
import { sortSessions } from './sessionOrder';
```

在 `StoreState` 接口中 `updateSession` 之后加入：

```ts
  /** 新会话入列（项目绑定/草稿复用路径）：去重并按与后端一致的规则插入 */
  addSession: (session: Session) => void;
  /** 运行开始：本地即时标记 running 并按后端排序规则置顶（流末 loadSessions 对账） */
  markSessionRunning: (id: string) => void;
```

在实现区（`updateSession` 之后）加入：

```ts
  // 新会话入列：id 已存在则 no-op；排序规则与后端 SessionRepository.list() 一致
  addSession: (session) => {
    set((state) => {
      if (state.sessions.some((s) => s.id === session.id)) return {};
      return { sessions: sortSessions([session, ...state.sessions]) };
    });
  },

  // 运行开始：乐观标记 running 并即时置顶。后端 run_started 事件与流末
  // loadSessions() 会以服务端真值对账；last_error 清空与服务端语义一致
  // （update_run_status 传 error=None 时清旧错误）。
  markSessionRunning: (id) => {
    set((state) => {
      const target = state.sessions.find((s) => s.id === id);
      if (!target) return {};
      const updated: Session = {
        ...target,
        run_status: 'running',
        last_message_at: Date.now(),
        last_error: null,
      };
      return {
        sessions: sortSessions(state.sessions.map((s) => (s.id === id ? updated : s))),
      };
    });
  },
```

同时把 `createSession` 中的：

```ts
      set((state) => ({
        sessions: [session, ...state.sessions],
        currentSessionId: session.id,
      }));
```

改为：

```ts
      set((state) => ({
        sessions: sortSessions([session, ...state.sessions]),
        currentSessionId: session.id,
      }));
```

- [ ] **Step 4: 运行确认通过**

Run: `npx vitest run src/shared/lib/__tests__/store.test.ts`
Expected: PASS（原有测试 + 新增 3 tests）

- [ ] **Step 5: Commit**

```bash
git add src/shared/lib/store.ts src/shared/lib/__tests__/store.test.ts
git commit -m "feat(sidebar): add addSession/markSessionRunning store actions"
```

---

### Task 3: `useChat` 发送即置顶 + `run_started` 事件分支

**Files:**
- Modify: `src/features/send-message/useChat.ts`（`sendMessage` 中 `markStreamActive` 之后；`onEvent` 的 `session_updated` 分支）
- Test: `src/features/send-message/__tests__/useChat.sessionUpdatedIncremental.test.ts`

**Interfaces:**
- Consumes: Task 2 的 `useStore.getState().markSessionRunning(id: string): void`
- Produces: 无新导出；行为契约——`run_started` 事件到达时**不**触发全量 `loadSessions()`，仅原地置顶。

- [ ] **Step 1: 写失败测试（追加到已有 describe 内）**

```ts
  it('run_started 事件原地标记 running 并置顶，不做全量会话重载', async () => {
    seedSession('旧标题');
    await sendWithSessionUpdated({
      type: 'session_updated',
      subtype: 'run_started',
    });
    const session = useStore.getState().sessions.find((s) => s.id === SESSION_ID);
    expect(session?.run_status).toBe('running');
    // 仅 finishStream 兜底一次；run_started 不再走全量 loadSessions
    expect(loadSessionsSpy).toHaveBeenCalledTimes(1);
  });
```

- [ ] **Step 2: 运行确认失败**

Run: `npx vitest run src/features/send-message/__tests__/useChat.sessionUpdatedIncremental.test.ts`
Expected: FAIL —— `loadSessionsSpy` 被调用 2 次（事件落入 else 分支）

- [ ] **Step 3: 实现**

`sendMessage` 中，找到：

```ts
      markStreamActive(sid, { streamId: null, cancel: null, finish: null });
      setError(null);
      setErrorSessionId(null);
```

在 `markStreamActive` 之后插入：

```ts
      // 2026-11-19 实时排序：运行开始即本地置顶（后端 run_started 事件 +
      // 流末 loadSessions() 对账）。不等待首个事件，发送瞬间侧栏就应重排。
      useStore.getState().markSessionRunning(sid);
```

`onEvent` 中，把：

```ts
              if (evt.type === 'session_updated') {
                if (evt.subtype === 'title_updated' && typeof evt.title === 'string') {
                  useStore.getState().updateSession(sid, { title: evt.title });
                } else {
                  // 其它 session_updated 子类型仍走全量刷新
                  void useStore.getState().loadSessions();
                }
                return;
              }
```

改为：

```ts
              if (evt.type === 'session_updated') {
                if (evt.subtype === 'title_updated' && typeof evt.title === 'string') {
                  useStore.getState().updateSession(sid, { title: evt.title });
                } else if (evt.subtype === 'run_started') {
                  // 2026-11-19 实时排序：运行开始原地置顶，不做全量重载
                  // （SQL 已按 run_status 排序，此前缺的只是运行期间的刷新信号）。
                  useStore.getState().markSessionRunning(sid);
                } else {
                  // 其它 session_updated 子类型仍走全量刷新
                  void useStore.getState().loadSessions();
                }
                return;
              }
```

- [ ] **Step 4: 运行确认通过（连同既有两条用例）**

Run: `npx vitest run src/features/send-message/__tests__/useChat.sessionUpdatedIncremental.test.ts`
Expected: PASS（3 tests）

- [ ] **Step 5: Commit**

```bash
git add src/features/send-message/useChat.ts src/features/send-message/__tests__/useChat.sessionUpdatedIncremental.test.ts
git commit -m "feat(sidebar): promote running session on send and run_started event"
```

---

### Task 4: Welcome 项目绑定路径即时入列

**Files:**
- Modify: `src/pages/Welcome.tsx`（`draftSessionRef` 类型、`ensureDraftSession`、`handleSubmit`、`useStore` 解构）
- Test: `src/pages/__tests__/Welcome.test.tsx`

**Interfaces:**
- Consumes: Task 2 的 `addSession(session: Session): void`
- Produces: 无新导出。

- [ ] **Step 1: 写失败测试（追加到 `describe('Welcome page')`）**

```ts
  it('项目绑定路径创建的新会话立即写入 store 列表', async () => {
    const projectSession = {
      id: 'project-session-id',
      title: '新对话',
      created_at: 0,
      updated_at: Date.now(),
      last_message_at: null,
      message_count: 0,
      is_pinned: false,
    };
    const createProjectSessionMock = vi.fn().mockResolvedValue({
      project: { id: 'p1', name: 'P', path: '/tmp/p1' },
      session: projectSession,
    });
    const projectApiModule = await import('../../shared/api/projectApi');
    vi.spyOn(projectApiModule.projectApi, 'createSession').mockImplementation(
      createProjectSessionMock,
    );
    localStorage.setItem('sage-welcome.projectId', 'p1');
    const addSessionMock = vi.fn();
    const setState = useStore.setState as unknown as (partial: Record<string, unknown>) => void;
    setState({ addSession: addSessionMock });

    renderWelcome();
    const textarea = screen.getByPlaceholderText(/.*/i);
    fireEvent.change(textarea, { target: { value: 'hello' } });
    fireEvent.keyDown(textarea, { key: 'Enter' });

    await waitFor(() => {
      expect(addSessionMock).toHaveBeenCalledWith(projectSession);
    });
    vi.restoreAllMocks();
    localStorage.clear();
  });
```

实现者注意：
- `STORAGE_KEY_PROJECT` 的真实值以文件内常量为准（当前为 `sage-welcome.projectId`，若不符按常量实际值修改 seed 的键）。
- 若 Enter 键无法触发提交（组件可能要求按钮点击），改为点提交按钮；以页面现有交互为准，断言不变。
- 该用例依赖 mock `projectApi.createSession`，需 `vi.spyOn` 在 `renderWelcome()` 之前设置、结束后 `restoreAllMocks()`。

- [ ] **Step 2: 运行确认失败**

Run: `npx vitest run src/pages/__tests__/Welcome.test.tsx`
Expected: FAIL —— `addSession` 未被调用

- [ ] **Step 3: 实现**

1）`useStore` 解构（文件内 `const { ... } = useStore(...)` 或 hook 解构处）加入 `addSession`。当前 Welcome 从 `useStore` 取 `createSession`、`setCurrentSessionId` 等，模仿同样写法：

```ts
  const addSession = useStore((s) => s.addSession);
```

若该组件采用 `useStore()` 整体解构，则直接在解构对象中加入 `addSession`。

2）导入类型：

```ts
import type { Session } from '../shared/lib/store';
```

（与既有 `import { useStore } from '../shared/lib/store';` 合并或并列，遵循文件既有风格。）

3）`draftSessionRef` 增加 `session` 字段：

```ts
  const draftSessionRef = useRef<{
    projectId: string | null;
    sessionId: string;
    session?: Session;
  } | null>(null);
```

4）`ensureDraftSession` 内部改为（保持其它逻辑不动）：

```ts
        let sessionId: string;
        let created: Session | undefined;
        if (projectId) {
          const result = await projectApi.createSession(projectId);
          sessionId = result.session.id;
          created = result.session;
        } else {
          sessionId = await createSession();
        }
```

并把 `draftSessionRef.current = { projectId, sessionId };` 改为：

```ts
        draftSessionRef.current = { projectId, sessionId, session: created };
```

5）`handleSubmit` 中把：

```ts
        const draft = draftSessionRef.current;
        let sessionId: string;
        if (draft && draft.projectId === (effectiveProjectId ?? null)) {
          sessionId = draft.sessionId;
        } else {
          sessionId = effectiveProjectId
            ? (await projectApi.createSession(effectiveProjectId)).session.id
            : // 2026-11-04 (fix/skip-workspace-binding): effectiveProjectId === null
              // 表示用户在新会话页明确选择"不绑定项目"，传 skipBinding=true 跳过工作区解析链。
              // 语义对齐主流 AI 应用 (Cursor / Cline / Windsurf) 的"显式选择 > 自动推断"原则。
              await createSession(effectiveProjectId === null);
        }
        draftSessionRef.current = null;
```

改为：

```ts
        const draft = draftSessionRef.current;
        let sessionId: string;
        let createdSession: Session | undefined;
        if (draft && draft.projectId === (effectiveProjectId ?? null)) {
          sessionId = draft.sessionId;
          createdSession = draft.session;
        } else if (effectiveProjectId) {
          const result = await projectApi.createSession(effectiveProjectId);
          sessionId = result.session.id;
          createdSession = result.session;
        } else {
          // 2026-11-04 (fix/skip-workspace-binding): effectiveProjectId === null
          // 表示用户在新会话页明确选择"不绑定项目"，传 skipBinding=true 跳过工作区解析链。
          // 语义对齐主流 AI 应用 (Cursor / Cline / Windsurf) 的"显式选择 > 自动推断"原则。
          sessionId = await createSession(effectiveProjectId === null);
        }
        draftSessionRef.current = null;
        // 2026-11-19 实时排序：项目绑定/草稿复用路径此前只建库不写 store，
        // 新会话要等流末全量刷新才出现。创建即入列。
        if (createdSession) addSession(createdSession);
```

6）`handleSubmit` 的 `useCallback` 依赖数组补充 `addSession`。

- [ ] **Step 4: 运行确认通过**

Run: `npx vitest run src/pages/__tests__/Welcome.test.tsx`
Expected: PASS（原有 + 新增 1 test）

- [ ] **Step 5: Commit**

```bash
git add src/pages/Welcome.tsx src/pages/__tests__/Welcome.test.tsx
git commit -m "fix(sidebar): insert project-bound new session into sidebar list immediately"
```

---

### Task 5: 后端 `run_started` 事件

**Files:**
- Modify: `backend/api/legacy_routes.py`（`/chat/stream` producer 中 run 开始的 `update_run_status` 块，约 L598-608）
- Test: `backend/tests/integration/test_chat_stream_run_started.py`（新建）

**Interfaces:**
- Produces: NDJSON 事件 `{"type": "session_updated", "subtype": "run_started", "session_id": <str>}`，位于流的前段（先于 content/done）。
- 前端契约：`run_started` 不携带额外字段，前端按 `session_id`（当前实现用闭包 `sid`）置顶。

- [ ] **Step 1: 写失败测试**

```python
"""2026-11-19 实时排序：/api/v1/chat/stream 在 run 开始时推送 run_started 事件。

此前侧栏会话列表只在流结束时全量刷新 —— 运行中的会话要等流结束才会
按运行态重排。producer 在 running 落库后推送 session_updated/run_started，
前端据此即时置顶。
"""

from __future__ import annotations

import json
from typing import Any, List
from unittest.mock import patch

import pytest
from httpx import ASGITransport, AsyncClient

from backend.data.session_repo import SessionRepository
from backend.main import app

pytestmark = pytest.mark.integration

CHAT_STREAM_PATH = "/api/v1/chat/stream"


def _ensure_stream_registry() -> None:
    from backend.api.chat_stream_registry import StreamRegistry

    if not hasattr(app.state, "streams") or app.state.streams is None:
        app.state.streams = StreamRegistry()


def _parse_ndjson(text: str) -> List[dict]:
    return [json.loads(line) for line in text.split("\n") if line.strip()]


@pytest.mark.asyncio()
async def test_legacy_stream_emits_run_started_event():
    _ensure_stream_registry()
    sid = SessionRepository().create().id

    async def mock_run_loop(messages: Any, max_iterations: int = 5, **kwargs: Any) -> Any:
        from backend.core.legacy.agent_state import AgentEvent, AgentState

        yield AgentEvent(state=AgentState.DONE, iteration=0, content="ok")

    with patch("backend.api.legacy_routes.SageAgent") as MockAgent:
        MockAgent.return_value.run_loop = mock_run_loop

        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
            headers={"X-Sage-Local-Authorization": "Bearer test-local-auth-token"},
        ) as ac:
            create_resp = await ac.post(
                CHAT_STREAM_PATH,
                json={"session_id": sid, "message": "ping"},
            )
            assert create_resp.status_code == 200
            stream_id = create_resp.json()["streamId"]

            attach_resp = await ac.get(f"{CHAT_STREAM_PATH}/{stream_id}")
            assert attach_resp.status_code == 200

    events = _parse_ndjson(attach_resp.text)
    started = [
        e
        for e in events
        if e.get("type") == "session_updated" and e.get("subtype") == "run_started"
    ]
    assert started, f"未找到 run_started 事件，events={[(e.get('type'), e.get('subtype'), e.get('state')) for e in events]}"
    assert started[0]["session_id"] == sid
```

（认证头沿用 `backend/tests/integration/test_chat_title_generation.py` 的既有写法；若 conftest 提供不同的 token/header，按该文件为准。）

- [ ] **Step 2: 运行确认失败**

Run: `/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/integration/test_chat_stream_run_started.py -x -q`
Expected: FAIL —— 未找到 run_started 事件

- [ ] **Step 3: 实现**

把 `legacy_routes.py` 中：

```python
            try:
                await to_thread(
                    SessionRepository().update_run_status, data.session_id, "running"
                )
            except Exception as status_err:  # noqa: BLE001 — fail-open
                logger.debug("会话运行态(running)写入失败: %s", status_err)
```

改为：

```python
            run_status_applied = False
            try:
                run_status_applied = await to_thread(
                    SessionRepository().update_run_status, data.session_id, "running"
                )
            except Exception as status_err:  # noqa: BLE001 — fail-open
                logger.debug("会话运行态(running)写入失败: %s", status_err)
            # 2026-11-19 实时排序：running 落库后推送 run_started，前端据此把
            # 会话即时置顶（SQL 已按 run_status 排序，此前运行期间无刷新信号，
            # 侧栏要等流结束 loadSessions 才重排）。伪会话（无 sessions 行）
            # rowcount=0 → 不推送。fail-open：事件推送失败不影响主流。
            if run_status_applied:
                try:
                    await entry.queue.put(
                        {
                            "type": "session_updated",
                            "subtype": "run_started",
                            "session_id": data.session_id,
                        }
                    )
                except Exception as evt_err:  # noqa: BLE001 — fail-open
                    logger.debug("session_updated/run_started 事件推送失败: %s", evt_err)
```

- [ ] **Step 4: 运行确认通过**

Run: `/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/integration/test_chat_stream_run_started.py -x -q`
Expected: PASS

再跑相邻回归：
Run: `/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/integration/test_chat_stream.py backend/tests/integration/test_chat_title_generation.py -x -q`
Expected: PASS

- [ ] **Step 5: ruff 检查**

Run: `/home/fz/anaconda3/envs/sage-backend/bin/python -m ruff check backend/api/legacy_routes.py backend/tests/integration/test_chat_stream_run_started.py`
Expected: 无新增告警

- [ ] **Step 6: Commit**

```bash
git add backend/api/legacy_routes.py backend/tests/integration/test_chat_stream_run_started.py
git commit -m "feat(chat): emit run_started session_updated event when a run begins"
```

---

### Task 6: 文档更新 + 全量验证

**Files:**
- Modify: `docs/technical/110-session-list-scroll-archive.md`（追加"实时排序与运行态"小节）
- Modify: 本计划文档（勾选步骤）

- [ ] **Step 1: 文档更新**

在 `docs/technical/110-session-list-scroll-archive.md` 末尾追加：

```markdown
## 实时排序与运行态（2026-11-19）

排序由后端 `SessionRepository.list()` 的 SQL 决定：
`is_pinned DESC → run_status IN ('running','suspended') DESC → updated_at DESC`。
前端列表是 store 快照，此前只在流结束 `loadSessions()` 时刷新，导致运行中的
会话要等流结束才重排。现在：

- `useChat.sendMessage` 发送瞬间调用 store `markSessionRunning(sid)`（乐观置顶）；
- 后端 `/api/v1/chat/stream` 在 `run_status='running'` 落库后推送
  `session_updated / run_started` 事件，前端同分支原地置顶，不再触发全量拉取；
- 流结束仍以 `loadSessions()` 全量对账（标题、终态徽章、最终顺序）。
- 本地比较器 `src/shared/lib/sessionOrder.ts` 字段顺序与 SQL 严格一致。
- 新会话：`store.createSession()` 与项目绑定路径（`projectApi.createSession` →
  Welcome 提交时 `addSession`）都会即时入列，不再等流末刷新。
```

- [ ] **Step 2: 全量验证（前端）**

Run: `npx vitest run src/shared/lib/__tests__/sessionOrder.test.ts src/shared/lib/__tests__/store.test.ts src/features/send-message/__tests__/useChat.sessionUpdatedIncremental.test.ts src/pages/__tests__/Welcome.test.tsx`
Expected: 全部 PASS

Run: `npx eslint src/shared/lib/sessionOrder.ts src/shared/lib/store.ts src/features/send-message/useChat.ts src/pages/Welcome.tsx`
Expected: 无 error

Run: `npx prettier --check src/shared/lib/sessionOrder.ts src/shared/lib/store.ts src/features/send-message/useChat.ts src/pages/Welcome.tsx`
Expected: 全部通过（否则 `npx prettier --write` 后重跑）

架构棘轮：若仓库提供 `npm run check:architecture`，运行并确认无新增违规（新增 `sessionOrder.ts`/测试文件行数很小，预期不触发阈值）。

- [ ] **Step 3: 全量验证（后端）**

Run: `/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/integration/test_chat_stream_run_started.py backend/tests/integration/test_chat_stream.py backend/tests/integration/test_chat_title_generation.py -q`
Expected: PASS

- [ ] **Step 4: 勾选本计划文档步骤并提交**

```bash
git add docs/plans/2026-11-19_session-list-live-sort.md docs/technical/110-session-list-scroll-archive.md
git commit -m "docs(sidebar): document live session-list ordering (run_started + instant insert)"
```

---

## 风险评估与依赖

| 风险 | 影响 | 缓解 |
|---|---|---|
| `run_started` 事件与发送乐观更新重复触发 | 无（幂等） | 两个入口调用同一 store 动作，仅排序一次 |
| 本地比较器与服务端 SQL 不一致导致抖动 | 流末全量刷新会纠正，最大一次刷新窗口 | 比较器与 SQL 字段顺序严格一致并有单测锁定；流末 `loadSessions()` 对账 |
| `session_updated` 未知 subtype 语义变化 | 无 | 仅新增 `run_started` 分支，其余 subtype 仍走全量刷新 |
| store 排序改变 pinned 之上插入的旧行为 | 新建会话不再压在 pinned 之上 | 与后端一致，属于修正 |
| Welcome 测试对提交交互的假设（Enter 触发） | 测试写法可能与组件交互不符 | 以页面既有交互为准（按钮点击兜底），断言 addSession 调用不变 |
| 后端事件在流建立前推送丢失 | 前端乐观更新可覆盖当前窗口 | 乐观置顶为主、事件为权威补充、流末对账兜底 |
| 双分支同步 | win7（py38）需 cherry-pick 验证 | 本计划仅落 main；后续 cherry-pick 时事件为纯 dict 无版本差异，前端代码需按 win7 文件结构适配 |

依赖：无新增依赖。后端单测依赖既有 `backend/tests/conftest.py` 的临时 DB/认证 fixture。
