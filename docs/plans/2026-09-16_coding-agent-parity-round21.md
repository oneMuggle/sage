# 编码代理对标差距分析·第二十一轮：run 级墙钟上限（2026-09-15）

- **状态**：批次 A 已交付（分支 `feat-parity-r21-batch-a`，基线 origin/main bd6ce80a = #880）
- **上游文档**：round11（BU2 token 预算守门）、round16（BU6 归因）、round18（BU7 预警）、round19（BU8 消耗可见性）——本轮补"时长"维度的护栏
- **对标对象**：Devin（run 超时自动终止）、Claude Code（后台代理时限）
- **编号约定**：延续 BU 系
- **方法**：预算守门/收口路径核验，附 file:line

## 0. 结论速览

token 预算（BU2）管"花多少"，任务级 wall-clock（O2）管"单任务卡死"——**缺"整个 run 跑了多久"的上限**：每个任务都正常完成但数量失控（如 conductor 误判循环派发）时，run 可以无限跑下去。Devin/Claude Code 均有 run 级时限。

## 1. 差距矩阵

| # | 差距 | 证据 | 对标 | 优先级 |
| --- | --- | --- | --- | --- |
| BU11 | 无 run 级墙钟上限 | `_check_run_budget` 仅查 token 预算；O2 仅任务级 900s | Devin run timeout | **P2** |

## 2. 设计（批次 A：BU11）

- **BU11**：`OrchSettings.run_wall_clock_limit_min: int = 0`（0 = 关闭，默认关闭）+ `_RAW_KEYS["runWallClockLimitMinutes"]`。
- `_check_run_budget` 同点位增墙钟判断：`now - _first_dispatch_at >= limit*60_000` → 置 `_budget_exceeded` 同款收口（复用 `_cancelled` 传播与 BU6 归因，error 文案 `wall_clock_exceeded: …`）。
- 归因优先级保持：预算 > 墙钟 > 用户取消 > 跳过（预算先判不变；墙钟仅当预算未触顶时归因）。

## 3. 批次 A 实施与验证记录（2026-09-16）

- **BU11**：`OrchSettings.run_wall_clock_limit_min`（分钟，0=关闭默认，`runWallClockLimitMinutes` 键）+ `_check_run_wall_clock()`（首次派发起墙钟时长 ≥ 上限 → 置 `_wall_clock_exceeded` + `_cancelled` 传播收口）；每任务终态后与预算守门同点位调用；merged 守卫归因顺序：预算 > 墙钟 > 用户取消 > 跳过（预算先判不变）；`_aggregate` 头部墙钟触顶标注（与预算标注 if/elif 互斥）。
- 测试：`test_chat_dispatcher_wall_clock.py` 4 例（同批收口归因 / 关闭零影响 / 字段默认 / _RAW_KEYS 映射）；dispatcher 全家桶 61 passed（1 例真实 git worktree 测试隔离性 flake，单独跑通过）；ruff 全过。

## 4. 批次 B 实施与验证记录

（本轮为单批次交付，无批次 B）

## 5. 交付记录

| 批次 | main | win7 |
| --- | --- | --- |
| A（run 级墙钟上限） | PR #887（squash c4edb78a） | PR #889（cherry-win7-r21，经 e25a859f 落位 9e68bc6a） |

win7 对齐说明：零冲突落位；py3.8 纪律照旧；wall_clock 4 例本地绿。并行流的 #919（alpha39 bump）合并时顺带将本批对齐内容带入 win7 tip。
