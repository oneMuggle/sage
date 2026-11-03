# 思考过程展示档位（detail / trace / result）

> 日期：2026-11-02
> 分支：`feat/thinking-display-modes`
> 方案：三档可调（detail / trace / result）+ 三级作用域（消息 > 会话 > 全局）+ 纯前端渲染策略

## 1. 定位与目标

Sage 聊天区对 AI 思考过程（`reasoning_content` + `tool_calls`）提供**三档可调展示**：

| 档位     | 值       | 用户意图                     | 典型场景                   |
| -------- | -------- | ---------------------------- | -------------------------- |
| 详细思考 | `detail` | 审阅推理链，确认 AI 理解正确 | 复杂任务、debug            |
| 仅执行   | `trace`  | 监督执行过程，关注工具调用   | 日常协作（**默认**）       |
| 仅结果   | `result` | 只看最终结果                 | 长任务、批量问答、结果速览 |

核心约束：

1. 任何被隐藏的内容都**可回看**——后端始终流式下发完整数据，前端仅控制渲染密度；
2. 切换即时生效且可回溯——切回 `detail` 时历史消息的思考过程立即可见；
3. 默认档位 = `trace`（与功能上线前行为最接近，降低迁移成本）；
4. 三级作用域覆盖：**消息级 > 会话级 > 全局默认 > 回落 `trace`**。

## 2. 模块与数据流

### 2.1 文件清单

| 文件                                                           | 职责                                                                                                    |
| -------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------- |
| `src/features/chat/displayMode/types.ts`                       | `DisplayMode` 类型、`DEFAULT_DISPLAY_MODE`（`'trace'`）、`DISPLAY_MODE_VALUES`、`isValidDisplayMode`    |
| `src/features/chat/displayMode/displayModeStore.ts`            | 会话级 / 消息级覆盖层读写（sessionStorage + 内存 Map）+ 订阅通知                                        |
| `src/features/chat/displayMode/resolveDisplayMode.ts`          | 纯函数 `resolveDisplayMode` + `getDisplayContract` 渲染契约推导                                         |
| `src/features/chat/displayMode/useDisplayMode.ts`              | React hook：订阅全局/会话/消息覆盖，输出有效档位与 setter                                               |
| `src/features/chat/displayMode/globalDisplayModePreference.ts` | 模块级共享 global preference 读取（一次 IPC / app，`sage:setting-changed` 事件 reload）                 |
| `src/features/chat/displayMode/toolGrouping.ts`                | 从 `Message.tsx` 抽取的工具分组判定（`hasSpecialToolCalls` / `canGroupToolCalls` / `toolGroupSummary`） |
| `src/pages/chat/DisplayModeSwitch.tsx`                         | 聊天区顶部档位切换器（手写 menu，`role="menu"` + `role="menuitemradio"`）                               |
| `src/widgets/chat/Message.tsx`                                 | 接入 `useDisplayMode` + `getDisplayContract` 渲染                                                       |
| `src/widgets/chat/ThinkingDisplay.tsx`                         | 思考渲染统一出口：detail/trace 直出 `ThinkingPanel`；result 出合并汇总条 + 一次点击就地展开明细           |
| `src/widgets/chat/ToolGroupToggle.tsx`                         | 从 `Message.tsx` 抽出的工具组折叠条（DOM / testid / 文案原样保留，用于守住架构棘轮）                     |
| `src/features/chat/displayMode/resultSummary.ts`               | 纯函数 `buildResultSummaryText`：result 档汇总条文案随实际隐藏内容变化                                   |
| `src/widgets/chat/MessageMarkdownParts.tsx`                    | `ThinkingPanel` 接受 `mode` + `defaultExpanded` prop                                                    |
| `src/widgets/chat/thinkingExpansionStore.ts`                   | `getThinkingExpanded` 三态查询 + variant key                                                            |
| `src/widgets/chat/messageContextMenu.ts`                       | 「思考展示」submenu（3 checkbox + follow-session）                                                      |
| `src/pages/settings/BasicTab.tsx`                              | 全局默认档位 `<select>`                                                                                 |
| `src/entities/setting/settingsRegistry.ts`                     | 注册 `chat_display_mode`（`enumSetting`, storage=`'preference'`）                                       |
| `src/entities/setting/settingFactories.ts`                     | 从 `settingsRegistry.ts` 抽取的 4 个工厂函数                                                            |
| `src/pages/settings/settingsSearchEntriesChat.ts`              | 从 `settingsSearchEntries.ts` 抽取的聊天搜索条目（含 `chat_display_mode`）                              |
| `src/shared/lib/i18n/locales/{zh,en}/chatDisplayMode.ts`       | 16 个 i18n key（中英文各一份）                                                                          |

### 2.2 数据流

```
                        ┌──────────────────────────────────────────┐
L1 preference ─────────►│                                          │
  (globalDisplayMode     │  useDisplayMode(sessionId, messageId)    │
   Preference.ts)        │        ↓ resolveDisplayMode()            │
L2 sessionStorage ─────►│   effective: DisplayMode                 │
  (displayModeStore)     │        ↓ getDisplayContract()            │
L3 sessionStorage ─────►│   contract: DisplayContract              │
  (displayModeStore)     └──────────────┬───────────────────────────┘
                                       ↓
          ┌────────────────────────────┼────────────────────────────┐
          ↓                            ↓                            ↓
    ThinkingPanel               toolGrouping.ts              Message.tsx
    (defaultExpanded,     (threshold / summary /        (分组条 / 逐卡 /
     autoExpandWhile       special排除)                 思考面板条件渲染)
     Streaming)
```

后端**不参与**：仍流式下发完整 `reasoning_content` 与 `tool_calls`，档位只影响渲染。

## 3. 渲染契约

`getDisplayContract(mode)` 返回 `DisplayContract`，驱动 `Message.tsx` 渲染分支：

| 契约字段                   | `detail` | `trace` | `result` | 说明                                    |
| -------------------------- | -------- | ------- | -------- | --------------------------------------- |
| `showThinkingPanel`        | `true`   | `true`  | `false`  | `result` 模式不渲染独立 `ThinkingPanel` |
| `thinkingDefaultExpanded`  | `true`   | `false` | `false`  | 首次挂载时的思考展开默认值              |
| `autoExpandWhileStreaming` | `true`   | `false` | `false`  | 流式期间是否自动展开思考                |
| `toolGroupThreshold`       | `3`      | `3`     | `1`      | 触发工具分组的最小调用数                |
| `toolGroupDefaultExpanded` | `true`   | `true`  | `false`  | 工具分组条初始展开/折叠                 |
| `toolCardDefaultCollapsed` | `false`  | `true`  | `true`   | 单个工具卡默认展开/折叠                 |

`result` 模式的「隐藏内容可回看」由 `ThinkingDisplay.tsx` 统一实现：不渲染独立 `ThinkingPanel`，
而是渲染一条**合并汇总条**（`data-testid="display-mode-result-summary"`），文案由
`buildResultSummaryText()` 随实际隐藏内容变化：

| 思考被隐藏 | 工具调用被隐藏 | 文案 |
| ---------- | -------------- | ---- |
| 是         | N > 0          | `已隐藏思考过程与 N 步工具调用` |
| 是         | 0              | `已隐藏思考过程` |
| 否         | N > 0          | `已隐藏 N 步工具调用` |

点击汇总条 → `Message.tsx` 的局部 state `resultDetailExpanded` 置真 → `ThinkingPanel`
（`defaultExpanded=true`，**一次点击即可看到思考正文**）与全部工具卡片就地渲染。
result 档下工具卡片的可见性**只认** `resultDetailExpanded`，不沿用 `toolGroupExpanded`
（后者是挂载时契约初值，trace/detail 默认展开；沿用会让切到 result 的已挂载消息继续逐条
显示工具卡片，与汇总条「已隐藏」文案矛盾——验收标准「切换对历史消息立即生效」）。

切回 `detail` 或 `trace` 后思考面板立即可见。

**安全排除（所有档位生效）**：被拦截的调用（`blockReason`）、含图像/媒体引用的调用、产出 artifact 的调用——由 `hasSpecialToolCalls` 判定——**绝不能**被收进汇总条。

## 4. 存储与解析

### 4.1 三级作用域

```
L3 消息级  sessionStorage['sage:display-mode:message:<messageId>']   ← 最高优先
L2 会话级  sessionStorage['sage:display-mode:session:<sessionId>']
L1 全局级  preference['chat_display_mode']（settingsClient → backend preference）
             └─ 缺省 = DEFAULT_DISPLAY_MODE ('trace')
```

### 4.2 sessionStorage 双写

`displayModeStore` 使用内存 Map + sessionStorage 双写：

- 内存 Map：跨组件重挂载（如消息 id 替换）立即生效；
- sessionStorage：跨页面刷新保留（best-effort）。

Key 前缀：`sage:display-mode:session:` 和 `sage:display-mode:message:`。

### 4.3 Store API

```
displayModeStore.getSession(sessionId)   → DisplayMode | null
displayModeStore.setSession(sessionId, mode)
displayModeStore.clearSession(sessionId)
displayModeStore.getMessage(messageId)   → DisplayMode | null
displayModeStore.setMessage(messageId, mode)
displayModeStore.clearMessage(messageId)
displayModeStore.clearAll()
```

每次写操作调用 `emit()` → 递增 `version` + 通知所有 listener → 触发 `useSyncExternalStore` 消费者重渲染。

### 4.4 全局默认：共享单次读取

`globalDisplayModePreference.ts` 实现模块级 singleton：

- `snapshot: DisplayMode` + `loaded: boolean` + `inflight: Promise<void> | null`；
- 首次订阅时 `settingsClient.getPreferenceStrict('chat_display_mode')` 一次 IPC 读取；
- 监听 `sage:setting-changed` 自定义事件；`detail.key === 'chat_display_mode'` 时重新 IPC 读取并通知所有消费者；
- `subscribeGlobalDisplayMode` 首次调用时触发懒加载（`ensureWired` + `load`），后续调用直接返回当前快照；
- IPC 去重：`inflight` Promise 确保并发订阅不发起多次读取；
- 失败降级：IPC 失败时保留上一次有效快照（首次为 `DEFAULT_DISPLAY_MODE`），并且**不置 `loaded`**——
  下一个订阅者（新消息挂载 / 页面重挂载）或 `sage:setting-changed` 事件会再次触发读取。
  否则后端冷启动晚于聊天页挂载时，本会话会永久停留在默认档位。
  不引入重试定时器：模块级挂起的定时器会污染消费方的全局定时器语义（如复制复位定时器的卸载断言），
  而订阅触发已覆盖实际自愈路径。

## 5. 展开状态语义

### 5.1 三态查询

`thinkingExpansionStore` 新增 `getThinkingExpanded(key): boolean | undefined`：

- `undefined` → 用户从未操作，应使用 `defaultExpanded`（来自档位契约）；
- `true` / `false` → 用户显式展开/折叠，应**始终遵守**。

`ThinkingPanel` 初始化：

```
1. 显式值存在（getThinkingExpanded(variantKey) !== undefined）→ 用显式值
2. 否则 → 用 defaultExpanded（来自档位契约）
```

### 5.2 Variant key

`` variantKey = `${mode}:${thinkingExpansionKey(reasoning)}` ``

其中 `thinkingExpansionKey(reasoning) = \`${reasoning.length}-${hashText(reasoning)}\``。

不同档位各自独立记忆展开状态：在 `detail` 展开思考，切到 `trace` 时默认折叠，切回 `detail` 时恢复展开。避免"切档位冲掉手动操作"的困惑。

### 5.3 档位切换重置

`ThinkingPanel` 内 `prevModeRef` + `useEffect` 实现 ref-gated 重置：

- 仅 `prevModeRef.current !== mode`（档位真正变化）时重新读取 variant key 的存量展开态；
- 流式 delta 导致 `variantKey` 变化（reasoning 增长 → hash 变化）时**不**触发重置。

## 6. UI 入口

### 6.1 聊天区顶部档位切换器

`src/pages/chat/DisplayModeSwitch.tsx`，挂载于 `ChatHeaderBar.tsx` 的 `SessionSettingsMenu` 之前。

- 触发按钮：`Brain` 图标（lucide-react）+ 当前档位标签 + `ChevronDown`；
- `aria-label="${t('chat.displayMode.label')} · ${t(MODE_LABELS[mode])}"`；
- 点击展开手写下拉菜单（`role="menu"`）；
- 三个 `role="menuitemradio"` 项（详细思考 / 仅执行 / 仅结果），当前档位 `aria-checked={true}`；
- 分隔线后第四项「跟随全局默认」（`clearSessionMode()`，清除会话级覆盖）；
- 切换 → `displayModeStore.setSession()` → store `emit()` → 所有已挂载 `useDisplayMode` 消费者重渲染。

### 6.2 消息右键菜单 submenu

`src/widgets/chat/messageContextMenu.ts` 在助手消息菜单中（`if (isAssistant)`）添加 `display-mode-submenu`，位于 `save-to-memory` 之后、`onDelete` 之前。

- submenu 标签：`t('chat.displayMode.label')`（中文「思考展示」/ 英文「Reasoning display」）；
- 4 个 `kind: 'checkbox'` 项：
  - `display-mode-detail` / `display-mode-trace` / `display-mode-result`：勾选写 `displayModeStore.setMessage(message.id, mode)`；
  - `display-mode-follow-session`：调用 `displayModeStore.clearMessage(message.id)`；
- follow-session 标签：会话有覆盖时显示 `「跟随会话 (${会话档位标签})」`，无覆盖时回落 `「跟随全局默认」`；
- `checked` 状态在每次菜单打开时从 `displayModeStore` 重新读取（`buildContextMenuItems` 在 `ContextMenu` 的 `items` prop 中为函数式求值）。

### 6.3 设置页全局默认

`src/pages/settings/BasicTab.tsx`，`anchor="chat_display_mode"`，位于 streaming toggle 之后，在 `settings.basic.appearance` 分组内。

- 使用 `useConfirmedPreference<DisplayMode>` 读写 preference；
- `<select>` 三个 `<option>`（`detail` / `trace` / `result`），标签取 `chat.displayMode.*`；
- 写入 → 后端 `setPreferenceStrict` 广播 `sage:setting-changed` → 前端 `globalDisplayModePreference.ts` 监听并重读 → **当前窗口**立即更新；
  其他窗口不订阅该 DOM 事件（`settingsClient.notifyPreference` 只在当前窗口 `dispatchEvent`），需在下次读取（重挂载/重载）后生效。

## 7. 架构约束

### 7.1 三个零余量文件

| 文件                       | 基线   | 处理方式                                                                                                                               |
| -------------------------- | ------ | -------------------------------------------------------------------------------------------------------------------------------------- |
| `Message.tsx`              | 807 行 | 抽取 `toolGrouping.ts`（`hasSpecialToolCalls` / `canGroupToolCalls` / `toolGroupSummary`），净减 ~26 行                                |
| `settingsRegistry.ts`      | 812 行 | 抽取 `settingFactories.ts`（`booleanSetting` / `numberSetting` / `enumSetting` / `orchNumber`），净减 ~73 行                           |
| `settingsSearchEntries.ts` | 847 行 | 抽取 `settingsSearchEntriesChat.ts`（4 条目：`streaming` / `inputHistorySize` / `attachment_rag` / `chat_display_mode`），净减 ≥ 40 行 |

### 7.2 "永远不抬基线" 规则

`architecture-baseline.json` 锁定三个文件的最大行数。超过即 CI Architecture 红。

- 新增功能**必须抽取**而非内联；
- prettier 折行可能静默 +1 行（历史教训）——提交前跑 `node scripts/architecture-check.mjs`；
- 必要时压回单行而非抬基线。

### 7.3 抽取模式

- 抽出的模块保持行为等价（先写单测锁住旧行为再改）；
- 原文件 `import` + re-export，对外 API 不变（如 `settingFactories.ts` 由 `settingsRegistry.ts` re-export）；
- 新文件无自己的行数棘轮问题（远低于 800 行上限）。

## 8. 后端契约

### 8.1 `SettingsRepository.KEYS` 白名单

`backend/data/settings_repo.py` 第 115 行包含 `"chat_display_mode"`。

`SettingsRepository` 以白名单验证 preference 键——不在名单中的键写入返回 HTTP 400。
本次新增的 `chat_display_mode` 必须在此白名单中，否则全局默认档位写入静默失败。

### 8.2 前端写入路径

前端通过 `preference` 存储（`settingsClient.getPreferenceStrict` / `setPreferenceStrict`）读写。

`settingsRegistry.ts` 中 `chat_display_mode` 的 `storage: 'preference'` 确保设置页走正确路径。

### 8.3 win7 同步注意

cherry-pick 到 `release/win7` 时**必须携带** `backend/data/settings_repo.py` 的 `chat_display_mode` 白名单行。
否则 win7 分支的全局默认档位写入 400，设置永不生效。

## 9. 测试与验证

### 9.1 测试覆盖

| 测试文件                            | 覆盖范围                                                                                             |
| ----------------------------------- | ---------------------------------------------------------------------------------------------------- |
| `displayMode.test.ts`（types 内联） | `isValidDisplayMode` 合法/非法值                                                                     |
| `resolveDisplayMode.test.ts`        | 三级优先级、非法值回落 `DEFAULT_DISPLAY_MODE`、`getDisplayContract` 三档完整断言                     |
| `displayModeStore.test.ts`          | getSession/setSession/clearSession、getMessage/setMessage/clearMessage、subscribe + emit 通知        |
| `useDisplayMode.test.tsx`           | re-render on setSession/setMessage、shared global store 单次读取、`sage:setting-changed` 事件 reload |
| `toolGrouping.test.ts`              | `hasSpecialToolCalls` 排除、`canGroupToolCalls` 阈值 3/3/1、`toolGroupSummary` 文案                  |
| `ThinkingPanel.test.tsx`            | variant key 分档位记忆、`autoExpandWhileStreaming` 门控、ref-gated 重置                              |
| `thinkingExpansionStore.test.ts`    | `getThinkingExpanded` 三态（undefined/true/false）、显式优先于默认                                   |
| `DisplayModeSwitch.test.tsx`        | 打开/关闭菜单、session override set + aria-checked、follow-global clears override                    |
| `ChatHeaderBar.p172.test.ts`        | `topHeaderControls` 治理 tuple 5→6                                                                   |
| `messageContextMenu.test.ts`        | submenu shape、store integration、follow-session label                                               |
| `resultSummary.test.ts`             | `buildResultSummaryText` 四种隐藏组合文案（真值取自 zh 词典）                                        |
| `Message.displayMode.test.tsx`      | result 档汇总条折叠 / 一次点击展开、特殊调用不被藏、trace 档不变、切档位对已挂载消息立即生效          |

### 9.2 验证命令

```bash
npx vitest run                              # 全量前端测试
node scripts/architecture-check.mjs          # 架构行数检查
npm run typecheck                            # TypeScript 类型检查
npm run verify:pre-push                      # eslint + architecture-check
```

### 9.3 冒烟矩阵

3 档位 × (流式中 / 流式后 / 历史消息) × (有工具 / 无工具 / 有特殊工具) = 27 组合。

## 10. 已知边界与后续

### 10.1 无服务端持久化

会话级与消息级 override 存于 sessionStorage，关闭浏览器窗口/Electron renderer 后丢失。
全局默认存于后端 preference，跨窗口保留。这是有意的 YAGNI 决策（计划 §5.3）。

### 10.2 切换档位时单帧闪烁

`useEffect` 在 paint 后执行 `setIsExpanded`，可能导致一帧视觉跳动（trace→detail 切换时
思考面板先以折叠态渲染再展开）。cosmetic，已 parked。

### 10.3 ContextMenu 的 checked 状态刷新时机

`buildMessageContextMenuItems` 在每次菜单打开时调用（`ContextMenu` 的 items 为函数式求值），
因此 checked 状态在 re-open 时自动更新。但已打开的菜单不会实时刷新——需关闭后重开。

### 10.4 手写菜单的 a11y 局限

`DisplayModeSwitch` 使用手写 `<div role="menu">` 而非 Radix DropdownMenu。
已提供 `aria-haspopup` / `aria-expanded` / `aria-checked` / `role="menuitemradio"`，
但缺少 Radix 提供的 roving focus、Escape 关闭等完整键盘语义。已 parked（LOW）。

### 10.5 `result` 档明细展开状态在档位切换间保留

`resultDetailExpanded` 是消息组件本地 state：在 result 档展开明细后切到其他档位再切回，
仍保持展开。这是有意行为——避免档位切换冲掉用户的手动操作（与 `thinkingExpansionStore`
分档位记忆展开态的取向一致）。

### 10.6 消息级条目的内存积累

`displayModeStore` 的内存 Map 中消息级条目在 `clearMessage` 前始终存在。
已被 GC 的消息（如切换会话）的条目仍占 Map 空间，但体量极小（每条 ~100B），
实际可忽略。`clearAll()` 可在会话切换时主动调用。
