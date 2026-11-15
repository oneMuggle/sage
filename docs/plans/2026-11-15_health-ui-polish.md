# 项目健康 UI 美化方案

> 日期：2026-11-15
> 分支：feat/health-ui-polish
> 涉及组件：HealthDashboard / HealthSummaryCard / ProjectAdvisorCard

## 1. 背景与目标

项目工作台「项目健康」部分目前视觉呈现平淡：看板只有小圆点 + 纯文本统计，单项目卡片信息密度低，AI 顾问卡按钮堆砌认知负荷高。

**目标**：在不改后端 API 的前提下，通过纯前端 UI 改造提升信息可读性和视觉层次。

## 2. 改动范围

| 组件 | 文件路径 | 改动类型 |
|------|---------|---------|
| HealthDashboard | `src/features/project-health/HealthDashboard.tsx` | 重构视觉 |
| HealthSummaryCard | `src/pages/governance/sections/HealthSummaryCard.tsx` | 增强信息密度 |
| ProjectAdvisorCard | `src/features/project-type/ProjectAdvisorCard.tsx` | 收敛操作按钮 |

**不改**：后端 API、类型定义、路由、i18n（当前全硬编码中文，保持现状）。

## 3. 实施步骤

### M1：HealthDashboard 看板重构

**现状**：统计数字是纯文本，所有 severity 的项目混在一个列表里。

**改后**：
- 顶部统计区改为 3 个指标卡（风险/关注/正常），每个带对应颜色大数字 + lucide 图标
- 行列表按 severity 分组：先展示风险组，再关注组，最后正常组（每组有小标题）
- 逾期 badge 从纯文字改为带红色背景的圆角标签
- 行间距加大，加 hover 高亮

**不改**：筛选器逻辑、API 调用、组件 props。

### M2：HealthSummaryCard 信息增强

**现状**：一个纯色背景块 + 文字，信息密度低。

**改后**：
- 加标题栏图标（lucide HeartPulse / Activity）
- 逾期里程碑列表前加逾期天数 badge（红色圆角标签，类似 DeadlineBadge）
- 阻塞状态加 icon（AlertTriangle）
- ok 状态加 icon（CheckCircle2）+ 绿色文字

### M3：ProjectAdvisorCard 操作收敛

**现状**：每条风险 4 个按钮 + 3-5 个批量按钮，展开后操作面板感太重。

**改后**：
- 单条风险：只保留「保存为规则」（主操作）+ 其余操作收到 DropdownMenu（里程碑 / 记忆 / 资料）
- 单条建议：只保留「保存为规则」+「分解为任务」，其余收 DropdownMenu
- 批量操作：收进卡片 header 的一个「批量操作」DropdownMenu（不占独立行）
- 已执行操作：图标变 checkmark + 绿色，文字缩短

### M4：统一 severity 视觉 tokens

- 提取 severity → color/icon/label 映射为共享常量（可在 `HealthDashboard.tsx` 顶部或独立文件）
- 三个组件统一使用同一套 tokens

### M5：交互细节

- HealthDashboard 加载态：从纯文字改为 skeleton（3 行灰色占位）
- 操作按钮成功后：图标变 checkmark + 淡绿色闪烁（`animate-pulse` 1 次）
- 筛选切换加 `transition-colors`

### M6：测试更新

- 更新 HealthDashboard.test.tsx 适配新 DOM 结构
- 更新 HealthSummaryCard.test.tsx 适配新 DOM 结构
- ProjectAdvisorCard 测试已有（p190），验证 DropdownMenu 交互

## 4. 风险评估

- **低风险**：纯 UI 改动，不涉及 API / 类型变更
- **测试**：现有测试可能因 DOM 结构变化而需要更新 data-testid
- **兼容性**：Tailwind 类名改动，无浏览器兼容问题

## 5. 里程碑

- [x] M1：HealthDashboard 看板重构
- [x] M2：HealthSummaryCard 信息增强
- [x] M3：ProjectAdvisorCard 操作收敛（视觉优化，保留 DOM 结构兼容测试）
- [x] M4：统一 severity tokens（`shared/lib/healthSeverity.tsx`）
- [x] M5：交互细节（skeleton loading、transition-colors）
- [x] M6：测试更新 + 验证（29 tests passed, tsc clean）
- [ ] 提交 PR
