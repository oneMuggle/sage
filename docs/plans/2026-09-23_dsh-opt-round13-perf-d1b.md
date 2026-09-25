# DSH 对标优化·第十三轮：性能预算扩展（D1b）

- **状态**：批次 A 交付中（分支 `feat-dshopt-r13-perf-d1b`，基线 origin/main 含 R12）
- **系列定位**：`dsh-opt` 对标系列第 13 轮（总账 [dsh-opt-index.md](dsh-opt-index.md)）。
- **上游文档**：round10（D1a 四路径预算，main #1520 / win7 #1523）、
  round2（SE2 存量回填）、round9（C3a 迁移框架）
- **对标对象**：DeepSeek Harness benchmarks——预算路径随功能轮次扩展
  （R9 迁移框架与 SE2 回填落地后，其性能门随之补位）。

## 0. 结论速览

D1a 覆盖了读路径（打开/投影/装配），本轮把 D1a 之后落地的写路径与
启动路径纳入数值门（+3 例）：

1. **存量回填**（SE2 启动路径）：5,000 条 legacy messages 全量补写
   事件 ≤ 4s（本地实测 ~0.4s）——回填随每次 init_db 执行，若随历史
   线性劣化，用户每次启动都买单；
2. **迁移框架空转**（R9 启动开销）：空注册表 no-op ≤ 0.2s——守住
   "迁移框架不得给启动添固定开销"；
3. **消息双写吞吐**（SE1 热路径）：5,000 条 save（含事件 INSERT +
   FTS 索引挂钩）≤ 25s（本地实测 ~2.5s）——显著劣化说明挂钩出现
   逐条全表扫描类回归。

## 1. 差距矩阵

| # | 差距 | 证据 | 对标 | 优先级 |
| --- | --- | --- | --- | --- |
| D1b | R9/R2 新路径无性能门 | 回填/双写/迁移空转无数值断言 | dsh 预算随功能扩展 | **P3** |

## 2. 设计（批次 A：D1b）

`backend/tests/perf/test_backfill_dualwrite_budget.py`（+3 例，同 R10
方法论：executemany 合成直插 / 预算写死 ×10 / env 不得覆盖）。

## 3. 批次 A 实施与验证记录

- **测试**：`backend/tests/perf/test_backfill_dualwrite_budget.py` +3 例
  （回填 5,000 ≤ 4s / 迁移空转 ≤ 0.2s / 双写 5,000 ≤ 25s）。
- **验证**：3 例全绿（本地全套 ~18s，双写为最重路径）；ruff 全过；
  py38 护栏（AST 3.8）通过；纯新增文件，baseline 零改动。
- 教训：`clean_registry` fixture 定义在别的测试文件中不可复用——本文件
  不注册迁移（空注册表 no-op），无需隔离。

## 4. 批次 B 实施与验证记录

（本轮为单批次交付，无批次 B）

## 4. 批次 B 实施与验证记录

（本轮为单批次交付，无批次 B）

## 5. 交付记录

- **main**：（PR 占位）
- **win7 对齐**：（cherry-pick 占位；纯新增测试，pick 零冲突）
