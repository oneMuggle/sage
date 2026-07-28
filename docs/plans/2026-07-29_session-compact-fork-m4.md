# 会话工程：上下文压缩 + 会话分叉 (M4)

> **状态：** 已完成（待合并）
> **日期：** 2026-07-29
> **目标分支：** `feat/session-compact-fork`（基于 `main`，独立于 M1/M2/M3）

---

## 0. TL;DR

移植 claw-code 的 conversation-engineering 模式（`rust/crates/runtime/src/compact.rs`
的 `estimate_session_tokens` / `should_compact` / `get_compact_continuation_message`
与 `Session::fork`），适配 sage 的 session/message 持久化层。

| 维度 | 内容 |
|---|---|
| 涉及模块 | `backend/chat/compaction.py` (新) · `backend/api/legacy_routes.py` · `backend/data/session_repo.py` · `backend/data/database.py` · `backend/data/settings_repo.py` · `backend/memory/working.py` · `electron/commands.ts` · `src/widgets/chat/*` · `src/widgets/session/SessionItem.tsx` · `src/pages/Chat.tsx` · `src/shared/api/sessionApi.ts` |
| 新增依赖 | **零** |
| 兼容性 | Python 3.8 + pydantic v1/v2 双兼容；对存量用户 DB 只做幂等 `ALTER TABLE ADD COLUMN` |

---

## 1. 背景与目标

长对话的 token 成本与上下文噪音需要**压缩**；探索性对话需要无损的**分叉**。
两个能力都落在请求层 / 仓储层，不侵入 `backend/core/legacy/agent.py` 内部，
保证本分支可独立于 M1/M2/M3 前后合并。

### 目标（MoSCoW）

| 优先级 | 目标 |
|---|---|
| **Must** | 手动压缩：`POST /api/v1/sessions/{id}/compact` + 前端 `/compact` 真实 action |
| **Must** | 自动压缩：chat 请求层在 run_loop 前检查阈值，失败永不阻塞聊天 |
| **Must** | 会话分叉：`POST /api/v1/sessions/{id}/fork` + 消息级"从此处分叉" UI + 侧栏 fork 徽标 |
| **Should** | 阈值可配：settings key `compact_threshold_tokens`（默认 6000）+ env `SAGE_COMPACT_THRESHOLD` 覆盖 |
| **Won't (本里程碑)** | 压缩状态的前端流事件（AgentEvent 无 notice 类型，不发明新协议）；分叉树视图 |

---

## 2. 关键设计决策

### 2.1 偏离：CoW → 全量前缀复制（DELIBERATE DEVIATION）

原计划文档设想 fork 采用 copy-on-write（共享消息存储 + 分叉点指针）。
**实际采用全量前缀复制**：

- 桌面级会话只有数百条消息，复制成本可忽略（一次 fork ≈ 数百行 INSERT）；
- 复制后读写路径**零特判**（`get_by_session` 不需要理解分叉关系），回归风险最小；
- CoW 的复杂度（共享行的级联删除语义、分叉点之后的写分裂）远超当前收益。

CoW 推迟到真正出现存储压力时再评估。`sessions.fork_root` /
`sessions.forked_at_message_id` 两列的语义对两种实现都兼容，届时不需要
再次迁移 schema。

### 2.2 压缩对 DB 纯净

`backend/chat/compaction.py` 只接受消息序列（`session_repo.Message` 对象或
`{"role","content"}` dict），返回新列表；删除旧行 / 插入续接消息 / 更新计数
全部由 `legacy_routes.py` 的落盘编排完成。压缩逻辑可被单测完整覆盖而不触碰 SQLite。

### 2.3 自动压缩挂在请求层

钩子位于 `chat_stream_create` 的 producer 内、user 消息落盘之前（压缩的是
**存量历史**，不含本轮新消息）。整块 `try/except` 隔离：压缩失败只记日志，
流式事件照常产出。AgentEvent 没有 notice 类事件，本里程碑不向前端推送
压缩状态（不发明新前端协议）。

### 2.4 REST 契约

**POST /api/v1/sessions/{session_id}/compact**

| 场景 | 状态码 | body |
|---|---|---|
| 压缩成功 | 200 | `{"ok": true, "compacted": true, "before": N, "after": M, "removed": N-M'}` |
| 低于地板（<12 条或 token 未达阈值） | 200 | `{"ok": true, "compacted": false, "reason": "below_message_floor" \| "below_token_threshold", ...}` |
| 会话不存在 | 404 | FastAPI detail |
| 无 LLM 配置 / 摘要失败 | 502 | `{"ok": false, "error": "llm_not_configured" \| "compaction_failed", "message": ...}`，DB 不动 |

**POST /api/v1/sessions/{session_id}/fork** body `{"at_message_id"?: str, "title"?: str}`

| 场景 | 状态码 | body |
|---|---|---|
| 成功 | 200 | 新会话 JSON（含 `fork_root` / `forked_at_message_id`） |
| 源会话 / 分叉点消息不存在 | 404 | 结构化 detail `type: session_not_found \| message_not_found` |

**settings key**：`compact_threshold_tokens`（SettingsRepository.KEYS 白名单，
默认 6000；env `SAGE_COMPACT_THRESHOLD` 优先级最高）。

**消息数地板**：`MIN_COMPACT_MESSAGE_COUNT = 12`（硬编码常量）。

### 2.5 schema 迁移

`sessions` 表幂等追加两列（沿用 `messages.reasoning_content` 的既有
PRAGMA table_info + ALTER 模式，对新库与存量库一致生效）：

- `fork_root TEXT NULL` — 分叉源会话 id
- `forked_at_message_id TEXT NULL` — 分叉点（源消息 id）；NULL = 复制到源会话末尾

`Session.to_dict()` 序列化带上两列 → `list_sessions` / `get_session` 响应
包含 `fork_root`，侧栏徽标直接消费。

---

## 3. 实施步骤

### 后端

- [x] 步骤 1：`backend/memory/working.py` 提取模块级 `estimate_tokens`（`WorkingMemory._estimate_tokens` 委托）
- [x] 步骤 2：`backend/chat/compaction.py` — estimate_messages_tokens / should_compact / build_compaction_prompt / continuation_message / compact_messages + CompactionError
- [x] 步骤 3：`backend/data/database.py` — sessions 表 fork_root / forked_at_message_id 幂等迁移
- [x] 步骤 4：`backend/data/session_repo.py` — Session 数据类两列 + to_dict + fork_session 编排 + ForkSourceNotFoundError
- [x] 步骤 5：`backend/data/settings_repo.py` — `compact_threshold_tokens` 加入 KEYS 白名单
- [x] 步骤 6：`backend/api/legacy_routes.py` — compact / fork 路由 + 请求层自动压缩钩子（LLM 客户端装配：请求 llm_config 优先，回退 app_settings 的 chatModel endpoint）
- [x] 步骤 7：单测 `backend/tests/unit/chat/test_compaction.py`（15 例）
- [x] 步骤 8：API 测试 `backend/tests/api/test_session_compact_api.py`（6 例）+ `test_session_fork_api.py`（7 例）
- [x] 步骤 9：集成测试 `backend/tests/integration/test_chat_auto_compaction.py`（2 例：成功压缩 + 失败不阻塞）
- [x] 步骤 10：ruff clean + py3.8 py_compile + 全量 pytest 回归

### 前端

- [x] 步骤 11：`electron/commands.ts` — session_compact / session_fork 路由（fork body camelCase→snake_case 映射）+ guard 测试
- [x] 步骤 12：`src/shared/api` — Session 类型两处补 fork 字段 + SessionCompactResult + sessionApi.compact/fork（刻意不走 withRetry：压缩重试浪费 token、fork 非幂等）
- [x] 步骤 13：`slashCommands.ts` — compact 由 'prompt' 模式改为 'compact' action 模式
- [x] 步骤 14：`ChatInput.tsx` — onCompact 回调；`Chat.tsx` — toast（成功计数 / 跳过 / 失败）+ 重载消息（续接摘要行由后端持久化）
- [x] 步骤 15：`Message.tsx` — user/assistant 消息分叉按钮（memo 比较器同步更新）；`MessageList.tsx` 透传 onFork
- [x] 步骤 16：`SessionItem.tsx` — fork_root 存在时显示 git-branch 徽标 + tooltip
- [x] 步骤 17：i18n zh + en 新键（compact_success / compact_skipped / compact_failed / fork_from_here / fork_success / fork_failed / session.fork_badge）
- [x] 步骤 18：vitest（slash compact action / fork payload+导航 / 徽标渲染 / Chat 页 toast）+ tsc --noEmit + typecheck:electron + eslint clean

---

## 4. 风险评估与依赖

| 风险 | 缓解 |
|---|---|
| 压缩误删用户消息 | 续接消息 created_at = 首条保留消息 -1ms，保序；LLM 失败整体跳过（不留半成品）；手动路由失败时 DB 零改动 |
| 自动压缩阻塞聊天 | producer 内独立 try/except，失败只记日志 |
| 存量 DB 迁移 | 幂等 ALTER（PRAGMA table_info 探测），与既有 reasoning_content 迁移同模式 |
| 与 M1/M2/M3 合并顺序 | 不触碰 agent.py / hex ChatService；仅 legacy 路由层 + 仓储层增量，前后合并均无冲突面 |

## 5. 不在范围内

- ❌ 分叉的 copy-on-write（见 §2.1）
- ❌ 压缩/分叉的 hex API 路径（session 面目前整体在 legacy_routes，API_MODE 默认 legacy）
- ❌ 分叉树 / 谱系可视化
- ❌ 压缩策略的按 provider 差异化
