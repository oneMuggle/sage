# R116 批次计划 —— HeartbeatMonitor 车道心跳监控测试

日期：2026-09-23 ｜ worktree：`.worktrees/feat-r116-scan`（基于 origin/main 0a41c6e4）

## 背景

`backend/orchestration/heartbeat.py`（109 行，HeartbeatMonitor）监控编排
lane 的心跳健康（HEALTHY/STALLED/TRANSPORT_DEAD），触发恢复回调。无测试。

## 批次内容

新增 `backend/tests/unit/orchestration/test_heartbeat_monitor.py`（10 用例）：

- 健康心跳 → HEALTHY 无回调；
- 心跳超 stalled_after → STALLED + on_stalled 回调；
- 心跳超 dead_after → TRANSPORT_DEAD + on_dead 回调；
- transport_alive=False → 立即 TRANSPORT_DEAD；
- heartbeat=None 的 lane 安全跳过；
- 多 lane 混合各自正确标记；
- 非 RUNNING lane 不参与检查；
- monitor start/stop 生命周期与重复 start 防护；
- stop 从未 start 安全。

fake registry（list_lanes_by_status/update_lane）注入，零后端依赖。

## 验证矩阵

- 本机：py_compile + CI 同款 ruff 0.4.4 全过。
- CI：Backend (Python) pytest 全量。

## 不做

- 不改生产代码。
