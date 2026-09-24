# DSH 对标优化·第十轮：性能预算基准第一刀（D1a）

- **状态**：批次 A 交付中（分支 `feat-dshopt-r10-perf-budget`，基线 origin/main 含 R9）
- **系列定位**：`dsh-opt` 对标系列第 10 轮（总账 [dsh-opt-index.md](dsh-opt-index.md)）。
- **上游文档**：round9（C3a 迁移框架，main #1512 / win7 #1516）
- **对标对象**：DeepSeek Harness benchmarks 方法论——按用户路径（非微
  基准）、合成负载、数值预算写死常量、"环境变量不得覆盖预算"、**PR 必过**
  的仓库级性能门。

## 0. 结论速览

sage 有完整的 E2E 分层但没有任何性能数值预算——回归靠人感知。本轮落
性能预算基准第一刀：合成 5,000 消息/事件的长会话，对四条用户路径断言
数值预算（默认进 CI，持续给信号）：

1. 长会话打开（get_by_session 全量）≤ 0.5s
2. 事件投影（events_to_history × 5,000）≤ 0.5s
3. 表投影（db_rows_to_history × 5,000，parity 另一侧）≤ 0.5s
4. 请求装配 + 强制截断（build_request_messages_from_events）≤ 1.0s

预算 = 本地实测 × 10 写死常量（共享 runner 正常波动不触线；O(n²) 化
回归会成倍越线）。另含大会话 parity 抽查（正确性优先）。

## 1. 差距矩阵

| # | 差距 | 证据 | 对标 | 优先级 |
| --- | --- | --- | --- | --- |
| D1a | 无按用户路径的性能数值预算 | 预算散落四处且无数值门 | dsh benchmarks（PR 必过性能门） | **P2** |

## 2. 设计（批次 A：D1a）

- `backend/tests/perf/test_session_projection_budget.py`：`perf` 标记
  （pytest.ini 注册）+ `unit`；合成会话 fixture（executemany 直插
  messages + session_events，绕过逐条 save 的真实写路径以保证基准
  只测读路径）；`CI_SCALE=10` 常量与预算写死（env 不得覆盖）。
- 抽查用例：大会话上事件投影 ≡ 表投影（SE1 parity 在 5,000 规模成立）。

## 3. 批次 A 实施与验证记录

- **测试**：`backend/tests/perf/test_session_projection_budget.py`——
  `perf` 标记注册进 pytest.ini（strict-markers 合规）；合成 fixture 用
  executemany 直插双轨（绕过逐条 save，基准只测读路径）；5 用例 =
  4 条预算路径 + 大会话 parity 抽查。全套本地实测 ~8.5s（单用例远低于
  120s 超时），默认进 CI。
- **预算**：0.5 / 0.5 / 0.5 / 1.0 秒（本地实测 × 10 写死；`SAGE_PERF_SCALE`
  之类的运行时覆盖**刻意不提供**，对齐 dsh 纪律）。首轮未触线（实测均在
  预算 1/10 以内），后续回归成倍越线即信号。
- **验证**：5 例全绿（含大会话 parity）；projection/migrations 回归
  12 例全绿；ruff 全过；py38 护栏（AST 3.8）通过。新增文件均为新增，
  baseline 零改动。

## 4. 批次 B 实施与验证记录

（本轮为单批次交付，无批次 B）

## 4. 批次 B 实施与验证记录

（本轮为单批次交付，无批次 B）

## 5. 交付记录

- **main**：（PR 占位）
- **win7 对齐**：（cherry-pick 占位）
