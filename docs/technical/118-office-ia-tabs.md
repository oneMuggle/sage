# 118. /office 信息架构：按任务域分组的顶层 Tab

> 日期：2026-11-02 · 分支：main `feat/office-ia-restructure`（#2797）→ cherry-pick 到 `release/win7`
> 范围：前端渲染层。不改后端 API，不改 Agent 工具清单，不改任何面板的业务逻辑。

## 1. 问题

`/office`（侧栏「文档与验收」）自 2026-07 起以「每个能力批次在页面末尾追加一个 `<section>`」的方式累积，页面膨胀到 **十余个常驻区块**：

| 区块 | 组件 | 使用频率 |
|------|------|----------|
| 暂存目录检查 | `OfficeStagingInspector` | 极低（仅导入异常时） |
| 能力徽章条 | `OfficeCapabilityBar` | 被动展示 |
| 文件选择 ×4 | `OfficeFilePicker` | 高 |
| 预览面板 | `OfficePreviewPanel` | 高 |
| 文档列表 / 快照 | `OfficeDocumentList` / `OfficeSnapshotPanel` | 中高 |
| 编辑预览弹窗 | `OfficeEditPreviewDialog` | 中 |
| 生成表单 | `OfficeGenerateForm` | 中 |
| 期刊模板助手 | `JournalPanel` | 低 |

具体症状：

1. **任务混杂** —— 处理流 / 生成流两条互不相关的任务纵向平铺，页面无分区。
2. **诊断抢位** —— 只读诊断组件占据页面最顶部，不管用不用都占首屏。
3. **「模板」入口分散** —— OOXML 模板模式与期刊模板助手各自独立成块。
4. **无导航** —— 只能滚动寻找，深度以屏计。
5. **标题不一致** —— 侧栏「文档与验收」vs 页内 H1「Office 文档」。
6. **深链缺失** —— 产物面板只能跳 `/office`，无法直达「生成」。

## 2. 方案

按**任务域**重组为顶层 tab：

```
/office?tab=documents|generate
```

| Tab | 内容 |
|-----|------|
| **文档处理**（默认） | 文件选择 ×4、预览、编辑预览、文档列表、快照、批量 |
| **文档生成** | `OfficeGenerateForm`；`JournalPanel` 收在默认收起的 `<details>` 折叠卡内 |

诊断降噪：能力徽章条与暂存目录检查收进页头「环境」胶囊按钮的 popover。

### 2.1 与 main 的差异（win7 特有）

main 侧有 4 个任务域（多「审校与规范」「LaTeX」两个，LaTeX 内再分 3 个二级 tab）。这两个域依赖的功能栈尚未同步到 `release/win7`：

| 缺失项 | 来源 | 状态 |
|--------|------|------|
| `backend/api/office_latex_routes.py` | LaTeX L0–L5c（main） | 未同步 |
| `Latex*Panel` ×7 | LaTeX L0–L5c（main） | 未同步 |
| `WordRuleExtractionPanel` / `WordBatchAuditPanel` | Word 文档智能 M0a–M6c（main #2733–#2791） | 未同步 |

因此 win7 只暴露已具备功能的两个分区。**`OFFICE_TAB_IDS` 是唯一事实源** —— 后续功能同步到位后，往数组里加 id、补面板、补 i18n 键即可，路由与 keep-alive 逻辑无需改动。

## 3. 实现要点

### 3.1 URL 为唯一事实源

`src/pages/office/officeTabs.ts` 定义参数名与解析：

```ts
export const OFFICE_TAB_PARAM = 'tab';
export const OFFICE_TAB_IDS = ['documents', 'generate'] as const;
export const DEFAULT_OFFICE_TAB = 'documents';
```

`Office.tsx` 用 `useSearchParams()` 读取当前 tab，非法值经 `parseOfficeTab()` 回落默认 —— 深链、浏览器前进后退、书签都因此可用，且永远不会渲染出空白面板。

默认值**不写回 URL**（`documents` 时删除 `tab` 参数），避免默认态污染书签。

### 3.2 keep-alive

各面板把输入路径、审计结果存在组件本地 `useState`。直接卸载/重挂会丢失全部输入与结果，因此：

- 面板用 Radix `forceMount` + `hidden={activeTab !== id}` 常驻（视觉隐藏而非卸载）；
- 首次激活才挂载 —— `useKeepAliveTabs(active)` 维护已激活过的 id 列表，未激活过的 tab 不渲染内容。

结果：首次进入 `/office` 只挂载当前任务域的面板；切走再切回，表单与结果仍在。

### 3.3 复用既有 Tabs 封装

仓库已有 `src/shared/ui/Tabs/Tabs.tsx`（`@radix-ui/react-tabs` 封装，自带 `tablist/tab/tabpanel` 角色、`aria-selected` 与键盘导航），直接复用，未新建公共组件。

> **Radix Tabs 的激活时机**：`TabsTrigger` 在 `onMouseDown`（`button === 0 && !ctrlKey`）、`onKeyDown`（Enter/Space）时激活，**不在 `onClick` 激活**。测试里必须 `fireEvent.mouseDown(trigger, { button: 0, ctrlKey: false })`，`fireEvent.click` 不会触发 `onValueChange`。

### 3.4 文件拆分

`src/pages/Office.tsx` 保持在架构预算（800 行）内：

| 文件 | 职责 |
|------|------|
| `src/pages/Office.tsx` | 页面骨架、tab 编排、documents/generate 两个 tab 的内容 |
| `src/pages/office/officeTabs.ts` | URL 参数常量、解析、keep-alive hook |
| `src/pages/office/OfficeEnvironmentButton.tsx` | 页头「环境」popover（能力徽章 + 暂存检查） |

### 3.5 顺手清理

- `JournalPanel`：根节点 `flex h-full` → 自适应高度（页面是 `overflow-y-auto` 的 auto-height 容器，`h-full` 语义错误）；硬编码 `text-slate-800/slate-500` → 设计 token `text-text`/`text-muted`。
- `office.title`：zh「Office 文档」→「文档与验收」，en「Office Documents」→「Documents and Review」，与侧栏一致。
- 新增 8 个 i18n 键（zh/en 同步）：`office.tabs.label`、`office.tab.documents`、`office.tab.generate`、`office.env.title`、`office.env.capabilities`、`office.env.staging`、`office.generate.journal.title`、`office.generate.journal.hint`。

### 3.6 深链入口

| 入口 | 目标 |
|------|------|
| `OfficeDeliveryDrawer` 拒绝后跳转 | `/office?tab=documents` |
| slash `/office` | `/office?tab=documents` |
| slash `/journal` | `/office?tab=generate`（JournalPanel 在该 tab 的折叠区内） |
| 侧栏 / 任务中心 / 命令面板 / 欢迎页 | `/office`（落在默认 tab，无需改动） |

## 4. 测试

`src/pages/__tests__/Office.tabs.test.tsx` 覆盖：默认 tab 与空 URL、`aria-selected` 与 `hidden` 属性、两个 trigger 的 URL 同步、切回默认 tab 清除 `tab` 参数、两种深链（合法 / 非法回落）、keep-alive 保持 mounted、`<details>` 默认收起、Enter 键激活。

`src/pages/__tests__/Office.workspace.test.tsx` 更新（stub 新增的 JournalPanel）、`src/widgets/chat/__tests__/slashCommands.navigate.test.ts` 更新（深链路由断言）。

> **win7 注意**：`vi.mock()` 指向的模块路径必须在本分支真实存在。main 侧 mock 了 `../office/OfficeLatexTab` 与 `../../features/office/WordRuleExtractionPanel`，这两个文件在 win7 不存在，直接照搬会让 Vitest 模块解析失败 —— cherry-pick 时必须删掉这两个 mock。

## 5. 兼容性

纯前端改动，无后端 API 与工具变更 —— `release/win7` cherry-pick 无 Python 3.8 / pydantic v1 适配成本。

需要注意两点：

1. **win7 侧文档编号避让** —— main 的 `123-office-ia-tabs.md` 在 win7 撞上 `117=桌面宠物`，改号为 `118`。
2. **feature 缺口** —— 见 §2.1，win7 只落地两个任务域。
