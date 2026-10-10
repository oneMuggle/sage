# Sage 桌面端第三轮 UI 与前端架构收官报告（2026-10-10）

> 关联前序文档：
> - 第一轮 UI 深度审计方案：`docs/mcp-sage-ui-deep-audit-plan-20261009.md`（PR `#1922`–`#1927`）
> - 第二轮 UI 深度优化方案：`docs/mcp-sage-ui-round2-optimization-plan-20261010.md`（PR `#1932`–`#1933`）
> - 本轮目标：完成全站 12 个一级路由页面的 48px (`h-12`) 顶栏壳层 (`PageHeader`) 100% 统一，并将 `architecture-baseline.json` 中剩余的 6 个 `>800` 行前端 (`src/`) 模块全部拆解归零（`6 -> 0`）。

---

## 一、全站 48px (`h-12`) 顶栏壳层 100% 统一（`UI-R3-P0`）

### 1. 背景与痛点
在第一轮（`Skills` / `ScheduledTasks` / `TodoPage`）与第二轮（`ChatHeaderBar` / `OfficePageHeader`）改造后，全站仍有 7 个二级功能页使用各自手写的非标顶栏（`border-b` 高度不一、标题字号从 `text-sm` 到 `text-lg` 不等、副标题换行挤压内容区高度）：
- `src/pages/Memory.tsx`（记忆管理页）
- `src/pages/Agents.tsx`（多智能体配置页）
- `src/pages/Orchestration.tsx`（多通道并行编排看板页）
- `src/pages/Projects.tsx`（项目工作台页）
- `src/pages/ModelCatalog.tsx`（模型目录与定价页）
- `src/pages/Arena.tsx`（Arena 控制台页）
- `src/pages/ArenaAccounts.tsx`（Arena 账号池页）

### 2. 落地方案
1. **全面接入 `<PageHeader />` 48px (`h-12`) 统一顶栏原语**：
   - `Memory.tsx`：移除手写 `<div className="p-4 border-b">`，接入 `<PageHeader icon={Brain} title={...} subtitle={...} actions={...} />`，导出 JSON 与自动提取开关收入右侧 `actions` 插槽。
   - `Agents.tsx`：移除内联 `<div className="flex items-center justify-between">`，外层改为 `flex flex-col h-full overflow-hidden`，顶部固定 `<PageHeader icon={Bot} />`，下方列表独立滚动。
   - `Orchestration.tsx`：移除双行 `<header className="px-6 py-4 border-b">`，将新建通道表单 (`orchestration-create-form`) 紧凑收纳进 `<PageHeader icon={GitBranch} actions={...} />`，释放纵向看板空间。
   - `Projects.tsx`：移除 `<header className="mb-5">`，升级为标准 `<PageHeader icon={FolderKanban} />` + 独立滚动内容区。
   - `ModelCatalog.tsx`：接入 `<PageHeader icon={BookOpen} testId="model-catalog-header" actions={...} />`，将刷新按钮收敛至顶栏右侧，保留粘性搜索与过滤栏。
   - `Arena.tsx` 与 `ArenaAccounts.tsx`：移除内联标题块，接入 `<PageHeader icon={Layers} />`（直接从 `../shared/ui/PageHeader` 导入以避免桶文件冷启动开销），将页签切换器、代理模式选择、添加账号与刷新操作收纳进 `actions` 插槽。

---

## 二、前端 `src/` 超大文件基线彻底清零（`UI-R3-P1`，`6 -> 0`）

### 1. 拆解明细对比表

| 原模块路径 | 拆解前行数 (`main` / `win7`) | 拆解后主模块行数 (`main` / `win7`) | 新增职责子模块（全部 `<= 800` 行） |
| --- | ---: | ---: | --- |
| `src/shared/api/types.ts` | `2470` / `2402` | `14` / `14` | `types/chatAndEventTypes.ts` (`669`/`661`)、`types/domainEntityTypes.ts` (`630`/`630`)、`types/officeDocTypes.ts` (`713`/`653`)、`types/templateAndTaskTypes.ts` (`462`/`462`) |
| `src/shared/api/demoInterceptors.ts` | `2184` / `2205` | `572` / `593` | `demoFixturesCore.ts` (`538`)、`demoFixturesSessionsAndAgents.ts` (`427`)、`demoOfficeAndSystemHandlers.ts` (`678`) |
| `src/features/send-message/useChat.ts` | `1304` / `1179` | `792` / `684` | `chatStreamRuntime.ts` (`595`/`576`) |
| `src/features/office/__tests__/OfficeEditPreviewDialog.test.tsx` | `960` / `960` | `500` / `500` | `buildUpdateOps.test.ts` (`462`) |
| `src/widgets/chat/progress/__tests__/TaskTreeSection.rerun.test.tsx` | `904` / `904` | `483` / `483` | `TaskTreeSection.elapsedAndCaps.test.tsx` (`479`) |
| `src/features/send-message/__tests__/useChat.test.ts` | `2007` / `2006` | `644` / `644` | `useChat.streamingAndGates.test.ts` (`634`)、`useChat.taskBoardEvents.test.ts` (`619`)、`useChat.transparencyAndSubagents.test.ts` (`468`/`467`) |

### 2. 架构门禁收紧结果
- 运行 `node scripts/architecture-check.mjs --tighten` 后：
  - `main` 分支从 `architecture-baseline.json` 中移除全部 **6 个** `src/` 条目（前端历史超标配额从 `6,821` 行降至 **`0` 行**）。
  - `release/win7` 分支从 `architecture-baseline.json` 中移除全部 **6 个** `src/` 条目（前端历史超标配额从 `6,734` 行降至 **`0` 行**）。
- 至此，整个 `src/` 前端代码库（含生产代码与单元测试）**100% 满足单文件 `<= 800` 行硬性架构红线**，零豁免残留。

---

## 三、三轮 UI 与前端架构优化全景汇总（Round 1 ~ Round 3）

| 轮次 | 核心成果 | 关联 PR (`main` / `win7`) |
| --- | --- | --- |
| **第一轮 (`UI-P0` ~ `UI-P2`)** | 顶栏 5 项会话控制收敛 + 单行极简输入盒、设置弹窗左导航+右内容双栏重构、字体阶梯令牌化、统一 `<EmptyState />` 与首批 `<PageHeader />` | `#1922`/`#1923`、`#1924`/`#1925`、`#1927`/`#1926` |
| **第二轮 (`UI-R2-P0` ~ `UI-R2-P2`)** | 顶栏会话标题双击重命名与更多菜单、粘贴长文本自动折叠芯片、回到底部未读流式胶囊、`OfficePageHeader` 紧凑化、`font-scale-baseline.json` 归零、拆解 4 个 `>800` 行组件 | `#1932` / `#1933` |
| **第三轮 (`UI-R3-P0` ~ `UI-R3-P1`)** | 剩余 7 个二级页 `<PageHeader />` 100% 统一、剩余 6 个 `>800` 行 `src/` 模块全部拆解、`architecture-baseline.json` 前端 `src/` 条目清零（`0` 豁免） | 本轮 PR |
