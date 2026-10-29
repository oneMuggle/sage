# 新会话页（Welcome）三项 UX 缺陷修复方案

> 日期：2026-10-29
> 分支：`fix/welcome-ux-improvements`（worktree：`.worktrees/fix-welcome-ux-improvements`）
> 范围：新对话页（`/welcome`）输入框排版、下拉框宽度、推荐助手弹窗

---

## 背景与目标

用户在新会话页反馈三项缺陷：

1. 输入框中文字没有上下居中（略偏下），发送按钮同样偏下。
2. 「选择项目」「选择使用的模型」「选择是否创建新 worktree」三个下拉框过长，占据整个窗口。
3. 推荐助手的「写报告」「整理资料」等弹窗背景透明，无法使用；且推荐项本身是否有用/常用需重新评估。

**为什么现在做**：这三点都直接影响新会话页的首屏可用性——用户进入 `/welcome` 第一眼看到的就是这三个元素。缺陷 3 还牵连到「推荐助手」的产品定位（结构化表单 vs 轻量 prompt chip），改动面跨越 `entities/welcome` → `widgets/welcome` → `pages/Welcome` 三层，需要一次规划到位。

**约束**：本软件为**内网部署**，后端无法访问公网。因此推荐项设计必须假设「只有用户自己提供的资料（工作区文件 / 附件 / 内网文档）」可用，不能依赖联网搜索、在线模板等能力。

---

## 根因分析

### 缺陷 1：输入框文字偏下（InputCard.tsx）

实测（Playwright，1280×900，单行状态）：

| 元素 | top | height | bottom | 中心 |
|---|---|---|---|---|
| 输入框容器（含边框+padding） | 357 | 46 | 403 | 380 |
| textarea | 374 | 20 | 394 | **384** |
| `+` 按钮（h-7） | 366 | 28 | 394 | 380 |
| 发送按钮（h-9） | 367 | 36 | 403 | **385** |

两个容器都用了 `items-end`（底对齐）：

- `src/widgets/chat/InputCard.tsx:556` — 外层行 `flex items-end gap-2`
- `src/widgets/chat/InputCard.tsx:566` — 输入框内层行 `... flex items-end gap-2`

后果：

- **textarea**：单行高度 20px（`text-sm` → font-size 14px / line-height 20px），被底对齐到 28px 的内容区（`+` 按钮高度决定）底部 → 中心比输入框中心低 4px。
- **发送按钮**：36px，被底对齐到 46px 输入框的外框底部 → 中心比输入框中心低 5px。

另有一个隐藏因素：`textarea` 用 `text-sm`（line-height 20px）撑不出 28px 行高，文字在 28px 内容区内本身也是顶偏的。

> 注：输入框为 `WelcomeInputCard` 与聊天页共用组件（`InputCard`），改动会同时影响聊天页 —— 这是预期行为，两处都要修好。

### 缺陷 2：下拉框占据整个窗口（Select.tsx）

两层叠加的 bug：

**(A) Trigger 被撑满 —— `w-full` 覆盖了消费者的宽度类**

`src/shared/ui/Select/Select.tsx:73` 的 `SelectTrigger` 基础类包含 `w-full`：

```
'flex h-10 w-full items-center justify-between gap-2 rounded-lg border border-line bg-bg px-3 py-2 text-sm text-ink shadow-sm transition-colors'
```

消费者（`ProjectPicker.tsx:41`、`ModelPicker.tsx:29`、`WorktreePicker.tsx:73`）传 `w-48` / `w-56` / `w-40`，但 **Tailwind v3 的 CSS 层叠顺序由生成顺序决定，而非 class 字符串顺序**：`w-48` 属于 spacing scale，生成早于 `w-full`，所以 `w-full` 胜出。

实测证实：

| Trigger | 声明宽度 | 实测宽度 |
|---|---|---|
| 选择项目 | `w-48` = 192px | **244px** |
| 选择模型 | `w-56` = 224px | **244px** |
| Worktree 选项 | `w-40` = 160px | **64px** |

第三个之所以更窄，是因为它被包在 `WorktreePicker.tsx:71` 的 `<div className="flex items-center gap-2">` 里，该 div 作为 toolbar 行的 flex item 被压缩，trigger 的 `w-full` = 父容器的压缩后宽度。

**(B) 面板被撑到视口宽度 —— Viewport 的 `min-w`**

`src/shared/ui/Select/Select.tsx:166-170`：

```
position === 'popper' &&
  'h-[var(--radix-select-trigger-height)] w-full min-w-[var(--radix-select-content-available-width)]'
```

Radix 在 popper 模式下把 `--radix-select-content-available-width` 定义为 `var(--radix-popper-available-width)`，即 trigger 周围**视口可用宽度**（`node_modules/@radix-ui/react-select/dist/index.mjs:713`），所以下拉面板几乎铺满窗口。

Radix 同时提供了 `--radix-select-trigger-width`（= `--radix-popper-anchor-width`，即 trigger 实际宽度，见同文件 `:715`），这才是应该使用的变量。

### 缺陷 3：弹窗背景透明（TaskBriefDialog.tsx）

`src/features/task-brief/TaskBriefDialog.tsx` 使用了一批**并不存在的 Tailwind color token**：

| 位置 | 当前写法 | 问题 |
|---|---|---|
| `:133` | `bg-ui-bg border border-ui-border` | `ui-bg` / `ui-border` 未定义 |
| `:117` | `bg-ui-surface border border-ui-border text-ui-foreground` | `ui-surface` / `ui-foreground` 未定义 |
| `:269`、`:277` | `border border-ui-border` | 同上 |

`tailwind.config.js` 中 `ui-*` 只定义了 6 个：`ui-page` / `ui-panel` / `ui-card` / `ui-overlay` / `ui-fg` / `ui-subtle`。**Tailwind JIT 对未定义的 utility 静默跳过**，于是 `Dialog.Panel` 完全没有背景色 → 透明。

同款 bug 还散布在：

- `src/features/task-brief/SavedTaskRecipes.tsx:29,50,86` — `border-ui-border`
- `src/pages/Welcome.tsx:445,453` — `border border-ui-border`
- `src/widgets/welcome/AssistantRecommendations.tsx:89` — `text-text-tertiary`（`text-text` 下只有 `DEFAULT` / `secondary` / `muted` / `inverse`）
- `src/entities/welcome/recommendations.ts:36,50,61,72,83` — `gradient: 'bg-ui-surface'`（推荐卡片的图标底色同样无效）

项目内其它弹窗的正确写法参考 `src/shared/ui/Modal.tsx:43`：`bg-surface-elevated dark:bg-surface`。

---

## 技术方案

### 方案 A：输入框垂直居中

改动 `src/widgets/chat/InputCard.tsx`：

1. 外层行 `:556` `items-end` → `items-center`；内层行 `:566` `items-end` → `items-center`。
2. textarea `:582` 增加 `min-h-9 leading-9`：
   - `min-h-9` = 36px，让 textarea 的高度与发送按钮（`h-9` = 36px）一致；
   - `leading-9` = 36px，行盒高度等于容器高度 → 单行文字在框内**光学居中**。

   > Tailwind v3 core plugin 顺序为 `fontSize` → `lineHeight`，因此 `leading-9` 会覆盖 `text-sm` 自带的 `line-height: 1.25rem`，无需 `!important`。

3. `+` 按钮保持 `w-7 h-7`（28px），在 36px 内容区内由 `items-center` 居中。

**为什么选 `items-center` 而不是让按钮贴底**：发送按钮（36px）与输入框内容区（36px）高度一致后，`items-center` 在单行状态下让三者中心严格对齐（误差 0px）；多行状态下按钮随文本框中部对齐，与"侧挂操作列"的主流布局一致，且避免了 `items-end` 时按钮底边与输入框 padding 外边缘错位的问题。

> autosize 逻辑（`InputCard.tsx:317-327`）把 height 设为 `min(scrollHeight, 200)`。`min-h-9` 只是 CSS 下限，不影响多行增长；`scrollHeight` 在 `min-h-9` 下最小为 36px，单行不会塌陷。

### 方案 B：下拉框宽度收敛

改动 `src/shared/ui/Select/Select.tsx`：

1. `SelectTrigger` 基础类去掉 `w-full`（`:73`）→ 宽度完全由消费者决定。
   - 全部 6 个调用点（`ProjectPicker` / `ModelPicker` / `WorktreePicker` ×3）都已自带宽度类，**无需改动消费者**。
2. `SelectContent` 的 Viewport（`:166-170`）：
   `min-w-[var(--radix-select-content-available-width)]` → `min-w-[var(--radix-select-trigger-width)]`
   → 面板宽度 = trigger 宽度，不再铺满视口。

3. 保险起见给 `WorktreePicker.tsx:71` 的包裹 div 加 `shrink-0`，避免 toolbar 行空间不足时再次压缩 trigger。

### 方案 C：弹窗背景与无效 token 清理

把无效 token 替换为项目已定义的语义色：

| 无效写法 | 替换为 |
|---|---|
| `bg-ui-bg` | `bg-surface-elevated dark:bg-surface` |
| `bg-ui-surface` | `bg-bg-subtle` |
| `border-ui-border` | `border-border` |
| `text-ui-foreground` | `text-text` |
| `text-text-tertiary` | `text-text-secondary` |

涉及文件：`TaskBriefDialog.tsx`、`SavedTaskRecipes.tsx`、`Welcome.tsx`、`AssistantRecommendations.tsx`、`recommendations.ts`。

### 方案 D：推荐助手 → 轻量 prompt chip

**产品判断**：当前 5 个推荐卡片点击后都打开 `TaskBriefDialog`——一个含 6 个字段（任务目标 / 项目范围 / 受众 / 资料要点 / 交付格式 / 长度格式要求）的结构化表单。对"快速开始"这个场景，表单过重：用户想的是"帮我写份报告"，不是"填一张工单"。

**内网约束下的取舍**：

- 保留 **写报告 / 整理资料 / 分析表格 / 写代码** 4 项——都只依赖用户自己提供的资料与工作区。
- 移除 **制作演示**——在无公网模板、无在线素材的场景下使用频次最低，且与"写报告"的交付路径重叠。
- 去掉结构化表单，改为**一行 prompt chip**：点击后把预设 prompt 填入输入框并聚焦，用户可继续补充/挂载附件后发送。

> **交互选型说明**：选择"填入 + 聚焦"而非"点击即发送"。理由：这些 prompt（"根据指定资料生成一份可交付的报告"）必须搭配用户自己的资料才有意义，自动发送会立刻发出一个无法执行的请求；填入式允许用户先挂附件再发送，同时避免了误触即发消息。实现上这只是一行 `setValue` 的差别，后续若要改成直发，改动同样是一行。

**改动点**：

- `src/widgets/welcome/AssistantRecommendations.tsx` — 网格卡片 → 单行/换行 chip（`flex flex-wrap gap-2`，chip 为圆角胶囊按钮，图标 + 标题，hover 态）。
- `src/pages/Welcome.tsx` — `handleRecommendationSelect` 从"打开 TaskBriefDialog"改为"回填输入框"；新增 `recommendationDraft` state 传给 `WelcomeInputCard`。
- `src/widgets/welcome/WelcomeInputCard.tsx` — 支持受控的 `initialValue` 回填（当前已有 `initialValue` prop + `useEffect` 同步，改为加一个 `draftKey` 以便重复点击同一 chip 也能触发）。
- `TaskBriefDialog` **保留**：已保存的任务配方（`SavedTaskRecipes`）仍需用它来"确认参数后复用"，因此顺手修好它的透明背景（方案 C）。

---

## 实施步骤

- [x] 步骤 1：建 worktree `fix/welcome-ux-improvements`，软链 `node_modules`
- [x] 步骤 2：写本方案文档
- [x] 步骤 3：方案 A —— `InputCard.tsx` 输入框居中（`items-center` ×2 + `min-h-9 leading-9`）
- [x] 步骤 4：方案 B —— `Select.tsx` trigger / viewport 宽度（去 `w-full`，viewport `min-w` 用 trigger 变量，WorktreePicker 加 `shrink-0`）
- [x] 步骤 5：方案 C —— `TaskBriefDialog.tsx` / `SavedTaskRecipes.tsx` / `Welcome.tsx` / `AssistantRecommendations.tsx` / `recommendations.ts` 无效 token 清理
- [x] 步骤 6：方案 D —— 推荐卡片改 chip + 回填输入框（新增 `chipRecommendations`、4 个 chip、draft 对象引用作触发、`focusRequest` 聚焦）
- [x] 步骤 7：`npm run typecheck`（0 error）+ `npm run lint`（0 error，109 warning 全为预存）+ vitest（4 个直接相关文件 31 passed；扩展至 widgets/shared/feature 共 194 个文件 823 passed）
- [x] 步骤 8：Playwright 实机复验（1440×900）—— 实测数据：
  - **垂直居中**：textarea `lineBoxCenterOffsetFromContainerCenter: 0`、send button `centerOffsetFromContainerCenter: 0`、容器 `alignItems: center`、`lineHeight=36px = contentBoxHeight=36px`
  - **下拉框宽度**：实测 181px / 211px / 160px，对应声明 `w-48=192px` / `w-56=224px` / `w-40=160px`（border-box 扣 border/padding，符合预期）
  - **下拉面板宽度**：viewportElWidth 226px / contentWidth 228px << 窗口 1440px
  - **chip 回填**：4 个 chip（写报告/整理资料/分析表格/写代码），点击「写报告」后 textarea.value = "根据指定资料生成一份可交付的报告"、`focused=true`、光标在末尾（selectionStart=16 = value.length）
  - **弹窗背景**：`backgroundColor: rgb(255,255,255)` 实色（修复前透明）、`borderColor: rgb(229,231,235)`、`opacity: 1`
- [ ] 步骤 9：cherry-pick 到 `release/win7`（前端纯改动，无 py3.8 适配需求）

## 风险评估与依赖

| 风险 | 等级 | 缓解 |
|---|---|---|
| `SelectTrigger` 去掉 `w-full` 后，新调用方忘记传宽度 → 触发器宽度塌缩为内容宽 | 低 | 当前 6 个调用点全部自带宽度；已在方案中记录约定 |
| `InputCard` 为欢迎页 / 聊天页共用，样式改动波及聊天页 | 中 | 聊天页同样是"文字偏下"的同一 bug，属于一并修复；步骤 8 会同时复验两页 |
| `leading-9` 未按预期覆盖 `text-sm` 的 line-height（CSS 顺序假设错误） | 中 | 步骤 8 用 computed style 实测 `line-height`，不靠推断 |
| 移除「制作演示」后，用户已保存的 `slides` 配方无法回填 | 低 | `SavedTaskRecipes` 走 `defaultRecommendations.find(id === scenario)`；`slides` id 仍保留在 `recommendations.ts` 的数据表里（仅从"chip 列表"中隐藏），查找不会落空 |
| `WelcomeInputCard` 回填与用户手动输入互相覆盖 | 低 | 用 `draftKey`（chip id + 点击序号）做触发源，仅在 draft 变化时覆盖 `value` |
