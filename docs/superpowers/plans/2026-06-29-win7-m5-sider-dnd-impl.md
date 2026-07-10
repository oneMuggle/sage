---
name: win7-m5-sider-dnd-impl
description: M5 Sider DnD 实施 plan — 8 phases,19 commits,与 main `01a54e8..e616bb2` 一一对应
metadata:
  type: plan
  status: ready
  spec: 2026-06-29-win7-m5-sider-dnd-design.md
  source_commits_main: "01a54e8..e616bb2 (19 commits)"
  branch: feat/win7-m5-sider-dnd
  base: release/win7
  date: 2026-06-29
---

# M5 Sider DnD Implementation Plan

## 进度

- [ ] Phase 1: 准备 (spec + plan + branch)
- [ ] Phase 2: 纯函数基础 (siderOrder + useStoredSiderOrder, 6 commits)
- [ ] Phase 3: 排序组件 (SortableSessionItem + List, 2 commits)
- [ ] Phase 4: sections hook (useSiderSections, 2 commits)
- [ ] Phase 5: section 容器 + placeholder (3 commits)
- [ ] Phase 6: Sidebar 重构 + i18n (4 commits)
- [ ] Phase 7: 测试恢复 + 收尾 (1 commit)
- [ ] Phase 8: CHANGELOG + push + PR (1 commit)

## Phase 1: 准备

**Commit 1.1** (no main equivalent, win7-specific):
```
docs: M5 Sider DnD design spec + implementation plan
```

**操作**:
- 写 `docs/superpowers/specs/2026-06-29-win7-m5-sider-dnd-design.md` (✅ 已完成)
- 写 `docs/superpowers/plans/2026-06-29-win7-m5-sider-dnd-impl.md` (本文档)
- `git switch -c feat/win7-m5-sider-dnd` (✅ 已完成)
- `git add docs/superpowers/{specs,plans}/2026-06-29-win7-m5-sider-dnd-*`
- `git commit -m "docs: M5 Sider DnD design spec + implementation plan"`

**验证**:
- `git log --oneline -1` 显示新 commit
- 分支名 = `feat/win7-m5-sider-dnd`, base = `release/win7`

---

## Phase 2: 纯函数基础 (6 commits)

### Commit 2.1: test(dnd): scaffold siderOrder pure function tests
**来源**:`01a54e8`

**操作**:
- 从 main 取 `01a54e8` 的 `src/widgets/sidebar/siderOrder.test.ts`
- `git show 01a54e8:src/widgets/sidebar/siderOrder.test.ts > src/widgets/sidebar/siderOrder.test.ts`
- 确认 jest→vitest 语法(项目用 vitest,无 describe.skip 之类的差异)
- `git add src/widgets/sidebar/siderOrder.test.ts`
- `git commit -m "test(dnd): scaffold siderOrder pure function tests"`

**验证**:
- `npx vitest run src/widgets/sidebar/siderOrder.test.ts` → 失败(impl 还没写,符合 TDD red)

### Commit 2.2: feat(dnd): implement siderOrder pure functions
**来源**:`6072f50`

**操作**:
- `git show 6072f50:src/widgets/sidebar/siderOrder.ts > src/widgets/sidebar/siderOrder.ts`
- 保持 main 原版不动(byte-for-byte)
- `git add src/widgets/sidebar/siderOrder.ts`
- `git commit -m "feat(dnd): implement siderOrder pure functions"`

**验证**:
- `npx vitest run src/widgets/sidebar/siderOrder.test.ts` → 全过
- `npx tsc --noEmit` → 0 errors

### Commit 2.3: test(dnd): extend siderOrder coverage to 26 tests
**来源**:`1c6ed22`

**操作**:
- `git show 1c6ed22:src/widgets/sidebar/siderOrder.test.ts > src/widgets/sidebar/siderOrder.test.ts`
- `git commit -m "test(dnd): extend siderOrder coverage to 26 tests"`

**验证**:
- `npx vitest run src/widgets/sidebar/siderOrder.test.ts` → 26/26 pass

### Commit 2.4: style(dnd): reformat siderOrder function signatures
**来源**:`43b436f`

**操作**:
- `git show 43b436f -- src/widgets/sidebar/siderOrder.ts` 看具体 diff
- 应用相同 format(prettier 多行签名 → 单行 / 反之)
- `git commit -m "style(dnd): reformat siderOrder function signatures"`

**验证**:
- `npx prettier --check src/widgets/sidebar/siderOrder.ts` → 0 issues
- `npx vitest run src/widgets/sidebar/siderOrder.test.ts` → 仍 26/26 pass

### Commit 2.5: test(dnd): scaffold useStoredSiderOrder hook tests
**来源**:`d2c4411`

**操作**:
- `git show d2c4411:src/features/sidebar/useStoredSiderOrder.test.ts > src/features/sidebar/useStoredSiderOrder.test.ts`
- `git commit -m "test(dnd): scaffold useStoredSiderOrder hook tests"`

**验证**:
- `npx vitest run src/features/sidebar/useStoredSiderOrder.test.ts` → 失败(impl 还没写)

### Commit 2.6: feat(dnd): implement useStoredSiderOrder hook
**来源**:`29ca1bb`

**操作**:
- `git show 29ca1bb:src/features/sidebar/useStoredSiderOrder.ts > src/features/sidebar/useStoredSiderOrder.ts`
- `git commit -m "feat(dnd): implement useStoredSiderOrder hook"`

**验证**:
- `npx vitest run src/features/sidebar/useStoredSiderOrder.test.ts` → 全过

**Phase 2 收尾验证**:
- `npx vitest run src/widgets/sidebar src/features/sidebar` → 全过
- `npx tsc --noEmit` → 0 errors
- `npx eslint src/widgets/sidebar src/features/sidebar` → 0 errors

---

## Phase 3: 排序组件 (2 commits)

### Commit 3.1: feat(dnd): add SortableSessionItem wrapper with drag handle
**来源**:`b971b92`

**操作**:
- `git show b971b92:src/widgets/session/SortableSessionItem.tsx > src/widgets/session/SortableSessionItem.tsx`
- `git commit -m "feat(dnd): add SortableSessionItem wrapper with drag handle"`

**验证**:
- `npx tsc --noEmit` → 0 errors

### Commit 3.2: feat(session): add SortableSessionList with dnd-kit context
**来源**:`627f968`

**操作**:
- `git show 627f968:src/widgets/session/SortableSessionList.tsx > src/widgets/session/SortableSessionList.tsx`
- `git commit -m "feat(session): add SortableSessionList with dnd-kit context"`

**验证**:
- `npx tsc --noEmit` → 0 errors
- `npx eslint src/widgets/session/Sortable*` → 0 errors

---

## Phase 4: sections hook (2 commits)

### Commit 4.1: feat(sider): add useSiderSections hook with persisted order + collapsed
**来源**:`9a96a73`

**操作**:
- `git show 9a96a73:src/features/sidebar/useSiderSections.ts > src/features/sidebar/useSiderSections.ts`
- `git commit -m "feat(sider): add useSiderSections hook with persisted order + collapsed"`

### Commit 4.2: test(sider): cover useSiderSections hydrate / toggle / reorder
**来源**:`1408657`

**操作**:
- `git show 1408657:src/features/sidebar/useSiderSections.test.ts > src/features/sidebar/useSiderSections.test.ts`
- `git commit -m "test(sider): cover useSiderSections hydrate / toggle / reorder"`

**Phase 4 验证**:
- `npx vitest run src/features/sidebar` → 全过

---

## Phase 5: section 容器 + placeholder (3 commits)

### Commit 5.1: feat(sider): add ConversationsSection with sortable session list and tests
**来源**:`fa3bcc1`

**操作**:
- `git show fa3bcc1:src/widgets/sidebar/ConversationsSection.tsx > src/widgets/sidebar/ConversationsSection.tsx`
- `git show fa3bcc1:src/widgets/sidebar/ConversationsSection.test.tsx > src/widgets/sidebar/ConversationsSection.test.tsx`
- `git commit -m "feat(sider): add ConversationsSection with sortable session list and tests"`

**验证**:
- `npx vitest run src/widgets/sidebar/ConversationsSection.test.tsx` → 全过

### Commit 5.2: feat(sidebar): add placeholder CronJob/Project/Team sections
**来源**:`d66d6af`

**操作**:
- 创建 `src/widgets/sidebar/sections/` 目录
- 从 main 取 3 个 placeholder 文件:
  - `git show d66d6af:src/widgets/sidebar/sections/CronJobSection.tsx > src/widgets/sidebar/sections/CronJobSection.tsx`
  - `git show d66d6af:src/widgets/sidebar/sections/ProjectSection.tsx > src/widgets/sidebar/sections/ProjectSection.tsx`
  - `git show d66d6af:src/widgets/sidebar/sections/TeamSection.tsx > src/widgets/sidebar/sections/TeamSection.tsx`
- **i18n 适配** (P5 内联):placeholder 文案改为 `t('sider.cronjobs.placeholder')` 等
- i18n keys 加到 `src/shared/lib/i18n/zh.ts` + `en.ts` + `TranslationKey` 类型
- `git commit -m "feat(sidebar): add placeholder CronJob/Project/Team sections"`

**验证**:
- `npx tsc --noEmit` → 0 errors
- `npm run lint` → 0 errors

### Commit 5.3: feat(sidebar): add barrel index for sidebar exports
**来源**:`d67ea88`

**操作**:
- 创建 `src/widgets/sidebar/index.ts`,re-export 所有 sidebar 组件
- `git show d67ea88:src/widgets/sidebar/index.ts > src/widgets/sidebar/index.ts`
- 同样 i18n 检查
- `git commit -m "feat(sidebar): add barrel index for sidebar exports"`

**验证**:
- `npx tsc --noEmit` → 0 errors

**Phase 5 收尾验证**:
- `npx vitest run src/widgets/sidebar` → 全过
- `npm run lint` → 0 errors

---

## Phase 6: Sidebar 重构 + i18n (4 commits)

### Commit 6.1: fix(dnd): align drag handle with session title using flex layout
**来源**:`69cd656`

**操作**:
- `git show 69cd656 -- src/widgets/session/SortableSessionItem.tsx` 看 diff
- 应用相同 flex 布局
- `git commit -m "fix(dnd): align drag handle with session title using flex layout"`

**验证**:
- `npx tsc --noEmit` → 0 errors

### Commit 6.2: style(sidebar): lint cleanup for SiderSection and ConversationsSection
**来源**:`de986f4`

**操作**:
- `git show de986f4 -- src/widgets/sidebar/` 看 diff
- 应用相同 lint cleanup
- `git commit -m "style(sidebar): lint cleanup for SiderSection and ConversationsSection"`

**验证**:
- `npm run lint` → 0 errors

### Commit 6.3: fix(sidebar): limit conversations section height to 50vh
**来源**:`de0445c`

**操作**:
- `git show de0445c -- src/widgets/sidebar/ConversationsSection.tsx` 看 diff
- 应用 max-height 50vh
- `git commit -m "fix(sidebar): limit conversations section height to 50vh"`

### Commit 6.4: fix(sidebar): integrate CronJobSection with SiderSection + fix I18nProvider in Chat tests
**来源**:`e616bb2`

**操作**:
- `git show e616bb2 -- src/widgets/layout/Sidebar.tsx` 看 diff → 用 SiderSection 装配
- `git show e616bb2 -- src/widgets/sidebar/sections/CronJobSection.tsx` → refactor CronJobSection 接受 collapsed/onToggleCollapsed
- `git show e616bb2 -- src/widgets/sidebar/sections/__tests__/CronJobSection.test.tsx` (if exists) → 更新测试
- `git show e616bb2 -- src/pages/__tests__/Chat.{auto-scroll,config-warning}.test.tsx` → wrap I18nProvider
- `git commit -m "fix(sidebar): integrate CronJobSection with SiderSection + fix I18nProvider in Chat tests"`

**验证**:
- `npx vitest run src/widgets/layout src/widgets/sidebar src/pages/Chat` → 全过
- `npx tsc --noEmit` → 0 errors
- `npm run lint` → 0 errors

**Phase 6 收尾验证**:
- `npm run lint` → 0 errors
- `npx tsc --noEmit` → 0 errors
- `npx vitest run` → 全过 (关注新增 + 恢复的测试)
- 手动打开应用验证:sidebar 拖动 / 折叠 / 持久化 行为

---

## Phase 7: 测试恢复 + 收尾 (1-2 commits)

### Commit 7.1: test: restore phase 9 deleted tests (M5 active + M6 skip)
**本会话独立 commit,无 main 对应**

**操作**:
- 从 main 取这 5 个文件的当前内容:
  ```bash
  # M5 相关,active
  git show origin/main:src/widgets/sidebar/SiderSection.test.tsx
  git show origin/main:src/widgets/sidebar/__tests__/sections-integration.test.tsx
  git show origin/main:src/widgets/layout/__tests__/Sidebar.new-chat.test.tsx

  # M6 相关,skip 包裹
  git show origin/main:src/pages/__tests__/Chat.welcome-routing.test.tsx
  git show origin/main:src/widgets/welcome/__tests__/WelcomeInputCard.test.tsx
  ```
- 写回对应路径
- 对 M6 相关两个,文件顶部添加:
  ```typescript
  // TODO(M6): Welcome 屏幕尚未在 win7 实现。
  // 本测试文件从 main 恢复以保留测试规范,内容用 describe.skip 包裹。
  // M6 实施时移除 skip 包裹即可激活。
  import { describe, it, expect, vi } from 'vitest';

  describe.skip('M6: Chat.welcome-routing (skipped until M6)', () => {
    // ... main 原内容
  });
  ```
- `git add src/widgets/sidebar/SiderSection.test.tsx src/widgets/sidebar/__tests__/sections-integration.test.tsx src/widgets/layout/__tests__/Sidebar.new-chat.test.tsx src/pages/__tests__/Chat.welcome-routing.test.tsx src/widgets/welcome/__tests__/WelcomeInputCard.test.tsx`
- `git commit -m "test: restore phase 9 deleted tests (M5 active + M6 deferred via describe.skip)"`

**验证**:
- `npx vitest run src/widgets/sidebar src/widgets/layout/__tests__/Sidebar.new-chat.test.tsx` → 全过(M5 active)
- `npx vitest run src/pages/__tests__/Chat.welcome-routing.test.tsx src/widgets/welcome/__tests__/WelcomeInputCard.test.tsx` → 0 个 active tests(都 skip 了),0 errors
- 全 vitest 仍全过

### Commit 7.2 (optional): style(sidebar): fix import ordering in SiderSection.test.tsx
**来源**:`904d492`

**操作**:
- `git show 904d492 -- src/widgets/sidebar/SiderSection.test.tsx` 看 diff
- 如果 7.1 恢复后 import order 已 OK,可 skip 此 commit
- 否则 `npx eslint --fix src/widgets/sidebar/SiderSection.test.tsx`
- `git commit -m "style(sidebar): fix import ordering in SiderSection.test.tsx"`

**验证**:
- `npx eslint src/widgets/sidebar/SiderSection.test.tsx` → 0 errors

---

## Phase 8: CHANGELOG + push + PR (1 commit)

### Commit 8.1: docs: add M5 Sider DnD to CHANGELOG [Unreleased]
**win7-specific commit,无 main 对应**

**操作**:
- 编辑 `CHANGELOG.md`,在 [Unreleased] 段下添加:
  ```markdown
  ### Added
  - feat: Sider DnD with @dnd-kit (siderOrder, useStoredSiderOrder, useSiderSections, SortableSessionItem/List, SiderSection, ConversationsSection, 3 placeholder sections)
  - i18n: 13 new sider.* keys
  - test: restore 3 M5-related + 2 M6-deferred test files
  ```
- `git add CHANGELOG.md`
- `git commit -m "docs: add M5 Sider DnD to CHANGELOG [Unreleased]"`

### Push + PR

**操作**:
```bash
git push -u origin feat/win7-m5-sider-dnd
gh pr create --title "feat(sider): M5 Sider DnD with @dnd-kit" \
  --body "M5 Sider DnD delivery: byte-for-byte port from main..." \
  --base release/win7 --head feat/win7-m5-sider-dnd
```

**PR body 模板**:
```markdown
## Summary
M5 Sider DnD: byte-for-byte port from main (19 commits, 8 phases).

## What's in
- 5 new Sider components (SiderSection, ConversationsSection, 3 placeholder)
- 2 new session components (SortableSessionItem, SortableSessionList)
- 3 new features (siderOrder, useStoredSiderOrder, useSiderSections)
- 13 new i18n keys (sider.section.*, sider.placeholder.*, sider.action.*)
- Sidebar.tsx refactored to use SiderSection + i18n
- 3 M5-related tests restored active, 2 M6 tests restored with describe.skip

## Source
git log origin/main 01a54e8^..e616bb2 (19 commits)

## Test plan
- [ ] vitest 全过
- [ ] lint + tsc 0 errors
- [ ] CI: Frontend / Electron build x2 / Electron smoke 全绿
- [ ] Manual: 拖动 sessions 验证顺序持久化
- [ ] Manual: 折叠 sections 验证状态持久化
- [ ] Manual: i18n 中英文切换 sider 标题显示正确
```

**最终验证**:
- `git log --oneline release/win7..feat/win7-m5-sider-dnd | wc -l` → 19 或 20
- `gh pr view --json state,mergeable,statusCheckRollup`

---

## 风险检查点 (跨 phase)

| 检查点 | Phase | 命令 | 通过条件 |
|---|---|---|---|
| vitest 子集 | 2,4,5,6 | `npx vitest run <dir>` | 0 failed |
| TypeScript | 2-6 | `npx tsc --noEmit` | 0 errors |
| Lint | 2-7 | `npm run lint` | 0 errors |
| 整体 vitest | 7 | `npx vitest run` | 0 failed |
| 整体 pytest | 7 | `pytest backend/tests/{unit,integration}` | 0 failed (M5 无后端改动,只需回归) |
| pre-push hook | 7 | `git push`(会触发) | backend-test + frontend-test 都过 |

## 收尾 (Phase 8 之后)

1. ✅ User review + merge PR
2. ✅ 远端 feat/win7-m5-sider-dnd 自动删除(gh 默认或显式 --delete-branch)
3. ✅ 本地 feat/win7-m5-sider-dnd 删除
4. ✅ Memory 更新: `sage-m5-sider-dnd-merged.md`
5. ⏭️ M6 (Welcome Screen) 准备(本次已恢复其测试文件作准备)
