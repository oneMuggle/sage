# 编码代理对标差距分析·第十五轮：后台工作流指令化与重派可见性（2026-09-12）

- **状态**：批次 A 已交付（分支 `feat-parity-r15-batch-a`，基线 origin/main f4042ec7 = #668）
- **上游文档**：round12（BD 系后台派发/收集已交付）、round10/13（retry_of 重派已交付）——本轮把两者的"机制"补上"conductor 认知"与"用户可见性"
- **对标对象**：Claude Code（后台代理 + TaskOutput 的系统级指引）、Devin（重派透明度）
- **编号约定**：延续 BD/RD 系
- **方法**：conductor prompt / 事件面 / 前端渲染三处核验，附 file:line

## 0. 结论速览

round12/13 交付了机制（background 派发、collect 收集、retry_of 重派），但两个"最后一公里"未通：

1. **BD4 conductor 不知道后台工作流**：conductor 的 system prompt（计划块，`legacy_routes.py`）只讲同步派发与失败处理——`background=true` + `collect_subagents` 组合仅存在于工具 description，conductor 没有被指引"何时该用后台模式、collect 超时意味着什么"。模型对工具的用法认知主要来自 system prompt 的工作流指引。
2. **RD13 徽章 用户不可见**：`_emit_task_status` 事件（`chat_dispatcher.py`）携带 retry_count 但不携带 retry_of——重派任务在任务树上看不出"这是重派"，用户无法追溯"哪些任务是重做的"。

## 1. 差距矩阵

| # | 差距 | 证据 | 对标 | 优先级 |
| --- | --- | --- | --- | --- |
| BD4 | conductor 无后台工作流指引 | `legacy_routes.py` 计划块（RT11 失败指令后无 background/collect 指引） | Claude Code 后台代理指引 | **P2** |
| RD13+ | 重派任务无前端标识 | `_emit_task_status` 事件无 retry_of 字段；`TaskStatusEvent` 类型无该字段；TaskTreeSection 无徽章 | Devin 重派透明度 | P2 |

## 2. 设计（批次 A：BD4+RD13+）

- **BD4**：计划块在 RT11 失败指令后追加 `_BACKGROUND_GUIDE` 常量——何时用 background=true（本批任务运行期间还需要并行做其他工作）、collect_subagents 语义（超时可重复 collect；wait=false 可取快照）、预算触顶时直接汇总。
- **RD13+**：`_emit_task_status` 事件增 `retry_of` 字段（None → 不带键，前端零成本）；前端 `TaskStatusEvent` 类型扩展 + TaskTreeSection 任务行对 retry 非空者显示"重派"小徽章。
- py3.8 纪律照旧；win7 对齐仅后端 + 前端普通 ts/tsx。

## 3. 批次 A 实施与验证记录

（实施后回填）

## 4. 批次 B 实施与验证记录

（本轮为单批次交付，无批次 B）

## 5. 交付记录

（各批次 PR 号与双分支交付号于交付后回填）
