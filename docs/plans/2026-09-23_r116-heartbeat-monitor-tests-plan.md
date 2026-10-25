# R116 批次计划 —— HeartbeatMonitor 车道心跳监控测试（重建）

日期：2026-09-25 ｜ worktree：`.worktrees/feat-r116-scan`（基于 origin/main 3ac73f00）

## 背景

`backend/orchestration/heartbeat.py`（109 行，HeartbeatMonitor）监控编排
lane 的心跳健康（HEALTHY/STALLED/TRANSPORT_DEAD），触发恢复回调。无测试。

## 批次内容

新增 `backend/tests/unit/orchestration/test_heartbeat_monitor.py`（10 用例）。

## 验证矩阵

- 本机：py_compile + CI 同款 ruff 0.4.4 全过。
- CI：Backend (Python) pytest 全量。

## 不做

- 不改生产代码。
