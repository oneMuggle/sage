# 多会话并行与会话状态/进度/产物·侧边栏绑定优化方案（2026-09-06）

- **状态**：批次 A（S1–S4）已交付 + S5/S7/S9 已交付（分支 `feat/multi-session-parallel`，win7 对齐 cherry-pick 中）；S6/S8 为 round-2 U1/U6 的会话维度增量，其中 S6-lite（会话项 +N 变更徽章）已随批次 A 落地，S8 待 U6 交付
- **实施说明**：S1 写库点采用"producer 内两处直写"替代原计划的 registry 回调（LLMError 在 registry 层面记 done、事件层面记 failed，producer 才知道真实结局）；S6-lite 以流槽位内的 write_file/edit_file/apply_patch 成功调用数计变更，不依赖 git 面板
- **对标对象**：ZCode（多会话并行 + 会话级 todo 计划 + 后台任务通知 + 产物按会话交付）；互引 [coding-agent-parity-round2](./2026-09-06_coding-agent-parity-round2.md) 的 U1（diff 视图）/ U3（Git 面板）/ U5（消息排队）/ U6（OS 通知），本文不重复其内容
- **方法**：三路代码勘察（后端流与编排状态机 / 前端流 store 与侧边栏 / 持久化层），全部结论附 `file:line` 证据并已抽查复核
- **编号约定**：S = Session 系（会话运行态 / 并行 / 侧边栏绑定）；与 round-2 的 L/U/F 编号互引

## 0. 结论速览（对应三个提问）

1. **是否支持多会话同时进行？——后端已完整支持，前端刻意锁死为单流。** 后端每次 `/chat/stream` 生成独立 streamId、独立 asyncio task、独立 SageAgent（`backend/api/chat_stream_registry.py:135-166`、`backend/api/legacy_routes.py:2479`、`_ACTIVE_STREAMS` 字典 `legacy_routes.py:357`），无任何"已有运行中流则拒绝"的限制，取消全部按 id 定向（`POST /interrupt` → `interrupt_stream`，`legacy_routes.py:2551/:367`）。但渲染端 `useChat.ts:122` 以 `isLoading || loadingRef.current` 全局互斥，且新发送会**取消上一条流**并中断后端（`useChat.ts:124-139`）；流式 store 是单槽位（`chatStreamStore.ts:58` `streaming: StreamingState | null`），第二条流会覆盖第一条的进度展示。旁证：`/btw` 侧问（`useChat.ts:621-695`，伪会话 `__btw__`）已经证明双流并存技术上可行。
2. **运行/完成/失败是否有标识？——流级状态机存在但仅内存、不分会话；重启即失明。** 流状态 `pending → running → done | failed | suspended`（`chat_stream_registry.py:103-114`，迁移点集中在 `_run_producer` :168-188），LLM 失败发 `state:'failed'` + error 事件（`legacy_routes.py:2456-2461`）；编排 run/task/step 有正式状态机并落库可重放（`backend/domain/orch_events.py:27-219`，`orch_runs/orch_tasks/orch_events` 表）。但普通 `sessions` 表**无任何状态列**（`backend/data/database.py:246-261`），前端 `Session` 接口亦无（`src/shared/lib/store.ts:13-26`）——侧边栏无法标识哪个会话在跑、哪个失败，重启后 running 态也无处恢复。
3. **侧边栏进度/变更/产物是否与会话绑定？——产物后端已全会话绑定但侧边栏不可见；进度不分会话；变更无面板。** 侧边栏会话项仅渲染 fork 徽章/标题/日期/置顶（`src/widgets/session/SessionItem.tsx:44-103`）；唯一徽章是全局 attention 计数不分会话（`Sidebar.tsx:85-87`）。产物在 DB/API 层已按 session_id 绑定（`artifacts` 表 `database.py:550-564`、`/sessions/{id}/artifacts`、`artifact_repo.py:55/:80`），但只在右侧面板手动刷新（`useArtifacts.ts` 仅 sessionId 变化时拉取），记录时无任何事件推送。进度（taskBoard 五元组/todos）存在不分会话的全局单例里，切会话后仍显示旧会话的任务板。"变更"（diff 列表）作为功能不存在，属 round-2 U1/U3 范畴。

对标 ZCode 的差距本质：ZCode 的会话是**一等运行实体**——每个会话有独立 todo 计划（in_progress/completed/pending 即进度）、可后台并行运行、完成/失败有状态标识并可通知、产物以文件路径按会话交付。Sage 的对应能力在数据层大多已存在，缺的是**会话级键控的状态层 + 侧边栏消费**。

## 1. 现状勘察明细

### 1.1 并发链路

| 层 | 现状 | 证据 |
| --- | --- | --- |
| 后端 chat 流 | 每请求独立 streamId + asyncio task + 独立 agent，注册进进程级字典；多订阅 attach 支持 | `chat_stream_registry.py:135-166`（`StreamRegistry.create`）、`legacy_routes.py:354-360`（`_ACTIVE_STREAMS`）、`:2483`（attach） |
| 后端编排 | 子任务信号量并发（默认 4）+ lane 并发 | `backend/orchestration/chat_dispatcher.py:200/:470`、`orch_settings.py:29` |
| 取消 | 按 stream_id / run_id 定向，无隐式取消 | `legacy_routes.py:367/:391-421`、`orch_routes.py:184-194` |
| 前端互斥 | `isLoading` 全局拒绝新发送；新发送先 cancel + interrupt 上一条流 | `useChat.ts:122`、`:124-139`、`ChatInput.tsx:230` |
| 前端单槽 | `streaming/taskBoard/todos` 均为全局单值，`startStream` 全量重置 | `chatStreamStore.ts:57-60/:115` |

### 1.2 状态与持久化

| 层 | 状态集 | 持久化 | 证据 |
| --- | --- | --- | --- |
| chat 流 | pending/running/done/failed/suspended | ❌ 仅内存（TTL 回收） | `chat_stream_registry.py:103-114/:168-188/:190-222` |
| 编排 run/task/step | 完整状态机 + 迁移表 + 事件重放 | ✅ SQLite + 启动恢复 | `orch_events.py:27-219`、`database.py:822-929`、`backend/main.py:400-424` |
| sessions 表 | 无状态列（仅 pinned/archived/计数） | — | `database.py:246-261`；`session_repo.py:117` 为 `SELECT *`，加列即透传 |
| 重启语义 | 编排 finalize 默认 failed；chat 流直接消失 | — | `legacy_routes.py:1962-1963/:424-439` |

### 1.3 侧边栏与三件数据

| 数据 | 会话绑定 | 侧边栏可见 | 证据 |
| --- | --- | --- | --- |
| 会话项 | 行级绑定，但仅标题/日期/置顶/fork | 无状态、无进度、无计数 | `SessionItem.tsx:44-103` |
| attention（审批/提问） | ❌ 全局计数 | 全局徽章 | `Sidebar.tsx:85-87`；AgentEvent 已有 `session_id` 字段但未用于键控（`src/shared/api/types.ts:295-346`） |
| 进度（taskBoard/todos） | ❌ 全局单例，切会话不跟随 | ❌ 仅右侧面板 | `chatStreamStore.ts:57-60`、`ProgressSection.tsx` |
| 产物 | ✅ DB+API 全绑定 | ❌ 仅 RightPanel 页签，手动刷新 | `database.py:550-564`、`artifact_routes.py:10`、`useArtifacts.ts` |
| 变更/diff | — | — | 功能不存在（round-2 U1） |

## 2. 差距与优化项（S 系）

| # | 差距/优化 | 方案要点 | 对标 | 优先级 |
| --- | --- | --- | --- | --- |
| S1 | **会话运行态不落库** | `sessions` 表加 `run_status TEXT DEFAULT 'idle'`（idle/running/completed/failed/suspended）、`last_error TEXT`、`last_run_at INTEGER`；写库点收敛在 `_run_producer` 状态迁移处 + LLM failed 分支；启动恢复时把遗留 `running` 清为 `failed`（沿用编排 finalize 的 default-failed 语义）；`SELECT *` 已透传，前端 `Session` 接口补字段即可 | ZCode 会话常驻状态 | **P0** |
| S2 | **流式 store 不分会话** | `chatStreamStore` 的 `streaming/streamingToolCalls/taskBoard/todos` 改为按 sessionId 键控（`Record<string, …>` 或 Map），保留既有 messageId/runId 守卫逻辑不变，仅外层加键；`Chat.tsx`/`RightPanel`/`ProgressSection` 改读 `currentSessionId` 槽位；切会话即看该会话的实时进度（ZCode 语义） | ZCode per-session todo/进度 | **P0** |
| S3 | **发送互斥锁死并发** | `useChat` 的 `isLoading` 守卫改为"当前会话是否在流中"（从 S2 的 keyed store 派生）；跨会话允许并行；同会话内不做双流——新消息入队、流结束后自动发送（并入 round-2 U5 排队方案）；删除"新发送取消上一条流"中的跨会话误伤（该逻辑保留用于同会话重试场景）。后端加 `max_concurrent_sessions` 设置（默认 2，复用 `orch_settings.py:29` 先例），超限走排队 | ZCode 多会话并行 + 后台运行 | **P0** |
| S4 | **侧边栏无状态标识** | `SessionItem` 增状态点：running=呼吸/spinner、completed=✓（短时效，如 60s 后淡出）、failed=✗（点击弹出 last_error）、suspended=⏸；attention（待审批/待提问）从全局计数下沉为按 session 聚合（事件已带 session_id），会话项显示注意力点 | ZCode 运行/完成/失败 + attention | **P1** |
| S5 | **进度不进侧边栏** | S2 键控后，taskBoard 五元组（done/total）与 todos 完成度天然按会话可聚合；`SessionItem` 显示 mini 进度（如 `2/5` 细进度条），数据源为 keyed store + `sessions.run_status` 兜底 | ZCode todo 计划即进度 | P1 |
| S6 | **变更（diff）不绑定会话** | 承接 round-2 U1/U3：右侧面板加"变更"页签，消费第一轮已交付的 `git_status`/`git_diff`/checkpoint 工具按会话列出改动文件；侧边栏会话项显示 `+N 变更` 徽章。无后端改动 | ZCode/Cursor per-session changes | P1 |
| S7 | **产物无事件推送** | `artifact_repo.record_artifact` 成功后发 `artifact.created` 事件（经该 session 活跃流的 BroadcastQueue 附着，或新增轻量 `/sessions/{id}/events` SSE）；`useArtifacts` 改事件驱动刷新；产物数进 S4 徽章体系。注意：记录发生在工具路径（ContextVar 带 session_id，`backend/tools/context.py`），需 session_id → 活跃 stream 的映射（`_ACTIVE_STREAMS` 已有归属） | ZCode 产物实时入列 | P2 |
| S8 | **完成/失败通知不分会话** | 承接 round-2 U6：`done`/`state:'failed'`/`permission_request` 事件触发 OS 通知时携带会话标题与 id，点击聚焦该会话；failed 会话在侧边栏保持 ✗ 直到用户查看 | ZCode 任务完成通知 | P2 |
| S9 | **定时/唤醒会话不可见** | suspended 会话（A4 WakeScheduler，`StreamEntry.wake_id`）与 cron 注入目标会话在侧边栏显示 ⏰/⏸ 标记；数据源 `sessions.run_status='suspended'` + 调度器 job 列表 | ZCode 后台任务可见性 | P3 |

### 2.1 重点项路径勘察

- **S1 运行态落库（P0，S4/S5 的数据前提）**：状态迁移点已高度集中——`chat_stream_registry.py` 的 `_run_producer` 在同一函数内完成 running/done/failed 三迁移，`suspend()` 单独一处；在 `StreamRegistry` 上加一个可选的 `on_status_change(session_id, status, error)` 回调，`legacy_routes.py` 装配时注入写库函数（`session_repo` 加 `update_run_status`），避免散弹式改库。风险点：TTL 回收时不改库（以 finalize 语义为准）；attach 旧流时状态已是库中权威值。
- **S2 键控改造（P0，工作量最大）**：先列全消费方清单再动手——`useChat`（读写）、`Chat.tsx:296`（clearTaskBoard）、`ChatInput.tsx`（isLoading）、`RightPanel.tsx:399-409`、`ProgressSection`/`TodoListSection`/`PlanCardList`（只读）。建议加 `useSessionStreamState(sessionId)` 选择器钩子统一出口，避免组件直接摸 Map。`/btw` 伪会话改为真实旁路 key，行为不变。
- **S3 并行语义（P0）**：`loadingRef` 从 hook 级单值改为 `Map<sessionId, streamId>`；中断逻辑改为显式"停止该会话"按钮 + 会话切换不打断后台流。后端 `max_concurrent_sessions` 超限时返回 409 + `queueHint`，前端转排队（与 U5 同一队列实现）。与 round-2 L3（重试退避）配套评估，避免并行放大限流。
- **S4 徽章（P1，感知最强）**：数据源三路合并——活跃流（keyed store，瞬时）、`sessions.run_status`（持久，启动/切页兜底）、attention 事件（按 session 聚合的 zustand store，替代 `Sidebar.tsx:85-87` 全局计数）。纯前端 + S1 一张表变更。

## 3. 实施批次

- **批次 A（P0，最小闭环"并行 + 状态可见"）**：S1 落库 → S2 键控 → S3 解互斥 → S4 徽章（S1/S2 可并行开发，S4 依赖两者）。
- **批次 B（P1）**：S5 进度下沉、S6 变更绑定（依赖 round-2 U1 交付）、S8 通知（依赖 round-2 U6 交付，可与 U6 合并实施）。
- **批次 C（P2+）**：S7 产物事件、S9 定时/唤醒可见性。
- **依赖关系**：S6/S8 分别挂在 round-2 批次 B 的 U1/U6 之下，本文只补"会话维度"增量；S2 是 S3/S5 的前提，S1 是 S4/S9 的前提。
- **win7 对齐**：S1 为纯 SQLite + py3.8 兼容写法（禁 PEP 604/585），沿用 cherry-pick 惯例。

## 4. 风险与开放决策

1. **并发放大限流**：多会话并行 = 多 LLM 并发请求。决策点：`max_concurrent_sessions` 默认值（建议 2）与排队 UX；与 L3 重试落地顺序解耦但需联调。
2. **同会话排队 vs 拒绝**：现状是静默拒绝（`useChat.ts:122` 直接 return，用户无反馈）。建议改为入队自动发送（对齐 ZCode 与 round-2 U5），避免"消息发了没反应"的观感。
3. **重启恢复语义**：遗留 `running` 一律清为 `failed` 并附 `last_error='应用重启，运行中断'`，与编排 finalize 的 default-failed（`legacy_routes.py:1962-1963`）语义一致；不做断点续跑（成本高、聊天场景收益低）。
4. **键控迁移风险**：`chatStreamStore` 是跨路由单例（文件头注释自述此设计），S2 改造须保证旧消费方逐个迁移期间行为不变，建议先加 keyed 结构 + 兼容选择器，再分批切换消费方。

## 5. 证据来源说明

- 后端勘察：`backend/api/chat_stream_registry.py`、`backend/api/legacy_routes.py`（流生命周期/中断/finalize）、`backend/domain/orch_events.py`（状态机）、`backend/data/database.py` + `session_repo.py` + `artifact_repo.py`、`backend/orchestration/`（dispatcher/executor/event_hub）。
- 前端勘察：`src/features/send-message/`（useChat/chatStreamStore/chatApi）、`src/shared/lib/store.ts`、`src/widgets/session/SessionItem.tsx`、`src/widgets/layout/Sidebar.tsx`、`src/widgets/chat/`（RightPanel/ProgressSection/artifacts）、`src/features/artifacts/useArtifacts.ts`。
- 关键结论已人工抽查复核：useChat 发送互斥与取消上一条流、chatStreamStore 单槽结构、sessions 表无状态列、StreamEntry 状态机文档。
