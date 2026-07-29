# 35 · 会话工程：上下文压缩 + 会话分叉（M4）

移植 claw-code 的 conversation-engineering 模式（`rust/crates/runtime/src/compact.rs`
的 `estimate_session_tokens` / `should_compact` / `get_compact_continuation_message`
与 `Session::fork`），适配 sage 的 session/message 持久化层。

两个能力都落在**请求层 / 仓储层**，不侵入 `backend/core/legacy/agent.py` 内部。
新增依赖：**零**。兼容性：Python 3.8 + pydantic v1/v2 双兼容；对存量用户 DB
只做幂等 `ALTER TABLE ADD COLUMN`。

---

## 1. 压缩模块（backend/chat/compaction.py）

对 DB 纯净：只接受消息序列（`session_repo.Message` 对象或 `{"role","content"}` dict），
返回新列表。删除旧行 / 插入续接消息 / 更新计数全部由 `legacy_routes.py` 的落盘编排完成，
因此压缩逻辑可被单测完整覆盖而不触碰 SQLite。

| 函数 | 职责 |
| --- | --- |
| `estimate_messages_tokens` | token 估算（复用 `backend/memory/working.py` 模块级 `estimate_tokens`） |
| `should_compact` | 阈值判定 |
| `build_compaction_prompt` | 构造摘要提示 |
| `continuation_message` | 生成续接消息 |
| `compact_messages` | 编排上述步骤，失败抛 `CompactionError` |

**消息数地板**：`MIN_COMPACT_MESSAGE_COUNT = 12`（硬编码常量）。

**阈值配置**：settings key `compact_threshold_tokens`（`SettingsRepository.KEYS`
白名单，默认 6000）；env `SAGE_COMPACT_THRESHOLD` 优先级最高。读取口径见
`get_compact_threshold`。

**保序保证**：续接消息 `created_at` = 首条保留消息 −1 ms。LLM 摘要失败则整体跳过，
不留半成品；手动路由失败时 DB 零改动。

## 2. 自动压缩挂在请求层

钩子位于 `chat_stream_create` 的 producer 内、**user 消息落盘之前**——压缩的是
存量历史，不含本轮新消息。整块 `try/except` 隔离：压缩失败只记日志，流式事件照常产出。

`AgentEvent` 没有 notice 类事件，本里程碑**不向前端推送压缩状态**（不为此发明新前端协议）。

## 3. 分叉：全量前缀复制（对原计划的有意偏离）

原设计设想 copy-on-write（共享消息存储 + 分叉点指针），**实际采用全量前缀复制**：

- 桌面级会话只有数百条消息，复制成本可忽略（一次 fork ≈ 数百行 INSERT）
- 复制后读写路径**零特判**（`get_by_session` 不需要理解分叉关系），回归风险最小
- CoW 的复杂度（共享行的级联删除语义、分叉点之后的写分裂）远超当前收益

CoW 推迟到真正出现存储压力时再评估。`fork_root` / `forked_at_message_id` 两列的语义
对两种实现都兼容，届时**不需要再次迁移 schema**。

### schema 迁移

`sessions` 表幂等追加两列（沿用 `messages.reasoning_content` 的既有
PRAGMA table_info + ALTER 模式，对新库与存量库一致生效）：

| 列 | 类型 | 语义 |
| --- | --- | --- |
| `fork_root` | `TEXT NULL` | 分叉源会话 id |
| `forked_at_message_id` | `TEXT NULL` | 分叉点（源消息 id）；NULL = 复制到源会话末尾 |

`Session.to_dict()` 序列化带上两列 → `list_sessions` / `get_session` 响应包含
`fork_root`，侧栏徽标直接消费。

## 4. REST 契约（backend/api/legacy_routes.py，挂载 /api/v1）

### POST /api/v1/sessions/{session_id}/compact

| 场景 | 状态码 | body |
| --- | --- | --- |
| 压缩成功 | 200 | `{"ok": true, "compacted": true, "before": N, "after": M, "removed": ...}` |
| 低于地板（<12 条或 token 未达阈值） | 200 | `{"ok": true, "compacted": false, "reason": "below_message_floor" \| "below_token_threshold", ...}` |
| 会话不存在 | 404 | FastAPI detail |
| 无 LLM 配置 / 摘要失败 | 502 | `{"ok": false, "error": "llm_not_configured" \| "compaction_failed", ...}`，**DB 不动** |

LLM 客户端装配顺序：请求 `llm_config` 优先，回退 `app_settings` 的 chatModel endpoint。

### POST /api/v1/sessions/{session_id}/fork

body `{"at_message_id"?: str, "title"?: str}`

| 场景 | 状态码 | body |
| --- | --- | --- |
| 成功 | 200 | 新会话 JSON（含 `fork_root` / `forked_at_message_id`） |
| 源会话 / 分叉点消息不存在 | 404 | 结构化 detail `type: session_not_found \| message_not_found` |

## 5. 前端

- `electron/commands.ts` — `session_compact` / `session_fork` 路由（fork body
  camelCase→snake_case 映射）
- `src/shared/api/sessionApi.ts` — `compact` / `fork`，**刻意不走 `withRetry`**：
  压缩重试浪费 token、fork 非幂等
- `slashCommands.ts` — `/compact` 由 `'prompt'` 模式改为 `'compact'` action 模式
- `ChatInput.tsx` `onCompact` 回调；`Chat.tsx` toast（成功计数 / 跳过 / 失败）+
  重载消息（续接摘要行由后端持久化）
- `Message.tsx` — user/assistant 消息「从此处分叉」按钮（memo 比较器同步更新）；
  `MessageList.tsx` 透传 `onFork`
- `SessionItem.tsx` — `fork_root` 存在时显示 git-branch 徽标 + tooltip
- i18n zh + en：`compact_success` / `compact_skipped` / `compact_failed` /
  `fork_from_here` / `fork_success` / `fork_failed` / `session.fork_badge`

## 6. 已知限制

**自动压缩尚不降低每轮 LLM token。** legacy chat producer（`chat_stream_create`）
只组装 `messages = [system, attachments?, user]` 交给 `run_loop`，**不注入持久化历史**。
因此 M4 自动压缩改写的是 DB，实际收益 = 持久化存储有界 + UI / fork 健全性；
**每轮 token 节省要等聊天路径开始把持久化历史喂给 `run_loop` 才生效**。

跟进标记：`FOLLOWUP(persisted-history-injection)`。历史注入落地后本限制自动解除，
压缩逻辑本身无需改动（`_maybe_auto_compact_session` docstring 中有同样声明）。

## 7. 不在范围内

- 分叉的 copy-on-write（见 §3）
- 压缩 / 分叉的 hex API 路径（session 面目前整体在 `legacy_routes`）
- 分叉树 / 谱系可视化
- 压缩策略的按 provider 差异化

## 8. 测试

| 层 | 文件 | 覆盖 |
| --- | --- | --- |
| 单元 | `backend/tests/unit/chat/test_compaction.py` | 15 例：估算 / 阈值 / 提示构造 / 续接 / 失败路径 |
| API | `backend/tests/api/test_session_compact_api.py` | 6 例：成功 / 双跳过原因 / 404 / 502 双分支 |
| API | `backend/tests/api/test_session_fork_api.py` | 7 例：全量复制 / 分叉点 / 结构化 404 |
| 集成 | `backend/tests/integration/test_chat_auto_compaction.py` | 2 例：成功压缩 + 失败不阻塞聊天 |
| 前端 | `Chat.compact-fork.test.tsx`、`ChatInput.compact.test.tsx`、`Message.fork.test.tsx`、`SessionItem.fork-badge.test.tsx` | slash action / fork payload+导航 / 徽标渲染 / toast |
