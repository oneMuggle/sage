# 主会话布局优化：统计条下沉到输入框下方

> 日期：2026-11-24
> 状态：方案已评审（待实施）
> 触发：用户反馈主会话顶部"用量统计 / 响应速度统计 / 上下文统计"占据宝贵空间，应参考主流 AI 应用下沉到输入框下方
> 范围：仅前端布局与前端取数逻辑（不含后端口径变更）
> 分支：`docs/chat-composer-status-bar`（本轮仅方案，实施另开 feat 分支）

---

## 一、背景与目标

### 1.1 现状盘点

| 统计项 | 当前承载组件 | 当前位置 | 源码位置 |
|--------|--------------|----------|----------|
| 用量统计（token / 成本） | `SessionUsageBadge`（与响应速度同组件） | 顶栏左侧 | `src/widgets/chat/SessionUsageBadge.tsx:134`；挂载于 `src/pages/chat/ChatHeaderBar.tsx:69` |
| 响应速度统计（平均延迟 / 缓存命中率） | 同上（同一 badge 的第 2、3 段） | 顶栏左侧 | `src/widgets/chat/SessionUsageBadge.tsx:103-124` |
| 上下文统计（占用条 / 百分比） | `ContextMeter` | 顶栏右侧齿轮菜单 `SessionSettingsMenu` 内 | `src/pages/chat/SessionSettingsMenu.tsx:62-65`；组件 `src/widgets/chat/ContextMeter.tsx` |
| 引导语（"Sage 会记住你的项目信息…"） | i18n `chat.hint` | 输入框下方居中 | `src/shared/lib/i18n/locales/zh/chatAndSider.ts:160-161`；渲染于 `src/widgets/chat/InputCard.tsx:691-703`，由 `src/widgets/chat/ChatInput.tsx:968` 传入 |

补充事实：用量统计与响应速度统计在代码上是**同一个组件** `SessionUsageBadge`（一个 badge 内渲染三段：`💰 {tokens} tok{cost}` · `🎯 {hitRatePct}%` · `⚡ {avgLatencySec}s`），因此本次下沉实际涉及**两个渲染载体**（badge + meter），不是三个独立组件。

### 1.2 问题诊断

| 编号 | 问题 | 说明 |
|------|------|------|
| P1 | **语义错位** | 「上下文占用」「本会话累计用量」属于**会话运行态**指标，与用户此刻正在输入的内容强相关；放在顶栏（与"对话标题 / 工作区切换 / 模型选择"等**导航与配置**控件同层）语义不对等，且顶栏是全局操作区，不是数据观测区。 |
| P2 | **顶栏拥挤** | 顶栏左区当前 5 项（对话标题 / WorkspaceSwitcher / WorkspaceBranchPicker / SessionUsageBadge / SessionIdBadge），`flex-wrap` 下窄窗口会换行，把纵向空间进一步压缩。 |
| P3 | **取数重复** | `SessionUsageBadge` 与 `ContextMeter` 各自独立调用 `fetchSessionUsage(sessionId)`，同一个会话、同一个接口被请求两次，轮询周期也各自为政。 |
| P4 | **刷新口径不一致** | `ContextMeter` 在**流式结束**时（`streamingMessageId` 由非空变空）会重新拉取；`SessionUsageBadge` 没有该逻辑，导致一轮对话结束后，用量数字仍停留在上一次轮询的旧值。 |
| P5 | **载体不匹配** | 用量明细目前只能通过 `title` 原生 tooltip 查看（`SessionUsageBadge.tsx:133`），信息量（平均/P95/最慢延迟 + 分模型明细）在原生 tooltip 中既不可读也无法排版。 |
| P6 | **弹层方向将失效** | `ContextMeter` 当前 `placement="bottom"`（弹层向下展开），在齿轮菜单内向下展开是正确的；一旦下沉到输入框底部，弹层必须改为**向上**展开，且水平方向需从 `right-0` 改为左对齐，否则会溢出视口右缘。 |

### 1.3 目标

1. 把「用量统计」「响应速度统计」「上下文统计」三块统一收纳到**输入框正下方**的一条状态条中。
2. 空会话时该位置显示**引导语**（保留原文案），有消息后由状态条接管该行 —— 两者互斥，不再同时出现。
3. 视觉与交互参考主流 AI 应用（Claude Code / Cursor / ChatGPT / DeepSeek）的 composer 底部状态区惯例。
4. 顺带消除 P3 取数重复与 P4 刷新口径不一致。
5. 顶栏回归"导航 + 配置"单一职责。

### 1.4 非目标（本轮明确不做）

| 不做的事 | 原因 |
|----------|------|
| 不移动 `SessionModelPicker`（模型选择） | 模型选择是**配置**动作，本轮仅下沉**观测类**指标，模型选择留在顶栏避免与权限档位产生新耦合 |
| 不动 `PermissionModeSwitch`（权限档位） | 同上，属配置控件 |
| 不动 `SessionIdBadge` | 会话标识是导航信息，不属于观测指标 |
| 不改后端用量统计口径 | 本次是纯前端布局调整，`/api/v1/usage/session/{id}` 返回结构与算法保持不变 |
| 不清理 `ContextPressureBadge` | 经核查为**死代码**（仅有自测引用，无生产调用），清理属独立议题，本轮不夹带 |

### 1.5 既有可复用资产（重要）

`src/widgets/chat/InputCard.tsx:156-159` 已存在一个**未被使用**的扩展槽位：

```tsx
/**
 * UX-IA R1 批次 D：输入框右下角的会话控件（模型、上下文占用、权限档位），
 * 渲染在发送/停止按钮左侧，对标 ChatGPT / Claude 的 composer 布局。
 */
composerControls?: React.ReactNode;
```

说明仓库**早已预留**了"composer 底部控件区"这一设计位，本次下沉属于把该设计位落到实处，而非引入新范式。

---

## 二、主流 AI 应用对标

| 产品 | 统计类信息位置 | 形态 | 与输入框关系 |
|------|----------------|------|--------------|
| Claude Code | 输入框下方（composer 底部） | 单行紧凑文字 + hover 展开 | 占据原本"提示/快捷键提示"的同一行 |
| Cursor | 输入框下方 | 左侧 token/上下文占用，右侧模型与模式 | 与 composer 同容器，独立于顶部工具栏 |
| ChatGPT | 输入框下方 | 上下文/字数提示，仅在接近上限时显示 | 顶栏无任何统计 |
| DeepSeek / Kimi / 豆包 | 输入框下方 | 模型名 + 上下文占用百分比 | 顶栏仅标题 |

**共性规律三条**：

1. **观测指标归 composer**，配置控件归顶栏 —— 顶栏保持"我在哪个会话 / 用哪个模型 / 什么权限"的稳定心智。
2. **状态条与提示语同位互斥** —— 空闲态是"教学提示"，工作态是"运行指标"，不并存。
3. **明细走 popover，摘要走单行** —— 摘要必须一行读完，明细才展开。

---

## 三、方案设计

### 3.1 布局前后对比

**Before（现状）**

```
┌──────────────────────────────────────────────────────────────┐
│ 对话  [工作区▾] [分支▾]  💰 12.3k tok$0.05 · 🎯 68% · ⚡ 2.1s  #a1b2   [👥][模型▾][权限][⋯][面板]│  ← 顶栏拥挤
├──────────────────────────────────────────────────────────────┤
│                                                              │
│                    （消息列表）                              │
│                                                              │
├──────────────────────────────────────────────────────────────┤
│ ┌──────────────────────────────────────────────────────┐   │
│ │ 输入区                                              │   │  ← px-4 py-2.5
│ └──────────────────────────────────────────────────────┘   │
│        Sage 会记住你的项目信息，无需重复说明上下文 · …      │  ← 引导语独占一行
└──────────────────────────────────────────────────────────────┘
```

**After（目标）**

```
┌──────────────────────────────────────────────────────────────┐
│ 对话  [工作区▾] [分支▾]  #a1b2   [👥][模型▾][权限][⋯][面板]│  ← 顶栏回归导航+配置
├──────────────────────────────────────────────────────────────┤
│                                                              │
│                    （消息列表）                              │
│                                                              │
├──────────────────────────────────────────────────────────────┤
│ ┌──────────────────────────────────────────────────────┐   │
│ │ 输入区                                              │   │
│ └──────────────────────────────────────────────────────┘   │
│ 💰 12.3k tok $0.05  🎯 68%  ⚡ 2.1s      上下文 ▓▓▓░░ 42%  128/8000 │  ← 状态条
└──────────────────────────────────────────────────────────────┘
```

空会话时（`messages.length === 0`）最后一行显示引导语原文案，其余完全相同。

### 3.2 状态条规格

单行、左右分布，与 composer 同宽（继承 `px-4`），字号用既有 token `text-ui-2xs`（**禁止** `text-[Npx]`，见 §五 门禁）。

| 位置 | 内容 | 视觉 | 交互 |
|------|------|------|------|
| 左一 | `💰 {total_tokens} tok {estimated_cost}` | `text-muted`，成本存在时显示 `$` | 点击 → popover 用量明细 |
| 左二（次级） | `🎯 {cache_hit_rate}%` 缓存命中率 | 更弱的 `text-muted`，可折叠 | 随 popover 一起 |
| 左三 | `⚡ {avg_latency}s` 平均响应 | 平均 > 10s 时 `text-warning` | 点击 → popover 延迟明细（平均/P95/最慢 + 分模型） |
| 右一 | 上下文占用 `▓▓▓░░ 42%` | 进度条 + 百分比 | 点击 → 展开分类明细（沿用 `ContextMeter` 的 8 类 breakdown） |
| 右二 | 字数 `128 / 8000` | 超过硬上限 `text-error` | 无（沿用现有 `chat-char-count`） |

约束：状态条**一行不换行**（`flex-nowrap` + `min-w-0` + `truncate`），窄窗口按 §3.6 折叠。

### 3.3 顶栏变化

| 位置 | 现状 | 变更后 |
|------|------|--------|
| 左区 | 对话标题 / WorkspaceSwitcher / WorkspaceBranchPicker / **SessionUsageBadge** / SessionIdBadge | 对话标题 / WorkspaceSwitcher / WorkspaceBranchPicker / SessionIdBadge（**移除 SessionUsageBadge**） |
| 右区 | SessionParticipantsStrip / SessionModelPicker / 权限档位 / DisplayModeSwitch / 提取待办 / SessionSettingsMenu / SessionSessionMenu / RightPanelToggle | 不变 |
| 齿轮菜单 | 权限档位 + **上下文用量(ContextMeter)** | 仅保留权限档位（**移除上下文用量块**） |

> 顶栏移除的 badge/计量器，其治理审计导出（`auditChatHeaderBarGovernance` P172、`auditSessionUsageBadgeGovernance` P194、`auditContextMeterGovernance` P186）**必须保留**，审计实现迁至新组件，不得因 UI 搬迁而删除。

### 3.4 引导语策略（已确认：空会话才显示）

- **判定**：会话无消息（`messages.length === 0`）时显示引导语；一旦有消息，状态条接管该行。
- **传参方式（推荐 a）**：由 `Chat.tsx` 显式传入 `isEmptySession` prop。

  | 方案 | 做法 | 评价 |
  |------|------|------|
  | (a) ✅ 显式 prop | `Chat.tsx` 已持有 `messages`，直接传 `isEmptySession={messages.length === 0}` 到 `ChatInput` | 数据流单向、可测、无隐藏耦合；**推荐** |
  | (b) 组件内读 store | `ChatInput` 内部 `useChat()` 读 messages | 隐式依赖，测试需 mock store，且 `ChatInput` 与 `Chat.tsx` 双份消息来源 |

- **文案**：保留 `chat.hint` 原文案不动（`zh` / `en` 均不改），避免 i18n 波及面扩大。

### 3.5 弹层与方向修正

| 组件 | 现状 | 变更后 |
|------|------|----------|
| `ContextMeter` | `placement="bottom"`，容器 `absolute right-0 z-50 w-80` | 新增 `align?: 'left' \| 'right'`（默认 `right` 保持向后兼容），下沉场景传 `align="left"`；`placement` 传 `"top"` 使弹层向上展开 |
| 用量/延迟明细 | 仅原生 `title` tooltip（P5） | 新增受控 popover，复用 `SessionUsageBadge` 已导出的 `formatSessionUsageMarkdown(usage)` 生成 Markdown 明细；`formatSessionUsageJson` 保留导出不变 |

弹层向上展开时需确认不与 `TerminalPanel` 等 z-index 更高的浮层冲突（见 §七 R6）。

### 3.6 响应式折叠

| 视口宽度 | 状态条形态 |
|----------|-----------|
| ≥ 1024px | 全量：用量 / 命中率 / 延迟 / 上下文 / 字数 |
| 640–1023px | 隐藏缓存命中率段（次级信息），保留用量 / 延迟 / 上下文 / 字数 |
| < 640px | 上下文折叠为 `▓▓░ 42%`（去掉分类弹层，改为点击提示）；仅保留 `⚡ 2.1s` 与字数 |

---

## 四、技术方案

### 4.1 组件结构

```
src/pages/Chat.tsx
  └─ <ChatInput sessionId={currentSessionId} isEmptySession={messages.length === 0} />
       └─ src/widgets/chat/ChatInput.tsx
            └─ <InputCard statusSlot={...} hint={isEmptySession ? t('chat.hint') : undefined} />
                 └─ src/widgets/chat/InputCard.tsx
                      └─ <ComposerStatusBar sessionId={sessionId} />   ← 新增
```

新增文件：

| 文件 | 职责 |
|------|------|
| `src/widgets/chat/ComposerStatusBar.tsx` | 渲染单行状态条（用量 / 命中率 / 延迟 / 上下文 / 字数），组合子组件与 popover |
| `src/widgets/chat/hooks/useSessionUsage.ts` | 统一取数：一次 `fetchSessionUsage` 供用量与上下文共用，承载轮询与流末刷新 |

### 4.2 `useSessionUsage(sessionId, refreshKey?)` 行为约定

| 场景 | 行为 |
|------|------|
| `sessionId` 变化 | 立即拉取 |
| `refreshKey` 变化 | 立即拉取（供上层强制刷新用） |
| 流式进行中 | 60s 轮询（沿用 `SessionUsageBadge` 现状） |
| **流式结束** | **立即拉取**（新增，对齐 `ContextMeter` 现状，修复 P4） |
| 请求失败 | 静默失败，不抛错、不打断输入（沿用现状） |
| 无 `sessionId` | 不请求，渲染占位 |

`SessionModelPicker.tsx:300` 处既有的**一次性** `fetchSessionUsage` 调用**保持不变**（模型选择器需要独立的最新值，不纳入共享 hook）。

### 4.3 改造清单

| # | 文件 | 动作 | 详情 |
|---|------|------|------|
| 1 | `src/widgets/chat/ComposerStatusBar.tsx` | 新增 | 状态条主组件 |
| 2 | `src/widgets/chat/hooks/useSessionUsage.ts` | 新增 | 共享取数 hook |
| 3 | `src/widgets/chat/InputCard.tsx` | 改 | 新增 `statusSlot?: React.ReactNode` prop；页脚行改为「左：statusSlot 或 hint，右：字数计数」；`hint` 允许为空 |
| 4 | `src/widgets/chat/ChatInput.tsx` | 改 | 新增 `sessionId?: string \| null`、`isEmptySession?: boolean` prop；`hint` 仅在 `isEmptySession` 为真时传 |
| 5 | `src/pages/Chat.tsx` | 改 | 向 `ChatInput` 传 `sessionId` 与 `isEmptySession` |
| 6 | `src/pages/chat/ChatHeaderBar.tsx` | 改 | 移除 `<SessionUsageBadge>`；保留 `auditChatHeaderBarGovernance` |
| 7 | `src/pages/chat/SessionSettingsMenu.tsx` | 改 | 移除「上下文用量」块；保留权限档位 |
| 8 | `src/widgets/chat/SessionUsageBadge.tsx` | 改 | 降级为状态条内的**纯展示**子组件（去掉自取数与轮询），改用 `useSessionUsage` 注入的 props；保留 `formatSessionUsageMarkdown` / `formatSessionUsageJson` / `auditSessionUsageBadgeGovernance` 导出 |
| 9 | `src/widgets/chat/ContextMeter.tsx` | 改 | 去掉自取数，改为受控（`usage` prop）；新增 `align` prop；`placement` 支持 `"top"`；保留 `ContextSourceList` / `auditContextMeterGovernance` 导出 |
| 10 | `src/widgets/chat/ChatInput.tsx` | 改 | `composerControls` 已有槽位**不复用**，另起 `statusSlot`（`composerControls` 语义是"发送键左侧的按钮"，本需求是"输入框下方整行"，形态不同） |
| 11 | `src/shared/lib/i18n/locales/zh/chatAndSider.ts` | 改 | 新增 4 个 key（见 §4.4） |
| 12 | `src/shared/lib/i18n/locales/en/chatAndSider.ts` | 改 | 新增对应 4 个 key |
| 13 | `src/pages/__tests__/chatHeaderMenus.test.tsx` | 改 | 第 88 行断言 `context-meter-stub` 需调整（见 §五） |
| 14 | `src/widgets/chat/__tests__/SessionUsageBadge*.test.tsx` | 改 | 组件改为受控后测试需重写 |
| 15 | `src/widgets/chat/__tests__/ContextMeter*.test.tsx` | 改 | 同上 |
| 16 | `src/widgets/chat/__tests__/ComposerStatusBar.test.tsx` | 新增 | 状态条渲染与交互测试 |

### 4.4 i18n 新增 key

| key | zh | en |
|-----|----|----|
| `chat.status.usage` | 用量 | Usage |
| `chat.status.cacheHit` | 缓存命中率 | Cache hit |
| `chat.status.latency` | 响应速度 | Latency |
| `chat.status.context` | 上下文占用 | Context |

---

## 五、测试方案

### 5.1 新增测试

| 文件 | 覆盖点 |
|------|--------|
| `src/widgets/chat/__tests__/ComposerStatusBar.test.tsx` | 三块统计均渲染；数值格式正确；点击用量弹明细；延迟 > 10s 时 `text-warning`；无 `sessionId` 时不请求不报错；窄窗口折叠 |
| `src/widgets/chat/__tests__/hooks/useSessionUsage.test.ts` | `sessionId` 变化重拉；流末刷新；轮询清理；失败静默 |

### 5.2 既有测试调整

| 测试 | 现状 | 变更 |
|------|------|--------|
| `src/pages/__tests__/chatHeaderMenus.test.tsx:88` | 断言齿轮菜单内存在 `context-meter-stub` | 改为断言齿轮菜单**不含** context-meter；另在 `ChatHeaderBar` 相关测试中断言顶栏**不含** `session-usage-badge` |
| `SessionUsageBadge*.test.tsx` | 组件自取数 | 改为传入 `usage` prop 的受控测试 |
| `ContextMeter*.test.tsx` | 组件自取数 | 同上，并补 `align` / `placement` 断言 |

### 5.3 门禁

| 门禁 | 命令 | 关注点 |
|------|------|--------|
| 单测 | `npm run test`（vitest） | 新增 + 调整用例全绿 |
| 类型 | `npx tsc --noEmit` | 新增 props 类型贯通 |
| 字号 token | `node scripts/check-font-scale.mjs` | **禁止** `text-[Npx]`，只能用 `text-ui-2xs` 等既有 token |
| 文件行数 | `scripts/count-lines.sh` + `architecture-policy.json` | `maxFileLines: 800`；`InputCard.tsx` 现 745 行，加 `statusSlot` 后接近上限，必要时拆分 |
| 架构 | `node scripts/architecture-check.mjs` | `forbidCycles` / `forbidDeepImports` 不新增违规 |

---

## 六、实施步骤

### M1 取数层与组件骨架

- [ ] 新增 `src/widgets/chat/hooks/useSessionUsage.ts`（含流末刷新）
- [ ] 新增 `src/widgets/chat/ComposerStatusBar.tsx` 骨架（先只渲染静态占位）
- [ ] `InputCard.tsx` 增加 `statusSlot` prop，页脚行支持「左 slot / 右字数」
- [ ] `ChatInput.tsx` 增加 `sessionId` / `isEmptySession` props
- [ ] `Chat.tsx` 传参

### M2 位置切换

- [ ] `ComposerStatusBar` 接入真实数据，替换 `SessionUsageBadge` / `ContextMeter` 的自取数
- [ ] `ChatHeaderBar.tsx` 移除 `SessionUsageBadge`
- [ ] `SessionSettingsMenu.tsx` 移除上下文用量块
- [ ] `ChatInput.tsx` 引导语改为仅空会话显示
- [ ] 治理审计导出全部保留且断言仍成立

### M3 交互与响应式

- [ ] `ContextMeter` 增加 `align` prop，弹层改向上展开
- [ ] 用量/延迟 popover（复用 `formatSessionUsageMarkdown`）
- [ ] 响应式折叠（640 / 1024 断点）

### M4 测试与收尾

- [ ] 新增 `ComposerStatusBar.test.tsx` / `useSessionUsage.test.ts`
- [ ] 调整 `chatHeaderMenus.test.tsx:88` 及受影响测试
- [ ] 跑通 §五 全部门禁
- [ ] 补 `docs/technical/` 章节 + `docs/user-manual/` 章节，删除本计划文件

### M5 双分支同步

- [ ] 在 `release/win7` 上 cherry-pick 主干改动
- [ ] py38 / pydantic v1 兼容性核验（本改动为纯前端，理论上无需适配）
- [ ] win7 CI 通过后开 PR

---

## 七、风险与依赖

| 编号 | 风险 | 等级 | 缓解 |
|------|------|------|----------|
| R1 | 既有测试大面积失败（`chatHeaderMenus.test.tsx:88` 断言齿轮菜单内存在 context meter） | 中 | M2 同步改测试；`grep -rn "context-meter-stub\|session-usage-badge" src/` 全量排查引用点 |
| R2 | 治理审计函数（P172/P186/P194）因组件搬迁导致断言失效 | 中 | 审计实现随组件迁移，导出符号名保持不变，避免其他模块 import 断裂 |
| R3 | `SessionUsageBadge` / `ContextMeter` 改为受控后，既有测试的"自取数"前提失效 | 中 | 受控化与测试改写在 M1–M2 同一批次完成，不留中间红 |
| R4 | 字号 token 门禁 | 低 | 只用 `text-ui-2xs`；提交前跑 `check-font-scale.mjs` |
| R5 | `InputCard.tsx` 745 行逼近 800 行上限 | 中 | 把页脚逻辑抽为独立子组件，或将 `ComposerStatusBar` 与 `InputCard` 解耦 |
| R6 | 状态条 popover 向上展开可能与 `TerminalPanel` 等高 z-index 浮层冲突 | 低 | 实测层级；必要时给状态条 popover 设定不低于 `TerminalPanel` 的 z-index |
| R7 | 窄窗口下状态条与字数计数重叠 | 低 | §3.6 分级折叠 + `min-w-0 truncate` |
| R8 | 双分支同步遗漏 | 中 | M5 明确纳入 PR 流程；cherry-pick 后跑 win7 CI |

**依赖**：无新增第三方依赖。全部基于既有 `fetchSessionUsage` / `useChatStreamStore` / Tailwind token。

---

## 八、后续可选项（本轮明确不做）

1. 状态条可点击项增加"复制用量明细"按钮（复制 Markdown）。
2. 上下文占用接近上限时状态条变色预警（≥ 80% 黄，≥ 95% 红）。
3. 顶栏 `SessionIdBadge` 也下沉到状态条（会进一步减轻顶栏，但会削弱"会话标识可见性"）。
4. 延迟指标补 P50（当前后端只给 avg / p95 / max）。
5. `ContextPressureBadge` 死代码清理（独立 PR）。

---

## 九、决策记录

| 日期 | 决策 | 选择 | 理由 |
|------|------|------|------|
| 2026-11-24 | 引导语去留 | 空会话才显示，有消息后由状态条接管 | 两者互斥是主流 AI 应用惯例；空会话是教学窗口，工作态是运行监控 |
| 2026-11-24 | 本轮交付物 | 先只出方案，不实施代码 | 用户确认 |
| 2026-11-24 | 统计条形态 | 单行紧凑 + popover 明细 | 对齐 Claude Code / Cursor 的 composer 状态区 |
| 2026-11-24 | 上下文统计位置 | 从齿轮菜单移出，与用量/延迟同处状态条 | 三者同属观测指标，同位才能形成完整"运行态面板" |
