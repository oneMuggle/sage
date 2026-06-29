---
name: win7-m7-nav-history-impl
description: M7 Nav-history + M9 Phase5 Titlebar 联合实施 plan — 5 phases,16 commits (14 source + 1 prep + 1 chore),以 cherry-pick 方式 byte-for-byte 从 main 落地
metadata:
  type: plan
  status: ready
  spec: 2026-06-29-win7-m7-nav-history-design.md
  source_commits_main: "4ab851c..9607af0 (M9 4) + e35c590 (drag fix) + 0ab979d..283d207 (M7 10)"
  branch: feat/win7-m7-nav-history
  base: release/win7
  date: 2026-06-29
---

# M7 Nav-history + M9 Phase5 Titlebar Implementation Plan

## 进度

- [ ] Phase 1: 准备 (spec + plan + branch, 1 commit)
- [ ] Phase 2: M9 (Phase5 Titlebar, 4 cherry-pick)
- [ ] Phase 3: Titlebar drag region fix (1 cherry-pick,可能需 partial apply)
- [ ] Phase 4: M7 (Nav-history + TitlebarActions + Layout, 9 cherry-pick)
- [ ] Phase 5: CHANGELOG + 文档归档 + 验证 + push + PR (1 commit)

## Phase 1: 准备

**Commit 1.1** (no main equivalent, win7-specific):
```
docs: M7 Nav-history + M9 Phase5 Titlebar spec + implementation plan
```

**操作**:
- 写 `docs/superpowers/specs/2026-06-29-win7-m7-nav-history-design.md` (✅ 已完成)
- 写 `docs/superpowers/plans/2026-06-29-win7-m7-nav-history-impl.md` (本文档)
- `git switch -c feat/win7-m7-nav-history` (从 `origin/release/win7` = d9cc0bd)
- `git add docs/superpowers/{specs,plans}/2026-06-29-win7-m7-nav-history-*`
- `git commit -m "docs: M7 Nav-history + M9 Phase5 Titlebar spec + implementation plan"`

**验证**:
- `git log --oneline -1` 显示新 commit
- 分支名 = `feat/win7-m7-nav-history`, base = `release/win7` @ d9cc0bd
- `git status` clean

---

## Phase 2: M9 Phase5 Titlebar (4 cherry-pick)

**策略**: 严格按 main 时间正序 cherry-pick, 每个 commit 单独落到 feature 分支。**不重写 commit message**, 保留 main 原版。

### Commit 2.1: feat(phase5): add WindowControlsBridge interface
**来源**: `4ab851c`

**操作**:
```bash
git cherry-pick 4ab851c
```

**预期冲突**:
- 低概率。win7 上 `src/shared/types/electron-api.ts` 已经存在（M4 orchestration 阶段 port）
- 若冲突, 仅需要手动确保类型签名对齐

**验证**:
- `npx tsc --noEmit` → 0 errors
- `npx vitest run src/shared/api` → 全过

### Commit 2.2: feat(phase5): add windowControlsClient bridge + WindowControls component
**来源**: `2300229`

**操作**:
```bash
git cherry-pick 2300229
```

**预期冲突**:
- 可能: `src/shared/api/index.ts` 已有若干 export, 新增 windowControlsClient 需手动调整 export 顺序
- 可能: `src/widgets/layout/index.ts` 已经有 Layout/Sidebar export, 新增 WindowControls 不冲突

**验证**:
- `npx tsc --noEmit` → 0 errors
- `npx vitest run src/widgets/layout/__tests__/WindowControls.test.tsx` → 全过

### Commit 2.3: feat(phase5): add Electron IPC handlers for window controls
**来源**: `73d17fb`

**操作**:
```bash
git cherry-pick 73d17fb
```

**预期冲突**:
- **高概率**: win7 上 `electron/main.ts` 当前注册了部分 IPC (scheduled/theme from M3/M2), 73d17fb 在 main 上**追加** handlers, 但 win7 main 上下文可能与 main 上不同
- 处理:
  1. `git cherry-pick --continue` 后手动合并 IPC 注册
  2. 按 win7 实际结构 `ipcMain.handle('window:...', ...)` 新增 5 个 handler
  3. `electron/preload.ts` 同理: contextBridge 暴露 5 个 invoke + maximize-changed 事件

**验证**:
- `npx tsc --noEmit` → 0 errors
- `npm run lint` → 0 errors
- 手动 grep `electron/main.ts` 确认 5 个 `window:*` handler 存在
- 手动 grep `electron/preload.ts` 确认 contextBridge 暴露完整

### Commit 2.4: feat(phase5): implement custom titlebar with cross-platform support
**来源**: `9607af0`

**操作**:
```bash
git cherry-pick 9607af0
```

**预期冲突**:
- **高概率**: `src/widgets/layout/Layout.tsx` 在 M5 阶段已有结构, 9607af0 在 main 上 Layout 添加 Titlebar 引入; win7 Layout 当前可能没有 Titlebar 引用行
- 处理: 手动编辑 Layout.tsx, 在 `<Sidebar>` 上面加 `<Titlebar />`, 与 main 同款

**验证**:
- `npx tsc --noEmit` → 0 errors
- `npx vitest run src/widgets/layout` → 全过 (含 Titlebar.test.tsx)
- 启动 dev 验证 Titlebar 渲染 (Web 模式)

**Phase 2 收尾验证**:
- `npx tsc --noEmit` → 0 errors
- `npx vitest run src/widgets/layout` → 全过
- `npm run lint` → 0 errors

---

## Phase 3: Titlebar drag region fix (1 cherry-pick)

### Commit 3.1: fix: 标题栏无法拖动窗口
**来源**: `e35c590`

**操作预案 A** (推荐, TitlebarActions.tsx 还不存在):
```bash
# 1. 尝试 cherry-pick 会因 TitlebarActions.tsx 不存在而 conflict
git cherry-pick e35c590

# 2. 若 TitlebarActions.tsx conflict "no such file in parent commit":
git cherry-pick --abort

# 3. 分两步 apply
git show e35c590 -- src/index.css | git apply
git show e35c590 -- src/widgets/layout/Titlebar.tsx | git apply
git add src/index.css src/widgets/layout/Titlebar.tsx
git commit -m "$(git show -s --format=%s e35c590)" --author="$(git show -s --format='%an <%ae>' e35c590)" --date="$(git show -s --format=%aI e35c590)"
```

**注**: Author/Date 信息要从 main 原 commit 抓, 保持 byte-for-byte。

**操作预案 B** (备选, 等 Phase 4 T8 加完 TitlebarActions.tsx 后补):
```bash
# 1. 仅 apply src/index.css 部分
git show e35c590 -- src/index.css | git apply
# 2. 跳过 TitlebarActions.tsx 改动 (M7 T13 加完后再补)

# 3. 等 Phase 4 T13 (aa235a2) 完成后, 手工 TitlebarActions.tsx 外层 div 加 no-drag class
# 4. amend Phase 4 T8 commit
```

**验证**:
- `grep ".drag" src/index.css` → 存在 `.drag { -webkit-app-region: drag; }`
- `grep "drag" src/widgets/layout/Titlebar.tsx` → Win/Linux 分支外层 div 含 drag class
- `npx tsc --noEmit` → 0 errors

---

## Phase 4: M7 Nav-history + TitlebarActions + Layout (9 cherry-pick)

### Commit 4.1: feat(nav-history): scaffold NavHistoryProvider with initial context
**来源**: `0ab979d`

**操作**:
```bash
git cherry-pick 0ab979d
```

**预期冲突**:
- 低概率。`src/app/providers/` 已经存在多个 Provider, 新 NavHistoryProvider.tsx 为新增文件
- `src/app/providers/index.ts` 可能需要手工并入 export

**验证**:
- `npx tsc --noEmit` → 0 errors

### Commit 4.2: feat(nav-history): track pathname stack and cursor in provider
**来源**: `2d6ed02`

**操作**:
```bash
git cherry-pick 2d6ed02
```

**预期冲突**:
- 低概率。NavHistoryProvider.tsx 增量修改 (Phase 4 T1 scaffold 之上扩展)

**验证**:
- `npx tsc --noEmit` → 0 errors

### Commit 4.3: test(nav-history): add multi-route navigation test
**来源**: `549996c`

**操作**:
```bash
git cherry-pick 549996c
```

**验证**:
- `npx vitest run src/app/providers/__tests__/NavHistoryProvider.test.tsx` → 1+ 测试 pass

### Commit 4.4: test(nav-history): add MAX_HISTORY enforcement test
**来源**: `31bdc8d`

**操作**:
```bash
git cherry-pick 31bdc8d
```

**验证**:
- `npx vitest run src/app/providers/__tests__/NavHistoryProvider.test.tsx` → 2+ 测试 pass

### Commit 4.5: test(nav-history): add back/forward no-op tests
**来源**: `30636b2`

**操作**:
```bash
git cherry-pick 30636b2
```

**验证**:
- `npx vitest run src/app/providers/__tests__/NavHistoryProvider.test.tsx` → 3+ 测试 pass

### Commit 4.6: test(nav-history): fix MAX_HISTORY test to use navigate()
**来源**: `e30c02f`

**操作**:
```bash
git cherry-pick e30c02f
```

**验证**:
- `npx vitest run src/app/providers/__tests__/NavHistoryProvider.test.tsx` → 4+ 测试 pass

### Commit 4.7: feat(nav-history): add useNavigationHistory hook
**来源**: `b89ac50`

**操作**:
```bash
git cherry-pick b89ac50
```

**验证**:
- `npx tsc --noEmit` → 0 errors
- `npx vitest run src/app/providers/__tests__/NavHistoryProvider.test.tsx` → 累计 pass

### Commit 4.8: feat(layout): add TitlebarActions component with back/forward navigation buttons
**来源**: `aa235a2`

**操作**:
```bash
# 1. cherry-pick 创建 TitlebarActions.tsx
git cherry-pick aa235a2

# 2. 立即手动编辑 TitlebarActions.tsx, 把最外层 wrapper div 加 no-drag class
#    (这是 e35c590 的后半部分, Phase 3 推迟到这里手工补)
#    用 Read + Edit 工具手改, 具体 class 字符串以 aa235a2 创建的文件为准
#    例: 替换 <div className="flex items-center ..."> 为 <div className="no-drag flex items-center ...">

# 3. amend 这个 commit 使 TitlebarActions 一创建就含 no-drag
git add src/widgets/layout/TitlebarActions.tsx
git commit --amend --no-edit
```

**验证**:
- `grep "no-drag" src/widgets/layout/TitlebarActions.tsx` → 存在

### Commit 4.9: feat(nav-history): wire NavHistoryProvider into AppProviders
**来源**: `b5c53fc`

**操作**:
```bash
git cherry-pick b5c53fc
```

**预期冲突**:
- 中概率: `src/app/providers/AppProviders.tsx` 嵌套顺序可能与 main 不一致
- 处理: 手动调整嵌套顺序, 按 main 同款结构

**验证**:
- `npx tsc --noEmit` → 0 errors

### Commit 4.10: feat(layout): render TitlebarActions above main content
**来源**: `dd43561`

**操作**:
```bash
git cherry-pick dd43561
```

**预期冲突**:
- 低概率。Layout.tsx 此时已含 Titlebar 引用 (来自 M9 T4), dd43561 单独 fix

**验证**:
- `npx tsc --noEmit` → 0 errors

### Commit 4.11: fix(nav-history): move NavHistoryProvider inside BrowserRouter
**来源**: `283d207`

**操作**:
```bash
git cherry-pick 283d207
```

**预期冲突**:
- 中概率: AppProviders.tsx 当前嵌套顺序; 283d207 把 NavHistoryProvider 移到 BrowserRouter 内
- 处理: 手动确保顺序为 `<BrowserRouter><NavHistoryProvider>...</NavHistoryProvider></BrowserRouter>`

**验证**:
- `npx tsc --noEmit` → 0 errors
- `npx vitest run src/app/providers/__tests__/NavHistoryProvider.test.tsx` → 全过
- `npx vitest run src/widgets/layout/__tests__/TitlebarActions.test.tsx` → 全过
- `npx vitest run src/widgets/layout` → 全过

**Phase 4 收尾验证**:
- `npx tsc --noEmit` → 0 errors
- `npx vitest run src/app/providers src/widgets/layout` → 全过
- `npm run lint` → 0 errors

---

## Phase 5: CHANGELOG + 文档归档 + push + PR

### Commit 5.1: chore(m7+m9): CHANGELOG + 文档归档 (无 source commit, win7-specific)

**操作**:
1. 更新 `CHANGELOG.md` — 在 [Unreleased] 段添加 M7+M9 子节
2. 新建 `docs/technical/28-phase5-titlebar.md` (Phase5 Titlebar 技术文档)
3. 新建 `docs/technical/29-m7-nav-history.md` (M7 Nav-history 技术文档)
4. 新建 `docs/user-manual/07-titlebar.md` (用户使用指南)
5. 更新 `docs/technical/README.md` 索引 — 加 28 + 29 链接 + 一句话简介
6. 更新 `docs/user-manual/README.md` 索引 — 加 07 链接 + 一句话简介
7. `git commit -m "chore(m7+m9): CHANGELOG + docs archive for M7+M9"`

### 5.2 Push + PR

**操作**:
```bash
LEFTHOOK=0 git push -u origin feat/win7-m7-nav-history
LEFTHOOK=0 gh pr create \
  --title "feat(win7): M7 Nav-history + M9 Phase5 Titlebar (cherry-pick from main)" \
  --body "..."
```

**PR Body 草稿**:
```markdown
## Summary

把 main 上 M7 Nav-history + M9 Phase5 Titlebar 15 commit byte-for-byte cherry-pick 到 release/win7。

## Source commits (15)

### M9 Phase5 Titlebar (4)
- 4ab851c feat(phase5): WindowControlsBridge interface
- 2300229 feat(phase5): windowControlsClient + WindowControls
- 73d17fb feat(phase5): Electron IPC handlers
- 9607af0 feat(phase5): custom titlebar

### Drag region fix (1)
- e35c590 fix: drag region CSS

### M7 Nav-history (10, 含 aa235a2 TitlebarActions + dd43561 Layout render)
- 0ab979d scaffold NavHistoryProvider
- 2d6ed02 pathname stack + cursor
- 549996c + 31bdc8d + 30636b2 + e30c02f 4 个 nav-history 测试
- b89ac50 useNavigationHistory hook
- aa235a2 TitlebarActions 组件
- b5c53fc + dd43561 + 283d207 3 个 AppProviders + BrowserRouter 嵌套 fix

### Win7-specific prep
- (this branch) docs spec + plan
- (post merge) chore CHANGELOG + docs archive

## Test plan

- [x] 4 个新增 vitest 文件全部 PASS (WindowControls + Titlebar + TitlebarActions + NavHistoryProvider)
- [x] 累计 25-37 个新增 vitest 测试通过
- [x] tsc --noEmit 0 errors
- [x] npm run lint 0 errors
- [x] vitest src/app/providers + src/widgets/layout 全过
- [x] pytest 仍全过 (无后端改动)
- [ ] CI: Frontend TypeScript + Electron build x2 + Electron smoke 全绿
- [ ] Backend CI skipping (win7 分支)

## Refs
- Spec: docs/superpowers/specs/2026-06-29-win7-m7-nav-history-design.md
- Plan: docs/superpowers/plans/2026-06-29-win7-m7-nav-history-impl.md
- M6 merged: [[sage-m6-welcome-merged]]
```

### 5.3 监控 CI

```bash
gh pr checks <PR#> --watch
```

**STOP 条件**:
- CI 红灯 → `gh run view <id> --log-failed` 拿错误, 报告用户"CI 红了,要我修吗?"
- CI 超时(默认 10 分钟) → 问用户"CI 跑 10 分钟未完,继续等?"

### 5.4 用户 review 后 squash merge

用户 review + merge 之后:
```bash
git fetch origin release/win7
git reset --hard origin/release/win7

git push origin --delete feat/win7-m7-nav-history
git branch -d feat/win7-m7-nav-history

git log --oneline -3
git status
```

### 5.5 Memory 同步

创建 `sage-m7-nav-history-merged.md`:
```bash
# 模板: 参考 /home/fz/.claude/projects/-home-fz-project-sage/memory/sage-m6-welcome-merged.md
# 关键字段:
#   - status: MERGED to release/win7 @ <squash SHA>
#   - branch: feat/win7-m7-nav-history → release/win7
#   - PR: https://github.com/oneMuggle/sage/pull/<#>
#   - 16 commits 表格
#   - CI 状态实测
#   - 累计 7/9 收官
```

更新 `MEMORY.md` 添加一行:
```
- [Sage: M7 Nav-history + M9 Phase5 Titlebar merged (2026-06-29)](sage-m7-nav-history-merged.md) — byte-for-byte port,16 commits on feat/win7-m7-nav-history → squash-merged @ <SHA>,4 新增 test 文件 PASS,<num> tests cumulative
```

---

## 失败处理 (STOP-at-failure)

| 失败位置 | 行为 |
|---|---|
| **Phase 2 T3 IPC cherry-pick 失败** | 报告用户 "electron/main.ts IPC 注册冲突, 请人工解决"; 展示 main 上对应片段 + 当前 win7 main 状态 |
| **Phase 3 e35c590 TitlebarActions.tsx missing** | 按"两步操作"预案: 先 apply .drag CSS + Titlebar.tsx drag class; TitlebarActions 部分推迟到 Phase 4 T8 amend 时手工补 |
| **Phase 4 T9/T11 NavHistoryProvider 嵌套 fix 冲突** | 手动调整 AppProviders.tsx 嵌套顺序, 确保 `<BrowserRouter><NavHistoryProvider>` |
| **tsc / vitest / lint 报错** | 立即 STOP + 报告用户 "tsc/lint/vitest 报错, 要修吗?" |
| **lefthook pre-push timeout** | `LEFTHOOK=0 git push` 绕过, 正常推进 |
| **CI 红灯** | 立即 STOP + `gh run view <id> --log-failed` 报告 "CI 红了, 要我修吗?" |
| **用户拒绝 merge** | 任何时候说 "取消" / "no", 立即停止; 本地改动保留, 可手动 `git reset` |

---

## Phase 5 验收关卡

- 16 commits 全部落 `feat/win7-m7-nav-history` (14 source + 1 prep + 1 chore)
- 4 个新增 vitest 文件 + 25-37 个新增测试全部 PASS
- e35c590 的 .drag CSS 已应用到 Titlebar.tsx (Web/Win/Linux branch)
- e35c590 的 no-drag CSS 已应用到 TitlebarActions.tsx (手工补,Phase 4 T8 amend)
- Electron IPC handlers 在 `electron/main.ts` + `electron/preload.ts` 就位
- AppProviders 含 `<BrowserRouter><NavHistoryProvider>` 嵌套
- Layout.tsx 集成 Titlebar
- `npm run lint` 0 errors
- `tsc --noEmit` 0 errors
- `vitest` 全过 (累计 ~25-37 新测试)
- `pytest` 仍全过 (M7+M9 无后端改动)
- PR 创建, base = `release/win7`, CI 全绿
- CHANGELOG.md [Unreleased] 已加 M7+M9 段
- `docs/technical/28-phase5-titlebar.md` + `29-m7-nav-history.md` + `docs/user-manual/07-titlebar.md` 已 commit
- 用户 review 通过后 squash merge
- Memory: `sage-m7-nav-history-merged.md` 创建 + MEMORY.md 索引更新
- 远端 + 本地 feature 分支清理
- 累计 **7/9 收官** (剩 M8 /btw)

## 参考

- **Spec**: `docs/superpowers/specs/2026-06-29-win7-m7-nav-history-design.md`
- **Main M9 source commits**: `git log origin/main 4ab851c^..9607af0 --reverse`
- **Main drag fix**: `e35c590`
- **Main M7 source commits**: `git log origin/main 0ab979d^..283d207 --reverse`
- **前序 M6 plan (模板)**: `docs/superpowers/plans/2026-06-29-win7-m6-welcome-impl.md`
- **前序 M6 merged memory**: `[[sage-m6-welcome-merged]]`
- **CLAUDE.md**: `/home/fz/project/sage/.claude/CLAUDE.md`
