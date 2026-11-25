# Composer 状态条（会话观测指标下沉）

> 2026-11-25。把原先占据顶栏与齿轮菜单的「用量统计 / 响应速度统计 / 上下文统计」三块观测指标下沉到输入框下方的一条状态条，与空会话引导语同位互斥。纯前端改动，后端 `/api/v1/usage/session/{id}` 口径不变。

---

## 1. 背景

下沉前这三块指标分散在三处，且存在两类结构性问题：

| 问题 | 表现 |
|------|------|
| 语义错位 | 「本会话累计用量」「上下文占用」属于会话运行态指标，却与"对话标题 / 工作区切换 / 模型选择"等导航配置控件同处顶栏；顶栏是全局操作区，不是数据观测区 |
| 取数重复 | `SessionUsageBadge` 与 `ContextMeter` 各自调用 `fetchSessionUsage(sessionId)`，同一会话同一接口请求两次，轮询周期各自为政 |
| 刷新口径不一致 | 只有 `ContextMeter` 在流式结束时补拉；一轮对话结束后，用量 / 延迟数字仍停留在上一次轮询的旧值 |
| 明细不可读 | 用量明细塞在原生 `title` tooltip 里（平均 / P95 / 最慢 + 分模型），既无法排版也无法完整阅读 |

对标 Claude Code / Cursor / ChatGPT / DeepSeek 的 composer footer 惯例，观测指标归输入区、配置控件归顶栏、摘要单行 + 明细 popover。

---

## 2. 组件结构与数据流

```
src/pages/Chat.tsx
  └─ <ChatInput isEmptySession={messages.length === 0} />
       └─ src/widgets/chat/ChatInput.tsx
            │  statusSlot = useMemo(
            │    () => isEmptySession ? undefined : <ComposerStatusBar sessionId={effectiveSessionId} />
            │  )                       ← memo 组件（InputCard/ChatInput 均为 memo），
            │                            slot 必须稳定引用，否则每次渲染都重建子树
            └─ <InputCard statusSlot={statusSlot} hint={isEmptySession ? t('chat.hint') : undefined} />
                 └─ src/widgets/chat/InputCard.tsx 页脚行
                      ├─ 左：statusSlot ?? hint（二选一，互斥）
                      └─ 右：字数计数（既有 chat-char-count）
                           └─ <ComposerStatusBar sessionId />   ← 新增
                                ├─ useSessionUsage(sessionId)     ← 唯一取数入口
                                ├─ <SessionUsageBadge usage={usage} />          （受控）
                                └─ <ContextMeter usage={usage} placement="top" align="right" /> （受控）
```

新增文件：

| 文件 | 职责 |
|------|------|
| `src/widgets/chat/ComposerStatusBar.tsx` | 组合单行状态条：左 = 用量徽章，右 = 上下文条；两者都无数据时整体不渲染 |
| `src/widgets/chat/hooks/useSessionUsage.ts` | 统一取数：一次请求同时供给用量与上下文，承载轮询与流末刷新 |

### 2.1 与会话内嵌 `composerControls` 槽位的关系

`InputCard` 早已预留 `composerControls` 槽位（发送键左侧的按钮位）。本次**不复用**它，另起 `statusSlot`：前者语义是"输入框内右下角按钮"，本需求是"输入框下方整行"，形态与布局归属不同，混用会让职责含糊。

---

## 3. `useSessionUsage(sessionId)` 行为契约

| 场景 | 行为 |
|------|------|
| `sessionId` 变化 | 先作废在途请求并清空旧值（避免显示上一会话的数字），再立即拉取 |
| 空闲会话 | 只拉取一次，**不轮询**（无意义的周期刷新被去掉） |
| 流式进行中 | 60s 兜底轮询（覆盖长回答期间的累计量增长） |
| 流式结束（`streaming.messageId` 非空 → null 跳变） | **立即补拉一次**：本轮最终的 token / 成本 / 延迟只有此刻才准确 |
| 旧请求迟到 | 请求序号守卫（`requestSeqRef`）：只有最后一次请求的结果可以落地，旧会话的在途响应不覆盖新会话 |
| 请求失败 | 静默：保留上一次的值、不抛错、不打断输入（状态条是增强信息） |
| `sessionId` 为 null | 不请求，`usage` 保持 null |

流式状态取自 `useChatStreamStore` 的 `selectSessionSlots(state, sessionId).streaming?.messageId`。`SessionModelPicker` 内部的一次性 `fetchSessionUsage` 调用保持独立，不并入本 hook（模型选择器需要自己的最新值）。

---

## 4. 受控化改造

| 组件 | 改造前 | 改造后 |
|------|--------|--------|
| `SessionUsageBadge` | 自取数 + 自轮询 | 受控：`usage: SessionUsage \| null` prop；`requests === 0` 时返回 null；点击展开明细 popover（替代原生 title），`formatSessionUsageMarkdown` / `formatSessionUsageJson` 导出保持不变 |
| `ContextMeter` | 自取数 | 受控：`usage` prop；新增 `placement?: 'top' \| 'bottom'`（默认 `top`）与 `align?: 'left' \| 'right'`（默认 `right`）；`last_prompt_tokens == null` 时返回 null；`ContextSourceList` / `auditContextMeterGovernance` 导出保持不变 |

### 4.1 弹层方向

上下文条锚定在状态条**右端**，所以改为向上展开（`bottom-full mb-2`）同时保持右缘对齐（`right-0`）：宽度 320px（`w-80`）的弹层以锚点右缘为界向左铺开，正好落在视口内。若改成左缘对齐（`left-0`），弹层会从锚点向右伸出约 170–224px，溢出视口右缘 —— 这就是 `align` 默认保持 `right` 的原因。`ContextMeter` 在齿轮菜单时期的 `placement="bottom"` 场景由 `placement`/`align` 两个 prop 继续支持（测试覆盖）。

### 4.2 治理审计保留

顶栏移除徽章、齿轮菜单移除上下文块后，治理审计导出（`auditChatHeaderBarGovernance` P172、`auditContextMeterGovernance` P186、`auditSessionUsageBadgeGovernance` P194、`auditInputCardGovernance` P193）全部保留，符号名不变，避免其他模块 import 断裂。

---

## 5. 引导语互斥策略

- `Chat.tsx` 显式传 `isEmptySession={messages.length === 0}`（数据流单向、可测，不在 `ChatInput` 内隐式读 store）。
- `ChatInput.isEmptySession` 默认 `true`：所有旧调用方与既有测试无需改动，行为保持"显示引导语"。
- 空会话 → 页脚显示 `chat.hint` 原文案（i18n 未改）；有消息 → `statusSlot` 接管同一行，`hint` 让位。两者互斥、不并存。
- 有消息但尚无任何用量数据（`requests === 0` 且无上下文快照）时，`ComposerStatusBar` 返回 null，页脚该行留空，不渲染空壳。

---

## 6. 状态条内容与响应式

左起：`💰 {tokens} tok · ${cost}`（含缓存命中率 `🎯 N%`、平均响应 `⚡ Ns` 段）→ 右端：上下文占用条 + 百分比。

- 缓存命中率段仅在发生过缓存交互（read + creation > 0）时显示；平均 > 10s 时用 `text-warning`。
- 窄屏折叠沿用徽章既有断点：token 段 `hidden sm:inline`，缓存段 `hidden lg:inline`。
- 字号一律用既有 token `text-ui-2xs`（`text-[Npx]` 被 `scripts/check-font-scale.mjs` 门禁禁止）。
- 布局约束：`flex min-w-0 flex-1` + `justify-between`，不换行、不溢出。

---

## 7. 测试

| 文件 | 覆盖点 |
|------|--------|
| `src/widgets/chat/hooks/__tests__/useSessionUsage.test.tsx` | 空闲只拉一次不轮询；流中 60s 轮询、流末补拉并清表；切换会话先清空、迟到旧响应不覆盖；`sessionId=null` 不取数；失败静默保留旧值 |
| `src/widgets/chat/__tests__/ComposerStatusBar.test.tsx` | 无数据不渲染；有累计量渲染徽章 + 上下文条且 hook 收到正确 sessionId；仅有上下文快照时只渲染上下文条；弹层向上 + 右缘对齐 |
| `src/widgets/chat/__tests__/SessionUsageBadge.test.tsx` | 受控夹具：null / requests 0 不渲染；token + 成本格式；popover 开启关闭；缓存段条件显示；Markdown/JSON 导出 |
| `src/widgets/chat/__tests__/ContextMeter.test.tsx` | 受控夹具：空态；百分比与告警色；title 明细；分类弹层与堆叠条；`placement`/`align` 四向断言；无明细回退提示 |
| `src/widgets/chat/__tests__/ContextMeter.sources.test.tsx` | 来源四态与不可追溯提示（改为直接传夹具，不再 mock usageApi） |
| `src/pages/__tests__/chatHeaderMenus.test.tsx` | 齿轮菜单只含权限模式（`ContextMeter` stub 保留为回归护栏：若有人重新引入浮层，「不存在」断言立即失败） |

删除的旧测试：`SessionUsageBadge.active.test.tsx`、`ContextMeter.active.test.tsx` —— 其 60s 轮询门控关注点合并进 `useSessionUsage.test.tsx`。

门禁：`npm run test:run`、`npx tsc --noEmit`、`npm run lint`、`scripts/check-font-scale.mjs`、`scripts/count-lines.sh`、`scripts/architecture-check.mjs`。

---

## 8. 本轮明确不做

| 项 | 原因 |
|----|------|
| 移动 `SessionModelPicker` / `PermissionModeSwitch` / `SessionIdBadge` | 属配置与导航控件，观测指标才是本轮下沉对象 |
| 改后端口径 | 纯前端布局调整，`/api/v1/usage/session/{id}` 返回结构与算法不变 |
| 清理 `ContextPressureBadge` | 死代码清理属独立议题，不夹带 |
| 状态条点击复制 Markdown / 上下文阈值变色 / P50 延迟 | 后续可选项；实施后本计划文件删除，相关内容以此章节为准 |
