# 文档工作台（AI 文档工作台）重构方案

> 状态：设计已确认，待实施
> 日期：2026-11-06
> 分支：`worktree-office-ai-workbench`（基于 main）
> 定位：**AI 文档工作台**（参考 Cursor / ChatGPT Canvas / Notion AI）
> 承接：本方案是 `2026-11-04_office-ai-document-workbench.md`（Phase 0 ✅ 已交付 / Phase 1 实施中）的延续升级，聚焦三栏布局正式落地、AI 侧栏、生成 AI 化、规则生命周期闭环。

## 0. 与既有计划的关系（去重边界）

既有计划 `2026-11-04_office-ai-document-workbench.md` 覆盖同一功能域，**本方案不重做已交付部分**：

| 既有计划里程碑 | 状态 | 本方案处理 |
|---|---|---|
| Phase 0：统一导入 `OfficeIntake` / 去重 / blob URL / 历史可点击 / 高保真入口可见 | ✅ 已交付（main #2869） | **复用**：`OfficeIntake` 拖拽逻辑保留，宿主迁入 `DocumentEmptyState`；blob URL 管线保留 |
| Phase 1 M2.5：规范书库 MVP（`OfficeSpecLibrary`、`office_spec_*`、LLM 提取） | ✅ 已交付 | **复用**：作为规则组的数据来源；本方案增补「规则查看/修改/组合/导出」 |
| Phase 1 M3：`OfficeAiAssistantPanel` 问题列表 + `office_ai_review_routes` | ✅ 已交付 | **升级形态**：能力保留，宿主从内嵌面板改为常驻 `AiSidebar` |
| Phase 2 M4：AI 起草（`AiDraftWizard`、`office_ai_draft_routes`） | ⬜ 未开始 | **合并实施**：本方案 P3 `GenerateWorkspace` 即 M4 的前端形态，后端按 M4 端点设计实现，不再另起一套 |
| Phase 3：Excel/PPT 版式预览 spike | ⬜ 未开始 | **不在本方案范围**（保持独立排期） |

结论：本方案 = 既有计划 Phase 1 收尾 + Phase 2 形态重构 + 规则生命周期闭环。实施时必须先读既有计划，避免重复实现 M2.5/M3 已交付的端点与组件。

## 1. 背景与目标

### 现状问题

当前 `/office` 页面为 4 个并列 Tab（文档处理 / 文档生成 / 审校与规范 / LaTeX），存在以下问题：

1. **内容没有串起来**：导入、预览、编辑、生成、审校各自独立，用户需要在 Tab 之间来回切换，缺乏统一的任务流。
2. **高保真预览体验差**：
   - 高保真不是默认视图，需要手动点开；
   - iframe 固定高度 `h-[32rem]`，内容超出窗口不会自动调整；
   - iframe 无纵向滚动条，长文档难以阅读。
3. **导出 PDF 不可用**：无本机转换器（LibreOffice / MS Word）时导出按钮直接 `disabled` 灰掉，没有任何引导。
4. **编辑预览没有 AI 参与**：`OfficeEditPreviewDialog` 只有表单编辑，没有改写/润色/审校能力。
5. **选择文件与预览割裂**：左侧 `OfficeIntake` 与右侧 `OfficePreviewPanel` 是两块独立区域，占屏且流程断裂。
6. **文档生成没有 AI 参与**：`OfficeGenerateForm` 是纯表单，没有自然语言生成、参考资料生成、对话式填充。
7. **"期刊文档助手"语义狭窄**：实际能力覆盖所有模板文档，不应只叫期刊。
8. **审校与规范太乱**：`OfficeSpecLibrary` / `OfficeAiAssistantPanel` / `WordRuleExtractionPanel` / `WordBatchAuditPanel` 4 个面板并列，规则生命周期（提取 / 查看 / 修改 / 组合 / 导出）没有闭环。

### 目标

将页面重构为 **AI 文档工作台**：

- **统一画布**：文件选择与预览合并为一个组件，无文件时是入口、有文件时是预览、拖入文件可替换。
- **AI 侧栏常驻**：所有 Tab 共享一个 AI 侧栏，支持选中改写/润色、侧栏对话、指令式修改、AI 审校建议。
- **高保真默认**：默认高保真渲染，失败自动降级结构化视图；内容超出自动滚动。
- **生成 AI 化**：4 种生成模式（自然语言 / 参考资料 / 模板对话 / 迭代优化）。
- **规则生命周期闭环**：AI 辅助提取 → 查看 → 修改 → 组合 → 导出分享。
- **命名通用化**："期刊文档助手" → "模板文档"，页面名 → "文档工作台"。

## 2. 涉及的文件与模块

### 前端（重构）

| 文件 | 动作 |
|------|------|
| `src/pages/Office.tsx` | 重构：三栏布局壳 + 状态编排 |
| `src/pages/office/OfficeLayout.tsx` | 新增：左栏 + 主区 + AI 侧栏布局 |
| `src/pages/office/officeTabs.ts` | 扩展：侧栏状态、Tab 重命名（rules） |
| `src/features/office/canvas/*` | 新增：统一文档画布（5 个组件） |
| `src/features/office/sidebar/*` | 新增：AI 侧栏（6 个组件） |
| `src/features/office/generate/*` | 新增：生成工作台（7 个组件） |
| `src/features/office/rules/*` | 新增：规则管理（6 个组件） |
| `src/features/office/OfficePreviewPanel.tsx` | 保留工具逻辑，渲染部分迁入 `DocumentPreview` |
| `src/features/office/OfficeIntake.tsx` | 保留拖拽/选择逻辑，宿主迁入 `DocumentEmptyState` |
| `src/features/office/OfficeEditPreviewDialog.tsx` | 保留，接入 AI 修改指令 |
| `src/features/office/DocumentAuditPanel.tsx` | 保留，作为单文档审校结果面板 |
| `src/features/office/WordBatchAuditPanel.tsx` | 保留，收进规则 Tab 底部 |
| `src/features/office/OfficeSpecLibrary.tsx` | **保留**（测试依赖）；作为规则组的导入/管理入口，在新 `RulesWorkspace` 中挂载 |
| `src/features/office/OfficeAiAssistantPanel.tsx` | **保留**（9 个测试依赖）；抽取内部能力到 `sidebar/` hooks，新侧栏就绪后另开 PR 删除旧组件 |
| `src/features/office/WordRuleExtractionPanel.tsx` | 保留为「AI 提取规则」对话框的底层实现，外层加 `RuleExtractionDialog` |
| `src/features/journal/JournalPanel.tsx` | **不修改**（4 个测试 + barrel `exports=2` 契约）；新增 `office/generate/TemplateLibrary.tsx`，复用 `useJournalTemplates`，在 generate tab 中替代其渲染位置 |
| `src/features/office/officeWorkspaceStore.ts` | 改为 `src/entities/office/officeWorkspaceStore.ts`（与 `entities/*/store` 现有 zustand 惯例一致） |

### 后端（新增/增强）

| 文件 | 动作 |
|------|------|
| `backend/api/ai_routes.py` | 新增：rewrite / chat / audit / extract-rules / summarize |
| `backend/api/rules_routes.py` | 新增：rules CRUD / check-conflicts / export / import |
| `backend/api/office_routes.py` | 增强：generate/template-chat、generate/iterate、templates |
| `backend/services/rule_extractor.py` | 增强：结构化输出 RulePack |
| `backend/services/document_generator.py` | 增强：模板对话式填充、迭代优化 |
| `backend/data/rule_repo.py` | 新增：规则组/规则持久化（SQLite） |
| `backend/data/migrations/` | 新增迁移：规则表（groups / rules / packs） |

### 文档

| 文件 | 动作 |
|------|------|
| `docs/technical/133-office-ai-workbench.md` | 新增技术章节（实施完成后归档；**编号待实施时按两分支实测分配**，win7 的 §133 已被专家 M4 占用，main 可能顺延至 §134） |
| `docs/user-manual/36-document-workbench.md` | 新增用户手册章节（同上，编号待实测） |

## 3. 技术方案

### 3.1 信息架构

```
┌─────────────────────────────────────────────────────────────┐
│  Header: "文档工作台" + [环境] + 工作区路径                    │
├──────────┬──────────────────────────────────────────────────┤
│ 左侧栏    │  主工作区 (flex-1)                 AI 侧栏 (320px)│
│ 240px    │                                                  │
│ 📁 文档库 │  ┌──────────────────────────────┐  ┌──────────┐│
│  ├─ 文件1 │  │  统一文档画布                 │  │ ✨ AI助手 ││
│  └─ ...   │  │  (无文件→入口 / 有文件→预览)  │  │ 选中浮出  ││
│ ──────── │  │  (高保真默认，失败降级)       │  │ 对话      ││
│ ✨ AI助手 │  │  (内容超出自动滚动)           │  │ 快捷指令  ││
│  ├─ 新对话│  └──────────────────────────────┘  │ 输入      ││
│  └─ 历史  │                                    └──────────┘│
├──────────┴──────────────────────────────────────────────────┤
│  Tabs: [文档] [生成] [规则] [LaTeX]                           │
└─────────────────────────────────────────────────────────────┘
```

**Tab 变化**：`documents`（文档）/ `generate`（生成）/ `rules`（规则）/ `latex`（LaTeX，3 子 Tab 不变）。

### 3.2 统一文档画布（DocumentCanvas）

- 合并 `OfficeIntake` + `OfficePreviewPanel` 为单一组件。
- **无文件**：`DocumentEmptyState` — 拖拽/选择入口。
- **有文件**：`DocumentPreview` — 高保真 iframe（默认）或结构化视图。
- **拖入新文件**：覆盖层提示"释放以替换当前文档"，释放后导入并刷新预览。
- 工具栏：`[高保真▼] [编辑预览] [规则审校] [导出PDF]`。

**高保真修复**：

「默认高保真」按格式精确定义，避免与「无转换器」矛盾：

| 格式 | 渲染器 | 是否默认开 | 无转换器时的行为 |
|---|---|---|---|
| Word | `docx-preview`（内置，`DocxNativePreview`） | ✅ 默认开 | 不需要转换器，始终可用 |
| PDF | Chromium 内置 viewer + blob URL（已有） | ✅ 默认开 | 不需要转换器，始终可用 |
| Excel | 无内置版式渲染 | ⬜ 有 LibreOffice/Word 才开 | 结构化视图 + 工具栏「安装转换器」引导（不显示为高保真失败） |
| PPT | 无内置版式渲染 | ⬜ 有 LibreOffice/Word 才开 | 同上 |

- iframe 容器：`flex-1 min-h-0 overflow-y-auto`，iframe `w-full h-full min-h-[32rem]`（替换固定 `h-[32rem]`）。
- 已声明可高保真但渲染失败（`onError` / 加载后空白 / 5s 超时）→ 自动降级结构化视图 + toast「已切换到结构视图」。
- 结构化视图容器同样 `flex-1 min-h-0 overflow-y-auto`，保证长文档可滚动。

**导出 PDF**：
- 无转换器时按钮保持可点击，点击弹出 `ConverterGuideDialog`（检测 OS → 给出 LibreOffice 下载链接 + 说明）。
- 有转换器时走现有 `officeApi.exportPdf` 流程。

### 3.3 AI 侧栏（AiSidebar）

- **触发**：选中文本浮出操作条（改写/润色/翻译/解释）；侧栏按钮展开；快捷指令；自由输入（支持 `/` 前缀）。
- **四种能力**：
  1. **选中改写/润色** → 请求 → 结果带 `[应用][丢弃][重试]`。
  2. **侧栏 AI 对话** → system prompt 注入当前文档结构化内容，多轮对话按文档分组。
  3. **指令式修改** → AI 定位段落 → diff 展示 → 确认应用。
  4. **AI 审校建议** → 逐段检查 → 建议列表（`第3段：措辞不当`）→ `[应用][跳过]` / 批量应用。
- **快捷指令按 Tab 变化**：文档（审校全文/提取规则/生成摘要/翻译）；生成（从摘要扩展/优化结构/补充细节/检查一致性）；规则（提取规则/检查冲突/合并相似）；LaTeX（编译检查/引用格式化/公式校对）。

**新增后端端点**（`/api/v1/ai/*`）：`rewrite`、`chat`、`audit`、`extract-rules`、`summarize`，共享 `document_context` 参数。

### 3.4 生成工作台（GenerateWorkspace）

- **四种模式**：自然语言生成 / 从参考资料生成 / 对话式模板填充 / 迭代优化。
- 左侧配置区（40%）+ 右侧预览区（60%，复用文档画布）。
- 生成后配置区切换为迭代优化：`[展开更多][精简内容][调整语气][补充数据]` + 自定义指令 + 版本回溯。
- **模板库**：新增 `TemplateLibrary`（网格卡片：期刊论文 / 项目报告 / 会议纪要 / 技术文档 / 合同范本 / 自定义），复用 `useJournalTemplates`；`JournalPanel` 文件与导出保持不变（其 P162 governance 测试与 barrel 契约不破坏）。
- **新增/增强后端**：`office/generate/template-chat`、`office/generate/iterate`、`office/templates`。

### 3.5 规则管理（RulesWorkspace）

规则生命周期：**AI 提取 → 查看 → 修改 → 组合 → 导出分享**。

- **AI 提取**：选源文档 → AI 提取格式/术语/结构规则 → 侧栏展示候选规则 → `[全部添加][逐条审核][取消]`。
- **查看**：按组分类、可折叠、搜索、显示名称/类型/严重度/启用状态。
- **修改**：详情面板编辑名称/类型/严重度/范围/描述/检查模式（regex 精确 / AI 语义）。
- **组合**：底部规则包 tag，拖入/移除，组间优先级，`[审校当前文档]` 执行。
- **导出**：`.sage-rules` 包 / Markdown / JSON，含组 + 规则 + 优先级。

**数据结构**：

```typescript
interface Rule {
  id: string;
  name: string;
  type: 'format' | 'terminology' | 'citation' | 'structure' | 'custom';
  severity: 'error' | 'warning' | 'info';
  scope: 'full' | 'heading' | 'body' | 'table' | 'caption';
  description: string;
  checkMode: 'regex' | 'ai';
  pattern?: string;
  aiPrompt?: string;
  enabled: boolean;
  groupId: string;
}

interface RuleGroup {
  id: string;
  name: string;
  description: string;
  rules: Rule[];
  priority: number;
  builtin: boolean;
}

interface RulePack {
  name: string;
  version: string;
  groups: RuleGroup[];
  exportedAt: string;
  exportedBy: string;
}
```

**新增后端**（`/api/v1/rules/*`）：`extract`、`groups`（GET/POST）、`:id`（PUT）、`check-conflicts`、`export`、`import`。

### 3.6 状态管理

新增 `officeWorkspaceStore.ts`（Zustand）：`activeDocument` / `previewMode` / `fidelityFailed` / `sidebarOpen` / `conversation` / `selection` / `generateMode` / `generatedDoc` / `activeRuleGroups`。

### 3.7 关键实现细节

- **选中文本检测与段落映射**：`selectionchange` 监听 + 判定 `anchorNode` 是否在画布内，写入 store；浮出操作条绝对定位于选区上方。
  - **Word（docx-preview）**：`DocxNativePreview` 渲染后按段落为每个 `<p>` 注入 `data-para-index`；选区向上查找最近的 `[data-para-index]` 得到段号，`regex` 规则与 AI 修改都以此为锚点，保证「diff 定位到第 N 段」可落到具体段落。
  - **PDF（iframe viewer）**：iframe 内文本选区无法跨源读取，回退为「截取选区前 80 字符作为上下文」传给 AI，写回时走原文 PDF 不支持的路径 → 禁用「应用到文档」，只提供「复制结果」。
  - **结构化视图**：直接读 DOM 段落索引（与 `DocumentAuditPanel` 现有锚点一致）。
- **规则冲突检测**：同 scope + 同 checkMode 的规则交给 LLM 判定"是否冲突"，展示冲突列表供用户取舍。
- **iframe 降级**：`onLoad` 检测空/报错或 5s 超时 → `fidelityFailed=true` → 结构化视图。

## 4. 实施步骤（里程碑）

### P1：画布 + 布局（基础）

- [x] 新增 `OfficeLayout` 三栏布局壳（左栏 + 主区 + AI 侧栏占位）。
- [x] 新增 `DocumentCanvas` / `DocumentEmptyState` / `DocumentPreview` / `DocumentToolbar`，合并选择+预览。
  - _注：空态 / 预览 / 工具条分别落在已有的 `OfficeIntake` / `OfficePreviewPanel` / 工具条 JSX，`DocumentCanvas` 是统一入口；`DocumentEmptyState` / `DocumentPreview` / `DocumentToolbar` 三个组件被合并进画布与现有入口，不再作为独立文件存在。_
- [x] 高保真默认 + 滚动修复 + 渲染失败自动降级。
- [x] `ConverterGuideDialog` 导出 PDF 无转换器引导。
- [x] 拖入新文件替换当前文档。
- [ ] `officeWorkspaceStore` 基础状态。
  - _延期到 P2（AI 侧栏）一起实现——侧栏需要工作区感知状态，届时再引入。_

**验证**：文档 Tab 功能全通；高保真默认、长文档可滚动、导出引导可用；E2E 通过。
  - _UI 冒烟需启动 Electron 桌面端；本 worktree 未安装 `node_modules`（仅含 vitest 所需依赖），无法在会话内启动。单元 / 集成测试覆盖了 5 条冒烟项：默认高保真 (`OfficePreviewPanel`)、长文档可滚动 (`OfficePreviewPanel.test`)、拖入替换 (`DocumentCanvas.test`)、导出引导 (`ConverterGuideDialog.test`)、左栏切换中栏预览 (`Office.tabs.test` + `OfficeLayout`)。UI 冒烟留给 PR 合并前由 reviewer 本地运行。_

### P2：AI 侧栏

- [ ] `AiSidebar` + `FloatingActionBar` + `ConversationArea` + `SuggestionCard` + `QuickActions` + `CommandInput`。
- [ ] 选中文本浮出 + 4 种能力（改写/润色、对话、指令式修改、审校建议）。
- [ ] 后端 `ai_routes.py`（rewrite/chat/audit/extract-rules/summarize）。
- [ ] 快捷指令按 Tab 变化。
- [ ] `OfficeEditPreviewDialog` 接入 AI 修改。

**验证**：侧栏交互全通；选中→改写→应用闭环；后端 AI 端点可用。

### P3：生成 + 规则

- [ ] `GenerateWorkspace` + 四模式（自然语言 / 参考资料 / 模板对话 / 迭代优化）。
- [ ] `TemplateLibrary` 在 generate tab 替代 `JournalPanel` 的渲染位置（"期刊文档助手" → "模板文档"；`JournalPanel` 文件与测试保留）。
- [ ] `RulesWorkspace` + 规则 CRUD / 组合 / 冲突检测 / 导出导入。
- [ ] 后端 `rules_routes.py` + `rule_repo.py` + 迁移。
- [ ] 文档归档：技术章节 + 用户手册章节。

**验证**：生成和规则功能全通；规则导出→导入往返一致；E2E 通过。

### 每阶段收尾

- 每阶段独立可合并，P2/P3 依赖 P1。
- 完成后同步 `docs/plans` 勾选、技术文档归档、两个分支（main / release/win7）cherry-pick 兼容性验证。

## 5. 风险评估与依赖

| 风险 | 影响 | 缓解 |
|------|------|------|
| Electron 21 / Chromium 106 的 iframe PDF viewer 不稳定 | 高保真不可用 | 降级路径必须可靠测试；blob URL（已有实践） |
| AI 侧栏 diff 需精确段落定位 | 应用改错位置 | 复用 `DocumentAuditPanel` 段落索引机制 |
| 规则导出格式跨版本兼容 | 旧包无法导入 | 版本字段 + 向后兼容解析器 |
| 重构期间旧功能回归 | 用户受影响 | 保留旧组件直到新组件通过测试，分阶段替换 |
| 双分支（main / win7）同步成本 | 移植冲突 | 新代码避免直接依赖 pydantic 2，使用 `pydantic_compat` 垫片 |
| AI 端点 token 消耗 | 成本上升 | 审校/提取走批量 + 缓存；语义检查可关 |

**依赖**：

- 现有 `officeApi` / `useOfficeDocuments` 保持兼容，作为数据层不重写。
- 现有 `OfficeEditPreviewDialog` / `DocumentAuditPanel` / `WordBatchAuditPanel` 复用，不重写。
- 后端 LLM 网关（现有 `llm_client`）复用。

## 6. 测试策略

| 层级 | 覆盖 |
|------|------|
| 单元 | store 状态流转、规则冲突检测、规则包序列化/反序列化 |
| 组件 | `DocumentCanvas`（空/有文件/拖入替换）、`AiSidebar`（浮出/对话/应用）、`RuleList`（CRUD） |
| 集成 | 后端 API（generate / iterate / extract / export / import） |
| E2E | 导入→预览→选中→AI 改写→应用；生成→迭代→导出；规则提取→组合→导出→导入 |
