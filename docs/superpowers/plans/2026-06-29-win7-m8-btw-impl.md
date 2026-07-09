---
name: win7-m8-btw-impl
description: M8 /btw + @文件提及 byte-for-byte port from main — 7 phases,8 source commits (含 2 partial),cherry-pick 顺序: 1f00624 → 15b977c(partial) → 0d82f9a → 38a4f5f → 47e9c24 → a04fbfd → e3b668c(partial+手工合成) → df747bd(partial)
metadata:
  type: plan
  status: ready
  spec: 2026-06-29-win7-m8-btw-design.md
  source_commits_main: "1f00624 + 15b977c (partial) + 0d82f9a + 38a4f5f + 47e9c24 + a04fbfd + e3b668c + df747bd (partial)"
  branch: feat/win7-m8-btw
  base: release/win7
  date: 2026-06-29
---

# M8 /btw 补充消息面板 + @文件提及 — Implementation Plan

## 进度

- [ ] Phase 1: 准备 (spec + plan + branch, 1 commit)
- [ ] Phase 2: BtwState Zustand store (cherry-pick 1f00624)
- [ ] Phase 3: fileSearchClient + useAtFileQuery + AtFileMenu (cherry-pick 15b977c partial + 0d82f9a + 38a4f5f)
- [ ] Phase 4: useBtwCommand + useChat.askBtw (cherry-pick 47e9c24)
- [ ] Phase 5: BtwOverlay component (a04fbfd)
- [ ] Phase 6: 集成 — ChatInput.tsx 手工合成 + MessageList.tsx (cherry-pick e3b668c partial)
- [ ] Phase 7: df747bd partial (useChat.ts string|undefined + chat.btw.question i18n + logger.error)
- [ ] Phase 8: CHANGELOG + 文档归档 + 验证 + push + PR

---

## Phase 1: 准备

**Commit 1.1** (no main equivalent, win7-specific):
```
docs: M8 /btw + @文件提及 spec + implementation plan
```

**操作**:
- 写 `docs/superpowers/specs/2026-06-29-win7-m8-btw-design.md` (✅ 已完成)
- 写 `docs/superpowers/plans/2026-06-29-win7-m8-btw-impl.md` (本文档)
- `git switch -c feat/win7-m8-btw` (从 `origin/release/win7` = b7b17b3) ✅ 已完成
- `git add docs/superpowers/{specs,plans}/2026-06-29-win7-m8-btw-*`
- `git commit -m "docs: M8 /btw + @文件提及 spec + implementation plan"`

**验证**:
- `git log --oneline -1` 显示新 commit
- 分支名 = `feat/win7-m8-btw`, base = `release/win7` @ b7b17b3
- `git status` clean

---

## Phase 2: BtwState Zustand store (1f00624)

**Commit 2.1**: `feat(chat): add BtwState Zustand store for /btw overlay`
**来源**: `1f00624`

**操作**:
```bash
git cherry-pick 1f00624
```

**预期冲突**:
- 无 — 全新文件,win7 无 `src/entities/chat/*` 目录,直接新建

**验证**:
- `src/entities/chat/btwState.ts` 存在
- `src/entities/chat/__tests__/btwState.test.ts` 存在
- `npx vitest run src/entities/chat/__tests__/btwState.test.ts` 全绿

---

## Phase 3: fileSearchClient + useAtFileQuery + AtFileMenu

### Commit 3.1: fileSearchClient (15b977c partial)
**来源**: `15b977c` — 仅取 fileSearchClient.ts + test + 一行 btwState.test.ts 增量

**操作**:
```bash
# 手工 partial apply — 不能直接 cherry-pick
git show 15b977c -- src/shared/api/fileSearchClient.ts | git apply
git show 15b977c -- src/shared/api/__tests__/fileSearchClient.test.ts | git apply
git show 15b977c -- src/entities/chat/__tests__/btwState.test.ts | git apply
git add src/shared/api/fileSearchClient.ts \
        src/shared/api/__tests__/fileSearchClient.test.ts \
        src/entities/chat/__tests__/btwState.test.ts
git commit -m "feat(shared): add fileSearchClient for file search (cherry-pick 15b977c partial)"
```

**跳过文件**:
- `src/widgets/layout/Titlebar.tsx` + test (win7 简化版不同)
- `src/features/feedback/FeedbackButton.tsx` + `FeedbackModal.tsx` + tests (win7 未 port)

**预期冲突**: 无 (新文件)

**验证**: `fileSearchClient.test.ts` 全绿

### Commit 3.2: useAtFileQuery hook (0d82f9a)
**来源**: `0d82f9a`

**操作**:
```bash
git cherry-pick 0d82f9a
```

**预期冲突**: 无 — 新文件 `src/features/chat/useAtFileQuery.ts` + test

**验证**: `useAtFileQuery.test.tsx` 全绿

### Commit 3.3: AtFileMenu + i18n atFile keys (38a4f5f)
**来源**: `38a4f5f`

**操作**:
```bash
git cherry-pick 38a4f5f
```

**预期冲突**:
- `src/shared/lib/i18n/{en,zh}.ts`: 仅新增 `atFile.*` namespace,若冲突手工 apply (合并 namespace)

**验证**: `AtFileMenu.test.tsx` 全绿,i18n 翻译键测试全绿

---

## Phase 4: useBtwCommand + useChat.askBtw (47e9c24)

**Commit 4.1**: `feat(chat): add useBtwCommand hook and useChat.askBtw method`
**来源**: `47e9c24`

**操作**:
```bash
git cherry-pick 47e9c24
```

**预期冲突**:
- `src/features/send-message/useChat.ts`: 高概率冲突(win7 在 M3 scheduler port 时已改过 useChat)
- **处理策略**: 保留 win7 现有 onSchedule 流,在 useChat.ts 中增量加 `askBtw` 方法

**冲突解决参考**:
- 保留 win7 `useChat.ts` 的所有现有 import + state
- 在 `sendMessage` 函数体前(或合适位置)加 `askBtw` 方法
- 保留 win7 `setIsLoading(true)` 等 M3 逻辑

**验证**: `useBtwCommand.test.ts` 全绿

---

## Phase 5: BtwOverlay component (a04fbfd)

**Commit 5.1**: `feat(chat): add BtwOverlay component for /btw floating panel`
**来源**: `a04fbfd`

**操作**:
```bash
git cherry-pick a04fbfd
```

**预期冲突**:
- `src/features/chat/index.ts`: 之前 3.2 / 3.3 已加部分导出,需手工合并

**验证**: `BtwOverlay.test.tsx` 全绿

---

## Phase 6: 集成 — ChatInput.tsx + MessageList.tsx (e3b668c partial)

### Commit 6.1: 手工合成 — 不直接 cherry-pick e3b668c
**原因**: `e3b668c` 是集成 commit,改动了 ChatInput.tsx 等多个文件,但 win7 的 ChatInput.tsx 与 main pre-M8 版本差异较大(含 onSchedule,无 useCallback 单独引入,无 SlashCommandMenu 导入)。

**操作策略**:
1. 取 `e3b668c` 中**新增文件部分**:
   - `src/widgets/chat/__tests__/ChatInput.btw.test.tsx` (NEW, 113 lines)
2. 取 `e3b668c` 中**win7 已存在但需要合并的文件**:
   - `src/features/chat/AtFileMenu.tsx` (e3b668c 改了 14 行,大概率冲突,手工合并)
   - `src/features/chat/BtwOverlay.tsx` (e3b668c 改了 13 行,大概率冲突,手工合并)
   - `src/features/chat/__tests__/AtFileMenu.test.tsx` (e3b668c 改了 13 行,手工合并)
   - `src/features/chat/__tests__/useAtFileQuery.test.tsx` (e3b668c 改了 3 行,手工合并)
   - `src/features/chat/__tests__/useBtwCommand.test.ts` (e3b668c 改了 5 行,手工合并)
   - `src/features/chat/index.ts` (e3b668c 改了 6 行,需合并)
   - `src/features/chat/useBtwCommand.ts` (e3b668c 改了 3 行,手工合并)
   - `src/features/send-message/index.ts` (e3b668c 改了 11 行,需合并)
   - `src/shared/api/__tests__/fileSearchClient.test.ts` (e3b668c 改了 16 行,手工合并)
   - `src/shared/api/fileSearchClient.ts` (e3b668c 改了 5 行,手工合并)
   - `src/widgets/chat/ChatInput.tsx` (**手工合成 win7 版本**)
   - `src/widgets/chat/MessageList.tsx` (**手工合成 win7 版本**)
   - `src/widgets/chat/__tests__/MessageList.test.tsx` (e3b668c 改了 8 行,手工合并)

**跳过文件**:
- `src/pages/__tests__/Chat.auto-scroll.test.tsx` (win7 无此文件,且 main pre-M8 才有)

**ChatInput.tsx 手工合成步骤**:
1. 取 main `e3b668c` 的 ChatInput.tsx 全文件作为基线
2. 替换为 win7 当前的 onSchedule 处理(从当前 win7 ChatInput.tsx 复制 onSchedule 部分)
3. 移除 SlashCommandMenu / slashCommands 相关(win7 无此模块)
4. 保留 AtFileMenu + useAtFileQuery + useBtwCommand 的导入

**MessageList.tsx 手工合成步骤**:
1. 取 main `e3b668c` 的 MessageList.tsx 全文件作为基线
2. 保留 win7 当前版本的所有 props(streamingMessageId 等)
3. 添加 BtwOverlay 挂载

**操作示例**:
```bash
# 1. 取 ChatInput.btw.test.tsx 新文件
git show e3b668c -- src/widgets/chat/__tests__/ChatInput.btw.test.tsx | git apply

# 2. 取 fileSearchClient 增量
git show e3b668c -- src/shared/api/fileSearchClient.ts | git apply

# 3. 手工合成 ChatInput.tsx
# (取 main e3b668c 版本作为基线,在 win7 上加 onSchedule 保留)

# 4. 手工合成 MessageList.tsx
# (取 main e3b668c 版本作为基线,在 win7 上加 BtwOverlay 挂载)

# 5. 手工合并其他小改动的文件
for f in src/features/chat/AtFileMenu.tsx \
         src/features/chat/BtwOverlay.tsx \
         src/features/chat/__tests__/AtFileMenu.test.tsx \
         src/features/chat/__tests__/useAtFileQuery.test.tsx \
         src/features/chat/__tests__/useBtwCommand.test.ts \
         src/features/chat/index.ts \
         src/features/chat/useBtwCommand.ts \
         src/features/send-message/index.ts \
         src/shared/api/__tests__/fileSearchClient.test.ts \
         src/widgets/chat/__tests__/MessageList.test.tsx ; do
  git show e3b668c -- "$f" | git apply  # 或手工 vimdiff
done

git add -A
git commit -m "feat(chat): Phase 6 @文件提及 + /btw 补充消息面板集成完成 (cherry-pick e3b668c + win7 手工合成)"
```

**验证**:
- `ChatInput.btw.test.tsx` 全绿
- `AtFileMenu.test.tsx` `useAtFileQuery.test.tsx` `useBtwCommand.test.ts` `BtwOverlay.test.tsx` `MessageList.test.tsx` 全绿
- `fileSearchClient.test.ts` 全绿
- ESLint 通过

---

## Phase 7: df747bd partial (useChat string|undefined + chat.btw.question i18n)

**Commit 7.1**: partial apply of df747bd
**原因**: M7 cherry-pick 时已取 df747bd 的 windowControlsClient.test 部分。本次只取剩余 3 项:
- `src/shared/lib/i18n/{en,zh}.ts`: `chat.btw.question` key
- `src/features/send-message/useChat.ts`: `string|null → string|undefined` (若 useChat.ts 还有此问题)
- `src/features/send-message/useChat.ts`: `logger.error(unknown) → String(err)` 转字符串

**操作**:
```bash
git show df747bd -- src/shared/lib/i18n/en.ts src/shared/lib/i18n/zh.ts | git apply
git show df747bd -- src/features/send-message/useChat.ts | git apply
git add src/shared/lib/i18n/en.ts src/shared/lib/i18n/zh.ts src/features/send-message/useChat.ts
git commit -m "fix(frontend): apply df747bd partial (chat.btw.question i18n + useChat string|undefined + logger.error)"
```

**验证**: i18n 翻译键测试全绿,vitest 全绿

---

## Phase 8: CHANGELOG + 文档归档 + 验证 + push + PR

**Commit 8.1**: `docs: M8 /btw + @文件提及 CHANGELOG + 文档归档`
```bash
# 更新 CHANGELOG.md
# 创建 docs/technical/30-m8-btw.md
# 更新 docs/user-manual/08-btw-at-file.md (新增章节)
# 更新 docs/technical/README.md (加章节链接)
# 更新 docs/user-manual/README.md (加章节链接)

git add CHANGELOG.md docs/
git commit -m "docs: M8 /btw + @文件提及 CHANGELOG + 文档归档"
```

**Commit 8.2 (验证后)**: `chore: pre-PR cleanup` (如有 lint fix / import order)

**push + PR**:
```bash
git push -u origin feat/win7-m8-btw
gh pr create --title "feat(win7): M8 /btw + @文件提及 (cherry-pick from main)" \
  --body "字节对齐 main 上 7 个 commit + 2 partial,以 byte-for-byte 方式 port 到 release/win7"
```

**监控 CI**:
```bash
gh pr checks <PR#> --watch
```

**合并**:
- 等所有 CI 绿
- `gh pr merge --squash --delete-branch`

**最终验证**:
- `git log release/win7 --oneline -1` = squash merge commit
- 远端 + 本地 feature 分支已删
- 工作区干净
- 写 memory 文件 + 更新 MEMORY.md 索引

---

## 关键决策

1. **Phase 2-5 按顺序 cherry-pick**: additive 部分大概率无冲突,可走 git 自动
2. **Phase 6 手工合成**: e3b668c 改动 ChatInput.tsx (win7 版含 onSchedule) → 必须手 patch
3. **Phase 7 partial apply**: df747bd 在 M7 已 cherry-pick 过 windowControlsClient 部分,本次只取剩余
4. **i18n key 计数**: win7 M7 是 101 keys,M8 新增 18 → 累计 119
5. **vitest 累计**: M7 是 544,M8 新增 ≥ 36 → 累计 ≥ 580

## 失败处理

| 失败 | 处理 |
|------|------|
| cherry-pick 冲突 | `git cherry-pick --abort`,回退到上一个 commit,改用 `git show <sha> -- <file> \| git apply` 手工取文件 |
| ESLint 报错 | `npx eslint --fix <file>`,不修语义只修格式 |
| i18n key 不匹配 | 检查 `__tests__/translations.test.ts` 期望值,加 key |
| useChat.ts 反复冲突 | 保留 win7 M3 scheduler 流,只增量加 askBtw |
| Electron smoke test 红 | 检查 BtwOverlay 默认关闭逻辑,smoke 流程不触发 |
| CI 红灯 | STOP,报告用户,不自动修 |