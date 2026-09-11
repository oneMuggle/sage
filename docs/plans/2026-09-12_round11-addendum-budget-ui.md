# 第十一轮补全：run 级 token 预算前端可见性（BU4，2026-09-12）

- **状态**：已交付（分支 `feat-parity-r14-batch-a`，基线 origin/main 99b652b5 = #655）
- **性质**：round11 BU 系的 UX 补全——预算守门（BU2）此前仅后端生效，配置键 `runTokenBudget` 无设置入口，用户无法感知/调整。

## 1. 内容

| # | 内容 | 要点 |
| --- | --- | --- |
| BU4 | 设置入口 + 类型补全 | `OrchSettings.runTokenBudget: number`（默认 0 = 不限，与后端 `orch_settings.py` `runTokenBudget`/`run_token_budget` 键对齐）；GeneralTab 编排 section 增"Run token 预算"NumberField（`orch-run-token-budget`），部分更新契约（保留其余 orch 键） |

守门行为（BU2，round11 已交付）不变：超限 → 剩余任务经 run 级取消通道收口 + `dispatch` 入口拒绝后续批次 + 聚合头部标注。

## 2. 验证

- `GeneralTab.orch.test.tsx` +2 例（渲染默认 0 / 修改保留其余 orch 键）→ 6 passed；tsc 全过；eslint 清洁。

## 3. 交付记录

（各批次 PR 号与双分支交付号于交付后回填）
