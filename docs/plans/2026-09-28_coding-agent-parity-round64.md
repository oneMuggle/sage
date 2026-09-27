# 编码代理对标差距分析·第六十四轮：win7 对齐小批次（r166 hooks 测试 + round63 文档回填同步）

- **状态**：单批次交付中（分支 `feat-parity-r64`，基线 origin/release/win7 ce8213b95）
- **上游文档**：#1743（r166）、#1745（R63 回填）、R63（round63）
- **编号约定**：对齐批次（ALG）

## 0. 结论速览

R63 收口后复扫：main 新增 4 个并行交付（#1741/#1742/#1743/#1744）。
逐项核对 win7 适用性：#1744 归 DSH 会话自有对齐管线（不抢）；#1741
不适用（其修复的 dict() 工厂仅存在于 main，win7 的 test_conventions.py
为旧版 194 行差）；**#1743 适用**——hooks_routes.py 已在 win7 而对应
测试文件缺失；另 round63 文档 §4/§5 的回填版（#1745）应同步 win7。

## 1. 差距矩阵

| # | 差距 | 证据 | 优先级 |
| --- | --- | --- | --- |
| ALG-7 | win7 有 `backend/api/hooks_routes.py` 但无 `test_hooks_routes.py` | cat-file 实证 | **P2** |
| ALG-8 | win7 的 round63 文档 §4/§5 仍是交付前占位 | #1745 仅改了 main 侧 | **P3** |
| —— | #1741 不适用 | dict() 工厂未上 win7，无 C408 红 | 跳过 |
| —— | #1744 不做 | DSH 系列由并行会话维护（见 #1737 惯例） | 跳过 |

## 2. 设计

- ALG-7：cherry-pick `7c40d0b29`（r166，+271 行新测试文件 + 方案文档）。
- ALG-8：cherry-pick `2ed9dc7e2`（#1745）中 round63 文档部分；
  总账 `parity-rounds-index.md` 为 main-only，冲突时继续排除。
- 验证：py38_hazard_scan 0 命中 + 新增测试本地（3.12）通过；
  py3.8 权威验证交由 Win7 LTS CI。

## 3. 实施与验证记录

- cherry-pick `7c40d0b29`：干净落地（新文件）。
- cherry-pick `2ed9dc7e2`：round63 文档 hunk 干净；总账按预期 modify/delete
  冲突，win7 侧排除。
- 本地：扫描 0 命中；hooks 测试 + 扫描器测试全绿（本地 3.12）。

## 4. 批次 B

（单批次，无）

## 5. 交付记录

（交付后回填）
