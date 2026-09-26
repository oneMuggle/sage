# 编码代理对标差距分析·第五十七轮：orch_events 保留策略（OPS5）

- **状态**：批次 A 交付中（分支 `feat-ops5-r57`，基线 origin/main 64d9790b = #1658）
- **上游文档**：DSH-R1 会话事件日志地基（orch_events 表 + repo）
- **对标对象**：生产级系统的事件保留策略（防无限增长）
- **编号约定**：延续 OPS 系

## 0. 结论速览

orch_events 表随编排 run 无限增长——没有任何保留策略或清理机制。
本轮新增 `delete_before(cutoff_ms)` 方法并在 `init_db()` 中按 30 天
默认保留期调用，防止表无限膨胀。

## 1. 差距矩阵

| # | 差距 | 证据 | 优先级 |
| --- | --- | --- | --- |
| OPS5 | orch_events 无保留策略 | 表持续增长无清理 | **P2** |

## 2. 设计（批次 A：OPS5）

- **repo**：`OrchEventRepository.delete_before(cutoff_ms) -> int` 删除
  `occurred_at < cutoff` 的事件行，返回删除行数。
- **init_db**：每次启动时按 30 天默认保留期调用（cutoff = now - 30d）。
- **测试**：+1 例（插入旧事件 → delete_before → 旧事件被删/新事件保留）。

## 3. 批次 A 实施与验证记录

- **orch_events_repo**：新增 `delete_before(cutoff_ms)` 方法——删除
  `occurred_at < cutoff` 的事件行，返回删除行数。
- **database.py init_db**：orch_events 建表+索引后按 30 天保留期执行
  DELETE（fail-open，失败不阻塞启动）。
- **测试**：+1 例（31 天前旧事件被删/近期事件保留），42 例全绿；ruff 全过。

## 4. 批次 B

（本轮为单批次交付，无批次 B）

## 5. 交付记录

（各批次 PR 号与双分支交付号于交付后回填）
