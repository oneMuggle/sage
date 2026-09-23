# 编码代理对标差距分析·第四十七轮：doctor 探针瞬时失败重试（OPS3）

- **状态**：批次 A 交付中（分支 `feat-doctor-retry-r47`，基线 origin/main a5a0d035 = #1429）
- **上游文档**：R40 audit-watch 同款 fail-open 哲学；本地全量套件 2h19m
  复盘中 `_try_import_backend` 在资源紧张下超时假阳性的实证
- **对标对象**：VS Code doctor 类诊断（瞬时环境抖动不产生永久误报）
- **编号约定**：OPS 系（流程自动化/健壮性）

## 0. 结论速览

doctor 的 `import backend.main` 探针在 20s 超时后直接判 False——本会话
全量套件（8000+ 测试连续运行，1h27m）的复盘中该探针因资源紧张超时，
产生假"损坏"误报；生产端重负载机器同样会遇到。本轮给探针加**一次重试**
（超时后以 60s 二次尝试），仍保持 fail-open 语义；同时消除本地全量
套件中该用例的 flake。

## 1. 差距矩阵

| # | 差距 | 证据 | 对标 | 优先级 |
| --- | --- | --- | --- | --- |
| OPS3 | 探针超时即误报，无重试 | `subprocess.run(timeout=20)` → except → False | VS Code doctor | **P2** |

## 2. 设计（批次 A：OPS3）

- **doctor.py `_try_import_backend`**：捕获 `subprocess.TimeoutExpired`
  后重试一次（timeout=60s）；其余 OSError 保持即时 False（binary 缺失
  等确定性失败重试无意义）。
- **测试**：+1 例（首次 TimeoutExpired → 重试成功 → True；两次超时 →
  False；OSError → 即时 False 不重试）。

## 3. 批次 A 实施与验证记录

- **doctor.py `_try_import_backend`**：首次 20s 探针超时（TimeoutExpired）
  后以 60s 重试一次；OSError（binary 缺失等确定性失败）即时 False 不重试；
  非 Timeout 的 SubprocessError 同样即时 False。fail-open 语义不变。
- **测试**：+2 例（超时→60s 重试成功且调用序列 [20,60] / 双超时 False），
  doctor 套件 38→40 例全绿；ruff 全过。前端零改动。
- **对全量套件的连带收益**：本会话 2h19m 全量复盘中该探针即因资源紧张
  超时假阳性（test_doctor 2 例 isolated 复跑皆绿），重试后该 flake 消除。

## 4. 批次 B 实施与验证记录

（本轮为单批次交付，无批次 B）

## 5. 交付记录

- **main**：PR #1436（squash `1fa169a3`，2026-09-23 merge，CI 12 项全绿）。
- **win7 对齐**：PR #1441（squash `f7eddc8f`，2026-09-24 merge，win7 必过项
  全绿——py38 套件 20m20s）。cherry-pick 干净落位，win7 基底 doctor 40 例
  本地全绿。
- **回填分支**：`docs/r47-parity-backfill`（本提交）。
