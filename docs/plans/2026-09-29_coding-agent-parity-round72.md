# 编码代理对标差距分析·第七十二轮：win7 对齐小批次（r178 MemoryManager 协调层测试）

- **状态**：单批次交付（分支 `feat-parity-r72`，基线 origin/release/win7 3ea442c70）
- **上游文档**：#1788（r178）
- **编号约定**：对齐批次（ALG）

## 0. 结论速览

R71 收口后 main 零新增提交；本轮评估 R71 期间并入 main 的
#1788（r178：MemoryManager 三层记忆协调层单测，+203 + 文档）对 win7
的适用性：

- 被测模块 `backend/memory/manager.py` 在 win7 存在（847 行），且
  测试所需方法面（remember/memorize/delete_memory/get_stats/
  add_to_working/compress）齐备 → 适用。
- **路径适配**：r178 原文件在 `tests/unit/memory/`（main 结构）。win7
  无该目录，且新建 `unit/memory/__init__.py` 会复现 R64 实证的模块
  名遮蔽（`memory.*` 与 backend/memory 包冲突）。故放置于 win7 遗留
  扁平路径 `tests/unit/test_memory_manager_coordination.py`（basename
  全树唯一，与既有 test_memory_manager*.py 不冲突）。
- DSH-R30（#1792/#1795）并行会话已自行对齐 win7（3ea442c70）→ 跳过。

## 1. 差距矩阵

| # | 差距 | 证据 | 优先级 |
| --- | --- | --- | --- |
| ALG-15 | win7 缺 r178 协调层测试 | manager 方法面齐备，实测 14 例全过 | **P2** |
| —— | DSH-R30 不做 | 并行会话已自行对齐（3ea442c70） | 跳过 |

## 2. 设计

内容不变迁移：`git checkout 46f73e566 -- <原路径>` 后 `git mv` 至
win7 扁平路径（测试内容零改动——win7 的 MemoryManager 实测行为与
main 一致）。

## 3. 实施与验证记录

- 14 例全绿（本地 3.12，win7 worktree 实测）；py38_hazard_scan
  0 命中；全量 collect 10472 例 0 错误。

## 4. 批次 B

（单批次，无）

## 5. 交付记录

- **批次（win7，本轮唯一交付面）**：#1802 `effd97ff`
  - 内容：#1788（r178）测试内容不变迁移 + 本文档；CI 一次全绿
    （11 checks 0 failure，含 Win7 LTS py38 job）。
- **总账回填**：即本提交。
