# 编码代理对标差距分析·第十轮：失败任务机制级重派（2026-09-11）

- **状态**：批次 A 已交付（分支 `feat/parity-r10-batch-a`，基线 origin/main ae044997 = #627）
- **上游文档**：round7（RT9 重试带失败上下文 + RT11 conductor 失败指令已交付）、round9（档案文件化已交付）——本轮把 round7 RT11 的"conductor 可重新派发"从 **prompt 指令升级为工具原语**
- **对标对象**：Devin（失败后 re-plan/重派）、Claude Code（重试继承工作目录与错误上下文）
- **编号约定**：本轮用 **RD 系**（Re-Dispatch）
- **方法**：在最新 main（#627 后）复核派发工具/解析/隔离目录三处现状，附 file:line

## 0. 结论速览

round7 之后，conductor 失败处理只剩"软机制"：system prompt 指令说"可重新派发"（`legacy_routes.py` 计划块 RT11 指令），conductor 也确实能对未知 task_id 动态加任务（`chat_dispatcher.py:393-399` 回退 tool-passed 值）——但**重派任务拿不到失败现场**：

1. **RD1 scratch 隔离目录不继承**：失败任务的 scratch_dir（`_scratch_dir_for`，`chat_dispatcher.py:866`，落 `task.parameters["scratch_dir"]`）随新任务重新生成全新目录——失败前已 clone/准备好的现场全部丢弃，重派=从零再来。
2. **RD2 失败原因不随行**：源任务的 `state.error` 只在聚合文本里出现过一次；重派新任务若 conductor 没在 goal 里手抄错误，子代理对上次为什么失败一无所知（RT9 的 retry_hint 消费端已就绪，但没有写入方）。
3. 对照 `followup_of`（`subagent_tool.py:44-49`、dispatcher `:411-418`）——done 任务已有"续聊"原语，failed 任务没有对应的"重派"原语，工具面不对称。

## 1. 差距矩阵

| # | 差距 | 证据 | 对标 | 优先级 |
| --- | --- | --- | --- | --- |
| RD1 | 重派任务不继承失败现场（scratch_dir 全新） | `chat_dispatcher.py:696`（`_scratch_dir_for` 每任务新生成） | Claude Code 重试同目录 | **P1** |
| RD2 | 失败原因不随重派任务走（retry_hint 无写入方） | RT9 消费端 `subagent_runner.py`（retry_hint 前置 prompt）；写入方仅 lane 重试（executor.py），跨派发无通道 | Devin re-plan 带上下文 | **P1** |
| — | 已具备：动态任务派发（未知 task_id 回退 tool 传值）、lane 内重试 retry_hint（RT9）、conductor 失败指令（RT11）、`retry_backoff_secs`（RT10） | `chat_dispatcher.py:393-399`、`executor.py:158-172`、`legacy_routes.py` RT11 块 | — | 不再建设 |

## 2. 设计（批次 A：RD1+RD2）

- **工具面**：`dispatch_subagents` task 条目增可选 `retry_of`（本 run 内已失败/被取消子任务的 task_id）；description 注明"重派=新任务 + 继承失败现场，与 followup_of（续聊 done 任务）互补，二者互斥时 retry_of 优先"。
- **解析**（dispatcher.dispatch 循环，followup_of 同位）：`retry_of` 有效条件 = 源在 `_states` 且终态 failed/cancelled 且 ≠ 自身；无效降级普通任务（与无效 followup_of 同款降级路径，`state.retry_of=None`）。**不建依赖**（源是 failed，建依赖会被 build_waves 级联判死）。
- **继承**（`_run_subagent_impl`）：源任务 `task.parameters["scratch_dir"]` 存在 → 覆盖新任务 scratch_dir（现场延续）；注入 `parameters["retry_hint"] = {"attempt": 源 lane retry_count+1, "last_error": 源 state.error}` → RT9 消费端自动前置"【重试 · 第 N 次】上次执行失败…"。
- **前端零改动**（任务树自然新增节点）；py3.8 纪律照旧。

## 3. 批次 A 实施与验证记录（2026-09-11）

- **工具面**：`dispatch_subagents` task 条目增 `retry_of`（INPUT_SCHEMA + description + _TOOL_DESCRIPTION 注明"继承工作现场与失败原因，与 followup_of 互补"）。
- **解析**（dispatcher.dispatch，followup_of 同位）：有效源 = 在 `_states` 且终态 failed/cancelled 且 ≠ 自身；无效降级普通任务并 warning（与无效 followup_of 同款降级路径）。不建依赖（源是 failed，建依赖会被 build_waves 级联判死）；与 followup_of 同传时二者语义独立（followup 链接 done 父、retry_of 优先级以源状态判定）。
- **继承**：逻辑提取为 `ChatDispatcher._apply_retry_inheritance(state, parameters)`（可直测纯方法）——源 task 的 `scratch_dir` 存在则覆盖新任务 parameters（现场延续）；注入 `retry_hint = {"attempt": 源 retry_count+1, "last_error": 源 error[:2000]}`（RT9 消费端前置 prompt）；源 task 缺失（跨 run/已清理）→ scratch 不覆盖、hint 仍注入兜底 `unknown`；非 retry 任务无操作。`_run_subagent_impl` 在 parameters 构建后调用。
- 测试：`test_chat_dispatcher_retry_of.py` 5 例（failed 源解析 + done 源降级 + 未知源降级 + 继承方法直测 + 注册表缺失兜底 + schema 暴露）；dispatcher 回归（skip/timeout/主套件）58 passed；ruff 全过。

## 4. 批次 B 实施与验证记录

（本轮为单批次交付，无批次 B）

## 5. 交付记录

| 批次 | main | win7 |
| --- | --- | --- |
| A（失败任务机制级重派） | PR #636（squash ff9aaf4e） | PR #637（cherry-win7-r10，squash 93ef2a0d） |

win7 对齐说明：零冲突落位；py38 job 首跑 `test_wiki_chat_stream` 403 flake（与本批改动无交集），rerun 后全绿，squash merge（#637）。
