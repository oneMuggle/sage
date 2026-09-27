# 编码代理对标差距分析·第六十八轮：win7 对齐小批次（r174 legacy models 13 DTO 测试）

- **状态**：单批次交付（分支 `feat-parity-r68`，基线 origin/release/win7 e73cd600b）
- **上游文档**：#1768（r174）
- **编号约定**：对齐批次（ALG）

## 0. 结论速览

R67 收口后 main 零新增提交；本轮评估对象为 R67 期间已并入 main 的
#1768（r174：legacy API 请求/响应 13 DTO 单测，+236 + 文档）。被测模块
`backend/api/legacy_models.py` 由 DSH #1767（R27 C1e）带入 win7 → 适用。
DSH-R27（#1763/#1767）为并行会话自行对齐（#1767 即证），跳过。
同名冲突检查：`tests/unit/api/` 包前缀隔离（R64 沉淀），win7 全测试树
无 `test_legacy_models` 同名文件 → 无冲突。

## 1. 差距矩阵

| # | 差距 | 证据 | 优先级 |
| --- | --- | --- | --- |
| ALG-14 | win7 缺 r174 test_legacy_models.py | 被测模块 legacy_models.py 已在（DSH #1767） | **P2** |
| —— | DSH-R27 不做 | 并行会话已自行对齐（e73cd600b） | 跳过 |

## 2. 设计

单 cherry-pick `03c2c67b9`（r174，+263：新测试文件 + 方案文档）。

验证：py38_hazard_scan 0 命中；新测试 + 受影响目录本地全绿；
全量 collect 0 错误；py3.8 权威验证交由 Win7 LTS CI。

## 3. 实施与验证记录

- cherry-pick 干净落地（新文件无冲突）。
- 本地验证：扫描 0 命中；新测试 + usage + legacy_settings + scanner
  全绿（本地 3.12）；全量 collect 10370 例 0 错误。

## 4. 批次 B

（单批次，无）

## 5. 交付记录

- **批次（win7，本轮唯一交付面）**：#1775 `db28c7c4`
  - 内容：#1768（ALG-14 r174）cherry-pick + 本文档；CI 一次全绿
    （11 checks 0 failure，含 Win7 LTS py38 job）。
- **总账回填**：即本提交。
