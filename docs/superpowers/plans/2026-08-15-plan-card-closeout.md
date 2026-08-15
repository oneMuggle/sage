# §13.7 编排计划卡延后项收尾 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 收尾 §13.7 三项延后项 —— C4 双击竞态防重入、handleStart 非 409 错误给用户反馈、旧库 NULL original_request 的 resume 兜底。

**Architecture:** 前两项在 `PlanCard.handleStart` 用 `useRef` 同步守卫 + 区分 409 静默/非 409 toast；409 的状态码通过「main 进程 invokeBackend 附加 + renderer 漏斗 desktopInvoke 解析 message」两级打穿 Electron IPC。第三项在 `useChat.resumeOrchestration` 用占位文案兜底 NULL 并 toast 提示。后端零改动。

**Tech Stack:** React 18 + TypeScript + Vite + vitest + Testing Library + sonner toast + Electron 21 IPC。

## Global Constraints

- 后端**零改动**；本计划只动前端 `src/` 与 `electron/` 及技术手册文档。
- 错误 409 语义：派发竞态下**静默**保持编辑态（TaskBoard 首 status 事件会锁），不 toast；非 409 才 toast。
- IPC 自定义属性过不了 Electron 21（main 进程 `sage:invoke` 用 `new Error(msg)` 重包装），**status_code 必须从 message 字符串解析**。
- 前端测试：`npx vitest run <file>`（单文件）；全量 `npm run test:run`；类型 `npm run typecheck`（前端）+ `npm run typecheck:electron`（electron）。
- commit message 走 conventional commits（`fix:` / `test:` / `docs:`）。

---

### Task 1: main 进程 invokeBackend 抛错附加 status_code

**Files:**
- Modify: `electron/invoke.ts:71-77`
- Test: `electron/__tests__/invoke.test.ts:141-144`

**Interfaces:**
- Consumes: `invokeBackend(cmd, args, backendUrl)` 现有签名；`node-fetch` 的 `res.ok/res.status`。
- Produces: 非 OK 响应抛出的 `Error` 带上 `status_code` 字段（数字）。message 格式不变：`Backend ${method} ${url} → ${status}: ${text}`。

- [ ] **Step 1: 改失败测试 —— 断言抛错带 status_code**

在 `electron/__tests__/invoke.test.ts` 替换现有第 141-144 行的 `throws on non-OK response with status code + body text` 测试为：

```ts
  it('throws on non-OK response with status_code attached', async () => {
    mockedFetch.mockResolvedValueOnce(mockJsonResponse('boom', { ok: false, status: 409 }));
    const err = await invokeBackend('list_sessions', {}, 'http://x').catch((e: unknown) => e);
    expect(err).toBeInstanceOf(Error);
    expect((err as Error).message).toMatch(/409.*boom/);
    expect((err as Error & { status_code?: number }).status_code).toBe(409);
  });
```

- [ ] **Step 2: 跑测试确认失败**

Run: `npx vitest run electron/__tests__/invoke.test.ts -t "status_code attached"`
Expected: FAIL —— `status_code` 为 undefined（当前 `throw new Error(...)` 不带字段）。

- [ ] **Step 3: 最小实现**

`electron/invoke.ts` 第 71-77 行改为：

```ts
  const res = await fetch(url, init);
  if (!res.ok) {
    const text = await res.text().catch(() => '');
    const err = new Error(
      `Backend ${route.method} ${url} → ${res.status}: ${text}`,
    ) as Error & { status_code?: number };
    // §13.7: 附加状态码（进程内契约；main 进程 sage:invoke 会用 new Error(msg)
    // 重包装剥掉自定义属性，renderer 侧由 desktopInvoke 从 message 解析兜底）。
    err.status_code = res.status;
    throw err;
  }
  return res.json();
```

- [ ] **Step 4: 跑测试确认通过**

Run: `npx vitest run electron/__tests__/invoke.test.ts`
Expected: PASS —— 全部用例绿（含 status_code attached）。

- [ ] **Step 5: Commit**

```bash
git add electron/invoke.ts electron/__tests__/invoke.test.ts
git commit -m "fix(orch): invokeBackend 抛错附加 status_code（§13.7 ② 前置）"
```

---

### Task 2: renderer 漏斗 desktopInvoke 从 message 解析 status_code

**Files:**
- Modify: `src/shared/api/desktopInvoke.ts`（整文件，26 行）
- Test: `src/shared/api/__tests__/desktop.test.ts`（describe `src/shared/api/desktopInvoke` 后追加）

**Interfaces:**
- Consumes: `window.electronAPI.invoke<T>(cmd, args)`；`ElectronAPI` 类型（`src/shared/types/electron-api.d.ts:129`）。
- Produces: 导出 `InvokeError` 类型（`Error` 带可选 `status_code`）。`invoke()` 拒绝的 Error 上 `status_code` 已填充（错误已带时保留，否则从 message 的 `→ (\d+):` 解析）。

- [ ] **Step 1: 写失败测试**

`src/shared/api/__tests__/desktop.test.ts`：
- 顶部 import 增加 `vi`, `afterEach`：`import { describe, it, expect, vi, afterEach } from 'vitest';`
- 在 `describe('src/shared/api/desktopInvoke', ...)` 块内追加两个用例：

```ts
  it('invoke: IPC 剥掉自定义属性后从 message 解析附加 status_code', async () => {
    const invokeMock = vi.fn().mockRejectedValue(
      new Error(
        'Backend POST http://127.0.0.1:8765/api/v1/orch/runs/r1/plan → 409: ' +
          '{"detail":"plan locked after dispatch"}',
      ),
    );
    (window as Record<string, unknown>).electronAPI = { invoke: invokeMock };
    await expect(
      DesktopInvoke.invoke('orchestration_update_plan', { runId: 'r1', plan: [] }),
    ).rejects.toMatchObject({ status_code: 409 });
    delete (window as Record<string, unknown>).electronAPI;
  });

  it('invoke: 错误已带 status_code 时保留不重复解析', async () => {
    const err = new Error('whatever') as Error & { status_code?: number };
    err.status_code = 500;
    const invokeMock = vi.fn().mockRejectedValue(err);
    (window as Record<string, unknown>).electronAPI = { invoke: invokeMock };
    await expect(DesktopInvoke.invoke('list_sessions')).rejects.toMatchObject({
      status_code: 500,
    });
    delete (window as Record<string, unknown>).electronAPI;
  });
```

- [ ] **Step 2: 跑测试确认失败**

Run: `npx vitest run src/shared/api/__tests__/desktop.test.ts`
Expected: FAIL —— 两个用例 `status_code` 均 undefined（当前 `invoke` 直接 `return api.invoke(...)`，错误原样抛出）。

- [ ] **Step 3: 最小实现**

`src/shared/api/desktopInvoke.ts` 改为：

```ts
/**
 * Renderer-side IPC shim — invoke(cmd, args) → Electron main process → backend HTTP.
 *
 * 命名历史（2026-06-13）：
 * - 旧名 tauriInvoke（误导：实际委托 Electron，与 Tauri 无关）
 * - 新名 desktopInvoke（准确：桌面端 invoke，与 transport 解耦）
 *
 * 内部委托 `window.electronAPI.invoke`（preload.ts 通过 contextBridge 注入）
 * 主进程（electron/main.ts）再把 invoke 转成对 backend FastAPI 的 HTTP 调用
 *
 * §13.7 (2026-08-15): 错误规范化 —— main 进程 sage:invoke 用 new Error(msg)
 * 重包装，Error 自定义属性过不了 Electron 21 IPC，但 message（含 `→ <status>:`）
 * 可靠。renderer 唯一漏斗在此解析附加 status_code，全局所有调用点可读。
 *
 * 测试通过 `vi.mock('@/shared/api/desktopInvoke')` 桩化，与底层 transport 解耦
 */
import type { ElectronAPI } from '../types/electron-api';

/** 跨 IPC 的 HTTP 错误 —— status_code 由本漏斗解析附加。 */
export interface InvokeError extends Error {
  status_code?: number;
}

const STATUS_RE = /→ (\d+):/;

export async function invoke<T>(cmd: string, args?: Record<string, unknown>): Promise<T> {
  const api: ElectronAPI | undefined =
    typeof window !== 'undefined' ? window.electronAPI : undefined;
  if (!api) {
    throw new Error(
      'electronAPI not available — preload script not loaded. ' +
        'If running outside Electron (e.g. plain browser), this is expected.',
    );
  }
  try {
    return await api.invoke<T>(cmd, args ?? {});
  } catch (err) {
    if (err instanceof Error && (err as InvokeError).status_code == null) {
      const m = err.message.match(STATUS_RE);
      if (m) (err as InvokeError).status_code = Number(m[1]);
    }
    throw err;
  }
}
```

- [ ] **Step 4: 跑测试确认通过**

Run: `npx vitest run src/shared/api/__tests__/desktop.test.ts`
Expected: PASS —— 新增两用例绿，既有用例不受影响。

- [ ] **Step 5: Commit**

```bash
git add src/shared/api/desktopInvoke.ts src/shared/api/__tests__/desktop.test.ts
git commit -m "fix(orch): renderer 漏斗从 message 解析 status_code（§13.7 ②）"
```

---

### Task 3: PlanCard C4 双击守卫 + 409 区分 + toast

**Files:**
- Modify: `src/components/PlanCard.tsx`（`handleStart` 45-53 行 + 顶部 import）
- Test: `src/widgets/chat/__tests__/PlanCard.test.tsx`（追加 describe 块）

**Interfaces:**
- Consumes: `orchRunClient.updatePlan(runId, items)`；`toast`（sonner）；`InvokeError` 类型（Task 2 产出，`src/shared/api/desktopInvoke`）。
- Produces: `handleStart` 双击单次落库；`err.status_code === 409` 静默保持编辑态；非 409 `toast.error('计划保存失败：' + message)` 且允许重试。

- [ ] **Step 1: 写失败测试**

`src/widgets/chat/__tests__/PlanCard.test.tsx`：
- 顶部 import（第 1-2 行之间）插入 `import { toast } from 'sonner';`（external 组按字母序：`@testing-library/react` < `sonner` < `vitest`）：

```tsx
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { toast } from 'sonner';
import { describe, expect, it, vi } from 'vitest';
```
- 文件末尾追加 describe 块：

```tsx
// ===== §13.7 延后项 (2026-08-15): C4 双击守卫 + 错误区分 =====
describe('PlanCard §13.7 (C4 双击 + 错误处理)', () => {
  const plan = [{ task_id: 't1', agent_id: 'researcher', goal: 'G' }];

  it('双击开始执行 → updatePlan 只调一次（ref 同步防重入）', async () => {
    vi.mocked(orchRunClient.updatePlan).mockResolvedValue({ ok: true });
    render(<PlanCard runId="r1" plan={plan} locked={false} onCancel={() => {}} />);
    const btn = screen.getByTestId('plan-start');
    fireEvent.click(btn);
    fireEvent.click(btn); // 双击：第二击在 await 完成前被同步拦截
    await waitFor(() => expect(orchRunClient.updatePlan).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(btn).toBeDisabled());
  });

  it('非 409 落库失败 → toast 提示 + 保持编辑态可重试', async () => {
    const toastErrorSpy = vi.spyOn(toast, 'error').mockImplementation(() => '');
    vi.mocked(orchRunClient.updatePlan)
      .mockRejectedValueOnce(new Error('network down'))
      .mockResolvedValueOnce({ ok: true });
    render(<PlanCard runId="r1" plan={plan} locked={false} onCancel={() => {}} />);
    const btn = screen.getByTestId('plan-start');
    fireEvent.click(btn);
    await waitFor(() =>
      expect(toastErrorSpy).toHaveBeenCalledWith(expect.stringContaining('计划保存失败')),
    );
    // ref 已复位 → 再点可成功
    fireEvent.click(btn);
    await waitFor(() => expect(orchRunClient.updatePlan).toHaveBeenCalledTimes(2));
    await waitFor(() => expect(btn).toBeDisabled());
    toastErrorSpy.mockRestore();
  });

  it('409 落库失败 → 静默（不 toast）保持编辑态', async () => {
    const toastErrorSpy = vi.spyOn(toast, 'error').mockImplementation(() => '');
    const err409 = new Error('Backend POST http://x/runs/r1/plan → 409: plan locked after dispatch') as Error & {
      status_code?: number;
    };
    err409.status_code = 409;
    vi.mocked(orchRunClient.updatePlan).mockRejectedValueOnce(err409);
    render(<PlanCard runId="r1" plan={plan} locked={false} onCancel={() => {}} />);
    const btn = screen.getByTestId('plan-start');
    fireEvent.click(btn);
    await waitFor(() => expect(orchRunClient.updatePlan).toHaveBeenCalledTimes(1));
    expect(toastErrorSpy).not.toHaveBeenCalled();
    expect(btn).not.toBeDisabled(); // 保持编辑态
    toastErrorSpy.mockRestore();
  });
});
```

- [ ] **Step 2: 跑测试确认失败**

Run: `npx vitest run src/widgets/chat/__tests__/PlanCard.test.tsx`
Expected: FAIL —— 双击用例 `toHaveBeenCalledTimes(1)` 断言失败（现为 2 次）；错误用例 toast 未被调。

- [ ] **Step 3: 最小实现**

`src/components/PlanCard.tsx`：
- import 块（1-21 行）改为：

```tsx
import { useRef, useState } from 'react';
import { toast } from 'sonner';

import { orchRunClient } from '../shared/api/orchRunClient';
import type { InvokeError } from '../shared/api/desktopInvoke';
import type { TaskPlanItem } from '../shared/api/types';
```

- 组件内加 `const startingRef = useRef(false);`（放在 `locallyLocked` 声明后），并把 `handleStart`（45-53 行）改为：

```tsx
  // §13.7 C4 (2026-08-15): ref 同步守卫 —— await 前置位，双击第二击被拦截
  // （React 状态更新异步，locallyLocked 在成功后 set 拦不住双击）。
  const startingRef = useRef(false);
  const handleStart = async () => {
    if (startingRef.current) return;
    startingRef.current = true;
    try {
      await orchRunClient.updatePlan(runId, items);
    } catch (err) {
      startingRef.current = false; // 失败后允许重试
      // 409（派发竞态）→ 静默保持编辑态，TaskBoard 首 status 事件会锁。
      if ((err as InvokeError).status_code === 409) return;
      toast.error(
        `计划保存失败：${err instanceof Error ? err.message : String(err)}`,
      );
      return;
    }
    setLocallyLocked(true);
  };
```

- [ ] **Step 4: 跑测试确认通过**

Run: `npx vitest run src/widgets/chat/__tests__/PlanCard.test.tsx`
Expected: PASS —— 既有 7 用例 + 新 3 用例全绿。

- [ ] **Step 5: Commit**

```bash
git add src/components/PlanCard.tsx src/widgets/chat/__tests__/PlanCard.test.tsx
git commit -m "fix(orch): 计划卡 C4 双击防重入 + 非 409 落库失败 toast（§13.7 ①②）"
```

---

### Task 4: useChat resumeOrchestration NULL original_request 兜底

**Files:**
- Modify: `src/features/send-message/useChat.ts`（顶部 import + `resumeOrchestration` 565-575 行）
- Test: `src/features/send-message/__tests__/useChat.resume.test.ts`

**Interfaces:**
- Consumes: `orchRunClient.resumeRun(runId)` 返回 `ResumeResponse`（`original_request?: string`）；`sendMessage(content, ...)`；`toast`（sonner）。
- Produces: `resumeOrchestration(runId)` —— NULL 时用占位文案 `（旧记录无原始请求，已从计划恢复）` 发送 + `toast.info('该记录缺少原始请求，已从计划恢复执行')`。

- [ ] **Step 1: 写失败测试**

`src/features/send-message/__tests__/useChat.resume.test.ts`：
- 顶部 import（第 1-2 行之间）插入 `import { toast } from 'sonner';`（external 组按字母序：`@testing-library/react` < `sonner` < `vitest`）：

```ts
import { act, renderHook, waitFor } from '@testing-library/react';
import { toast } from 'sonner';
import { beforeEach, describe, expect, it, vi } from 'vitest';
```
- 在 `describe('useChat.resumeOrchestration (PR C C2)')` 块内追加用例：

```ts
  it('original_request 缺失 → 占位文案发送 + toast 提示', async () => {
    seedActiveEndpoint();
    const plan = [{ task_id: 't1', agent_id: 'researcher', goal: 'G' }];
    const toastInfoSpy = vi.spyOn(toast, 'info').mockImplementation(() => '');
    invokeMock
      .mockResolvedValueOnce({
        ok: true,
        new_run_id: 'orch-new',
        session_id: 's',
        original_request: null,
        plan,
      })
      .mockResolvedValueOnce({ streamId: 'stream-resume' });
    listenMock.mockImplementationOnce(async (_n, cb) => {
      Promise.resolve().then(() =>
        cb({ payload: { state: 'done', iteration: 0, content: 'ok' } }),
      );
      return vi.fn();
    });

    const { result } = renderHook(() => useChat());
    await waitForSettingsLoaded();

    await act(async () => {
      await result.current.resumeOrchestration('orch-old');
    });

    const [, args] = invokeMock.mock.calls[2];
    expect(args.message).toBe('（旧记录无原始请求，已从计划恢复）');
    expect(args.orchestrationMode).toBe('force_multi');
    expect(toastInfoSpy).toHaveBeenCalledWith('该记录缺少原始请求，已从计划恢复执行');
    toastInfoSpy.mockRestore();
  });
```

- [ ] **Step 2: 跑测试确认失败**

Run: `npx vitest run src/features/send-message/__tests__/useChat.resume.test.ts -t "original_request 缺失"`
Expected: FAIL —— `args.message` 为 `''`（当前 `?? ''`），不是占位文案；toast 未被调。

- [ ] **Step 3: 最小实现**

`src/features/send-message/useChat.ts`：
- import 块第 1 行后插入 `import { toast } from 'sonner';`（external 组：`react` < `sonner`）：

```ts
import { useCallback, useMemo, useRef, useState } from 'react';
import { toast } from 'sonner';
```
- `resumeOrchestration`（565-575 行）改为：

```ts
  /** Wave 3 (2026-08-14): resume 恢复流 —— resumeRun → sendMessage(original_request, plan_override)。 */
  const resumeOrchestration = useCallback(
    async (runId: string) => {
      const resp = await orchRunClient.resumeRun(runId);
      // §13.7 (2026-08-15): 旧库 NULL original_request 兜底 —— 占位文案继续 + 提示，
      // 避免空串被当成正常消息发给 LLM（ChatRequest.message 无非空校验）。
      const content = resp.original_request ?? '（旧记录无原始请求，已从计划恢复）';
      if (!resp.original_request) {
        toast.info('该记录缺少原始请求，已从计划恢复执行');
      }
      await sendMessage(content, undefined, undefined, 'force_multi', {
        planOverride: resp.plan,
        runId: resp.new_run_id,
      });
    },
    [sendMessage],
  );
```

- [ ] **Step 4: 跑测试确认通过**

Run: `npx vitest run src/features/send-message/__tests__/useChat.resume.test.ts`
Expected: PASS —— 既有 2 用例 + 新用例全绿。

- [ ] **Step 5: Commit**

```bash
git add src/features/send-message/useChat.ts src/features/send-message/__tests__/useChat.resume.test.ts
git commit -m "fix(orch): resume 旧库 NULL original_request 占位文案兜底（§13.7 ③）"
```

---

### Task 5: §13.7 文档标记完成

**Files:**
- Modify: `docs/technical/42-chat-multi-agent-orchestration.md:329-333`

**Interfaces:**
- 无代码接口。产出：§13.7 三项标记为已完成（沿用 M4 的 `~~strike~~ ✅` 格式）。

- [ ] **Step 1: 更新 §13.7**

`docs/technical/42-chat-multi-agent-orchestration.md` 第 329-333 行改为：

```markdown
- **M4** ~~`updatePlan` 双调用~~ —— ✅ 已收口（2026-08-15）：删除 `Chat.handlePlanStart` + `onPlanStart` 透传链，`PlanCard.handleStart` 单次 updatePlan 落库即完成（派发由后端 conductor 驱动）
- **C4 双击竞态** ~~`handleStart` 连点两次可能双 updatePlan~~ —— ✅ 已收口（2026-08-15）：`useRef` 同步守卫 await 前置位，双击单次落库
- **handleStart 静默吞错** ~~落库失败（非 409）无用户反馈~~ —— ✅ 已收口（2026-08-15）：invoke 错误结构带 `status_code`，409 静默保持编辑态、非 409 toast 提示
- **original_request NULL 兜底** ~~旧库 NULL 行的 resume 需对 undefined 兜底~~ —— ✅ 已收口（2026-08-15）：占位文案 + toast 提示
- 进度可视化已知局限见 §9.3 / §11.7
```

- [ ] **Step 2: 验证**

Run: `grep -n "✅ 已收口（2026-08-15）" docs/technical/42-chat-multi-agent-orchestration.md | wc -l`
Expected: `4`（M4 + 三项新增）。

- [ ] **Step 3: Commit**

```bash
git add docs/technical/42-chat-multi-agent-orchestration.md
git commit -m "docs(orch): §13.7 三项延后项标记收口"
```

---

### Task 6: 全量回归 + 收尾

**Files:**
- 无新增/修改（验证用）。

**Interfaces:**
- 无。

- [ ] **Step 1: 前端全量单测**

Run: `npm run test:run`
Expected: 全绿（既有 ~1200 vitest + 本波新增）。

- [ ] **Step 2: 类型检查（前端 + electron）**

Run: `npm run typecheck && npm run typecheck:electron`
Expected: 0 errors（`InvokeError` 导入路径、`status_code` 属性断言全通过）。

- [ ] **Step 3: 后端回归（确认零改动不破坏）**

Run: `/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend -q`
Expected: 全绿（~3700）。后端无改动，只确认无回归。

- [ ] **Step 4: 删除本 plan 文件 + 清理**

按 feature-development.md 规范，功能并入技术手册（Task 5 已做）后删除本 plan：
Run: `rm docs/superpowers/plans/2026-08-15-plan-card-closeout.md`
并把 spec 归档（保留于 `docs/superpowers/specs/`）。

- [ ] **Step 5: 收口 commit + push**

```bash
git add -A && git commit -m "chore(orch): §13.7 延后项收尾 — 删 plan 文件" || echo "无新增改动"
git push -u origin fix/plan-card-closeout
```

Expected: 分支已推，等待创建 PR / 用户 merge。
