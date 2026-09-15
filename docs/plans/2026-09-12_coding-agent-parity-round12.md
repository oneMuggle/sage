# 编码代理对标差距分析·第十二轮：后台子代理派发与中途收集（2026-09-12）

- **状态**：批次 A 已交付（分支 `feat-parity-r12-batch-a`，基线 origin/main 298a00db = #645）
- **上游文档**：round6 §1.4 登记的 P3 取舍"主 agent 无法中途取部分结果（阻塞式聚合是工具协议使然）"——O4（observe_subagents）解决"看进度"后，本轮解决"派发后不阻塞"
- **对标对象**：Claude Code（`run_in_background` + TaskOutput/TaskStop 后台代理模型）
- **编号约定**：本轮用 **BD 系**（BackgrounD dispatch）
- **方法**：派发工具/dispatcher/事件投影三处现状核验，附 file:line

## 0. 结论速览

conductor 的并行派发是**同步阻塞原语**：`dispatch_subagents` 工具一直等到全部子任务终态、拿到聚合文本才返回（`subagent_tool.py:87-105` → `chat_dispatcher.dispatch`）。conductor 在等待期间无法做任何其他工作——不能基于先完成的结果提前行动、不能并行做自己的收尾。observe_subagents（O4）虽可"看进度"，但拿不到结果、也改变不了阻塞语义。Claude Code 的后台代理（run_in_background + TaskOutput）允许"派发后先干别的，随时收割"。

| # | 差距 | 证据 | 对标 | 优先级 |
| --- | --- | --- | --- | --- |
| BD1 | 派发不可后台化：工具协议阻塞至全部终态 | `subagent_tool.py:102`（`await dispatch`） | Claude Code run_in_background | **P1** |
| BD2 | 无中途收集原语：无"等待后台批次并取聚合"的工具 | 全库无 collect 工具 | Claude Code TaskOutput | **P1** |
| — | 已具备：observe_subagents 进度轮询（O4）、任务板/事件投影后台照常工作、预算守门（round11）在后台路径同样生效 | `chat_dispatcher` | — | 不再建设 |

## 1. 设计（批次 A：BD1+BD2）

- **dispatcher**：`start_background_dispatch(tasks)`（`asyncio.create_task(dispatch(...))`，在飞未终态返回 None 互斥）+ `wait_background(timeout)`（`asyncio.shield` —— collect 超时/取消不杀派发；无在飞抛 `RuntimeError(no_background_dispatch)`）。`dispatch()` 本体零改动。
- **工具**：`dispatch_subagents` 顶层 `background` 参数（默认 false，既有调用零变化）；background=true 立即返回 `{status:"dispatched_background", run_id, task_ids, note}`；在飞重复派发 → `background_dispatch_in_progress`。新增 `CollectSubagentsTool`（`timeout_secs` 默认 600；超时错误明示可再次 collect；仅支持异步）。
- **接线**：multi 分支注册 `CollectSubagentsTool(dispatcher)`；conductor profile 白名单成对追加。
- 前端零改动（任务树/事件投影对后台任务照常渲染）。

## 2. 批次 A 实施与验证记录（2026-09-12）

- 全部按 §1 落地：`chat_dispatcher.py`（`_bg_task` 句柄 + `start_background_dispatch`/`wait_background`）、`subagent_tool.py`（`background` 参数 + 后台快照返回 + `CollectSubagentsTool`）、`legacy_routes.py`（multi 分支注册 + 白名单成对追加 + 惰性导入改多行）。
- 测试：`test_chat_dispatcher_background.py` 7 例（start/wait 闭环 + 在飞互斥 + 超时 shield 不杀派发 + 无派发报错 + collect 透传/超时/无派发 + background 快照 + 在飞重复错误 + schema 暴露）；ruff 全过。

## 3. 批次 B 实施与验证记录

（本轮为单批次交付，无批次 B）

## 4. 交付记录

| 批次 | main | win7 |
| --- | --- | --- |
| A（后台派发与中途收集） | PR #648（squash 57740a42） | PR #650（cherry-win7-r12，squash 9c91e17f） |

win7 对齐说明：零冲突落位；py3.8 纪律（asyncio.TimeoutError + noqa UP041）随测试迁移；本地 ruff 全过 + background 7 例绿后由 CI（含 py3.8 job）终验，squash merge（#650）。
