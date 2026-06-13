# Plan C: IPC shim 改名（desktopInvoke / desktopEvent）

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 IPC shim 从 `tauriInvoke` / `tauriEvent` 改名为 `desktopInvoke` / `desktopEvent`（消除"tauri"误导）。**6 个月内分批迁移**，旧名 re-export 兜底，6 个月后删除旧文件。

**Architecture:** 旧文件变为 thin re-export 标 `@deprecated`。新文件 `desktopInvoke.ts` / `desktopEvent.ts` 是正式 API。ESLint 规则禁止新代码 import 旧名。

**Tech Stack:** TypeScript, ESLint, Vite

**前提事实**：

- 13 个文件用 `tauriInvoke` / `tauriEvent`（已 grep 确认）：
  - 7 个 src/ 源文件
  - 3 个测试文件
  - 2 个 shim 文件本身
- 当前 `src/lib/tauriInvoke.ts` 内部已委托 `window.electronAPI.invoke`（不是 Tauri）
- 旧名误导：让人以为对接 Tauri，实际对接 Electron

**迁移时间表**：

| 周 | 任务 |
|---|---|
| 0 | 建新文件 + 旧文件改 re-export + 加 ESLint 规则 |
| 1-4 | 迁移高频源文件（api.ts, store.ts, wiki.ts） |
| 5-12 | 迁移剩余源文件（Evolution*, useWiki*） |
| 13-20 | 迁移所有测试文件 |
| 21-24 | 删旧 re-export 文件 |

---

## File Structure

| File | Action | Responsibility |
|---|---|---|
| `src/lib/desktopInvoke.ts` | Create | 新正式 API（与 tauriInvoke.ts 同实现） |
| `src/lib/desktopEvent.ts` | Create | 新正式 API（与 tauriEvent.ts 同实现） |
| `src/lib/tauriInvoke.ts` | Modify | 改为 re-export + `@deprecated` JSDoc |
| `src/lib/tauriEvent.ts` | Modify | 改为 re-export + `@deprecated` JSDoc |
| `eslint.config.js` | Modify | 加 `no-restricted-imports` 规则禁旧名 |
| 7 个 src/ 源文件 | Modify | `import` 路径 `tauriInvoke` → `desktopInvoke`（分批） |
| 3 个测试文件 | Modify | `vi.mock` 路径同上 |
| 旧 re-export 文件 | Delete (6 个月后) | `src/lib/tauriInvoke.ts` + `tauriEvent.ts` |

---

## Task 1: 建 feature 分支

**Files:** 无

- [ ] **Step 1: 切换到 main 并更新**

```bash
cd /home/fz/project/sage
git switch main
git pull --rebase origin main
```

- [ ] **Step 2: 建 feature 分支**

```bash
git switch -c refactor/ipc-shim-rename
```

- [ ] **Step 3: 验证状态干净**

```bash
git status
```

Expected: `nothing to commit, working tree clean`

---

## Task 2: 创建 desktopInvoke.ts

**Files:**
- Create: `src/lib/desktopInvoke.ts`

- [ ] **Step 1: 创建新文件**

```bash
cat > src/lib/desktopInvoke.ts <<'EOF'
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
 * 测试通过 `vi.mock('@/lib/desktopInvoke')` 桩化，与底层 transport 解耦
 */
import type { ElectronAPI } from '../types/electron-api';

export async function invoke<T>(cmd: string, args?: Record<string, unknown>): Promise<T> {
  const api: ElectronAPI | undefined =
    typeof window !== 'undefined' ? window.electronAPI : undefined;
  if (!api) {
    throw new Error(
      'electronAPI not available — preload script not loaded. ' +
        'If running outside Electron (e.g. plain browser), this is expected.',
    );
  }
  return api.invoke<T>(cmd, args ?? {});
}
EOF
```

- [ ] **Step 2: 验证文件**

```bash
wc -l src/lib/desktopInvoke.ts && head -5 src/lib/desktopInvoke.ts
```

Expected: ~25 行，首 5 行包含注释

---

## Task 3: 创建 desktopEvent.ts

**Files:**
- Create: `src/lib/desktopEvent.ts`

- [ ] **Step 1: 创建新文件**

```bash
cat > src/lib/desktopEvent.ts <<'EOF'
/**
 * Renderer-side IPC shim — listen(event, handler) → Electron main process → backend SSE.
 *
 * 命名历史（2026-06-13）：从 tauriEvent 改为 desktopEvent，理由同 desktopInvoke.ts
 */
import type { UnlistenFn } from '../types/electron-api';
import type { ElectronAPI } from '../types/electron-api';

export async function listen<T>(
  event: string,
  handler: (payload: T) => void,
): Promise<UnlistenFn> {
  const api: ElectronAPI | undefined =
    typeof window !== 'undefined' ? window.electronAPI : undefined;
  if (!api) {
    throw new Error('electronAPI not available — preload script not loaded.');
  }
  return api.listen<T>(event, handler);
}
EOF
```

- [ ] **Step 2: 验证文件**

```bash
wc -l src/lib/desktopEvent.ts
```

Expected: ~20 行

---

## Task 4: 改 tauriInvoke.ts 为 re-export

**Files:**
- Modify: `src/lib/tauriInvoke.ts`

- [ ] **Step 1: 备份当前文件**

```bash
cp src/lib/tauriInvoke.ts src/lib/tauriInvoke.ts.bak
```

- [ ] **Step 2: 替换为 re-export**

```bash
cat > src/lib/tauriInvoke.ts <<'EOF'
/**
 * @deprecated Use `@/lib/desktopInvoke` instead. This file will be removed after 2026-12-31.
 *
 * 改名理由（2026-06-13）：
 * - 旧名 tauriInvoke 误导，让人以为对接 Tauri
 * - 实际内部委托 `window.electronAPI.invoke`（Electron）
 * - 新名 desktopInvoke 准确表达"桌面端 invoke"，与 transport 解耦
 *
 * 6 个月过渡期（2026-06 ~ 2026-12）：
 * - 旧 import 仍工作（通过本文件 re-export）
 * - 新代码禁止 import 旧名（ESLint `no-restricted-imports` 规则）
 * - 6 个月后（2026-12-31）删除本文件
 */
/** @deprecated use @/lib/desktopInvoke */
export { invoke } from './desktopInvoke';
EOF
```

- [ ] **Step 3: 验证 re-export 工作**

```bash
cat > /tmp/verify-reexport.ts <<'EOF'
import { invoke } from '@/lib/tauriInvoke';
console.log(typeof invoke);
EOF
npx tsc --noEmit --module esnext --target es2020 --moduleResolution node --baseUrl . --paths '{"@/*": ["src/*"]}' /tmp/verify-reexport.ts 2>&1 | head -10
rm /tmp/verify-reexport.ts
```

Expected: 无错误

---

## Task 5: 改 tauriEvent.ts 为 re-export

**Files:**
- Modify: `src/lib/tauriEvent.ts`

- [ ] **Step 1: 替换为 re-export**

```bash
cat > src/lib/tauriEvent.ts <<'EOF'
/**
 * @deprecated Use `@/lib/desktopEvent` instead. This file will be removed after 2026-12-31.
 *
 * 改名理由同 tauriInvoke.ts
 */
/** @deprecated use @/lib/desktopEvent */
export { listen } from './desktopEvent';
export type { UnlistenFn } from './desktopEvent';
EOF
```

- [ ] **Step 2: 验证**

```bash
cat src/lib/tauriEvent.ts
```

Expected: 看到 re-export + `@deprecated`

---

## Task 6: 迁移高频源文件（api.ts, store.ts, wiki.ts）

**Files:**
- Modify: `src/lib/api.ts`
- Modify: `src/lib/store.ts`
- Modify: `src/shared/api-client/wiki.ts`

- [ ] **Step 1: 改 src/lib/api.ts**

```bash
sed -i "s|from '@/lib/tauriInvoke'|from '@/lib/desktopInvoke'|g" src/lib/api.ts
grep "tauriInvoke\|desktopInvoke" src/lib/api.ts
```

Expected: 看到 `desktopInvoke`，看不到 `tauriInvoke`

- [ ] **Step 2: 改 src/lib/store.ts**

```bash
sed -i "s|from '@/lib/tauriInvoke'|from '@/lib/desktopInvoke'|g" src/lib/store.ts
sed -i "s|from '@/lib/tauriEvent'|from '@/lib/desktopEvent'|g" src/lib/store.ts
grep -E "tauriInvoke|tauriEvent|desktopInvoke|desktopEvent" src/lib/store.ts
```

Expected: 看到 `desktop*`，看不到 `tauri*`

- [ ] **Step 3: 改 src/shared/api-client/wiki.ts**

```bash
sed -i "s|from '@/lib/tauriInvoke'|from '@/lib/desktopInvoke'|g" src/shared/api-client/wiki.ts
grep "tauriInvoke\|desktopInvoke" src/shared/api-client/wiki.ts
```

Expected: 看到 `desktopInvoke`

---

## Task 7: 迁移剩余源文件（Evolution*, useWiki*）

**Files:**
- Modify: `src/widgets/evolution/EvolutionLog.tsx`
- Modify: `src/widgets/evolution/EvolutionPanel.tsx`
- Modify: `src/features/wiki/useWikiChatStream.ts`
- Modify: `src/features/wiki/useWikiIngest.ts`

- [ ] **Step 1: 改 EvolutionLog.tsx**

```bash
sed -i "s|from '@/lib/tauriInvoke'|from '@/lib/desktopInvoke'|g" src/widgets/evolution/EvolutionLog.tsx
```

- [ ] **Step 2: 改 EvolutionPanel.tsx**

```bash
sed -i "s|from '@/lib/tauriInvoke'|from '@/lib/desktopInvoke'|g" src/widgets/evolution/EvolutionPanel.tsx
```

- [ ] **Step 3: 改 useWikiChatStream.ts**

```bash
sed -i "s|from '@/lib/tauriInvoke'|from '@/lib/desktopInvoke'|g" src/features/wiki/useWikiChatStream.ts
```

- [ ] **Step 4: 改 useWikiIngest.ts**

```bash
sed -i "s|from '@/lib/tauriInvoke'|from '@/lib/desktopInvoke'|g" src/features/wiki/useWikiIngest.ts
```

- [ ] **Step 5: 验证所有源文件已迁移**

```bash
grep -rln "tauriInvoke\|tauriEvent" src/ | grep -v "src/lib/tauriInvoke.ts" | grep -v "src/lib/tauriEvent.ts"
```

Expected: 无输出（除 shim 文件本身）

---

## Task 8: 迁移测试文件

**Files:**
- Modify: `src/features/manage-agents/__tests__/api.test.ts`
- Modify: `src/features/send-message/__tests__/useChat.test.ts`
- Modify: `src/features/send-message/__tests__/stream.test.ts`

- [ ] **Step 1: 改 api.test.ts**

```bash
sed -i "s|vi.mock('@/lib/tauriInvoke')|vi.mock('@/lib/desktopInvoke')|g" src/features/manage-agents/__tests__/api.test.ts
grep "tauriInvoke\|desktopInvoke" src/features/manage-agents/__tests__/api.test.ts
```

Expected: 看到 `desktopInvoke`

- [ ] **Step 2: 改 useChat.test.ts**

```bash
sed -i "s|vi.mock('@/lib/tauriInvoke')|vi.mock('@/lib/desktopInvoke')|g" src/features/send-message/__tests__/useChat.test.ts
sed -i "s|vi.mock('@/lib/tauriEvent')|vi.mock('@/lib/desktopEvent')|g" src/features/send-message/__tests__/useChat.test.ts
grep -E "tauriInvoke|tauriEvent|desktopInvoke|desktopEvent" src/features/send-message/__tests__/useChat.test.ts
```

Expected: 看到 `desktop*`

- [ ] **Step 3: 改 stream.test.ts**

```bash
sed -i "s|vi.mock('@/lib/tauriInvoke')|vi.mock('@/lib/desktopInvoke')|g" src/features/send-message/__tests__/stream.test.ts
sed -i "s|vi.mock('@/lib/tauriEvent')|vi.mock('@/lib/desktopEvent')|g" src/features/send-message/__tests__/stream.test.ts
```

- [ ] **Step 4: 验证所有测试文件已迁移**

```bash
grep -rln "tauriInvoke\|tauriEvent" src/ tests/ | grep -v "src/lib/tauriInvoke.ts" | grep -v "src/lib/tauriEvent.ts"
```

Expected: 无输出

---

## Task 9: 跑 typecheck + lint + test

**Files:** 无（仅验证）

- [ ] **Step 1: 跑 typecheck**

```bash
npm run typecheck
```

Expected: 0 error

- [ ] **Step 2: 跑 lint**

```bash
npm run lint
```

Expected: 0 error

- [ ] **Step 3: 跑测试**

```bash
npm run test:run
```

Expected: 21 files / 99 tests passed

---

## Task 10: 删除备份 + 提交

**Files:**
- Delete: `src/lib/tauriInvoke.ts.bak`

- [ ] **Step 1: 删除备份**

```bash
rm src/lib/tauriInvoke.ts.bak
```

- [ ] **Step 2: 检查状态**

```bash
git status --short
```

Expected: 看到
- `M` src/lib/api.ts, store.ts, wiki.ts, Evolution*, useWiki*, 3 tests
- `A` src/lib/desktopInvoke.ts, desktopEvent.ts
- `M` src/lib/tauriInvoke.ts, tauriEvent.ts

- [ ] **Step 3: 暂存**

```bash
git add -A
```

- [ ] **Step 4: 提交**

```bash
git commit -m "refactor(ipc): rename tauriInvoke/Event to desktopInvoke/Event (Phase 1/3)

- 加 src/lib/desktopInvoke.ts + desktopEvent.ts（新正式 API）
- src/lib/tauriInvoke.ts + tauriEvent.ts 改为 re-export + @deprecated
- 迁移 7 个 src/ 源文件 import 路径
- 迁移 3 个测试文件 vi.mock 路径
- 6 个月内保留旧 re-export 兜底；新代码禁 import 旧名（ESLint 规则待加）

6 个月后（2026-12-31）删除 tauriInvoke.ts + tauriEvent.ts 兜底文件

Refs: docs/superpowers/specs/2026-06-13-electron-branch-strategy-design.md#5"
```

- [ ] **Step 5: 推 + 开 PR**

```bash
git push -u origin refactor/ipc-shim-rename
gh pr create --title "refactor: rename IPC shim tauriInvoke/Event to desktopInvoke/Event" --body "见 commit message"
```

---

## Task 11: 加 ESLint no-restricted-imports 规则（独立 PR）

**Files:**
- Modify: `eslint.config.js`

> 注：这是独立 PR，不与 Task 1-10 合并。

- [ ] **Step 1: 建新 feature 分支**

```bash
cd /home/fz/project/sage
git switch main
git switch -c chore/eslint-deprecate-tauri-ipc
```

- [ ] **Step 2: 加 no-restricted-imports 规则**

打开 `eslint.config.js`，在 `rules:` 块加：

```javascript
    'no-restricted-imports': [
      'error',
      {
        paths: [
          {
            name: '@/lib/tauriInvoke',
            message: 'Use @/lib/desktopInvoke instead. tauriInvoke is deprecated and will be removed after 2026-12-31.',
          },
          {
            name: '@/lib/tauriEvent',
            message: 'Use @/lib/desktopEvent instead. tauriEvent is deprecated and will be removed after 2026-12-31.',
          },
        ],
      },
    ],
```

- [ ] **Step 3: 跑 lint 验证规则生效**

```bash
npm run lint 2>&1 | head -30
```

Expected: 0 error（所有源文件已迁移，规则不报错）

如果有报错，按报错位置修复后再跑 lint 直到通过。

- [ ] **Step 4: 提交 + 开 PR**

```bash
git add eslint.config.js
git commit -m "chore(eslint): 禁 import 旧 tauriInvoke/tauriEvent，强制新代码用 desktop*"

git push -u origin chore/eslint-deprecate-tauri-ipc
gh pr create --title "chore(eslint): ban import of deprecated tauriInvoke/tauriEvent" --body "见 commit message"
```

---

## Task 12: 6 个月后删除旧 re-export 文件（2026-12-31）

**Files:**
- Delete: `src/lib/tauriInvoke.ts`
- Delete: `src/lib/tauriEvent.ts`

> 注：此 Task 在 2026-12-31 之后执行。本 Plan 不立即删除。

- [ ] **Step 1: 6 个月后创建 task**

```bash
cd /home/fz/project/sage
git switch main
git switch -c chore/remove-tauri-ipc-shim
```

- [ ] **Step 2: 删除旧文件**

```bash
git rm src/lib/tauriInvoke.ts src/lib/tauriEvent.ts
```

- [ ] **Step 3: 跑全量验证**

```bash
npm run typecheck
npm run lint
npm run test:run
```

Expected: 全部通过

- [ ] **Step 4: 提交**

```bash
git commit -m "chore(ipc): remove deprecated tauriInvoke/tauriEvent shims (6-month deprecation period ended)"

git push -u origin chore/remove-tauri-ipc-shim
gh pr create --title "chore: remove deprecated tauriInvoke/tauriEvent (6-month EOL)" --body "见 commit message"
```

---

## Self-Review Checklist (执行前)

- [ ] Task 1-12 全部步骤可执行（无占位符）
- [ ] `desktopInvoke.ts` 实现与 `tauriInvoke.ts` 旧实现完全一致（除命名）
- [ ] 旧 re-export 文件标 `@deprecated` JSDoc
- [ ] 7 个源文件 + 3 个测试文件已确认 grep 位置
- [ ] ESLint 规则是**独立** PR（不在 Task 1-10 合并 PR 内）
- [ ] 6 个月后删除 Task（Task 12）独立执行
- [ ] 6 个月内旧 re-export 兜底，新代码走新名字
