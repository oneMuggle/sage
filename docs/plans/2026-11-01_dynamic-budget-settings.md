# 动态迭代预算 P1：设置页参数暴露（2026-11-01）

> 分支：`feat/dynamic-budget-settings`  
> 基线：`origin/main` @ `190a6c9b5`  
> 前序：main #2741 / win7 #2749（动态预算 P0 已合并）

## 1. 目标

把 P0 中仅能通过 `SAGE_DYNAMIC_BUDGET_*` 环境变量调整的参数，暴露到
「设置 → 编排 → 动态迭代预算」：

- 总开关 `dynamicBudgetEnabled`；
- 各档初始预算 `budgetSimple / budgetMedium / budgetComplex / budgetLong`；
- 硬顶 `budgetHardCap`；
- 最大自动延长次数 `budgetMaxExtensions`。

优先级：**环境变量 > 设置页 > 代码默认**（env 保留 CI/运维覆盖能力）。

## 2. 涉及文件

### 后端

- `backend/orchestration/orch_settings.py`：新增 7 个字段、camelCase 映射与下界。
- `backend/core/legacy/iteration_budget.py`：新增 `BudgetConfig.from_settings()`。
- `backend/core/legacy/agent.py`：单次加载 OrchSettings，动态开关同时受设置页与 env 控制。
- `backend/data/settings_canonicalizer.py`：`LEGAL_ORCH_KEYS` + `ALIASES` 同步新增键
  （漏加会导致编排段保存 400 且前端静默吞错）。

### 前端

- `src/entities/setting/types.ts`：`OrchSettings` 与 `DEFAULT_ORCH_SETTINGS`。
- `src/entities/setting/settingsRegistry.ts`：设置项元数据（重置默认、搜索锚点）。
- `src/pages/settings/OrchestrationTab.tsx`：新增「动态迭代预算」区块。
- `src/pages/settings/settingsSearchEntries.ts`：搜索索引。
- `src/shared/lib/i18n/locales/{zh,en}/settingsUi.ts`：文案。

## 3. 实施步骤

- [x] 后端 OrchSettings 字段/映射/下界
- [x] `BudgetConfig.from_settings` + agent 接入（env > settings > default）
- [x] canonicalizer 白名单与别名
- [x] 前端 types / defaults / registry / search / UI / i18n
- [x] 后端单测（设置解析、优先级、agent 初始预算）
- [x] 前端类型检查 + OrchestrationTab 测试
- [x] architecture 门禁

## 4. 不做

- 交互式「继续 / 自动继续 / 停止」卡片；
- lane / subagent 的独立审计汇总；
- 长任务模式（per-request）开关。

## 5. 验收

- 设置页可开关动态预算并修改 6 个数值；
- 保存不触发 400（canonicalizer 白名单/别名齐全）；
- 修改后新 run 的初始预算/上限按设置生效；env 覆盖仍优先；
- 既有测试全绿。
