---
name: win7-m6-welcome-impl
description: M6 Welcome 实施 plan — 7 phases,16 commits,与 main `66603b1..bff49ef` 一一对应
metadata:
  type: plan
  status: ready
  spec: 2026-06-29-win7-m6-welcome-design.md
  source_commits_main: "66603b1..bff49ef (13 commits)"
  branch: feat/win7-m6-welcome
  base: release/win7
  date: 2026-06-29
---

# M6 Welcome Implementation Plan

## 进度

- [ ] Phase 1: 准备 (spec + plan + branch)
- [ ] Phase 2: 基础层 (i18n keys + hook + data, 3 commits)
- [ ] Phase 3: 4 个 widget (Hero + InputCard + AssistantRec + QuickAction, 4 commits)
- [ ] Phase 4: page 组合 + 路由 (Welcome.tsx + /welcome 路由 + Sidebar 还原, 2 commits)
- [ ] Phase 5: 测试 + 激活 skip (5 个新 test + welcome-translations + 激活 2 个 skip, 3 commits)
- [ ] Phase 6: lint cleanup + Chat pendingMessage fix (2 commits)
- [ ] Phase 7: CHANGELOG + 验证 + push + PR (1 commit)

## Phase 1: 准备

**Commit 1.1** (no main equivalent, win7-specific):
```
docs: M6 Welcome design spec + implementation plan
```

**操作**:
- 写 `docs/superpowers/specs/2026-06-29-win7-m6-welcome-design.md` (✅ 已完成)
- 写 `docs/superpowers/plans/2026-06-29-win7-m6-welcome-impl.md` (本文档)
- `git switch -c feat/win7-m6-welcome` (从 release/win7)
- `git add docs/superpowers/{specs,plans}/2026-06-29-win7-m6-welcome-*`
- `git commit -m "docs: M6 Welcome design spec + implementation plan"`

**验证**:
- `git log --oneline -1` 显示新 commit
- 分支名 = `feat/win7-m6-welcome`, base = `release/win7`

---

## Phase 2: 基础层 (3 commits)

### Commit 2.1: feat(i18n): add welcome.* translation keys for Phase 7
**来源**:`66603b1`

**操作**:
- `git show 66603b1 -- src/shared/lib/i18n/zh.ts src/shared/lib/i18n/en.ts` 看 diff
- 应用相同 18 个 keys 加到 win7 的 `src/shared/lib/i18n/zh.ts` + `en.ts`
- 同时把 keys 加到 `TranslationKey` 类型(在 zh.ts 中 export)
- 验证 `translations.test.ts` 的 key count 同步更新
- `git commit -m "feat(i18n): add welcome.* translation keys for Phase 7"`

**验证**:
- `npx tsc --noEmit` → 0 errors
- `npx vitest run src/shared/lib/i18n/__tests__/translations.test.ts` → 全过

### Commit 2.2: feat(welcome): add useTypewriterPlaceholder hook with proper timing
**来源**:`e0e7958`

**操作**:
- `git show e0e7958:src/features/welcome/useTypewriterPlaceholder.ts > src/features/welcome/useTypewriterPlaceholder.ts`
- 保持 main 原版
- `git commit -m "feat(welcome): add useTypewriterPlaceholder hook with proper timing"`

**验证**:
- `npx tsc --noEmit` → 0 errors

### Commit 2.3: feat(entities): add recommendations data for welcome screen
**来源**:`49145e0`

**操作**:
- `git show 49145e0:src/entities/welcome/recommendations.ts > src/entities/welcome/recommendations.ts`
- 保持 main 原版
- `git commit -m "feat(entities): add recommendations data for welcome screen"`

**验证**:
- `npx tsc --noEmit` → 0 errors
- 确认 AssistantRecommendation interface 引用 TranslationKey 类型正确(win7 zh.ts 已 export)

**Phase 2 收尾验证**:
- `npx tsc --noEmit` → 0 errors
- `npx vitest run src/shared/lib/i18n` → 全过

---

## Phase 3: 4 个 widget (4 commits)

### Commit 3.1: feat(welcome): add WelcomeHero component
**来源**:`51d80ad`

**操作**:
- `git show 51d80ad:src/widgets/welcome/WelcomeHero.tsx > src/widgets/welcome/WelcomeHero.tsx`
- `git commit -m "feat(welcome): add WelcomeHero component"`

**验证**:
- `npx tsc --noEmit` → 0 errors

### Commit 3.2: feat(welcome): add WelcomeInputCard with typewriter placeholder
**来源**:`3742d45`

**操作**:
- `git show 3742d45:src/widgets/welcome/WelcomeInputCard.tsx > src/widgets/welcome/WelcomeInputCard.tsx`
- **覆盖** 当前 10 行 stub
- `git commit -m "feat(welcome): add WelcomeInputCard with typewriter placeholder"`

**验证**:
- `npx tsc --noEmit` → 0 errors
- 手动 import 检查:stub 之前只接受 `placeholder/onSend/typewriterPhrases`,main 完整版会加 `prefill/disabled`,确保 type 完全对齐

### Commit 3.3: feat(welcome): add AssistantRecommendations grid component
**来源**:`08add7b`

**操作**:
- `git show 08add7b:src/widgets/welcome/AssistantRecommendations.tsx > src/widgets/welcome/AssistantRecommendations.tsx`
- `git commit -m "feat(welcome): add AssistantRecommendations grid component"`

**验证**:
- `npx tsc --noEmit` → 0 errors

### Commit 3.4: feat(welcome): add QuickActionBar with badge support
**来源**:`82dbd5a`

**操作**:
- `git show 82dbd5a:src/widgets/welcome/QuickActionBar.tsx > src/widgets/welcome/QuickActionBar.tsx`
- `git commit -m "feat(welcome): add QuickActionBar with badge support"`

**验证**:
- `npx tsc --noEmit` → 0 errors
- `npx eslint src/widgets/welcome` → 0 errors

**Phase 3 收尾验证**:
- `npx tsc --noEmit` → 0 errors
- `npm run lint` → 0 errors

---

## Phase 4: page 组合 + 路由 (2 commits)

### Commit 4.1: feat(welcome): add Welcome page composing all welcome widgets
**来源**:`5c9adf8`

**操作**:
- `git show 5c9adf8:src/pages/Welcome.tsx > src/pages/Welcome.tsx`
- **覆盖** 当前 5 行 stub
- `git commit -m "feat(welcome): add Welcome page composing all welcome widgets"`

**验证**:
- `npx tsc --noEmit` → 0 errors
- 手动检查:stub 之前只 export `Welcome()`,main 完整版 export 同样的 `Welcome()`,signature 对齐

### Commit 4.2: feat(routing): add /welcome route with chat sessionId gating fallback
**来源**:`8c02db6` (但本 commit 同时改 Sidebar.handleNewSession,分 2 个子 commit 落)

#### Commit 4.2a: feat(routing): add /welcome route with chat sessionId gating
**操作**:
- 先 `grep -rn "Route" src/app/ src/main.tsx` 找 win7 实际路由位置
- 在 win7 路由文件中加 `<Route path="/welcome" element={<Welcome />} />`
- 把 `<Route path="/chat">` 改成有条件:无 sessionId → `<Navigate to="/welcome" replace />`
- `git commit -m "feat(routing): add /welcome route with chat sessionId gating fallback"`

#### Commit 4.2b: fix(sidebar): revert handleNewSession to navigate('/welcome') from createSession
**操作**:
- 修改 `src/widgets/layout/Sidebar.tsx` 中 `handleNewSession`:
  - 之前 M5 临时方案:`await createSession(); setCurrentSessionId(sessionId);`
  - M6 还原:`navigate('/welcome');` (需要加 useNavigate hook)
- `git commit -m "fix(sidebar): revert handleNewSession to navigate('/welcome') from createSession"`

**验证**:
- `npx tsc --noEmit` → 0 errors
- `npx vitest run src/widgets/layout/__tests__/Sidebar.new-chat.test.tsx` → 全过(注意:这个测试 M5 时期是 describe.skip,M6 实施时也要激活它,因为 main 同款是 active;激活后 adapt 期望行为匹配 navigate)

---

## Phase 5: 测试 + 激活 skip (3 commits)

### Commit 5.1: test(welcome): add 5 unit test files
**来源**:`49fe624` 涵盖 5 个测试文件

**操作**:
- 从 main 取 5 个测试文件:
  ```bash
  git show origin/main:src/entities/welcome/__tests__/recommendations.test.ts > src/entities/welcome/__tests__/recommendations.test.ts
  git show origin/main:src/features/welcome/__tests__/useTypewriterPlaceholder.test.ts > src/features/welcome/__tests__/useTypewriterPlaceholder.test.ts
  git show origin/main:src/widgets/welcome/__tests__/WelcomeHero.test.tsx > src/widgets/welcome/__tests__/WelcomeHero.test.tsx
  git show origin/main:src/widgets/welcome/__tests__/AssistantRecommendations.test.tsx > src/widgets/welcome/__tests__/AssistantRecommendations.test.tsx
  git show origin/main:src/widgets/welcome/__tests__/QuickActionBar.test.tsx > src/widgets/welcome/__tests__/QuickActionBar.test.tsx
  ```
- 验证目录结构,创建 `__tests__` 子目录
- `git commit -m "test(welcome): add 5 unit test files (recommendations, typewriter, hero, recommendations grid, quick action bar)"`

**验证**:
- `npx vitest run src/entities/welcome src/features/welcome src/widgets/welcome/__tests__` → 全过

### Commit 5.2: test(i18n): add welcome-translations.test.ts (18 keys)
**操作**:
- `git show origin/main:src/shared/lib/i18n/__tests__/welcome-translations.test.ts > src/shared/lib/i18n/__tests__/welcome-translations.test.ts`
- `git commit -m "test(i18n): add welcome translation keys coverage (18 keys)"`

**验证**:
- `npx vitest run src/shared/lib/i18n/__tests__/welcome-translations.test.ts` → 全过

### Commit 5.3: test: activate M6-deferred tests + fix outdated "Claude"→"Sage"
**win7-specific commit**,无 main 对应

**操作**:
- 改 `src/widgets/welcome/__tests__/WelcomeInputCard.test.tsx`:
  - 顶部 `describe.skip` → `describe`
  - 修正任何过时硬编码(目前看 main 当前是 "Sage",win7 skip 的是 "Claude" 时代)
  - 移除顶部 TODO(M6) 注释
- 改 `src/pages/__tests__/Chat.welcome-routing.test.tsx`:
  - 同上
  - 特别确认 `expect(screen.getByText(/你好，我是 Sage/))` 匹配 main 当前(win7 skip 版本是 "Claude")
- `git add -u src/widgets/welcome/__tests__/WelcomeInputCard.test.tsx src/pages/__tests__/Chat.welcome-routing.test.tsx`
- `git commit -m "test: activate M6-deferred tests (WelcomeInputCard + Chat.welcome-routing)"`

**验证**:
- `npx vitest run src/widgets/welcome/__tests__/WelcomeInputCard.test.tsx` → active 6 tests 全过
- `npx vitest run src/pages/__tests__/Chat.welcome-routing.test.tsx` → active 2 tests 全过

**Phase 5 收尾验证**:
- `npx vitest run src/widgets/welcome src/entities/welcome src/features/welcome src/pages/__tests__/Chat.welcome-routing src/shared/lib/i18n` → 全过

---

## Phase 6: lint cleanup + Chat pendingMessage fix (2 commits)

### Commit 6.1: refactor(welcome): lint cleanup after Phase 7 integration
**来源**:`8bf7fe8`

**操作**:
- `git show 8bf7fe8 -- src/widgets/welcome/ src/pages/Welcome.tsx` 看 diff
- 应用相同 lint 修复(prettier 格式、unused import 等)
- `git commit -m "refactor(welcome): lint cleanup after Phase 7 integration"`

**验证**:
- `npm run lint` → 0 errors
- `npx prettier --check src/widgets/welcome src/pages/Welcome.tsx` → 0 issues

### Commit 6.2: fix: pass welcome page input to chat and fix race conditions
**来源**:`bff49ef`

**操作**:
- `git show bff49ef -- src/pages/Chat.tsx` 看 diff
- 应用相同 `useLocation` + `location.state.pendingMessage` 修复
- 注意:win7 Chat.tsx 可能路径略有不同(可能 `src/pages/Chat.tsx` 或 `src/widgets/chat/Chat.tsx`),需先 `find` 确认
- `git commit -m "fix: pass welcome page input to chat and fix race conditions"`

**验证**:
- `npx tsc --noEmit` → 0 errors
- `npx vitest run src/pages/__tests__/Chat.welcome-routing.test.tsx` → 全过

---

## Phase 7: CHANGELOG + 验证 + push + PR (1 commit)

### Commit 7.1: docs: add M6 Welcome to CHANGELOG [Unreleased]
**win7-specific commit**

**操作**:
- 编辑 `CHANGELOG.md`,在 [Unreleased] 段顶部加 M6 条目
- `git add CHANGELOG.md`
- `git commit -m "docs: add M6 Welcome to CHANGELOG [Unreleased]"`

**CHANGELOG 条目模板**:
```markdown
- **feat(M6): Welcome — 首次进入应用引导屏 (byte-for-byte port from main)**
  - 7 新组件/hook: WelcomeHero / WelcomeInputCard / AssistantRecommendations /
    QuickActionBar / useTypewriterPlaceholder / recommendations data / Welcome page
  - i18n: 18 新 `welcome.*` keys (hero / input / rec / quick)
  - 路由: `/welcome` + Chat sessionId gating fallback
  - Sidebar `+ 新对话`: M5 临时方案 `createSession()` 还原 main 同款 `navigate('/welcome')`
  - Chat: 接 location.state.pendingMessage,自动发送后清 state 防 race
  - 测试: 7 新 unit test files + 1 E2E + 激活 2 个 phase 9 skip 测试
```

### Push + PR

**操作**:
```bash
# 跳过 pre-push lefthook timeout (M5 经验)
LEFTHOOK=0 git push -u origin feat/win7-m6-welcome
gh pr create --title "feat(welcome): M6 Welcome screen with typewriter + recommendations" \
  --body "..." \
  --base release/win7 --head feat/win7-m6-welcome
```

**最终验证**:
- `git log --oneline release/win7..feat/win7-m6-welcome | wc -l` → 16 左右
- `gh pr view --json state,mergeable,statusCheckRollup`

---

## 风险检查点 (跨 phase)

| 检查点 | Phase | 命令 | 通过条件 |
|---|---|---|---|
| vitest 子集 | 2,3,5 | `npx vitest run <dir>` | 0 failed |
| TypeScript | 2-6 | `npx tsc --noEmit` | 0 errors |
| Lint | 2-6 | `npm run lint` | 0 errors |
| 整体 vitest | 7 | `npx vitest run` | 0 failed |
| 整体 pytest | 7 | `pytest backend/tests/{unit,integration}` | 0 failed (M6 无后端改动) |
| pre-push hook | 7 | `LEFTHOOK=0 git push` | 跳过 timeout,直接 push |

## 收尾 (Phase 7 之后)

1. ✅ CI 监控
2. ✅ User review + merge PR
3. ✅ 远端 feat/win7-m6-welcome 自动删除
4. ✅ 本地 feat/win7-m6-welcome 删除
5. ✅ Memory 更新: `sage-m6-welcome-merged.md`
6. ⏭️ M7 (Nav-history) 启动
