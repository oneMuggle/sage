# 编码代理对标差距分析·第三十三轮：级联跳过根因可见性（RD18）

- **状态**：批次 A 交付中（分支 `feat-parity-r33-batch-a`，基线 origin/main f1ee2a64 = #1204）
- **上游文档**：P1 拓扑调度（级联取消 error 前缀 `blocked_by_failed:<root>`）
- **对标对象**：Claude Code（被上游阻塞的任务明确标注）、Cursor（步骤跳过原因可见）
- **编号约定**：延续 RD 系

## 0. 结论速览

上游失败时，下游任务被级联置 failed，`error` 带 `blocked_by_failed:<根因>`
前缀——但前端失败行只显示 "✗"，**用户必须打开 Drawer 读原始 error 文本
才能知道"为什么这个任务连跑都没跑"**。本轮在任务树失败行解析该前缀，
渲染 `因 <root> 失败级联跳过` 徽章（title 含完整 error）。

## 1. 差距矩阵

| # | 差距 | 证据 | 对标 | 优先级 |
| --- | --- | --- | --- | --- |
| RD18 | 级联跳过任务行无根因标注 | TaskTreeSection failed 行仅图标+goal | Claude Code 阻塞标注 | **P3** |

## 2. 设计（批次 A：RD18）

- **TaskTreeSection**：failed/cancelled 行解析 `st.error?.startsWith('blocked_by_failed:')`
  → 提取根因 id，渲染 `task-tree-blocked-<id>` 徽章「因 <root> 失败级联跳过」，
  title = 完整 error。普通失败（无前缀）不受影响。
- **测试**：+2 例（前缀行渲染徽章且提取根因 / 普通失败不渲染）。

## 3. 批次 A 实施与验证记录

- **TaskTreeSection**：failed 行解析 `st.error` 的 `blocked_by_failed:` 前缀
  （dispatcher `_CASCADE_ERROR_PREFIX`，值为逗号连接的根因上游 id），
  渲染 `task-tree-blocked-<id>` 徽章「因 t0、t9 失败级联跳过」，title 带
  完整 error；无前缀的普通失败不渲染。
- **测试**：+1 例（多根因顿号连接 + 普通失败不渲染），文件 17 例全绿。
- 验证：`tsc --noEmit` 干净；eslint 改动文件零告警。后端零改动。

## 4. 批次 B 实施与验证记录

（本轮为单批次交付，无批次 B）

## 5. 交付记录

- **main**：PR #1208（squash `e879461b`，2026-09-19 merge，CI 12 项全绿）。
- **win7**：无需对齐 PR——并行会话的编排轮（#1240 任务层级化 + re-plan
  工具族，win7 对齐 #1245）已先行在同文件交付同款徽章（`task-tree-blocked-`
  已在 release/win7），本轮回退 cherry-pick（冲突内容与既有实现一致）。
- **回填分支**：`docs/r33-backfill`（本提交）。
