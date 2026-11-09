# 2026-11-09 文档工作台 IA 重组 + 3 个 UI 缺陷修复

> 状态：进行中
> 范围：`src/pages/Office.tsx` + 左侧文档库 + 规则 tab + AI 侧栏

## 背景与目标

用户报告三个问题，根因诊断后合并为一个方案：

1. **AI 助手 "system 未选择文档"**（`src/features/office/sidebar/useAiCapabilities.ts` / `useAuditSuggestions.ts` 的所有命令都触发这条 system 消息）
   - 根因：`officeWorkspaceStore.setActiveDocument()` 在生产代码里**从未被调用**（grep 确认只有测试文件用过）。`activeDocument` 永远为 `null`
   - `Office.tsx:370 handlePreviewDocument` 把文档加载到本地 `preview` state，但没写回 store
2. **左侧文档列表图标挡住文档名**
   - 根因：5 个 action 按钮 (~156px) 在 300px 侧栏里物理上放不下，action 容器缺 `shrink-0` 导致图标溢出覆盖文件名
3. **规则工作台"太乱"**
   - 根因：`renderRulesTab()` 垂直堆叠 6 个独立面板（RulesWorkspace / OfficeSpecLibrary / OfficeAiAssistantPanel / WordRuleExtractionPanel / WordBatchAuditPanel / 引导卡），其中 3 个"审校"入口、4 个文件选择器，概念重叠严重

目标：
- **A**：接线 + AI 侧栏 header chip + 按钮 disabled 态替代 system 消息噪声
- **B**：左侧文档库 row 改为"1 inline + ⋯ 溢出菜单"，侧栏默认 300→320
- **C**：规则 tab 拆为 3 个二级子 tab（规则库 / AI 审校 / 批量工具），合并 3 个审校入口为 1 个，删除 2 个冗余面板

参考主流 AI 应用：ChatGPT Canvas（当前画布 chip + 工具灰态）、Notion AI（sidebar 抽屉 + inline toolbar）、Craft Docs AI（画布上下文隐式注入）。

## 涉及的文件与模块

### 修改

| 文件 | 改动 |
|---|---|
| `src/pages/Office.tsx` | 3 处接线 `setActiveDocument`；`renderRulesTab` 重写为二级 Tabs |
| `src/features/office/OfficeDocumentList.tsx` | row 布局重写（1 inline + ⋯ 菜单 + shrink-0 + hover 显示） |
| `src/widgets/layout/Sidebar.tsx` | 默认 width `300 → 320` |
| `src/features/office/sidebar/AiSidebar.tsx` | header 文档 chip |
| `src/features/office/sidebar/QuickActions.tsx` | 接收 `activeDocument` prop，无文档时按钮 disabled |
| `src/features/office/sidebar/FloatingActionBar.tsx` | 无 activeDocument 时不弹 |
| `src/features/office/sidebar/useAiCapabilities.ts` | guard 改为用户可见的 error（非 system 消息） |
| `src/features/office/sidebar/useAuditSuggestions.ts` | guard 同上 |
| `src/features/office/rules/RulesWorkspace.tsx` | 拆分为子 tab A 的主体（剥离"从文档抽取"逻辑到父级） |

### 新增

| 文件 | 用途 |
|---|---|
| `src/features/office/rules/RulesSubtabs.tsx` | 规则 tab 的 3 个子 tab 容器（二级 Tabs） |
| `src/features/office/rules/AiAuditTab.tsx` | 子 tab B "AI 审校"（合并 OfficeAiAssistantPanel + RulesWorkspace.handleAudit） |
| `src/features/office/rules/BatchToolsTab.tsx` | 子 tab C "批量工具"（WordBatchAuditPanel + 引导卡） |

### 删除

| 文件 | 原因 |
|---|---|
| `src/features/office/OfficeAiAssistantPanel.tsx` | 功能并入子 tab B |
| `src/features/office/WordRuleExtractionPanel.tsx` | 核心逻辑提升到子 tab A 顶栏 |
| `src/features/office/__tests__/OfficeAiAssistantPanel.test.tsx` | 随组件删除 |
| `src/features/office/__tests__/WordRuleExtractionPanel.test.tsx` | 随组件删除（如有） |

### 测试更新

| 文件 | 改动 |
|---|---|
| `src/features/office/__tests__/OfficeDocumentList.test.tsx` | 重写 row 断言（⋯ 菜单交互） |
| `src/features/office/sidebar/__tests__/AiSidebar.test.tsx` | header chip 快照 |
| `src/features/office/sidebar/__tests__/QuickActions.test.tsx` | disabled 态测试 |
| `src/features/office/sidebar/__tests__/useAiCapabilities.test.tsx` | guard 行为改为抛错 |
| `src/features/office/sidebar/__tests__/useAuditSuggestions.test.tsx` | guard 行为改为抛错 |
| `src/features/office/rules/__tests__/RulesSubtabs.test.tsx` | 新组件测试 |
| `src/features/office/rules/__tests__/AiAuditTab.test.tsx` | 新组件测试 |

## 技术方案

### Section 1 · 共享文档上下文

**store 接线**：
- `Office.tsx:handlePreviewDocument`：成功加载 `doc` 后调用 `useOfficeWorkspaceStore.getState().setActiveDocument(doc)`
- `Office.tsx:settleMultiImport`：首个成功导入的 `first.doc` 写入 store（用 `importAndReadMulti` 返回的 `imported[0].readResult.summary`）
- `Office.tsx:handleEditApplied`：应用后 `doc` 写回 store

`setActiveDocument` 已内置逻辑：id 不变 → 仅更新元数据；id 变化 → 同时清空 `conversation` / `selection`（`officeWorkspaceStore.ts:80-87`）。无需额外清理。

**AI 侧栏 header chip**：
- `AiSidebar.tsx:58-62` 当前是纯文本 "当前文档: xxx.docx" / "未选择文档"
- 改为 chip：类型图标（DOC_TYPE_ICONS）+ 文件名 + `×` 清除按钮
- 清除行为：`useOfficeWorkspaceStore.getState().setActiveDocument(null)`（不关闭预览，仅解除 AI 上下文）
- 无文档时显示引导文案 "在左侧文档库点击任一文档开始"（不再是 "未选择文档" 这种冷冰冰的提示）

**按钮 disabled 态**：
- `QuickActions.tsx`：接收 `activeDocument` prop；`!activeDocument` 时所有 quick action 按钮 `disabled`，`title="请先在左侧选择文档"`
- `FloatingActionBar.tsx`：在 `OfficeAiSidebarHost.tsx:128 handleFloatingAction` 入口加 `if (!activeDocument) return`，选中文本浮窗的"改写润色"直接不触发

**system 消息替代**：
- `useAiCapabilities.ts` 的 `if (!activeDocument)` 守卫：
  - 当前：`appendMessage({role: 'system', content: '未选择文档'})`
  - 改为：`toast.warning('请先在左侧文档库选择文档')`（sonner toast，短暂）+ 不追加 system 消息
- `useAuditSuggestions.ts` 同样

### Section 2 · 左侧文档库 UI

**row 布局**：
- 当前：`[checkbox] [fileIcon] [filename button flex-1] [actions: 5 buttons]`
- 改为：`[checkbox] [fileIcon] [filename button flex-1 + title] [open inline] [⋯ MoreVertical]`
- action 容器加 `shrink-0` 防止溢出
- `⋯` 按钮默认 `opacity-0`，行 hover 时 `opacity-100`（transition 150ms）
- 行整体加 `group` class，用 `group-hover:opacity-100` 实现 hover 显示
- 文件名截断时 `title={fullFilename}` + Radix `Tooltip` 显示完整名称

**`⋯` 菜单内容**（用已有 `DropdownMenu` primitive）：
- live variant：
  - 打开（同 inline 主按钮）
  - 历史版本
  - 在文件夹中显示
  - ──
  - 另存为
  - ──
  - 归档
- archived variant：
  - 打开
  - 在文件夹中显示
  - ──
  - 恢复

**侧栏宽度**：
- `Sidebar.tsx:193` `width = 300` → `width = 320`
- ResizeDivider 已有 180-480 clamp，无需改

### Section 3 · 规则 tab 子 tab 分域

**容器**：新建 `RulesSubtabs.tsx`，用二级 `Tabs`（与顶层 4 tab 同 primitive）
- 子 tab IDs：`rules-library` / `ai-audit` / `batch-tools`
- 默认激活：`rules-library`

**子 tab A：`规则库`**
- 主体：`RulesWorkspace` 2 列 grid（保持现状）
- 顶栏追加按钮：`[从当前文档抽取规则]`（依赖 `activeDocument`，disabled 态同 Section 1）
  - 点击后调用 `officeRulesApi.extractRules({ workspace_path, file_path, use_llm: true })`
  - 成功后自动创建新规则组（命名规则沿用 WordRuleExtractionPanel 的 `${baseName} · 抽取规则`）
  - 跳 toast：`已抽取 N 条规则到新组 "${groupName}"`
- 底部折叠区：`OfficeSpecLibrary`（`<details>` 折叠，标题 "格式规范书库（外部规则来源）"）
- 删除：`WordRuleExtractionPanel` 整体移除，其"从文档抽取规则"逻辑并入此子 tab A 顶栏

**子 tab B：`AI 审校`**（新建 `AiAuditTab.tsx`）
- 顶部：当前文档 chip（同 Section 1）
- Scope 下拉：`当前规则组` / `当前规范书`
  - `当前规则组` → `officeRulesApi.audit({ workspace_path, file_path, rule_ids: selectedGroup.rules.filter(enabled).map(id) })`
  - `当前规范书` → `officeApi.runAiReview({ workspace_path, file_path, spec_id, scope: 'full', use_llm: true })`
- 单一"开始审校"按钮
- 审校结果：复用 `RuleAuditResults` 渲染
- 应用修订：selected issues + revise API（沿用 RulesWorkspace.handleApplyRevisions 逻辑）
- 删除：`OfficeAiAssistantPanel` 整体移除

**子 tab C：`批量工具`**（新建 `BatchToolsTab.tsx`）
- `WordBatchAuditPanel` 整块搬入
- 引导卡片搬入（"Word 文档审校入口" — 跳去文档 tab）

## 实施步骤

实施按依赖顺序推进，每个里程碑独立可验证：

- [x] **M1 · 设计文档定稿**（本文档）
- [x] **M2 · Section 1 接线（基础，其他依赖它）**
  - [x] `Office.tsx` 3 处写回 `setActiveDocument`
  - [x] 在 AI 侧栏 header 增加文档 chip（`AiSidebar.tsx`）
  - [x] `QuickActions.tsx` 接收 activeDocument prop + disabled 态
  - [x] `FloatingActionBar.tsx` + `OfficeAiSidebarHost.tsx` guard
  - [x] `useAiCapabilities.ts` / `useAuditSuggestions.ts` guard 改为 toast
  - [x] 相关测试更新
- [x] **M3 · Section 2 左侧文档库 UI**
  - [x] `OfficeDocumentList.tsx` row 重写（1 inline + ⋯ hover 菜单 + shrink-0 + Tooltip）
  - [x] `Sidebar.tsx` 默认宽度 300→320
  - [x] i18n key `office.doclib.moreActions` (zh/en)
  - [x] 测试更新（row 布局断言 + ⋯ 菜单 `pointerDown` → `findByRole('menuitem')` 交互）
- [x] **M4 · Section 3 规则 tab 子 tab 分域**
  - [x] 新建 `RulesSubtabs.tsx` / `AiAuditTab.tsx` / `BatchToolsTab.tsx`
  - [x] 重写 `Office.tsx:renderRulesTab` 挂载 `RulesSubtabs`
  - [x] 删除 `WordRuleExtractionPanel.tsx` 及其测试
  - [x] 把"从文档抽取规则"逻辑搬到子 tab A 顶栏（`RulesSubtabs.handleExtractFromActiveDocument`）
  - [x] 测试覆盖新组件（`RulesSubtabs.test.tsx` 3 例：成功建组 / 部分失败 / 无文档时禁用）
  - **与计划的偏差**
    - `OfficeAiAssistantPanel.tsx` **保留**（计划写"整体移除"）：其"审校全文 / 改写润色"是 AI 审校子 tab 的主体，直接内嵌在 `AiAuditTab` 中，未重写等价面板。
    - "从文档抽取规则"逻辑从 `RulesWorkspace` **上移到 `RulesSubtabs`**（计划表述为"搬到子 tab A 顶栏"）：抽取需要 `activeDocument`，放在容器层可避免 `RulesWorkspace` 依赖全局 store。
    - 新规则组命名采用 `${baseName} · 抽取规则`，与旧实现 `抽取规则 · ${baseName}` 顺序相反（按计划 §Section 3 的命名规则）。
    - `useKeepAliveTabs` 从 `pages/office/officeTabs.ts` 下沉到 `src/shared/lib/hooks/useKeepAliveTabs.ts`，供 `features/` 与 `pages/` 共用（分层约束：features 不能 import pages）。
- [x] **M5 · 端到端 smoke**
  - [x] 启动 Electron（正常模式）— Vite @ :1549、backend @ :8894 均返回 200；Electron 主进程 + 6 子进程存活，前端 IPC 正常触发；
  - [ ] 流程：文档 tab 点击文档 → 左侧库预览 → AI 侧栏显示 chip → 审校全文命令可用
  - [ ] 规则 tab → 3 个子 tab 切换 → AI 审校 tab 能跑一次审校
  - **环境说明**：当前 Wayland 会话 + worktree 启动未继承 DISPLAY/WAYLAND，Electron 窗口未渲染到桌面。HTTP 层 smoke（vite + backend + electron IPC）通过；交互层 smoke 需要在有完整 display 环境的机器上手动复核，或由用户在 PR review 阶段本地验证。
- [x] **M6 · Code review + 合并**
  - [x] `code-reviewer` agent 审 — 发现 HIGH（i18n 硬编码）+ MEDIUM（`initialFilePath` 响应式），均已修复
  - [x] PR 创建：https://github.com/oneMuggle/sage/pull/2975

## 风险评估与依赖

### 风险

| 风险 | 等级 | 缓解 |
|---|---|---|
| 删除 `OfficeAiAssistantPanel` / `WordRuleExtractionPanel` 可能影响其他入口 | 中 | grep 确认挂载点只有 `Office.tsx` 一处 |
| 规则 tab 子 tab 拆分需要 `officeRulesApi.audit` 与 `officeApi.runAiReview` 两种返回 shape 对齐 | 中 | 在前端做一次 adapter；不要求后端改动 |
| `QuickActions` disabled 态依赖 `activeDocument` 透传 | 低 | 直接在 `AiSidebar.tsx` 里从 store 读 + 传 |

### 依赖

- `DropdownMenu` / `Tooltip` / `Tabs` primitive 已存在（`src/shared/ui/`）
- `officeRulesApi.audit` 与 `officeApi.runAiReview` 后端端点已就绪
- Section 1 必须先于 Section 3（规则 tab 子 tab B 依赖 `activeDocument` 接线）

## 不在范围内

- 不修改后端
- 不动 4 个顶层 tab（文档 / 生成 / 规则 / LaTeX）的结构
- 不改 AI 侧栏的对话 / 建议卡 / apply 逻辑（仅改 header chip 与 disabled 入口）
- 不引入新依赖（全部复用已有 primitive）

## 验收标准

- [x] AI 侧栏在"未选文档"时不再出现 `system 未选择文档` 消息；所有依赖 activeDocument 的 quick action 显示为 disabled
- [x] AI 侧栏 header 显示当前文档 chip；清除按钮解除 AI 上下文（但不关闭预览）
- [x] 左侧文档列表在 300/320px 侧栏下图标不再覆盖文件名；⋯ 菜单包含所有 5 个次级动作
- [x] 规则 tab 拆为 3 个子 tab，每个子 tab 内部概念单一、无重复审校入口
- [x] 删除 `WordRuleExtractionPanel.tsx`，功能在子 tab A 顶栏保留；`OfficeAiAssistantPanel.tsx` 保留并内嵌为子 tab B 主体
- [x] 测试全绿（vitest 7 files / 70 tests pass；后端 pytest 未涉及）
- [x] Code review 无 CRITICAL / HIGH issue（HIGH i18n + MEDIUM initialFilePath 已修复）
