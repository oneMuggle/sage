# 编码代理对标差距分析·第七轮：运行时韧性——上下文生命周期 / 执行中控制 / 失败恢复（2026-09-10）

- **状态**：批次 A 已交付（分支 `feat/parity-r7-batch-a`，基线 origin/main 0e46f6f9 = #564）；批次 B / 批次 C 见 §7 / §8
- **上游文档**：round6（多智能体编排收口，批次 A/B/C 已交付）、round5（信任闭环还账，批次 A/B/C/D 已交付）——本文不重复其内容
- **对标对象**：Claude Code（auto-compact / 运行中打字转向 steering / Esc 中断保留 partial / 失败重试带上下文）、Cursor（长会话上下文管理）、Devin（失败后 re-plan）
- **编号约定**：本轮用 **RT 系**（Resilience），避免与 L/U/F（1-5 轮）、O/D（round6）混编
- **方法**：三路代码勘察（上下文生命周期链 / 执行中控制链 / 失败恢复链），全部结论附 `file:line` 证据，关键落点经人工复核

## 0. 结论速览

前六轮解决"工具面 + 会话语义 + 信任感 UI + 多智能体编排"之后，本轮盘点发现：Sage 在**长任务运行时**的韧性上有三类缺口——正常路径跑得动，但"上下文撑爆、用户中途转向、任务失败"三个异常场景都缺少机制级兜底：

1. **上下文溢出无闭环**：LLM 返回 400 类 context-length 错误被归入 UNKNOWN 直接失败终止（`errors.py:15-27` 枚举无 overflow 类型、`llm_client.py:351` 400→UNKNOWN、不可重试集合 `llm_client.py:36-43` 不含 UNKNOWN）——Claude Code 的做法是压缩历史后重试；且 run_loop 迭代之间历史只增不减（`agent.py:755-767`），唯一的 run 前自动压缩（`legacy_routes.py:2599-2610`）救不了已开跑的 run。压缩阈值（固定 6000 token，`compaction.py:123-138`）与历史截断预算（`history_token_budget()`）两套口径互不相认，前端 ContextMeter 的 tooltip（"达到阈值后会自动压缩历史"）与实际阈值行为脱节。
2. **执行中控制缺失**：流式运行中 UI 硬拦截发送（`ChatInput.tsx:263-264`），store 层排队队列（`useChat.ts:170-177`）只被三个漏守卫的 slash 路径触发（`ChatInput.tsx:311-364`，本身是 bug）——单 agent 没有 steering（运行中把补充指示注入当前 run）；后端同会话并发无 busy 防护（`chat_stream_registry.py:135-158` 无检查，纯前端守卫）；中断后 partial 输出不落盘（`legacy_routes.py:2783` 只在 DONE 持久化），留下无回复的悬空 user 消息、重载即丢内容；无 Esc 中断快捷键。
3. **失败恢复三处断点**：lane 重试是**盲重试**——每次从零重建 messages（`subagent_runner.py:170-198`），`last_error` 记了不注入（`executor.py:305`），三次失败只是同一 prompt 跑三遍；`retry_backoff_secs=[30,120,600]`（`models.py:113`）定义后**全仓无消费者**，重试立即连发；`Planner.refine_plan`/`get_plan_status` 是死 TODO 桩（`planner.py:468-501`，零调用方），conductor system prompt 无任何失败处理指令（`legacy_routes.py:2389-2406`），失败后唯一出路是 LLM 看聚合文本的自由裁量。

与主流的定位差异：Claude Code 的 auto-compact 按模型真实窗口百分比触发并保留摘要；Sage 的历史治理目前是"run 前压缩 + 超预算 drop-oldest"。本轮不追平"按窗口百分比的精确预算"（后端无模型窗口表，硬编码表在 `src/shared/lib/modelWindows.ts` 前端侧），先把**溢出闭环、执行中控制、失败重试质量**三个机制级缺口收口。

## 1. 三链路差距矩阵

### 1.1 上下文生命周期

| # | 现状 | 证据 | 对标 | 优先级 |
| --- | --- | --- | --- | --- |
| RT1 | **溢出错误无分类无恢复**：HTTP 400/413 归 UNKNOWN（不可重试、无降级），直接 FAILED 终止；`LLMErrorType` 无 overflow 类型 | `errors.py:15-27`；`llm_client.py:348-351`（400→UNKNOWN）、`:36-43`（可重试集合） | Claude Code 溢出后压缩重试 | **P0** |
| RT2 | **run 中段历史只增不减**：run_loop 就地 append，唯一防膨胀是工具结果字符帽（32k/条、256k/run）；无迭代边界检查 | `agent.py:827-851`（B1 预算）、`:949-1042`（append）；对照 `agent.py:476-480`（仅 chat() 单发路径有 ConsolidationPipeline） | Claude Code microcompact | P1 |
| RT3 | **压缩与截断两套口径**：auto-compact 阈值固定 6000 token + ≥12 条（与模型无关）；历史截断预算 `history_token_budget()`（≥18000 或随 max_context 推导）——压缩远早于截断触发，两机制不衔接 | `compaction.py:31,123-138`；`history_context.py:36-70`；`legacy_routes.py:2626-2644` | Claude Code 统一按窗口预算 | P1 |
| RT4 | **仪表文案失真**：ContextMeter tooltip 称"达到阈值后会自动压缩历史"，实际阈值（6000 token 启发式）与显示口径（真实 prompt_tokens ÷ 硬编码窗口表）互相对不上 | `ContextMeter.tsx:69-80`；`modelWindows.ts:7-33` | Claude Code "Context left until auto-compact" | P2 |
| — | 已具备：工具结果字符帽（B1）、run 前 auto-compact（M4）+ 手动 /compact（重入护栏）、历史 token 预算截断（保留最近、L9 省略说明）、ConsolidationPipeline（chat 单发）、记忆注入有界（画像 1400 字符/条目 100 字符） | `agent.py:827-851`、`legacy_routes.py:752-791,918+,2626-2644`、`manager.py:237-312` | — | 不再建设 |

### 1.2 执行中控制（单 agent）

| # | 现状 | 证据 | 对标 | 优先级 |
| --- | --- | --- | --- | --- |
| RT5 | **无 steering**：运行中发送被 UI 硬拦截；store 队列（仅自然完成才 flush）是"下一个新 run"不是"注入当前 run"；三个 slash 路径（prompt/skill/help）漏 isLoading 守卫，是队列的唯一触发方（本身是 bug） | `ChatInput.tsx:263-264`（拦截）、`:311-364`（漏守卫）；`useChat.ts:170-177,387-401`（队列语义） | Claude Code 运行中打字即时转向 | **P0** |
| RT6 | **后端无同会话 busy 防护**：`create()` 无条件新建 stream，同会话第二道流与第一道并行读写同一 history，纯靠前端守卫 | `chat_stream_registry.py:135-158`；`legacy_routes.py:1882-1966` | 服务端仲裁 | **P0** |
| RT7 | **中断后 partial 丢失**：producer 只在 DONE 持久化 assistant 内容，中断留下悬空 user 消息；UI 已渲染的内容重载即丢 | `legacy_routes.py:2783`（`if done_content`）、`:2887-2911`（终态 idle） | Claude Code partial 保留 transcript | P1 |
| RT8 | **无 Esc 中断**：Escape 仅用于关闭菜单 | `InputCard.tsx:189` | Claude Code Esc 即断 | P2 |
| — | 已具备：协作式中断链路（stop 按钮 → /interrupt → 置标志 → 迭代边界生效，工具等待者提前唤醒）、中断后会话立即可继续（终态 idle、user 消息保留）、运行中可打字（草稿持久）、重启恢复横幅 | `useChat.ts:752-777`、`agent.py:854-868,1565-1574`、`InterruptedRunBanner.tsx` | — | 不再建设 |
| — | 已知取舍（不在本轮）：单 agent 计划模式（先只读规划→批准→执行）——编排 multi 路径已有 confirmRun 门（`legacy_routes.py:2454-2495`），单 agent 版需要新 UI 范式，归入后续轮次 | 全仓 grep plan_mode 零命中 | Claude Code plan mode | P3 |

### 1.3 失败恢复（编排链）

| # | 现状 | 证据 | 对标 | 优先级 |
| --- | --- | --- | --- | --- |
| RT9 | **盲重试**：重试 = 同一 goal 从零重跑，`lane.metadata["last_error"]` 存而不注入重试 prompt，重试的子代理不知道自己失败过 | `executor.py:299-306`（记 last_error）、`:160`（再调 agent_runner）；`subagent_runner.py:170-198`（每次重建 messages）、`:255`（messages 仅成功时返回） | Claude Code/Devin 重试带错误上下文 | **P1** |
| RT10 | **重试无退避**：`retry_backoff_secs=[30,120,600]` 定义后全仓无消费者，`run_lane_with_retry` 立即连发——对限流/瞬时故障类失败效果差 | `models.py:113`；`subagent_runner.py:342-357`（while 循环无 sleep） | 通用韧性 | **P1** |
| RT11 | **re-plan 死桩 + conductor 无失败指令**：`refine_plan`/`get_plan_status` 是 TODO 桩零调用方；conductor system prompt 只讲"必须执行完全部 N 个子任务"，失败后无任何再规划指引 | `planner.py:468-501`；`legacy_routes.py:2389-2406` | Devin 失败后重规划 | P2 |
| — | 已具备：lane 重试上限（max_retries=2 + MAX_LANE_ITERATIONS=8 防御）、级联失败闭包（`blocked_by_failed:` 前缀，多级链可见）、任务级 wall-clock 超时（round6 O2）、单任务跳过（round6 B3）、单委派通路失败原文回传（主 agent 可自行重试） | `chat_dispatcher.py:585-619,696-699`、`subagent_tool.py:103-107`、`agent_tool.py:561-565` | — | 不再建设 |
| — | 已知取舍（不在本轮）：级联失败是终止性而非"挂起-恢复"（上游重试成功后下游放行）；run 失败后"只重跑失败任务"入口（plan_override 通道在但前端/端点双缺，round6 D4 已登记） | `chat_dispatcher.py:602-619`；`orchRunClient.ts:7-9` | — | P3 |

## 2. 批次规划

| 批次 | 主题 | 内容 | 状态 |
| --- | --- | --- | --- |
| **A（本批）** | 上下文溢出闭环 | RT1 溢出错误分类 + RT2 急救压缩重试闭环（含迭代边界高水位预防）+ RT3 压缩/截断口径统一 + RT4 仪表文案修正 | ✅ 已交付（见 §6） |
| **B** | 执行中控制 | RT5 单 agent steering（后端注入 + 前端运行中发送）+ RT6 同会话 busy 409 + RT7 中断 partial 落盘 + RT8 Esc 中断 | 见 §7 |
| **C** | 失败恢复 | RT9 重试带失败上下文 + RT10 backoff 消费 + RT11 死桩处置 + conductor 失败处理指令 | 见 §8 |

## 3. 批次 A 详细设计

### 3.1 RT1 溢出错误分类（P0，工作量 S）

- `errors.py`：`LLMErrorType` 增 `CONTEXT_OVERFLOW = "context_overflow"`。
- `llm_client.py` `_classify_exception`：HTTP status ∈ {400, 413} 且响应文本命中溢出特征串（大小写不敏感：`context length` / `maximum context` / `context_length` / `context window` / `prompt is too long` / `input token count` / `too many tokens` / `exceeds the maximum` / `reduce the length`）→ `CONTEXT_OVERFLOW`；不命中特征串的 400 维持 UNKNOWN（避免误判把真实参数错误标成溢出）。特征串表抽模块级常量 `_CONTEXT_OVERFLOW_MARKERS`。
- 溢出**不进**可重试集合（`_RETRYABLE_ERROR_TYPES`）——重试同一请求必然复现，必须由上层压缩后重试（3.2）。

### 3.2 RT2 急救压缩 + 重试闭环（P0，工作量 M）

- 新模块 `backend/core/legacy/context_first_aid.py`（零第三方依赖，py3.8 兼容）：
  - `estimate_messages_tokens(messages)`：`len/4 + CJK 计数`启发式（与 `working.estimate_tokens` 同口径，内联实现避免跨层依赖）。
  - `first_aid_compact(messages, keep_recent=6, tool_cap_chars=400)`：**就地**机械压缩，绝不增删消息（保持 tool_call ↔ tool 配对不被 API 拒绝）——保留末尾 `keep_recent` 条原样；更早的消息按角色截断：role=tool 内容 → 头 `tool_cap_chars` 字符 + `\n[已压缩：早期工具结果]`；assistant 长内容（>800 字符）→ 头 400 + 尾 100 + 标记；user 长内容同 assistant。返回估算 token 前后差。
  - 高水位常量 `DEFAULT_RUN_CTX_BUDGET_TOKENS = 100_000`，env `SAGE_RUN_CTX_BUDGET_TOKENS` 可覆盖（0 = 关闭预防性压缩）。
- `agent.py` `run_loop`：
  - **爆后修复**：response 获取段（流式回退非流式整体）包 `try/except LLMError`——`type == CONTEXT_OVERFLOW` 且本迭代未压缩过 → `first_aid_compact(messages)` → yield 一条 THINKING 提示事件（`上下文超限，已压缩早期工具结果后重试`）→ 重试一次；仍溢出 → 原样抛出（走既有 FAILED 面）。
  - **事前预防**：每轮迭代顶部（interrupt 检查之后）估算 `estimate_messages_tokens(messages)`，超预算 → 同一 `first_aid_compact` + THINKING 提示（不重试概念，只是防患）。
  - 收益面：conductor 与子代理共用 run_loop——编排链路自动获得同款兜底（round6 O2 wall-clock 超时是该兜底的失败面，两者互补：溢出先压缩，真挂死才超时）。

### 3.3 RT3 压缩/截断口径统一（P1，工作量 S）

- `compaction.py` `should_compact` 的阈值推导改为：显式 env/settings 覆盖优先（既有 `:31` 机制不动）；未覆盖时取 `history_token_budget()`（= 截断预算）——**当且仅当"再不压缩就要 drop-oldest 截断"时才压缩**，摘要替代丢弃。≥12 条消息地板保留（防极短会话误压）。
- `history_context.py` 不动（截断仍是最后防线，预算语义不变）。

### 3.4 RT4 仪表文案修正（P2，工作量 S）

- `ContextMeter.tsx` tooltip：改为如实描述——会话历史达到压缩阈值后下次发送前自动压缩（摘要替代丢弃）；run 运行中上下文超限会自动急救压缩并重试。不新增"剩余百分比"预测（后端无窗口表，避免二次失真）。

## 4. 批次 B 详细设计（预排期）

- **RT5 steering**：`SageAgent` 增 `_pending_user_messages`（deque）+ `inject_user_message(content)`（run 活跃时入队返回 True）+ run_loop 迭代顶部消费（与 interrupt 检查同位，`【用户补充】` 前缀 user 消息入上下文）；端点 `POST /api/v1/chat/steer`（`{stream_id, content}`，查 `_ACTIVE_STREAMS`）；前端 `useChat.sendMessage` 在会话已有活跃流时先试 steer、失败回退既有队列；补齐三个 slash 路径守卫（经 sendMessage 统一路径后自然修复）。
- **RT6 busy 409**：`StreamRegistry.create` 同会话已有活跃（pending/streaming）entry → 抛 `SessionBusyError` → 路由映射 409 `{code:"session_busy"}`。
- **RT7 partial 落盘**：producer 累积 CONTENT_DELTA；中断收尾且 partial 非空 → 落盘 assistant 消息（尾部加 `\n\n[已中断]` 标记）。
- **RT8 Esc**：`InputCard` keydown Escape → isLoading 且无菜单打开时触发 `onInterrupt`。

## 5. 批次 C 详细设计（预排期）

- **RT9**：`executor.execute_lane` 开头读 `lane.metadata` 的 `retry_count`/`last_error`，>0 时写入 `task.parameters["retry_hint"]`（不改变 `agent_runner` 调用签名，测试桩零感知）；`SubagentRunner.__call__` 读到 hint 时在 goal 前置 `【重试 · 第 N 次】上次失败：{last_error}。请调整方法避免重蹈覆辙。`
- **RT10**：`run_lane_with_retry` 增可选 `backoff_secs`；dispatcher 从 `RecoveryPolicy.retry_backoff_secs` 传入，attempt 间 `asyncio.sleep`（受 O2 wall-clock 超时整体约束）；`models.py` 默认退避从 `[30,120,600]`（当年按无人消费的占位值声明）调为交互友好的 `[5,15,30]`。
- **RT11**：删除 `refine_plan`/`get_plan_status` 死桩（诚实收口，与 round6 D2 plan_write 退役同逻辑）；conductor system prompt 增加失败处理指令（"子任务失败时：读错误文本→修正 hint/依赖→可重新派发；勿盲目原样重派"）。

## 6. 批次 A 实施与验证记录（2026-09-10）

- 全部 4 项按 §3 设计落地；改动文件：`backend/core/errors.py`（RT1 枚举）、`backend/core/legacy/llm_client.py`（RT1 `_CONTEXT_OVERFLOW_MARKERS` + `_is_context_overflow_text` + 400/413 分类，仅特征串命中才判溢出）、`backend/core/legacy/context_first_aid.py`（新，RT2 机械压缩/估算/高水位预算）、`backend/core/legacy/agent.py`（RT2 迭代边界高水位预防 + response 获取段急救环 `_MAX_FIRST_AID_ATTEMPTS=2`：常规 keep_recent=6 → 激进 keep_recent=2）、`backend/chat/compaction.py`（RT3 `default_compact_threshold()`：显式覆盖优先，否则 `history_token_budget()`）、`src/widgets/chat/ContextMeter.tsx`（RT4 tooltip 如实化）。
- 实现期设计修正：原设计"溢出后 yield 一条 THINKING 提示事件"不可行——前端 `useChat.ts` 把带 content 的中间态事件**追加进气泡**（`evt.content` 分支先于 uiText 分支），提示文本会污染回答内容且与 DB 不一致；改为仅日志的透明治理（压缩标记嵌入被截断消息本身，模型可自察）。
- 溢出重试与流式安全：首个增量之后失败无法安全重放（重试会重复下发内容），流式错误带 `_saw_content_delta` 标记，急救环对该路径跳过重试按原错误面终止——与既有"首个增量前才回退非流式"语义一致。溢出特征串不命中保持 UNKNOWN，避免参数错误误判。
- 测试：新增 `test_context_first_aid.py` 13 例（估算口径/结构不变式/保护区/标记/非法条目/预算 env）；`test_agent_run_loop.py` +5 例（急救重试→DONE、两次耗尽原样抛出、mid-stream 跳过急救、高水位预防、非溢出错误不触发）；`test_llm_client_errors.py` +5 例（4 组溢出特征分类 + 非 400 溢出特征保持 UNKNOWN）；`test_compaction.py` +4 例（env/settings 覆盖优先、无覆盖与截断预算同口径）。四文件 76 用例全绿；相关回归面（subagent_runner/history_context/chat_stream/compactor/orchestration 关键字）204 passed——失败项逐一与基线 stash 对照确认为本地既有（executor 14 errors + e2e router 1，见 round6 §6 同款记录）；ruff 全过。
- 前端仅 ContextMeter tooltip 文案（既有测试不校验该句子）；tsc/eslint 于批次 B 统一跑（共享 npm ci）。

## 7. 批次 B 实施与验证记录（2026-09-10）

- **RT5 steering**：`SageAgent` 增 `_pending_user_messages`（deque）+ `_run_loop_active` 窗口标志 + `inject_user_message()`（非活跃/空文本拒绝）+ `_drain_pending_user_messages()`；run_loop 启动清空残留（不跨 run 泄漏）、finally 收窄窗口；迭代顶部（中断检查之后）排空注入，格式 `【用户补充】{content}`（user role，与编排链 O1 边界投递同语义）。端点 `POST /api/v1/chat/steer`（`{stream_id, content}`，查 `_ACTIVE_STREAMS`；404 stream_not_found / 409 not_running / 400 empty_content·msg_too_long，额度 8KB 与 O1 对齐，纯内存不走 DB 锁）。前端：`chatApi.steer`（invoke `chat_steer`，失败归 false）→ `useChat.sendMessage` 会话忙时先试 steer（成功 toast"已转达，将在下一迭代边界生效"），编排模式与失败场景回退既有队列；`ChatInput.handleSend` 去掉 isLoading 硬拦截——三个 slash 路径漏守卫 bug 随统一路径自然修复。
- **RT6 busy 409**：`StreamRegistry.create` 同会话已有 pending/running 且非挂起的 entry → `SessionBusyError`（挂起流与终态不占位，无 session_id 不检查）；`chat_stream_create` 映射 409 `{code:"session_busy", active_stream_id}`。
- **RT7 partial 落盘**：producer 累积 CONTENT_DELTA（`streamed_partial_parts`）；finally 中用户取消且 DONE 未产出且有 partial → 落盘 assistant 消息（尾部 `[已中断]` 标记）+ 向队列推 `partial_persisted` 事件；LLMError/自然完成路径不落 partial（保持既有语义）。
- **RT8 Esc**：`InputCard.handleKeyDown` 在 emacs 绑定之后加 Escape→`onInterrupt`（isLoading 时）；slash 菜单打开时 Escape 优先归菜单（原分支 return），不误触。
- 测试：新增 `test_chat_steer.py` 9 例（agent 注入窗口/边界消费/跨 run 泄漏 + 端点 200/404/409/400）；`test_chat_stream_registry.py` +5 例（busy 拒绝/终态放行/挂起不占位/跨会话无碍/无 session 不检查）；前端 `ChatInput.steer.test.tsx` 3 例（运行中 Enter 可发送/停止按钮/Esc 空拦截）+ `InputCard.test.tsx` +3 例（Esc 中断/非加载不触发/加载中 Enter 照常）。后端 36 用例回归面全绿（含既有 interrupt/registry/streaming 回归），前端 25 passed；ruff / tsc / eslint 全过。

## 8. 批次 C 实施与验证记录（2026-09-10）

- **RT9 重试带失败上下文**：`executor.execute_lane` 读 `lane.metadata` 的 `retry_count`/`last_error`，重试时写 `task.parameters["retry_hint"]`（`contextlib.suppress(AttributeError)` 兼容不可写测试桩；hint 截 2000 字符）；`SubagentRunner.__call__` 组装 prompt 时前置 `【重试 · 第 N 次】上次执行失败：…请调整方法，避免重蹈覆辙`。选 `task.parameters` 载体而非改 `agent_runner` 调用签名——测试桩零感知。首次执行 prompt 与旧版逐字一致。
- **RT10 backoff 消费**：`run_lane_with_retry` 增 `backoff_secs` 可选参（索引按 `retry_count-1` 取、越界取末位，`asyncio.sleep` 退避，受 O2 wall-clock 超时整体约束）；dispatcher 把 `RecoveryPolicy.retry_backoff_secs` 传入两处重试环调用；`models.py` 默认退避 `[30,120,600]`（当年无人消费的占位值）→ `[5,15,30]`（桌面交互体感）。reviewer 路径不传 backoff，行为不变。
- **RT11 死桩处置 + conductor 失败指令**：删除 `Planner.refine_plan`/`get_plan_status`（零调用方；refine_plan 是 TODO 桩、get_plan_status 恒返回 not yet implemented——与 round6 D2 plan_write 退役同逻辑，留删除注释防复活）；conductor 计划块追加失败处理指令（读失败原因 → 可修复的改 goal/换 agent 重派新任务，不可行的在汇总说明，勿原样重派）。
- 测试：新增 `test_retry_resilience.py` 7 例（runner 前置 hint / 无 hint prompt 不变 / executor 写 hint / backoff 生效·无 backoff 不 sleep / 默认退避档位 / 死桩已删）；编排回归面（executor/planner/runner/dispatcher 超时与跳过）49 passed——14 个 executor error 与 round6 记录的本地基线完全一致（Windows 本地环境问题，CI 为准）；ruff 全过。
- CI 实证修正：dispatch 调用点直传 `backoff_secs` 会炸掉全部 `(executor, lane, agent_id)` 三参测试桩。且 `mock.patch(target, side_effect=fake)` 产出的 MagicMock 的 `inspect.signature` 恒为 `(*args, **kwargs)`——首次兼容（直接 `func_accepts_kwarg` 探测）被 CI 二次实证击穿，kwarg 照样落进三参 fake 的 TypeError。最终方案 `run_lane_accepts_backoff()`：穿透 `side_effect` 真实函数探测（`side_effect` 为返回值列表等不可调用对象时按原对象探测，Mock 吞任意 kwarg 无害）。修复后 dispatcher/review/router 全部桩密集测试文件 62 passed + CI 失败的 review_event 集成用例本地复现转绿。

## 9. 交付记录

（各批次 PR 号与双分支交付号于交付后回填）

| 批次 | main | win7 |
| --- | --- | --- |
| A | PR #571 | 待回填 |
| B | 待回填 | 待回填 |
| C | 待回填 | 待回填 |
