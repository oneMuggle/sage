# 123. /office 信息架构：顶层 Tab + LaTeX 二级分组

> 日期：2026-11-02 · 分支：`feat/office-ia-restructure`（main）→ cherry-pick 到 `release/win7`
> 范围：前端渲染层。不改后端 API，不改 Agent 工具清单，不改任何面板的业务逻辑。

## 1. 问题

`/office`（侧栏「文档与验收」）自 2026-07 起以「每个能力批次在页面末尾追加一个 `<section>`」的方式累积，历经 Office CRUD、期刊模板子系统、Word 文档智能（M0a–M6c）、LaTeX L0–L5c 等十余批，页面膨胀到 **14+ 个常驻区块**：

| 区块 | 组件 | 使用频率 |
|------|------|----------|
| 暂存目录检查 | `OfficeStagingInspector` | 极低（仅导入异常时） |
| 能力徽章条 | `OfficeCapabilityBar` | 被动展示 |
| 文件选择 ×4 | `OfficeFilePicker` | 高 |
| 预览面板（内嵌审校） | `OfficePreviewPanel` | 高 |
| 文档列表 / 快照 | `OfficeDocumentList` / `OfficeSnapshotPanel` | 中高 |
| 编辑预览弹窗 | `OfficeEditPreviewDialog` | 中 |
| 生成表单 | `OfficeGenerateForm` | 中 |
| 期刊模板助手 | `JournalPanel` | 低 |
| Word 规则抽取 | `WordRuleExtractionPanel` | 低 |
| Word 批量审校 | `WordBatchAuditPanel` | 低 |
| LaTeX ×7 | `Latex*Panel` | 中低 |

具体症状：

1. **任务混杂** —— 处理流 / 生成流 / 审校流 / LaTeX 写作流四条互不相关的任务纵向平铺，页面无分区。
2. **诊断抢位** —— 只读诊断组件占据页面最顶部；7 个 LaTeX 面板无条件全部展开，用户无 LaTeX 需求时也承担全部噪音与 mount 请求。
3. **「模板」四套并存** —— OOXML 模板模式、期刊模板、Word 范本规则抽取、LaTeX 模板助手，入口分散。
4. **无导航** —— 只能滚动寻找，深度以屏计。
5. **标题不一致** —— 侧栏「文档与验收」vs 页内 H1「Office 文档」。
6. **深链缺失** —— 产物面板只能跳 `/office`，无法直达「生成」或「LaTeX 审校」。

## 2. 方案

按**任务域**重组为 4 个顶层 tab，LaTeX 内部再分 3 个二级 tab：

```
/office?tab=documents|generate|rules|latex[&latex=project|templates|audit]
```

| Tab | 内容 |
|-----|------|
| **文档处理**（默认） | 文件选择 ×4、预览、编辑预览、文档列表、快照、批量 |
| **文档生成** | `OfficeGenerateForm`；`JournalPanel` 收在默认收起的 `<details>` 折叠卡内 |
| **审校与规范** | `WordRuleExtractionPanel`、`WordBatchAuditPanel`、审校说明卡（按钮跳「文档处理」） |
| **LaTeX** | 二级 tab：`project`（项目导入 + 编译）/ `templates`（模板助手 + 期刊规范档案）/ `audit`（源码审校 + PDF 版式审计 + 投稿合规） |

诊断降噪：能力徽章条与暂存目录检查收进页头「环境」胶囊按钮的 popover。

### 2.1 方案对比与设计原则

初稿评估过三条重组路径：

| 方案 | 做法 | 优点 | 缺点 |
|------|------|------|------|
| A. 仅折叠 | 每区块包 `<details>`，默认只开核心 | 改动最小 | 十余个折叠标题本身就是噪音；嵌套滚动更难用；不解决任务分组 |
| **B. 顶层 Tab + LaTeX 二级分组（推荐）** | 4 个任务域 tab，LaTeX 内部 3 子 tab | 一次到位解决混杂与长度；改动集中在前端挂载层；可平滑演进 | 需要 keep-alive + 测试迁移 |
| C. 路由拆分 + 侧栏子导航 | `/office/documents`、`/office/latex` 等独立路由 | 结构最彻底，可独立分享 | 侧栏已有 3 组导航，再加子级负担重；从聊天/产物跳转需二次跳转；改动面最大 |

选 B 的理由：任务混杂与页面长度是核心痛点，A 不解决分组，C 的改动面与收益不成比例。B 的改动集中在前端挂载层；若后续把 LaTeX 升级为独立侧栏入口，tab 内容可整体平移为新路由，不返工。

落地时遵循的设计原则：

- **按任务分组（job-to-be-done）** —— 域的划分依据是「用户要完成什么」，不是「哪个能力批次」。
- **首屏 = 最高频** —— 「文档处理」是默认 tab。
- **渐进披露** —— 低频、配置类、诊断类能力降为折叠卡、二级 tab 或状态浮层。
- **状态保持** —— tab 懒挂载，激活后常驻（`hidden` 隐藏而非卸载），切换不丢输入与结果。
- **单一入口** —— 一个功能只出现在一个地方；不复用视觉而语义不同的入口。
- **对齐既有先例** —— 复用设置页 IA 整理（PR #2657）的单一 registry 思路与 `src/shared/ui/Tabs/Tabs.tsx`，不另造公共组件。

## 3. 实现要点

### 3.1 URL 为唯一事实源

`src/pages/office/officeTabs.ts` 定义参数名与解析：

```ts
export const OFFICE_TAB_PARAM = 'tab';
export const OFFICE_LATEX_PARAM = 'latex';
export const OFFICE_TAB_IDS = ['documents', 'generate', 'rules', 'latex'] as const;
export const DEFAULT_OFFICE_TAB = 'documents';
```

`Office.tsx` 用 `useSearchParams()` 读取当前 tab，非法值经 `parseOfficeTab()` 回落默认 —— 深链、浏览器前进后退、书签都因此可用，且永远不会渲染出空白面板。

默认值**不写回 URL**（`documents` 时删除 `tab` 参数），避免默认态污染书签。

切出 `latex` 时同步清除 `latex` 子参数，防止残留深链。

### 3.2 keep-alive

各面板把输入路径、审计结果存在组件本地 `useState`。直接卸载/重挂会丢失全部输入与结果，因此：

- 面板用 Radix `forceMount` + `hidden={activeTab !== id}` 常驻（视觉隐藏而非卸载）；
- 首次激活才挂载 —— `useKeepAliveTabs(active)` 维护已激活过的 id 列表，未激活过的 tab 不渲染内容。

结果：首次进入 `/office` 不再一次性 mount 7 个 LaTeX 面板（它们 mount 时会拉 capabilities/profiles），首屏请求量同步下降；切走再切回，表单与结果仍在。

### 3.3 复用既有 Tabs 封装

仓库已有 `src/shared/ui/Tabs/Tabs.tsx`（`@radix-ui/react-tabs` 封装，自带 `tablist/tab/tabpanel` 角色、`aria-selected` 与键盘导航），直接复用，未新建公共组件。

> **Radix Tabs 的激活时机**：`TabsTrigger` 在 `onMouseDown`（`button === 0 && !ctrlKey`）、`onKeyDown`（Enter/Space）时激活，**不在 `onClick` 激活**。测试里必须 `fireEvent.mouseDown(trigger, { button: 0, ctrlKey: false })`，`fireEvent.click` 不会触发 `onValueChange`。

### 3.4 文件拆分

`src/pages/Office.tsx` 保持在架构预算（800 行）内：

| 文件 | 职责 |
|------|------|
| `src/pages/Office.tsx` | 页面骨架、tab 编排、documents/generate/rules 三个 tab 的内容 |
| `src/pages/office/officeTabs.ts` | URL 参数常量、解析、keep-alive hook |
| `src/pages/office/OfficeLatexTab.tsx` | LaTeX 二级 tab 与 7 个面板的归置 |
| `src/pages/office/OfficeEnvironmentButton.tsx` | 页头「环境」popover（能力徽章 + 暂存检查） |

### 3.5 顺手清理

- `JournalPanel`：根节点 `flex h-full` → 自适应高度（页面是 `overflow-y-auto` 的 auto-height 容器，`h-full` 语义错误）；硬编码 `text-slate-800/slate-500` → 设计 token `text-text`/`text-muted`。
- `office.title`：zh「Office 文档」→「文档与验收」，en「Office Documents」→「Documents and Review」，与侧栏一致。
- 新增 17 个 i18n 键（zh/en 同步）：`office.tabs.*`、`office.tab.*`、`office.latex.*`、`office.env.*`、`office.generate.journal.*`、`office.rules.guide.*`。

### 3.6 深链入口

| 入口 | 目标 |
|------|------|
| `OfficeDeliveryDrawer` 拒绝后跳转 | `/office?tab=documents` |
| slash `/office` | `/office?tab=documents` |
| slash `/journal` | `/office?tab=generate`（JournalPanel 在该 tab 的折叠区内） |
| 侧栏 / 任务中心 / 命令面板 / 欢迎页 | `/office`（落在默认 tab，无需改动） |

## 4. 测试

新增 `src/pages/__tests__/Office.tabs.test.tsx`（12 例）覆盖：默认 tab 与空 URL、`aria-selected` 与 `hidden` 属性、四个 trigger 的 URL 同步、切出 LaTeX 清除子参数、三种深链、非法值回落、keep-alive 保持 mounted、`<details>` 默认收起、Enter 键激活。

更新 `src/pages/__tests__/Office.workspace.test.tsx`（stub 新增的三个子面板）、`src/widgets/chat/__tests__/slashCommands.navigate.test.ts`（深链路由断言）。

## 5. 兼容性

纯前端改动，无后端 API 与工具变更 —— `release/win7` cherry-pick 无 Python 3.8 / pydantic v1 适配成本。仅需注意 win7 侧文档编号避让。
