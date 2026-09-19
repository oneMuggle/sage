# 编码代理对标差距分析·第四十轮：审计门自动化前置（OPS1）

- **状态**：批次 A 交付中（分支 `feat-audit-watch-r40`，基线 origin/main 13449746 = #1293）
- **上游文档**：`docs/plans/parity-rounds-index.md` 优化建议 3；R38 的 anyio
  审计门人工响应事件（约 2 小时阻塞窗口）
- **对标对象**：Devin/Claude Code 的依赖告警自动化（告警先于门禁失败）
- **编号约定**：OPS 系（流程自动化）

## 0. 结论速览

anyio 事件（R28）表明：新公告发布会让 win7 审计门**突然打红所有 win7
PR**，且只能人工响应。本轮新增 `Audit Watch` 定时 workflow：每日对
`backend/requirements-py38.txt` 跑 pip-audit 并与策略白名单求差，
存在未覆盖发现时自动创建/追加 `audit-watch` issue（附处置指引），
全清时自动关闭——**告警先于门禁失败**。

## 1. 差距矩阵

| # | 差距 | 证据 | 对标 | 优先级 |
| --- | --- | --- | --- | --- |
| OPS1 | 新公告无前置告警，只能等 PR CI 失败才发现 | R28 anyio 事件 | Devin 告警自动化 | **P2** |

## 2. 设计（批次 A：OPS1）

- **scripts/audit_watch.py**：复用 `check_dependency_audit` 的
  `pip_findings`/`validate_policy`（与强制门同语义），输出未覆盖清单
  （文本 + JSON）；退出码 0=覆盖 / 2=有未覆盖 / 1=输入或策略校验失败。
- **.github/workflows/audit-watch.yml**：每日 cron + 手动触发；
  pip-audit → 求差 → 未覆盖则创建/追加 `audit-watch` label issue，
  清零则自动关闭存量 issue。
- **测试**：scripts/tests/test_audit_watch.py 6 例（差集/格式化/CLI 退出码
  与输出文件/缺输入）。

## 3. 批次 A 实施与验证记录

- **scripts/audit_watch.py**：`uncovered_findings(pip_report, policy)` 复用
  强制门的 `pip_findings`/`validate_policy`（同语义求差）；CLI
  `--pip/--policy/--out/--json-out`，退出码 0/2/1（覆盖/有未覆盖/输入坏）。
- **.github/workflows/audit-watch.yml**：每日 cron 03:00 UTC + 手动触发；
  pip-audit(requirements-py38) → 求差 → 未覆盖创建/追加 `audit-watch`
  issue（含 osv 链接与处置指引），清零自动关闭存量 issue。
- **测试**：scripts/tests/test_audit_watch.py 6 例（覆盖空差集 / 未覆盖
  差集 / CLI 退出码与输出文件 / 缺输入 exit 1）。
- 验证：6 例全绿；ruff 全过。前端零改动。

## 4. 批次 B 实施与验证记录

（本轮为单批次交付，无批次 B）

## 5. 交付记录

（各批次 PR 号与交付号于交付后回填；纯 main 侧交付，win7 共享同一
workflow——audit-watch 定义于 main，release/win7 合并后同样生效）
