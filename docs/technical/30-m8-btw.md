# M8 /btw 补充消息面板 + @文件提及

> Win7 LTS 维护分支 byte-for-byte port 自 main 分支 Phase 6 (2026-06-29 收官)

## 模块定位

M8 把 main 分支 Phase 6 的两块交互增强落到 win7 LTS:

1. **`/btw` 补充消息面板** — 主对话运行中,用户可发"顺便问一下"型问题,浮层异步获取 LLM 答案,不打断主对话流
2. **`@文件提及`** — 输入 `@` 触发工作区文件搜索菜单,选中后插入 `@path/to/file`,作为上下文传给 LLM

## 架构

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

## 文件清单

### 新增模块

| 文件 | 用途 |
|------|------|
| `src/entities/chat/btwState.ts` | Zustand store(/btw 全局状态) |
| `src/entities/chat/__tests__/btwState.test.ts` | Store 单元测试 |
| `src/features/chat/useAtFileQuery.ts` | 提取 `@xxx` 模式 hook |
| `src/features/chat/__tests__/useAtFileQuery.test.tsx` | Hook 测试 |
| `src/features/chat/AtFileMenu.tsx` | @ 触发文件选择器 |
| `src/features/chat/__tests__/AtFileMenu.test.tsx` | 组件测试 |
| `src/features/chat/useBtwCommand.ts` | /btw 状态机 hook |
| `src/features/chat/__tests__/useBtwCommand.test.ts` | Hook 测试 |
| `src/features/chat/BtwOverlay.tsx` | /btw 浮层面板 |
| `src/features/chat/__tests__/BtwOverlay.test.tsx` | 组件测试 |
| `src/shared/api/fileSearchClient.ts` | 文件搜索 IPC 客户端 |
| `src/shared/api/__tests__/fileSearchClient.test.ts` | Client 测试 |
| `src/features/chat/index.ts` | 统一导出 |
| `src/features/send-message/index.ts` | useChat + BtwPayload 导出 |
| `src/widgets/chat/__tests__/ChatInput.btw.test.tsx` | ChatInput @ + /btw 集成测试 |

### 修改文件

| 文件 | 变更 |
|------|------|
| `src/widgets/chat/ChatInput.tsx` | 加 @ + /btw 拦截,保留 M3 onSchedule |
| `src/widgets/chat/MessageList.tsx` | 挂载 `<BtwOverlay />` |
| `src/widgets/chat/__tests__/MessageList.test.tsx` | mock BtwOverlay 避免上下文 |
| `src/features/send-message/useChat.ts` | 加 `askBtw` 方法 (47e9c24) |
| `src/shared/lib/i18n/zh.ts` | +11 keys (chat.atFile.* + chat.btw.* + chat.btw.question) |
| `src/shared/lib/i18n/en.ts` | +11 keys 英文翻译 |
| `src/shared/lib/i18n/__tests__/translations.test.ts` | key count 101 → 112 |

## 关键设计

### 1. 不新增 npm 包
- AbortController 是 Web API(浏览器 + Node 18+ 都内置)
- Zustand 已存在(M7 之前已 port)

### 2. 文件搜索超时
- `fileSearchClient.search()` 内置 3s AbortController
- 超时返回 `FileSearchTimeoutError`,AtFileMenu 显示"重试"按钮

### 3. 流式中断自动重连
- btw 流式响应支持 1 次自动重连
- 仍失败标 error,不丢消息

### 4. /btw 多实例管理
- 第二次触发 /btw 自动关闭前一个 overlay
- Esc 键:加载中关闭 overlay(不取消主请求);已加载关闭则保留答案

### 5. ChatInput 集成
- 输入 `^/btw\s+(.+)$` 触发,拦截后清空输入框
- `@<query>` 在 cursor 前缀提取,触发 AtFileMenu 浮层

### 6. i18n key 总数
- M1-M7: 101 keys
- M8 新增: 11 keys (`chat.atFile.{searching,empty,timeout,error,retry}` + `chat.btw.{title,placeholder,loading,error,close}` + `chat.btw.question`)
- **累计 112 keys**

## Win7 适配差异

| 维度 | main | win7 | 处理 |
|------|------|------|------|
| `Titlebar.tsx` | 含 FeedbackButton | 简化版(无 FeedbackButton) | 跳过 `15b977c` 中 Titlebar 修改 |
| `FeedbackButton/Modal` | 存在 | **未 port** | 跳过 |
| `ChatInput.tsx` | 含 SlashCommandMenu + useCallback | 含 onSchedule (M3 port) | 手工合成: 增量加 @ + /btw,保留 onSchedule |
| `useChat.ts` | 同 M8-final | M3 阶段已加 onSchedule 流 | 在 win7 基线上加 `askBtw` |
| `MessageList.tsx` | 同 M8-final | win7 简化版 | 在 win7 基线挂 BtwOverlay |

## 收官 SHA

| 项 | 值 |
|----|---|
| Source commits (main) | `1f00624` + `15b977c` (partial) + `0d82f9a` + `38a4f5f` + `47e9c24` + `a04fbfd` + `e3b668c` (partial + 手工合成) + `df747bd` (partial) |
| Win7 feature branch | `feat/win7-m8-btw` |
| Base | `origin/release/win7` @ `b7b17b3` |
| 收官 PR | (待 push) |
| 收官 SHA | (待 merge) |

## 测试统计

- vitest 累计: **585 passed | 8 skipped** (M7: 544 + M8 新增 41)
- 新增测试用例:
  - `btwState.test.ts`: 4 个
  - `useAtFileQuery.test.tsx`: 7 个
  - `AtFileMenu.test.tsx`: 7 个
  - `useBtwCommand.test.ts`: 5 个
  - `BtwOverlay.test.tsx`: 5 个
  - `ChatInput.btw.test.tsx`: 9 个
  - `fileSearchClient.test.ts`: 4 个
- ESLint + Prettier: 全绿
- Backend pytest: 跳过(无 Python 变更)

## 相关文档

- 原始 spec: `docs/superpowers/specs/2026-06-25-aionui-inspired-ui-design.md`
- 原始 plan: `docs/superpowers/plans/2026-06-25-phase6-at-file-btw.md` (main 上 M8 实施 plan)
- win7 spec: `docs/superpowers/specs/2026-06-29-win7-m8-btw-design.md`
- win7 plan: `docs/superpowers/plans/2026-06-29-win7-m8-btw-impl.md`
- 用户手册: `docs/user-manual/08-btw-at-file.md`
- 前序 M7: `docs/technical/29-m7-nav-history.md`