# ZCode 启发优化方案 — Round 2

> 日期：2026-09-27
> 分支：feat/zcode-inspired-optimizations
> 前置：Round 1 (154d09182) 已完成设计系统文档 + 字体 token 迁移

---

## 已完成（Round 1）

- [x] `docs/technical/51-design-system.md` 设计系统文档
- [x] `text-ui-*` 字体 token 在 tailwind.config.js 中定义
- [x] `Message.tsx` + 侧栏 7 文件字号迁移至 `text-ui-*`
- [x] FSD import-lint 已预存在
- [x] 代码块折叠 / 表格横滚已预存在

---

## Round 2 优化项

### Task 1：消息 Turn 分组折叠（P0 — 可读性质变）✅

**目标**：连续的 assistant 工具调用 + 工具结果 + 文本回复折叠为一个 Turn Group，
默认只显示最终文本 + "N 个工具调用" 摘要，点击展开查看完整过程。

**涉及文件**：
- [x] 新建 `src/widgets/chat/turnGrouping.ts` — 分组逻辑（纯函数，易于测试）
- [x] 新建 `src/widgets/chat/TurnGroup.tsx` — 折叠 UI 组件
- [x] 修改 `src/widgets/chat/MessageList.tsx` — 渲染层接入分组逻辑
- [x] 新建 `src/widgets/chat/__tests__/turnGrouping.test.ts` — 20 测试全绿

**分组规则**：
1. user 消息 → 开启新 Turn Group
2. assistant 消息（含 tool_calls 或纯文本）→ 归入当前 Turn Group
3. tool_result → 归入当前 Turn Group
4. topic_separator → 不参与分组，独立渲染
5. system/error → 不参与分组，独立渲染

**UI 规格**：
- 折叠态：显示最终文本摘要（截断 200 字） + 工具调用计数徽标
- 展开态：完整显示所有消息，带左侧缩进线
- 流式消息不参与折叠（始终展开）

---

### Task 2：Surface 层级视觉层次（P1）✅

**目标**：修复 CSS 变量覆盖问题 + 增加 surface 层级 token，让暗色模式有微妙的视觉深度。

**涉及文件**：
- [x] 修改 `src/index.css` — 新增 `--color-ui-page/-panel/-card/-overlay/-fg/-subtle` token + dark 覆写
- [x] 修改 `tailwind.config.js` — 注册 `ui-page/ui-panel/ui-card/ui-overlay/ui-fg/ui-subtle` 颜色
- [x] 修改 `src/shared/ui/Button.tsx` + `Card.tsx` — 变体切换到新 token
- [x] 修改 `src/widgets/layout/Sidebar.tsx` — `bg-surface` → `bg-ui-panel`

**新增 token**：
```
--color-surface-base:     页面底色（= --color-background）
--color-surface-sidebar:  侧栏（比 base 深/浅一级）
--color-surface-header:   顶栏（与 sidebar 同级）
--color-surface-card:     卡片/消息气泡（比 base 略高）
--color-surface-popover:  弹出层（最高层级）
```

---

### Task 3：全局使用统计面板（P1）✅

**目标**：在 Settings 页面新增"使用统计" Tab，展示 token 消耗趋势和分布。

**涉及文件**：
- [x] 新建 `src/pages/settings/UsageStatsTab.tsx` — SVG 面积图 + 水平条形图 + 汇总卡片 + CSV 导出
- [x] 修改 `src/pages/settings/Settings.tsx` — 注册 tab + render
- [x] 修改 `src/pages/settings/settingsSearchIndex.ts` — 新增 `usage-stats` tab key + 4 条搜索索引
- [x] 修改 `src/shared/lib/i18n/zh.ts` + `en.ts` — 新增 `settings.tab.usage-stats` 翻译
- [x] 复用 `src/shared/api/usageApi.ts`（已有完整 API 层，无需新建）

**展示内容**：
- 近 7 天 token 消耗折线图（输入/输出/思考 三色堆叠）
- 按模型使用占比（水平条形图）
- 按 Provider 使用占比
- 当前 session 统计卡片（复用 SessionUsageBadge 数据）

**数据来源**：
- 后端已有 `GET /api/v1/usage/stats` 端点
- 前端用 React Query 拉取 + 缓存

---

### Task 4：命令面板增强（P2 — 2h）✅

**目标**：扩展 CommandPalette 覆盖面，统一搜索入口。

**涉及文件**：
- [x] 修改 `src/widgets/command/CommandPalette.tsx` — 新增 Settings 搜索组 + Skills 搜索组

**新增搜索类别**：
1. **Settings 搜索** — 客户端搜索设置项名称/关键词，点击跳转 `/settings`
2. **Skills 搜索** — 客户端过滤技能列表，点击跳转 `/skills`

**实现细节**：
- Settings: 复用 `searchSettings(search)` 纯函数，取前 8 条
- Skills: 打开面板时 `skillsApi.list()` 预加载，按名称/描述过滤，取前 6 条
- 综合兜底: 全局搜索 + 设置 + 技能全空时显示"无匹配结果"

---

## 实施顺序

1. Task 2: Surface 层级（基础 token，其他 task 可能用到）
2. Task 1: Turn 分组折叠（核心 UX 提升）
3. Task 3: 使用统计面板（新增功能）
4. Task 4: 命令面板增强（锦上添花）

## 验收标准

- [x] 连续 assistant + tool_calls 消息折叠为 Turn Group，可展开/收起
- [x] CSS 无双重定义，sidebar/header/content 暗色模式视觉层级分明
- [x] Settings 新增"使用统计" Tab，展示近 7 天折线图 + 模型分布
- [x] 命令面板可搜索 settings/skills（session/memory 已有后端全局搜索）

## 不在本轮范围

- Lexical 富文本输入框（工作量大，独立 PR）
- Git 集成可视化（需要后端配合）
- 远程工作区 / SSH / WSL（与核心场景弱相关）
- 插件市场（架构量大）
