# DSH 对标优化·第十八轮：D1c 性能预算扩展（压缩/大规模投影/回填幂等/迁移空转）

- **状态**：批次 A 交付中（分支 `feat-dshopt-r18-ledger-d1c`，基线 origin/main 含 R17）
- **系列定位**：`dsh-opt` 对标系列第 18 轮（总账 [dsh-opt-index.md](dsh-opt-index.md)）。

## 0. 结论速览

D1b 覆盖了回填/迁移空转/双写吞吐后，本轮补齐压缩遍历与大规模投影：
- 压缩遍历 5,000 条 ≤ 1.0s
- 10,000 事件投影 + 表投影 parity ≤ 0.5s
- 回填幂等 ≤ 0.2s
- 迁移框架空转 ≤ 0.2s

## 3. 批次 A 实施与验证记录

- **测试**：`backend/tests/perf/test_d1c_extended_budgets.py` +3 例：
  1. 压缩遍历 5,000 条 ≤ 1.0s（should_compact + estimate_messages_tokens）
  2. 10,000 事件投影 + 表投影 parity ≤ 0.5s（双端逐字节一致）
  3. 回填幂等 500 行 ≤ 0.2s（二次运行零写入）
- **验证**：3 例全绿（本地全套 ~12s）；ruff 全过；py38 AST 3.8 通过；
  纯新增文件，baseline 零改动。
- **总账回填**：R14/R15/R16/R17 全部双分支 SHA + ✅ 状态已回填。

## 4. 批次 B 实施与验证记录

（本轮为单批次交付，无批次 B）

## 5. 交付记录

- **main**：（PR 占位）
- **win7 对齐**：（cherry-pick 占位）
- **总账回填**：R15-R17 行已更新为最终 SHA + ✅ 状态
