# 编码代理对标差距分析·第六十五轮：win7 对齐小批次（r167/r168/r169 测试三连）

- **状态**：单批次交付（分支 `feat-parity-r65`，基线 origin/release/win7 743579ccf）
- **上游文档**：#1746（r167）、#1749（r168）、#1751（r169）
- **编号约定**：对齐批次（ALG）

## 0. 结论速览

R64 收口后复扫：main 新增 3 个测试补齐轮（r167 诊断包 HTTP 端点 /
r168 runtime_routes 分派层 / r169 Node.js 运行时适配器）+ 1 个 DSH 重构
（#1750，并行 DSH 会话已自行对齐 win7 即 #1752，跳过）。三项测试的
被测模块（diagnostic_routes / runtime_routes / tools.adapters.node_adapter）
均在 win7 存在，全部适用；且 R64 补的 `tests/unit/api/__init__.py` 使
`test_runtime_routes` 同名冲突被包前缀天然规避（R64 修复的实证红利）。

## 1. 差距矩阵

| # | 差距 | 证据 | 优先级 |
| --- | --- | --- | --- |
| ALG-9 | win7 缺 r167 test_diagnostic_routes.py | 被测模块 diagnostic_routes.py 已在 | **P2** |
| ALG-10 | win7 缺 r168 test_runtime_routes.py | 同名遗留文件在 tests/api/，包前缀已隔离（R64） | **P2** |
| ALG-11 | win7 缺 r169 test_node_adapter.py | node_adapter.py 已在 win7 | **P2** |
| —— | #1750 不做 | DSH 会话已 cherry-pick（#1752） | 跳过 |

## 2. 设计

三个 cherry-pick（均为新文件 + 方案文档，无代码改动）：
`06335cd37`（r167）→ `dd8da3f39`（r168）→ `b71f576b5`（r169）。

验证：py38_hazard_scan 0 命中；三套新测试 + 受影响目录本地全绿；
全量 collect-only 0 错误；py3.8 权威验证交由 Win7 LTS CI。

## 3. 实施与验证记录

- 三连 cherry-pick 全部干净落地（新文件无冲突）。
- 本地验证：扫描 0 命中；477 例（三新套件 + hooks + scanner）全绿
  （本地 3.12）；全量 collect 0 错误。

## 4. 批次 B

（单批次，无）

## 5. 交付记录

（交付后回填）
