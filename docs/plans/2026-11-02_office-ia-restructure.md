# 文档与验收（/office）信息架构梳理与优化方案

> 日期：2026-11-02 · 状态：实施中（M0–M7 已完成；M8 `release/win7` 同步待办）
> 范围：前端 `/office` 页面的信息架构与页面元素（IA/UX）；不改后端 API、不改 Agent 工具能力清单
> 分支：main 先落，`release/win7` 同步（纯前端，win7 适配成本低）

## 1. 背景与目标

用户反馈：**「文档与验收」部分的模块和页面元素太杂乱了**，需要梳理后优化。

现状：`/office` 自 2026-07 的 Phase 1.3 起步，历经 Office CRUD、期刊模板子系统、Word 文档智能（M0a–M6a）、LaTeX L0–L5c 等十余个能力批次，**每个批次都以「在页面末尾追加一个 `<section>`」的方式落 UI**。页面从 4 个文件选择器 + 预览，膨胀到今天的 **14 个常驻区块**。能力没有丢，但页面已经失去信息架构。

目标：
1. 按**任务**（导入/处理、生成、审校、LaTeX 写作）重新组织，而不是按**能力批次**平铺。
2. 首屏只呈现一个任务域，页面纵向长度大幅缩短。
3. 高级/低频能力可发现但默认降噪（渐进披露）。
4. 功能零损失、testid 兼容、既有测试可迁移；切 tab 不丢输入与结果。

## 2. 现状清点

`src/pages/Office.tsx` 583 行，直接 import 8 个办公子面板 + 7 个 LaTeX 面板 + 4 个经 barrel 引入的核心组件。`src/features/office/` 共 36 个源文件、约 10.6k 行；office + journal 相关测试约 278 个用例。

有工作区时，页面自上而下常驻渲染：

| # | 区块 | 组件 | 行数 | 性质 | 预期使用频率 |
|---|------|------|------|------|--------------|
| 1 | 暂存目录检查 | `OfficeStagingInspector` | 135 | 只读诊断（导入生命周期） | 极低 |
| 2 | 能力徽章条 | `OfficeCapabilityBar` | 215 | 环境信息（soffice/PDF/LaTeX 可用性） | 被动展示 |
| 3 | 文件选择 ×4 | `OfficeFilePicker` | 260 | 核心：导入+读取 | 高 |
| 4 | 预览面板 | `OfficePreviewPanel`（内嵌 `DocumentAuditPanel`） | 735（+476） | 核心：预览/导出 PDF/编辑预览/Word 审校 | 高 |
| 5 | 文档列表 | `OfficeDocumentList` + `OfficeSnapshotPanel` | 440 + 293 | 核心：历史/归档/批量/快照 | 中高 |
| 6 | 编辑预览弹窗 | `OfficeEditPreviewDialog` | 795 | 预览面板内触发 | 中 |
| 7 | 生成表单 | `OfficeGenerateForm`（含模板模式） | 786 | 生成 OOXML/PDF | 中 |
| 8 | 期刊模板助手 | `JournalPanel`（+ `useJournalTemplates` 等） | ~250+ | 生成/校验期刊论文 | 低 |
| 9 | Word 规则抽取 | `WordRuleExtractionPanel` | 332 | 规范配置（规则包） | 低 |
| 10 | LaTeX 项目导入 | `LatexProjectImportPanel` | 129 | LaTeX：zip 导入 | 中低 |
| 11 | LaTeX 模板助手 | `LatexTemplatePanel` | 249 | LaTeX：槽位填充 | 中低 |
| 12 | LaTeX 源码审校 | `LatexAuditPanel` | 141 | LaTeX：审校 | 中低 |
| 13 | PDF 版式审计 | `LatexPdfAuditPanel` | 169 | LaTeX：审校 | 中低 |
| 14 | 投稿合规检查 | `LatexCompliancePanel` | 307 | LaTeX：审校 | 中低 |
| 15 | 期刊规范档案 | `LatexProfileLibraryPanel` | 254 | LaTeX：规范/档案 | 低 |
| 16 | 编译与红字版 | `LatexBuildPanel` | 256 | LaTeX：编译 | 中低 |

（另有 `OfficeDeliveryDrawer` / `OfficeStructuredPreviews` 在聊天产物与任务中心挂载，不在本页面，但会跳转到 `/office`。）

## 3. 问题诊断

1. **任务混杂**：① 导入/预览/管理已有文档（处理流）、② 生成新文档（生成流）、③ Word 审校与规则（审校流）、④ LaTeX 论文项目（写作流）——四条互不相关的任务被纵向堆在同一个页面里，页头没有任何分区。
2. **诊断与高级面板抢位**：`OfficeStagingInspector` 是导入异常时才需要的只读诊断，却占据页面最顶部；7 个 LaTeX 面板无条件全部展开，用户没有 LaTeX 需求时也要承受全部噪音。
3. **「模板」概念四套并存**：生成表单的 OOXML 模板模式（`OfficeGenerateForm`）、期刊模板（`JournalPanel`）、Word 范本规则抽取（`WordRuleExtractionPanel` 的 template 模式）、LaTeX 模板助手——四者入口分散在页面不同位置，用户无法建立心智模型。
4. **无导航**：页面没有任何 tab、锚点、目录或搜索；14 个区块只能滚动寻找，滚动深度以屏计。
5. **标题不一致**：侧栏叫「文档与验收」，页内 H1 是「Office 文档」（`office.title`），help/欢迎页又用「文档与验收 / Documents and review」。
6. **视觉不一致**：`JournalPanel` 用硬编码 slate 色（`text-slate-800/slate-500`）且根节点 `flex h-full`（在 `overflow-y-auto` 的 auto-height 页面里语义错误）；其余面板走设计 token（`text-text`/`bg-bg-subtle`/`border-border`）。`WordRuleExtractionPanel` 等 LaTeX 面板的中文文案为硬编码，未走 i18n。
7. **深链缺失**：`OfficeDeliveryDrawer`/产物面板只能跳到 `/office` 默认状态；无法直达「生成」或「LaTeX 审校」。
8. **状态保持风险**：各面板把输入路径、审计结果保存在组件本地 `useState`。若简单地做 tab 卸载/重挂，切 tab 会丢失全部输入与结果——tab 化必须配 keep-alive。

## 4. 设计原则

- **按任务分组（job-to-be-done）**：处理 / 生成 / 审校 / LaTeX 四个域。
- **首屏 = 最高频**：「文档处理」是默认 tab。
- **渐进披露**：低频、配置类、诊断类能力降为折叠卡、二级 tab 或状态浮层。
- **状态保持**：tab 懒挂载、激活后常驻（`hidden` 隐藏而非卸载），切换不丢输入与结果。
- **单一入口**：一个功能只出现在一个地方；不复用视觉而语义不同的入口。
- **对齐既有先例**：设置页 IA 整理（PR #2657，tab + 单一 registry）与 `ProjectGovernance.tsx` 的 `role="tablist"` 模式；把 tab 容器抽成合规公共组件（`tab` + `tabpanel` + 键盘导航），避免每页各写一套。

## 5. 推荐方案：顶层 4 Tab + LaTeX 二级分组

```
/office                                      H1：文档与验收          [环境 ●]
┌──────────────────────────────────────────────────────────────────────┐
│ [文档处理] [文档生成] [审校与规范] [LaTeX]                              │
├──────────────────────────────────────────────────────────────────────┤
│ 文档处理（默认）                                                       │
│   ┌ 选择文件（PPT/Word/Excel/PDF） ┐ ┌ 预览 / 编辑预览 / 导出 PDF ┐    │
│   ├────────────────────────────────┴─┴──────────────────────────────┤    │
│   │ 文档列表（进行中/已归档 · 批量 · 历史版本）                       │    │
│ 文档生成                                                               │
│   ┌ 生成新文档（自由表单 / 模板模式，含生成审计摘要）┐                  │
│   └ [▸ 期刊模板助手]（折叠卡，默认收起）            ┘                  │
│ 审校与规范                                                             │
│   ┌ Word 规则抽取（规范/范本 → 规则包 → 复核保存）┐                    │
│   └ 审校说明卡：Word 审校在预览面板内 →「去文档处理」┘                 │
│ LaTeX                                                                  │
│   [项目与编译] [模板与规范] [审校与合规]                                 │
│   项目与编译：项目导入 + 编译与红字版                                   │
│   模板与规范：模板助手 + 期刊规范档案                                   │
│   审校与合规：源码审校 + PDF 版式审计 + 投稿合规检查                    │
└──────────────────────────────────────────────────────────────────────┘
```

**逐项归置**

| 区块 | 去向 |
|------|------|
| 文件选择 ×4、预览、编辑预览、文档列表、快照、批量 | Tab「文档处理」（保持左右两栏 + 列表布局） |
| 生成表单 | Tab「文档生成」 |
| 期刊模板助手 | Tab「文档生成」内的折叠卡（默认收起），并修 `h-full`/slate 硬编码 |
| Word 规则抽取 | Tab「审校与规范」 |
| 7 个 LaTeX 面板 | Tab「LaTeX」的 3 个二级 tab，按工作流归组 |
| 能力徽章条 | 页头右侧「环境」胶囊按钮 → popover（徽章列表 + 暂存检查入口） |
| 暂存目录检查 | 收进「环境」popover 的「检查暂存目录（只读）」 |

**深链与入口**

- URL：`/office?tab=documents|generate|rules|latex&latex=project|template|audit`（`useSearchParams`），非法值回落默认。
- `OfficeDeliveryDrawer`、聊天产物面板的「去处理」跳到 `?tab=documents`；未来生成类产物跳 `?tab=generate`。
- 欢迎页卡片、帮助文档同步指向新 tab。

**keep-alive 实现**

- 顶层 tab 全部**懒挂载**（首次激活才渲染），激活过的 tab 用 `hidden` 常驻，`tabpanel` 容器保持 `aria-labelledby` 关联。
- LaTeX 二级 tab 同策略；三个子 tab 的容器也常驻。
- 这样首次进入 `/office` 时不再一次性挂载 7 个 LaTeX 面板（它们 mount 时会拉 capabilities/profiles），首屏请求量同步下降。

**顺手清理（随对应 tab 落地）**

- `JournalPanel`：`h-full` → 自适应高度；slate 硬编码 → 设计 token。
- 页面 H1 统一为「文档与验收」（`office.title` zh/en 同步修正），与侧栏一致。
- `WordRuleExtractionPanel` 等面板中文文案接入 i18n（可与本批次解耦，列为可选）。

## 6. 方案对比

| 方案 | 做法 | 优点 | 缺点 |
|------|------|------|------|
| A. 仅折叠 | 每区块包 `<details>`，默认只开核心 | 改动最小 | 14 个折叠标题本身就是噪音；嵌套滚动更难用；不解决任务分组 |
| **B. 顶层 Tabs + LaTeX 二级分组（推荐）** | 4 个任务域 tab，LaTeX 内部 3 子 tab | 一次到位解决混杂与长度；改动集中在前端挂载层；可平滑演进 | 需要公共 Tabs 组件 + keep-alive + 测试迁移 |
| C. 路由拆分 + 侧栏子导航 | `/office/documents`、`/office/latex` 等独立路由 | 结构最彻底，可独立分享 | 侧栏已有 3 组导航，再加子级负担重；从聊天/产物跳转需二次跳转；改动面最大 |

推荐 **B**。若后续决定把 LaTeX 升级为独立侧栏入口（「论文投稿」），B 的 LaTeX tab 内容可整体平移为新路由，不返工。

## 7. 实施步骤（里程碑）

- [x] M0 脚手架：抽公共 `TabList/TabPanel`（a11y：`role=tablist/tab/tabpanel` + 左右键切换 + `aria-selected`）；`/office` 接入 URL 参数；keep-alive 容器；H1 文案统一。
      → `src/pages/office/officeTabs.ts`（URL 参数解析 + `useKeepAliveTabs`）、`src/pages/Office.tsx`（复用既有 `src/shared/ui/Tabs/Tabs.tsx` 的 Radix 封装 + `forceMount`/`hidden`）。
      说明：未新建跨页公共 Tabs 组件 —— 仓库已有 `src/shared/ui/Tabs/Tabs.tsx`（Radix 封装，自带 `tablist/tab/tabpanel` 角色与键盘导航），
      直接复用即可；新增公共组件反而会与既有封装重复。
- [x] M1 文档处理 tab：迁移 pickers + preview + 文档列表；testid 全部保留；`Office.workspace.test.tsx` 适配。
- [x] M2 文档生成 tab：`OfficeGenerateForm` + `JournalPanel` 折叠卡；顺手修 `h-full` 与 slate 色。
- [x] M3 审校与规范 tab：`WordRuleExtractionPanel` + 审校说明卡（按钮切换到文档处理）。
- [x] M4 LaTeX tab：3 个二级 tab 归置 7 个面板（组件本身不改）→ `src/pages/office/OfficeLatexTab.tsx`。
- [x] M5 诊断降噪：能力徽章条 → 页头「环境」popover；`OfficeStagingInspector` 移入；空态精简。→ `src/pages/office/OfficeEnvironmentButton.tsx`。
- [x] M6 入口与深链：`OfficeDeliveryDrawer`/产物面板跳转带 `tab`；欢迎页与帮助文档更新。
      → `OfficeDeliveryDrawer.tsx`（拒绝后跳 `?tab=documents`）、`slashCommands.ts`（`/office` → `?tab=documents`，`/journal` → `?tab=generate`）。
      说明：`Sidebar.tsx` / `TaskCenterWidget.tsx` / `commandItems.ts` / `Welcome.tsx` 的 `/office` 入口落在默认 tab，无需改动。
- [x] M7 测试：更新/新增 tab 切换、keep-alive 状态保持、URL 深链、a11y 用例；跑 office 全量 + 前端全量。
      → 新增 `src/pages/__tests__/Office.tabs.test.tsx`（12 例）；更新 `Office.workspace.test.tsx`、`slashCommands.navigate.test.ts`。
      注意：Radix Tabs 在 `onMouseDown` 激活（不是 `onClick`），测试须 `fireEvent.mouseDown(trigger, { button: 0, ctrlKey: false })`。
- [ ] M8 `release/win7` cherry-pick（纯前端，注意 baseline 与文档编号冲突）。

## 8. 风险与依赖

- **既有测试 278 例**：`Office.workspace.test.tsx` 只 stub 了 barrel 中的部分组件，`JournalPanel` 与 7 个 LaTeX 面板是真实渲染的；tab 化会改变默认挂载集合 → 测试需要按新结构显式 mock 或按 tab 激活断言。
- **首次切换延迟**：懒挂载后首次切到 LaTeX tab 会触发 7 个面板 mount 时的 capabilities/profiles 请求；需 skeleton/loading 或 idle 预取。
- **架构门禁**：新增公共组件与页面文件会改 `architecture-baseline.json`；按分支各自更新。
- **体积棘轮**：新公共组件若被多页面引用，注意 bundle 体积门禁。
- **i18n**：tab 标签、说明卡 zh/en 同步；面板内既有硬编码中文先加键再替换。
- **a11y**：`ProjectGovernance` 的 tablist 无 `tabpanel` 且无键盘导航，公共组件需补全，不要复制其缺口。
- **后端零改动**：无 API/工具变化，故无 win7 兼容性风险；但 win7 文档编号（technical/user-manual）需避让。

## 9. 验收标准

- 有工作区时首屏只显示一个任务域；「文档处理」tab 页面纵向长度 ≤ 1.5 屏（1080p）。
- 现有全部功能在新 IA 中可达，既有 `data-testid` 不变（新增 tab 容器另加）。
- 切换 tab 后各面板的输入路径、审计结果、表单内容不丢失。
- `/office?tab=latex&latex=audit` 可直达；非法参数回落默认 tab。
- office 相关测试全绿 + 前端全量测试绿 + 架构/体积门禁绿。
- 双分支（main / release/win7）对齐。

## 10. 不在本轮范围

- 不改 Office/Word/LaTeX 后端 API 与 Agent 工具。
- 不合并四套「模板」子系统（语义合并是独立课题，见 `2026-10-31_word-document-intelligence.md` 的 M5c 等后续）。
- 不新建侧栏入口（LaTeX 独立页列为 P2 产品讨论）。
- 不改预览面板/审校的深水区交互（定位高亮、修订视图等）。
