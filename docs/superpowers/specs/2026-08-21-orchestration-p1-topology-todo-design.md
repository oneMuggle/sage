# 编排 P1：depends_on 拓扑调度 + Agent 自维护 todo 列表 — 设计文档

日期：2026-08-21
状态：已与用户确认设计方向
分支策略：main 实现 → 合并后 cherry-pick 到 release/win7（双分支同步，py3.8 兼容约束见 §5）

## 背景与目标

P0 编排控制批次（PR #353/#354）收尾后遗留两项高优先级 P1：

1. **depends_on 真实拓扑调度**——现状任务全并行派发，依赖关系仅透传展示给 LLM。`get_ready_tasks` 在三处实现（`models.py:385` TaskGraph、`task_registry.py:155`、`orchestration_repo.py:160`）但生产代码零调用。这是功能正确性缺口。
2. **Agent 自维护 todo 列表**——主 agent 缺少 Claude Code 式的结构化任务清单能力。定位为"通用工具 + 编排打通"，同 spec 分两阶段交付。

非目标（本次不做）：SendMessage 式子代理续聊、schema 结构化返回、worktree 隔离、legacy orchestrator 清理、Lane API 激活。

## 第一部分：depends_on 拓扑调度

### 现状

- 派发链路：conductor LLM 一次把整批任务交给 `DispatchSubagentsTool` → `ChatDispatcher.dispatch()`（`chat_dispatcher.py:207`）→ 内部对本批全部任务 `asyncio.gather(_run_one)` 全并行（L291-293），仅信号量限并发（默认 4）。
- `ChatTaskState` 无 depends_on 字段；`chat_dispatcher.py:235` 注释明确「depends_on 直接随 plan_json 透传（A4 不用）」。
- 计划层 `templates.py:18` 的 `depends_on` 由 `planner.py:253,422-431` 解析成 Task.blocked_by。
- 状态机已有 `blocked` 状态（`models.py:20-32`）。
- 前端 `TaskTreeSection.tsx:93-110` 渲染缩进 + 「↳ 依赖 t1, t2」文本。

### 设计决策（用户确认）

| 决策点 | 结论 |
|---|---|
| depends_on 语义 | **硬阻塞**：依赖未完成的任务不派发 |
| 强制点 | **dispatcher 内部分波**：不依赖 LLM 行为，确定性最强 |
| 上游失败传播 | **级联取消**：上游 failed/stopped 时传递闭包内下游直接置 failed 不派发 |

### 方案

改动集中在 `backend/orchestration/chat_dispatcher.py` 的 `dispatch()`：

1. **建图分层**：dispatch 入口用本批任务的 blocked_by 建 TaskGraph，Kahn 分层得到波次序列。检测到环则拒单，向 LLM 返回明确错误信息（含环路径），不派发任何任务。
2. **逐波执行**：
   - 每波内 `asyncio.gather` 全并行（信号量限流不变）；
   - 波间等待该波全部到达终态（completed/failed/stopped）；
   - 波完成后调用现成 `get_ready_tasks` 逻辑确定下一波成员。
3. **级联取消**：某任务终态为 failed 或 stopped 时，其传递闭包内所有未启动下游直接置 failed（原因标注 `blocked_by_failed:<upstream_id>`），不发子代理运行，SSE 正常推送状态变化。
4. **聚合不变**：全部终态后仍走现有 `_aggregate()`（`chat_dispatcher.py:466`）+ reviewer 流程；聚合结果中标注级联失败的任务及其根因上游。
5. **事件兼容**：每波开始/结束推现有 task_progress 类事件，前端无需协议变更即可看到顺序执行；后续可加波次号字段增强。

### 测试

- 单测：Kahn 分层正确性（线性/菱形/多入多出）、环检测拒单、级联取消闭包、单任务批退化为原行为。
- 并行性回归：同波内仍并行（复用 `test_orchestrator_parallel.py` 思路）。
- 集成：`test_chat_orchestration_stream.py` 增加两波场景（t1→t2,t3→t4）验证 SSE 顺序。

## 第二部分：Agent 自维护 todo 列表（两阶段）

### 定位（用户确认）

通用主 agent 工具 + 编排任务树打通；**单向镜像**（编排任务 → todo 展示）控制复杂度，不做反向升级。

### 阶段 1：通用 todo 工具

1. **工具**：新增 `todo_write` 工具注册到 conductor 及普通对话主 agent 工具表。操作集：`add`（subject/description）、`update`（status: pending/in_progress/completed）、`remove`。清单上限 20 项（防滥用宽松上界）。
2. **存储**：会话级内存（session 作用域 dict），生命周期与对话流一致，不落库。
3. **推送**：变更后通过现有 SSE 通道推 `todo_snapshot` 事件（全量快照而非增量，前端无状态合并负担）。
4. **前端**：聊天区新增 TodoList 卡片组件，实时渲染清单（状态徽章 pending/in_progress/completed）。路由切换保留行为依赖现有消息持久化机制，卡片随最新快照重建。

### 阶段 2：编排镜像打通

1. **镜像规则**：编排模式下 `task_plan` 事件产生时，自动将计划任务镜像为 todo 项（只读，禁用 todo_write 对这些项的修改）；任务状态机变化（running/completed/failed/stopped/blocked）同步映射到 todo 状态。
2. **波次推进可见**：第一部分拓扑分波的每波开始/结束同步反映到镜像项状态，用户在 todo 卡片看到波次推进。
3. **混合视图**：主 agent 自建 todo 项与编排镜像项共存于同一卡片，镜像项带标识区分。

### 测试

- 单测：todo 工具操作语义、上限校验、快照生成；镜像状态映射表全覆盖。
- 集成：SSE `todo_snapshot` 事件流；编排模式下镜像自动创建与状态跟随。
- 前端 vitest：TodoList 卡片渲染、状态徽章、镜像项标识。

## 错误处理

- 环检测失败：拒单错误信息含环路径（如 `t2 -> t3 -> t2`），LLM 可自纠重派。
- 级联失败原因写入 task result 与聚合摘要，reviewer 可感知。
- todo 工具非法 status/超上限：返回结构化错误给 LLM，不崩溃。
- SSE 断线重连：todo_snapshot 全量快照天然支持恢复。

## py3.8 兼容约束（win7 cherry-pick 前提）

- 禁用 PEP 604 运行时 union（`X | Y` 注解仅限 `from __future__ import annotations` 下的函数签名；isinstance 场景必须用 `Union`/`Optional` 显式导入）。
- 禁用 `zip(strict=)`、py3.10+ 括号 context manager、match 语句。
- 模块级变量注解不得带 forward-ref 引号（Ruff UP037 教训）。

## 实施顺序建议

1. 第一部分拓扑调度（独立 PR，功能正确性优先）
2. 第二部分阶段 1 通用 todo 工具（独立 PR）
3. 第二部分阶段 2 编排镜像（独立 PR）
每个 PR main 合并后评估 cherry-pick 到 release/win7。

## 风险与依赖

- 分波会拉长有依赖场景的总耗时（串行化代价）——预期内，换取正确性；无依赖场景行为不变（单波全并行）。
- `ChatDispatcher` 文件已较大，分波逻辑独立成模块（如 `topology.py`）保持文件 <800 行。
- 镜像打通依赖 SSE 协议扩展（todo_snapshot 新事件类型），需前后端同 PR 协调。
