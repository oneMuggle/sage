# 编码代理对标差距分析·第二十二轮：重派链防失控上限与墙钟上限设置入口（2026-09-17）

- **状态**：批次 A 已交付（分支 `feat-parity-r22-batch-a`，基线 origin/main c267457a = #924）
- **上游文档**：round10/13（retry_of 重派）、round21（BU11 墙钟上限）——本轮补两者的安全/UX 边角
- **对标对象**：Devin（重试上限防失控）、通用（时长护栏配置化）
- **编号约定**：延续 RD/BU 系
- **方法**：retry_of 链路/设置页核验，附 file:line

## 0. 结论速览

1. **RD14 重派链无防失控上限**：`retry_of` 链（t3←t2←t1）每次生成新 task_id，`build_waves` 环检测无法覆盖跨批次的链式引用——conductor 误判时可无限链式重派，token/时长成本失控。RT11 指令说"不要原样重派"但无机制强制。
2. **BU12 墙钟上限无设置入口**：BU11 的 `run_wall_clock_limit_min` 只有后端键，设置页无 NumberField（同 r14 BU4 的 runTokenBudget 前科）。

## 1. 差距矩阵

| # | 差距 | 证据 | 对标 | 优先级 |
| --- | --- | --- | --- | --- |
| RD14 | retry_of 链无防失控上限 | `chat_dispatcher.py` retry_of 解析处无计数 | Devin 重试上限 | **P1** |
| BU12 | 墙钟上限无设置页入口 | GeneralTab 编排 section 无 runWallClockLimitMinutes | 通用配置化 | P2 |

## 2. 设计（批次 A：RD14+BU12）

- **RD14**：`OrchSettings.maxRetryOfChains: int = 10`（每 run 重派上限）+ `_RAW_KEYS` 映射；`retry_of` 解析处超限 → 降级普通任务 + warning（与无效源同款降级路径）。
- **BU12**：GeneralTab 编排 section 增 `runWallClockLimitMinutes` NumberField（分钟，0=不限）。

## 3. 批次 A 实施与验证记录（2026-09-17）

- **RD14**：`OrchSettings.max_retry_of_chains`（默认 10，`maxRetryOfChains` 键）+ `ChatDispatcher._redeploy_count` 计数 + retry_of 解析处超限降级（`state.retry_of = None` + warning）；实现期踩坑——首版把计数器插在三元表达式前导致语法断裂，重写为后置检查（解析完成后才计数/剥离）。
- **BU12**：GeneralTab 编排 section 增 `runWallClockLimitMinutes` NumberField。
- 测试：`test_chat_dispatcher_retry_of` +2 例（同批链式失败重派验证 cap 降级、设置键注册）；budget/wall_clock 回归 23 passed；ruff/tsc 全过。

## 4. 批次 B 实施与验证记录

（本轮为单批次交付，无批次 B）

## 5. 交付记录

| 批次 | main | win7 |
| --- | --- | --- |
| A（重派链防失控上限与墙钟上限设置入口） | PR #985（squash 44fc1c30） | PR #991（cherry-win7-r22，squash ebe9552a） |

win7 对齐说明：零冲突落位；CI 含 py3.8 job 终验；`Backend unit (Windows, non-blocking)` job 首跑 7 例 Windows 平台测试失败（persona/path_safety/download 等），与本批改动无关（docs + orchestration 双域，本地全绿），确认为该 job 新增后首跑暴露的既有 Windows 基线问题。
