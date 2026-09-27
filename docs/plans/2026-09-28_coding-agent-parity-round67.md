# 编码代理对标差距分析·第六十七轮：win7 对齐小批次（r170 legacy settings + r172 窗口策略测试）

- **状态**：单批次交付（分支 `feat-parity-r67`，基线 origin/release/win7 8abaf25f0）
- **上游文档**：#1754（r170）、#1762（r172）
- **编号约定**：对齐批次（ALG）

## 0. 结论速览

R66 收口后 main 无新增提交（r170/r172 已在 R66 基线内），但对 win7 的
适用性尚未评估。逐项核对：

- r170（#1754）：`tests/unit/api/test_legacy_settings_routes.py`（+197），
  被测模块 `backend/api/legacy_settings_routes.py` 在 win7 存在 → 适用。
- r172（#1762）：`tests/unit/api/test_chat_request_policy.py`（+189 + 文档），
  被测模块由 DSH #1759 已带至 win7 → 适用。
- 同名冲突检查（沿用 R64 沉淀）：两文件均在 `tests/unit/api/`（有
  `__init__.py` 包前缀隔离），win7 遗留 `tests/api/` 无同名文件 → 无冲突。

## 1. 差距矩阵

| # | 差距 | 证据 | 优先级 |
| --- | --- | --- | --- |
| ALG-12 | win7 缺 r170 legacy settings 测试 | 被测模块在 win7 存在 | **P2** |
| ALG-13 | win7 缺 r172 窗口策略测试 | 模块由 DSH #1759 带入 win7 | **P2** |

## 2. 结构性发现（非本轮修复）

全量 diff `backend/tests/unit/`：main 领先 win7 **数百个测试文件**
（core/domain/orchestration/memory/model_catalog/wiki 等整个子目录在
win7 不存在；win7 亦有 15 个 main 已删除的遗留测试）。此量级远超单轮
对齐——r 系列并行会话正是在做增量回填。本循环按「跟随 r 系列、按批
对齐增量」策略，不在本轮一次性搬平。

## 3. 实施与验证记录

- 两连 cherry-pick 干净落地（新文件无冲突）。
- 本地验证：扫描 0 命中；两套新测试 + usage + scanner 全绿
  （本地 3.12）；全量 collect 10350 例 0 错误。

## 4. 批次 B

（单批次，无）

## 5. 交付记录

- **批次（win7，本轮唯一交付面）**：#1769 `0c6cd867`
  - 内容：#1754（ALG-12 r170）+ #1762（ALG-13 r172）双 cherry-pick
    + 本文档；CI 一次全绿（11 checks 0 failure，含 Win7 LTS py38 job）。
- **总账回填**：即本提交。
