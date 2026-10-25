# 编码代理对标差距分析·第二十七轮：单任务重试（RV4）

- **状态**：批次 A 交付中（分支 `feat-parity-r27-batch-a`，基线 origin/main 62a72421 = #1144）
- **上游文档**：round8（RV1 preset 回放 / RV2 rerun-failed / RV3 按钮）、round15（RD13+ retry_of 重派）
- **对标对象**：Claude Code（单个失败 Task 可单独重试，不必整批重跑）
- **编号约定**：延续 RV 系

## 0. 结论速览

RV2/VR3 提供了「只重跑失败任务」——但失败任务 ≥2 个时用户无法只重试其中
某一个；其余失败任务会被一并重跑（多花 LLM 调用）。本轮给 rerun-failed
增加可选 `task_ids` 过滤 + 任务树失败行内「重试」按钮：只重建所选任务及其
下游未完成闭包，done 任务照旧 preset 回放，**其余失败任务不进入新计划**
（goal 文案显式说明），对标 Claude Code 单 Task 重试。

## 1. 差距矩阵

| # | 差距 | 证据 | 对标 | 优先级 |
| --- | --- | --- | --- | --- |
| RV4-a | rerun-failed 不支持任务子集 | `orch_routes.rerun_failed` 无请求体，失败任务全量重建 | Claude Code per-Task retry | **P2** |
| RV4-b | 任务树失败行无单任务重试入口 | TaskTreeSection 仅有整批 onRerunFailed 与单任务跳过 | 同上 | **P2** |

## 2. 设计（批次 A：RV4）

- **后端**：`POST /orch/runs/{run_id}/rerun-failed` 接受可选
  `RerunFailedRequest{task_ids?: [str]}`（extra=forbid）：
  - 校验：task_id 必须在计划内（404）、不得为 done（409）、run 终态、
    所选任务非 done；
  - 闭包：所选任务 + 其传递依赖闭包内状态 ∈ {failed, cancelled, blocked,
    pending} 的任务重建（下游产物依赖新结果）；done 任务 preset 回放不变；
  - 其余失败任务（非所选、非闭包）不进入新计划；goal 前缀
    「单任务重试（t3 等 N 个）」；
  - 无 body 时行为与现状完全一致（rerun-all-failed）。
- **桥接**：`orchestration_rerun_failed` 透传 task_ids（invokeBackend 序列化
  请求体，path builder 不变）。
- **前端**：`orchRunClient.rerunFailed(runId, taskIds?)`；Chat.tsx
  `handleRerunFailed(runId, taskIds?)` 透传；RightPanel → ProgressSection →
  TaskTreeSection 新增 `onRetryTask?` 链路；任务树 failed 行内
  「重试」按钮（run 终态且提供回调时渲染，样式对齐「跳过」按钮）。
- **测试**：orch_routes 单任务重试 4 例（闭包重建 / done 保留 / 其余失败
  排除 / 404+409 校验）；TaskTreeSection 重试按钮 2 例（渲染与回调）。

## 3. 批次 A 实施与验证记录

- **后端**：`orch_routes.py` 增 `RerunFailedRequest{task_ids?}`（extra=forbid）
  与 `_depends_closure()`（下游传递闭包）；`rerun_failed` 子集模式：所选 +
  下游未完成重建、done preset 回放、闭包外失败任务排除（goal 显式说明
  "另有 N 个失败任务未包含"）；无 body 时 RV2 语义不变。校验 404（未知
  task）/409（done 任务 / running run / 无失败）。
- **前端**：`orchRunClient.rerunFailed(runId, taskIds?)`；Chat.tsx
  `handleRerunFailed(runId, taskIds?)`；RightPanel → ProgressSection →
  TaskTreeSection `onRetryTask` 链路；failed 行「重试」按钮
  （`task-tree-retry-<id>`，run 终态才渲染，stopPropagation 防 Drawer 误触）。
  electron 桥零改动（args 自动序列化请求体，camelToSnakeKeys 对 snake 键透传）。
- **测试**：后端 `test_orch_rerun_failed.py` 6→10 例（子集闭包 / 404 / 409
  done / pending 下游随闭包）；前端 TaskTreeSection 10→12 例（按钮渲染+
  回调 / 进行中不渲染）。
- 验证：后端 10 例全绿 + ruff 全过；前端 12 例全绿 + `tsc --noEmit` 干净 +
  eslint 六个改动文件零告警。

## 4. 批次 B 实施与验证记录

（本轮为单批次交付，无批次 B）

## 5. 交付记录

- **main**：PR #1150（squash `8d9b307c`，2026-09-19 merge，CI 12 项全绿）。
- **win7 对齐**：PR #1154（squash `bfb8bd03`，2026-09-19 merge，必过项全绿）。
  cherry-pick 干净落位（R1 面板全局化后 RightPanel 上下文仍兼容）；win7 基底
  后端 10 例 + 前端 12 例本地全绿。
- **回填分支**：`docs/r27-backfill`（本提交）。
