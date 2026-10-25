# R110 批次计划 —— event_projection 间歇 flake 根除（冻结 session_repo 时钟）

日期：2026-09-23 ｜ worktree：`.worktrees/feat-r110-scan`（基于 origin/main d545bb1f）

## 背景

issue #1465：`test_event_projection.py::test_parity_after_segment_retreat`
在本会话目击两次 CI 间歇失败（#1440 16:41Z、#1461 ~18:2xZ），rerun 均通过。
根因：`advance_segment` 内部用真实 `time.time()` 落 separator 的 created_at
（session_repo.py:978），测试侧合成时间戳只隔 1ms 窄缝；CI 负载/时钟抖动下
偶发同毫秒撞值——messages 按 created_at 排序、事件按 seq 排序，两端投影分叉。

既有稳化（-10s 基线）只保护了 separator 之前的消息；separator 之后仍依赖
真实墙钟恰好 ≥ separator.created_at + 1。

## 批次内容（测试侧，不改生产代码）

`test_parity_after_segment_retreat` 改为冻结 `session_repo` 的 `time` 引用：

- `_FakeTime.time()` 每次调用 +100ms 严格单调（步进远大于 float 截断抖动）；
- msg1/msg2 的 created_at 改由同一假时钟产生，与 advance_segment 内部的
  separator 时间戳同源，顺序关系确定；
- 删除 -10s 基线与局部 `_time` 导入；断言改用假时钟读数。

修复 issue：#1465。

## 验证矩阵

- 本机：py_compile + CI 同款 ruff 0.4.4 全过。
- CI：Backend (Python) pytest 全量（含本用例在内的 event_projection 面）。

## 影响面

- 纯测试改动；`monkeypatch.setattr(session_repo_module, "time", ...)` 仅
  影响该模块命名空间，测试后自动还原。
