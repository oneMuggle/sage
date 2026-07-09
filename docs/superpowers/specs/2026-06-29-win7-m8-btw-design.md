---
name: win7-m8-btw-design
description: M8 /btw 补充消息面板 + @文件提及 byte-for-byte port from main — 7 commits + 1 partial,37 files / +1697 lines (净),以 cherry-pick 方式落地到 feat/win7-m8-btw
metadata:
  type: spec
  status: ready
  base_branch: release/win7
  base_sha: b7b17b3
  feature_branch: feat/win7-m8-btw
  source_commits_main: "1f00624 + 15b977c (partial) + 0d82f9a + 38a4f5f + 47e9c24 + a04fbfd + e3b668c + df747bd (partial)"
  date: 2026-06-29
---

# M8 /btw 补充消息面板 + @文件提及 — Win7 LTS Byte-for-Byte Port 设计

## 1. 背景

**源模块:** main 分支 M8 /btw 实现,源自 `docs/superpowers/plans/2026-06-25-phase6-at-file-btw.md`(Stretch Plan)。

**目标:** 将 main 分支的 M8 /btw 实现 byte-for-byte port 到 `release/win7` LTS 维护分支。

**业务价值:**
- `/btw` 命令:用户在主任务运行中可发"补充问题"(by-the-way),在浮层异步获取答案,不打断主对话流
- `@文件提及`:输入 `@` 触发文件搜索菜单,选中后插入 `@path/to/file`,提升消息上下文精度
- win7 用户(macOS/Win 7 SP1)可享受完整对话增强体验

## 2. 来源 Commit 清单 (8 commits / 37 files / +1697 lines)

| # | SHA | Commit msg | Files | Notes |
|---|-----|-----------|-------|-------|
| 1 | `1f00624` | feat(chat): add BtwState Zustand store | 2 | `src/entities/chat/{btwState.ts,__tests__/btwState.test.ts}` — 全 new |
| 2 | `15b977c` | feat(shared): add fileSearchClient | 9 | **PARTIAL** — 跳过 Titlebar.tsx/test(win7 已是简化版)+ FeedbackButton/Modal(win7 未 port) |
| 3 | `0d82f9a` | feat(chat): add useAtFileQuery hook | 2 | 全 new |
| 4 | `38a4f5f` | feat(chat): add AtFileMenu component | 4 | + `atFile.*` i18n keys |
| 5 | `47e9c24` | feat(chat): add useBtwCommand hook | 3 | + useChat.ts 改: sendMessage 加 `btw` 选项 |
| 6 | `a04fbfd` | feat(chat): add BtwOverlay component | 2 | 全 new |
| 7 | `e3b668c` | feat(chat): Phase 6 @文件 + /btw 集成 | 15 | **部分应用** — ChatInput.tsx 需手工合成(win7 版本含 onSchedule) |
| 8 | `df747bd` (partial) | fix(frontend): 修预存 TS 错误 | 4 | 仅取 `chat.btw.question` i18n + useChat.ts `string\|null→string\|undefined` + logger.error 转字符串;**跳过** windowControlsClient.test(M7 已 cherry-pick 过) |

**净 stats(经 win7 适配后):**
- src/features/chat/* (NEW dir, 7 files)
- src/entities/chat/* (NEW dir, 2 files)
- src/shared/api/fileSearchClient.ts + test (NEW, 2 files)
- src/features/send-message/useChat.ts + index.ts (modified)
- src/shared/lib/i18n/{en,zh}.ts (modified, +18 btw/atFile keys)
- src/widgets/chat/ChatInput.tsx (modified, 增量加 @ + /btw)
- src/widgets/chat/MessageList.tsx (modified, 挂 BtwOverlay)
- src/widgets/chat/__tests__/ChatInput.btw.test.tsx (NEW)

## 3. Win7 适配差异 (与 main 不同)

| 维度 | main | win7 | 处理 |
|------|------|------|------|
| `Titlebar.tsx` | 含 FeedbackButton | 简化版(无 FeedbackButton) | 跳过 `15b977c` 中 Titlebar 修改 |
| `FeedbackButton/Modal` | 存在 | **未 port** | 跳过 `15b977c` 中 Feedback 文件 |
| `ChatInput.tsx` | 含 SlashCommandMenu + useCallback | 含 onSchedule (M3 port) 但无 Slash 菜单 | 手工合成: 增量加 @ + /btw,保留 onSchedule |
| `useChat.ts` | 同 M8-final | M3 阶段已加 onSchedule 流 | 在 win7 基线上加 `askBtw` |
| `MessageList.tsx` | 同 M8-final | win7 简化版(无 ThinkingPanel) | 在 win7 基线挂 BtwOverlay |
| 路由 | main 用 react-router 6.x | win7 已用 react-router 6 + Welcome/Memory/Agents 等路由 | 无需改路由 |
| i18n 框架 | main 已用 win7 同款 | win7 用 M1 port 的 i18n | 直接合并新增 keys |

## 4. 技术方案 (沿用 main 原方案)

### 4.1 架构切片

```
@文件提及链路:
  ChatInput 监听 @ 前缀
    → useAtFileQuery (解析 @xxx 模式)
      → fileSearchClient (IPC, 3s AbortController)
        → AtFileMenu (浮层 UI,键盘导航,超时重试)
          → 选中后插入 @path/to/file

/btw 链路:
  ChatInput 拦截 /btw 触发
    → useBtwCommand (open/close/appendDelta/setLoading 状态机)
      → btwState Zustand store (全局共享)
        → BtwOverlay (浮层,渲染 question/answer/loading/error)
        → useChat.sendMessage 加 options.btw = BtwPayload
```

### 4.2 关键不变量(沿用 main spec)

- 不新增 npm 包(AbortController 是 Web API;Zustand 已存在)
- 文件搜索超时: **3s AbortController**,超时显示"重试"按钮
- 流式中断: **自动重连 1 次**,仍失败标 error
- 多个 `/btw` 同时打开: 第二次自动关闭前一个
- `/btw` 加载中 Esc: 关闭 overlay,**不取消主请求**
- 不破坏现有 slash 命令(`/clear` `/help` `/search` `/summarize` `/translate` `/compact`)— win7 当前未实现 slash 命令菜单,M8 暂不引入 SlashCommandMenu
- FSD 架构: `features/chat/*` 组合逻辑, `entities/chat/*` 状态, `widgets/chat/*` UI
- TDD 严格: byte-for-byte port,**不重写测试**(沿用 main 测试用例,win7 已有相同测试 runner 配置)
- 现有 `useChat.sendMessage(content, sessionId?)` 增加可选第三参 `options?: { btw?: BtwPayload }`,不破坏现有调用
- i18n: 新增 `chat.atFile.*` `chat.btw.*` keys 到 `zh.ts`/`en.ts`

## 5. 风险评估

| 风险 | 等级 | 缓解 |
|------|------|------|
| ChatInput.tsx 与 win7 版冲突(e3b668c) | 中 | 手工合成: 先 cherry-pick additive 部分,再手 patch ChatInput.tsx,跑 ChatInput.btw.test.tsx 验证 |
| i18n key 计数漂移 | 低 | 跑测试,确保 101+18=119 |
| useChat.ts string\|null vs string\|undefined | 低 | 沿用 df747bd 修复,保持 string\|undefined |
| Bash heredoc 在 win7 简化版 Layout 下未覆盖 | 低 | ChatInput 测试用例覆盖,M8 不引入 Layout 变更 |
| Electron smoke test 受 btw 浮层影响 | 低 | BtwOverlay 默认关闭,smoke 流程不触发 |

## 6. 验收标准

- [ ] 全部 8 个 source commit(或 partial 等价物)落到 feat/win7-m8-btw
- [ ] vitest 全绿,**新增 ≥ 36 个 M8 测试用例**(btwState + useAtFileQuery + AtFileMenu + useBtwCommand + BtwOverlay + ChatInput.btw + fileSearchClient)
- [ ] vitest 累计通过数 ≥ 580(M7 的 544 + M8 新增)
- [ ] i18n keys 累计 ≥ 119(M7 的 101 + M8 新增 18)
- [ ] ESLint + Prettier 通过
- [ ] Electron build 矩阵 (ubuntu + windows) 通过
- [ ] Electron smoke test 通过
- [ ] Backend pytest 跳过(无 Python 变更)

## 7. 不在本任务范围

- SlashCommandMenu / slashCommands.ts / ShikiCodeBlock.tsx (main 上的 26eba9c / c607039 commit,win7 上未 port,也不属于 M8)
- FeedbackButton / FeedbackModal (win7 长期不做反馈模块)
- 路由层改动 (Welcome/Memory/Agents 路由已就位)
- 后端 Python 改动 (M8 纯前端 + IPC client 改动)

## 8. 相关文档

- 原始 spec: `docs/superpowers/specs/2026-06-25-aionui-inspired-ui-design.md`
- 原始 plan: `docs/superpowers/plans/2026-06-25-phase6-at-file-btw.md` (main 上 M8 实施 plan)
- 关联 plan: `docs/superpowers/plans/2026-06-29-win7-m8-btw-impl.md`(本文档对应的实施 plan)
- 前序 M7 memory: `~/.claude/projects/-home-fz-project-sage/memory/sage-m7-nav-history-merged.md`

## 9. 关键决策

1. **byte-for-byte port**: 不重写任何 main 代码,仅在 win7 已变基线上做最小合并
2. **15b977c partial apply**: 仅取 fileSearchClient + 一行 btwState.test.ts 增量
3. **e3b668c 手工合成**: ChatInput.tsx 在 win7 版本(已含 onSchedule)上手工加 @ + /btw 拦截,保留 onSchedule
4. **df747bd partial apply**: 仅取 useChat.ts string|undefined + chat.btw.question i18n key + logger.error 修复