# 迭代上限错误清晰化 + LLM 思考过程可见性修复

> 状态：已完成（待 PR 合并后归档）
> 创建：2026-10-29
> 分支：fix/iteration-cap-and-reasoning-display
> worktree：`.worktrees/fix-iteration-cap-and-reasoning-display`

## 背景与目标

用户报告两个独立问题：

1. **LLM 思考/输出不可见**：主 SSE 路径下只看到工具调用气泡，看不到模型推理文本（ThinkingPanel 不渲染）与最终回答。
2. **迭代上限错误提示误导**：用户看到「任务复杂度超出迭代上限 10 次」后误以为是 `complexity_classifier` 的分类结果（实际无关），且不知道是 **哪个 agent profile** 的上限被打满。

**目标**：

- 让 reasoning 在主 SSE 路径下可见（前端累积本就存在；缺口在后端流式分支
 丢弃 `response.reasoning_content`，步骤 4b 补齐兜底）。
- 让 `effective_max_iterations` 的记录与下发保持与优先级链一致，使超限
  错误能指出 **哪个 agent** + **上限来源**。
- 让超限错误文本明确指出 **哪个 agent** + **上限来源** + **去哪个设置项调**。
- 让中间态占位文案不再覆盖已流式产出的正文（失败场景下用户仍能看到模型
  已经写出的内容）。

## 涉及文件

见文末「涉及文件（最终）」—— 实施期核对后已校正（原表将 `useChat.ts` 误判为
reasoning 累积缺口；实际 reasoning 累积在 `chatStreamRuntime.ts` 的
`applyTransparencyAndToolEvents` 中已实现）。

## 事实校正（2026-10-29 实施前核对）

| 配置项 | 实际字段 | 默认值 |
|---|---|---|
| `orch_settings.max_iterations` | 全局统一上限 | 25 |
| `orch_settings.max_subagent_iterations` | 子代理（agent_tool）单次委派预算 | 6 |
| `orch_settings.max_scout_iterations` | 侦察 Agent 预算 | 4 |
| `orch_settings.max_planner_iterations` | 规划 Agent 预算（阶段 2.1 才消费） | 8 |
| profile `primary.max_iterations` | 主助手 profile 默认 | 25 |
| profile `researcher.max_iterations` | 研究 Agent profile 默认 | 8 |
| profile `coder.max_iterations` | 编码 Agent profile 默认 | 15 |
| profile `writer.max_iterations` | 写作 Agent profile 默认 | 10 |
| profile `memory_manager.max_iterations` | 记忆 Agent profile 默认 | 5 |

**关键观察**：`orch_settings` **不存在** `max_primary_iterations` / `max_coder_iterations` / `max_reviewer_iterations` / `max_writer_iterations` 等 per-agent 细分键。前端 `OrchSettings` 类型也没有对应字段。

**"10 次上限"的归因路径**：

- 当前 `orch_settings.max_iterations = 25`（默认非 0），所有走 fallback 路径的 agent 统一用 25
- 用户看到的"10"更可能来自：writer profile 默认=10 或调用方显式传 `max_iterations=10` 的场景（如 sub-agent 委派时 conductor 按 task 复杂度给定）
- 错误文案的"任务复杂度"措辞误导用户联想到 `complexity_classifier`（实际无关）

## 收敛方案（两个正交修复）

### Fix A — 错误消息携带结构化上下文

FAILED 事件字符串从：

```
max_iterations_exceeded (limit=10)
```

改为：

```
max_iterations_exceeded (limit=10, agent=writer, source=profile)
```

`source` 取值（与优先级链对应）：

| source 值 | 含义 | 触发条件 |
|---|---|---|
| `explicit` | 调用方硬覆盖 | 显式传 max_iterations 参数 |
| `orch.global` | 全局 UI 配置 | orch_settings.max_iterations > 0 |
| `profile` | profile 默认值 | orch global = 0，回落 profile（具体 profile id 见 `agent=`） |
| `default` | 兜底值 10 | 无 profile 且 orch global = 0 |

前端正则扩展为捕获 `agent` 与 `source` 两字段（兼容旧格式）：

```
^([a-z][a-z0-9_]*)\s*\(([^()]*)\)$
```

### Fix B — reasoning 不可见（实施期校正）+ 中间态占位符不再吞掉已流式正文

**实施前核对发现**：前端主 SSE 路径并不存在 reasoning 累积缺口——
`useChat.ts` 的 onEvent 会先调用 `applyTransparencyAndToolEvents`
（`chatStreamRuntime.ts:231-242`），已在其中按 `reasoning_delta` /
`reasoning` append、`reasoning_final` replace 写入 `useChatStreamStore`。
真正的 reasoning 丢失发生在**后端流式分支**：provider 不发
`reasoning_delta`、只把整段思考塞进 `response.reasoning_content` 时，
`agent.py` 流式路径只看 `stream_reasoning_parts`，整段思考被丢弃
（非流式路径本来有 `response.reasoning_content` 兜底）。

因此 Fix B 实际落实为两处后端/前端修改：

1. **后端兜底（步骤 4b）**：`agent.py` 流式分支在
   `stream_reasoning_parts` 为空时回退到 `response.reasoning_content`，
   补发一条 `REASONING` 事件，与非流式路径口径对齐。
2. **前端占位符修复（步骤 4）**：排查中发现第二条导致"只看到工具气泡"的
   路径——`thinking` / `acting` / `observing` 的中间态占位文案此前**无条件**
   `replaceContent`，LLM 一旦已流式产出正文，下一个工具事件就把正文擦掉；
   迭代上限失败（无 DONE 收尾）时 `finishStream` 又把残留占位符
   （`🤔 思考中…`）当正文写回消息，用户最终只看到一句占位文案。
   修复：用 `hasRealContent` 标记真实正文状态——
   - 首个真实 token 替换占位符，后续 token 追加；
   - 已有真实正文时中间态占位符不再覆盖正文；
   - `finishStream` 在从未产出正文时清空占位符，不写回消息；
   - DONE.content 与已流式内容去重，避免正文重复；
   - `step_done` 切新气泡时重置标记。

## 涉及文件（最终）

| 文件 | 角色 |
|---|---|
| `backend/core/legacy/agent.py` | 优先级链 `_limit_source` + FAILED 事件携带 agent/source + 流式路径 reasoning 兜底 |
| `src/shared/lib/errorMapping.ts` | 错误码→中文化映射 + agent/source 解析 + 差异化文案 |
| `src/features/send-message/useChat.ts` | 中间态占位符不得覆盖已流式正文；DONE 去重 |
| `src/features/send-message/chatStreamRuntime.ts` | 只读参考（reasoning 累积已在此实现） |
| `backend/agents/profiles.py` | 各 agent profile 的 `max_iterations` 硬编码默认（只读参考） |
| `backend/tests/unit/test_agent_run_loop.py` | 断言新错误串格式 + agent/source 用例 |
| `backend/tests/unit/test_agent_streaming.py` | 流式 reasoning 兜底回归 |
| `src/shared/lib/errorMapping.test.ts` | agent/source 解析与文案用例 |
| `src/features/send-message/__tests__/useChat.streamingAndGates.test.ts` | 占位符不覆盖正文 + DONE 去重用例 |

## 实施步骤

- [x] 步骤 1：`agent.py` — 重构 `effective_max_iterations` 记录 `_limit_source`（无行为变更）
- [x] 步骤 2：`agent.py` — FAILED 事件字符串携带 `agent=<id>, source=<src>`（无 agent 时省略该段）
- [x] 步骤 3：`errorMapping.ts` — 扩展正则 + agent/source 解析 + 差异化文案
- [x] 步骤 4：`useChat.ts` — 中间态占位符不得覆盖已流式正文（Fix B 校正后的实际缺口）
- [x] 步骤 4b：`agent.py` — 流式路径在 `stream_reasoning_parts` 为空时回退 `response.reasoning_content`
- [x] 步骤 5：本地回归验证（后端 pytest 94 项 + 前端 vitest 全量绿）
- [ ] 步骤 6：提交 PR

## 风险评估

| 风险 | 缓解 |
|---|---|
| 后端 error 字符串格式变化可能影响已有 `parseAgentErrorLimit` 消费方 | 新格式仍匹配 `^([a-z][a-z0-9_]*)\s*\(([^()]*)\)$`；前端解析失败回落老文案；老格式（只有 `limit=`）兼容 |
| reasoning 累积与 reattach 路径语义漂移 | reasoning 累积单点位于 `applyTransparencyAndToolEvents`（主/重接共用），后端只补发缺失事件 |
| FAILED 事件 `agent=<id>` 字段在无 profile 且 `agent_id` 为空的场景 | 该段整体省略（避免 `agent=, source=…` 畸形串）；前端对缺失 agent 回落「本次任务」 |

## 依赖

无外部依赖，纯内部重构。
