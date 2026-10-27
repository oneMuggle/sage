# 会话标题自动生成优化方案

> 创建日期：2026-10-27
> 分支：feat/session-title-optimization
> 状态：进行中

## 1. 背景与目标

### 1.1 现状问题

Sage 当前的会话标题生成机制存在多个结构性问题，导致长对话长期显示「新对话」：

1. **触发窗口过窄**：仅在 `message_count <= 2` 时触发（即第 1、2 轮对话），失败后永不重试
2. **事件链路断裂**：标题生成完成后推送的 `session_updated` 事件在 NDJSON 流的 `SENTINEL` 之后，前端收不到
3. **静默失败**：`build_llm_client_from_settings()` 返回 `None` 时无日志、无兜底
4. **用主聊天模型做标题**：慢且贵，容易超过前端 16s 补刷窗口
5. **状态语义模糊**：`"新对话"` 字符串既当占位符又当失败结果，无法区分

### 1.2 实测数据

对当前 `data/sage.db` 的 400 个会话统计：
- 已命名 385 个（96%）
- 仍是「新对话」59 个，其中 18 个是真实长对话（message_count 2~40）
- 典型案例：`message_count=40, run_status=idle` 的会话始终未命名

### 1.3 目标

1. **100% 命名成功率**：任何有真实消息的会话最终都有标题
2. **快速反馈**：标题生成 <3s，UI 立即感知
3. **失败可见**：LLM 不可用时有启发式兜底，不留 `None`
4. **语义清晰**：DB 层面区分"未生成"与"已生成"

## 2. 涉及的文件与模块

### 2.1 后端

| 文件 | 改动 |
|---|---|
| `backend/chat/title_generator.py` | 重构：引入 `TitleModelFactory`、启发式兜底、多语言 prompt |
| `backend/api/legacy_routes.py` | 修改触发条件、修复事件链路（SENTINEL 前等待标题） |
| `backend/application/services/chat_service.py` | 同步触发条件 |
| `backend/data/session_repo.py` | `title` 字段改为 `Optional[str]`，新增 `title_attempts` 列 |
| `backend/data/database.py` | migration：`title` 允许 NULL，加 `title_attempts` INT 默认 0 |
| `backend/scheduler/title_backfill.py` | 新增：启动后批量回补未命名会话 |

### 2.2 前端

| 文件 | 改动 |
|---|---|
| `src/shared/api/sessionApi.ts` | `create()` 默认 title 改为 `null` |
| `src/widgets/sidebar/sections/ConversationsSection.tsx` | 渲染 `title == null` 为「✨ 生成标题中…」骨架 |
| `src/features/send-message/useChat.ts` | 监听 `title_updated` 事件精确刷新单个会话 |
| `src/shared/api/types/chatAndEventTypes.ts` | 新增 `title_updated` 事件类型 |
| `src/shared/lib/store.ts` | `loadSessions()` 改为轮询模式（标题 pending 时每 2s 拉一次，最多 30s） |

### 2.3 配置

| 文件 | 改动 |
|---|---|
| `backend/data/settings_repo.py` | 新增 `titleModelId` 配置项 |
| `src/shared/lib/i18n/locales/zh/chatAndSider.ts` | 新增"生成标题中"翻译 |

## 3. 技术方案

### 3.1 架构设计

```
┌─────────────────────────────────────────────────────────────┐
│  User sends message                                         │
└─────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────┐
│  Producer: /chat/stream                                     │
│  - Push DONE event (with title_pending=true if title=null)  │
│  - AWAIT title task (max 3s) before SENTINEL                │
│  - Push title_updated event                                 │
│  - Push SENTINEL                                            │
└─────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────┐
│  TitleGenerator.generate()                                  │
│  - Try TitleModelFactory.get() (small/fast model)           │
│  - If fails: fallback to heuristic (first 30 chars)         │
│  - Update DB: sessions.title = "...", title_attempts += 1   │
│  - Push session_updated event                               │
└─────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────┐
│  Frontend: useChat.ts                                       │
│  - Receive title_updated event                              │
│  - Update session in store (no full reload needed)          │
│  - UI transitions from "✨ 生成标题中…" to actual title      │
└─────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────┐
│  Background: title_backfill.py (on app startup)             │
│  - Query: sessions WHERE title IS NULL AND message_count>0  │
│  - Batch generate (concurrency=3, rate limit 10/min)        │
│  - Max 100 sessions per startup                             │
└─────────────────────────────────────────────────────────────┘
```

### 3.2 关键设计决策

#### 3.2.1 DB schema 变更（实施后修订）

```sql
-- SQLite 不支持 ALTER COLUMN → 保留 title NOT NULL，改用哨兵值
ALTER TABLE sessions ADD COLUMN title_attempts INTEGER DEFAULT 0;
```

**实施偏离**：原计划让 `title` 可空。SQLite 无法 `ALTER COLUMN`，重建表风险大，
故保留 `title TEXT NOT NULL DEFAULT '新对话'`，用「`title == '新对话'` AND
`title_attempts < 3`」作为「尚未生成」的判定口径（`needs_title()` 集中封装）。
`title_attempts` 防止无限重试。

#### 3.2.2 触发条件

**旧逻辑**：
```python
if sess.message_count <= 2:
    asyncio.create_task(_generate_title())
```

**新逻辑**：
```python
if sess is not None and needs_title(sess):   # title 为哨兵值且 attempts < 3
    ...
```

**理由**：每轮都尝试直到成功（或达到 3 次上限），不再受 `message_count` 窗口限制。
`needs_title()` 同时兼容 `Session` 对象（legacy 路径）与 `dict`（hex 路径）。

#### 3.2.3 事件链路修复

**问题**：`SENTINEL` 在 `DONE` 后立即推送，标题事件送不到。

**方案 A（已实施，含修订）**：在 producer 推出 `DONE` 后、`SENTINEL` 前，对标题 task
做**不取消**的有界等待（最多 3s）：

```python
title_task = asyncio.create_task(_generate_title())
await asyncio.wait({title_task}, timeout=_TITLE_WAIT_S)  # 3.0s
```

**实施偏离**：原计划用 `asyncio.wait_for`。它会**取消**超时的 task，导致标题彻底丢失；
改用 `asyncio.wait`（不取消）—— 3s 内完成则 `title_updated` 事件赶在 `SENTINEL` 前入队，
前端即时刷新；超时则 task 继续在后台跑，落库后由前端轮询兜底。producer 也无需为标题
长期占用流活跃窗口。

#### 3.2.4 专用标题模型

`TitleModelFactory` 优先级：
1. `app_settings.titleModelId`（顶层键，值为模型 id 字符串；复用聊天端点凭据，仅覆盖
   `model` + `temperature=0.2`）
2. 未配置 → 用 chat 模型但加 3s 超时
3. 都没有 → 直接走启发式

**实施偏离**：原计划放在 `modelSelections.titleModel`。改用**顶层** `titleModelId`
与既有 `chatModel` 的扁平约定保持一致，避免改动前端 `modelSelections` 类型结构。

**理由**：标题生成是高频低价值任务，用主模型浪费 token 且慢。

#### 3.2.5 启发式兜底

```python
def fallback_title(user_msg: str, assistant_msg: str) -> str:
    text = user_msg.strip().split("\n")[0][:30]
    return text if len(text) >= 4 else assistant_msg[:30].strip()
```

**理由**：LLM 失败时 100% 也能得到可辨识的标题，不留 `None`。

#### 3.2.6 启动时批量回补

`backend/scheduler/title_backfill.py`：
- 启动后 30s 触发
- 查询 `sessions WHERE title IS NULL AND message_count > 0`
- 并发 ≤ 3，速率 ≤ 10/min
- 单次最多 100 个会话
- 失败记录 `title_attempts`，不再重试

**理由**：修复历史遗留未命名会话，提供最终一致性。

### 3.3 前端改动

#### 3.3.1 UI 过渡态

侧栏会话列表渲染逻辑：
```tsx
const displayTitle = session.title === null 
  ? '✨ 生成标题中…' 
  : session.title;
```

**理由**：用户立即感知"正在处理"，而不是看到误导性的"新对话"。

#### 3.3.2 精确刷新

监听 `title_updated` 事件，直接更新 store 中的单个 session：
```ts
if (evt.type === 'session_updated' && evt.subtype === 'title_updated') {
  useStore.getState().updateSessionTitle(evt.session_id, evt.title);
  return;
}
```

**理由**：避免全量 `loadSessions()` 的性能开销。

#### 3.3.3 轮询兜底

`loadSessions()` 改为：
```ts
async function loadSessionsWithPolling() {
  await loadSessions();
  const hasPending = sessions.some(s => s.title === null && s.message_count > 0);
  if (hasPending) {
    const interval = setInterval(async () => {
      await loadSessions();
      const stillPending = sessions.some(s => s.title === null && s.message_count > 0);
      if (!stillPending) clearInterval(interval);
    }, 2000);
    setTimeout(() => clearInterval(interval), 30000); // max 30s
  }
}
```

**理由**：即使事件丢失，也能通过轮询最终一致性。

## 4. 实施步骤

### Phase 1：DB schema + 后端核心（2 天）✅

- [x] 1.1 修改 `backend/data/database.py`：migration 加 `title_attempts` 列（`title` 保持 NOT NULL）
- [x] 1.2 修改 `backend/data/session_repo.py`：`Session` 新增 `title_attempts` 字段（`from_row`/`to_dict` 同步）
- [x] 1.3 重构 `backend/chat/title_generator.py`：
  - 新增 `TitleModelFactory`（支持配置专用模型）
  - 新增 `fallback_title()` 启发式兜底
  - 新增 `needs_title()` 统一判定
  - `generate()` 改为：先 LLM，失败走启发式，**永不返回 None**
- [x] 1.4 修改 `backend/api/legacy_routes.py`：
  - 触发条件改为 `needs_title(sess)`
  - `asyncio.wait(..., timeout=3.0)` 不取消等待 + `title_pending` 标记
- [x] 1.5 同步修改 `backend/application/services/chat_service.py`（`needs_title` + `title_attempts` 原子更新）
- [x] 1.6 `sqlite_adapter.py` 补 `title_attempts` 读写（hex 路径缺口）

### Phase 2：启动时回补（0.5 天）✅

- [x] 2.1 新建 `backend/scheduler/title_backfill.py`：
  - 查询未命名会话（`SessionRepository.list_untitled`）
  - 批量生成（并发 3，速率 10/min，单会话 15s 超时）
  - 集成到 `backend/main.py` 的 lifespan（启动 30s 后触发；关停时取消）
- [x] 2.2 编写单元测试 `backend/tests/unit/test_title_backfill.py`（11 个用例，覆盖正常/降级/超时/调度）

### Phase 3：前端（1.5 天）✅

> **实施偏离**：后端最终保留哨兵标题 `"新对话"`（SQLite 无法 ALTER COLUMN），
> 因此前端不按 `title == null` 判定"生成中"，而按
> `title === '新对话' && message_count > 0 && title_attempts === 0` 判定。
> 需后端在会话列表中透出 `title_attempts`（见 3.6）。

- [x] 3.1 `src/shared/lib/store.ts` + `src/shared/api/types/chatAndEventTypes.ts`：
  - `Session` 接口新增 `title_attempts?: number`
- [x] 3.2 `src/features/send-message/useChat.ts`：
  - 收到 `session_updated` + `subtype === 'title_updated'` 时精确
    `updateSession(sid, { title })`，避免全量 `loadSessions()` 抖动
  - 其它 `session_updated` 子类型仍走全量刷新
- [x] 3.3 `src/widgets/session/SessionItem.tsx`：
  - 渲染"生成标题中…"过渡态（哨兵标题 + 有消息 + 未尝试过）
- [x] 3.4 `src/shared/lib/i18n/locales/{zh,en}/workspaceAndTools.ts`：
  - 新增 `session.title_generating`
- [x] 3.5 `backend/adapters/out/storage/sqlite_adapter.py`：
  - `_sync_list_sessions` 透出 `title_attempts`（前端判定依据）
- [ ] 3.6 `src/shared/lib/store.ts`：`loadSessions()` 轮询兜底
  —— **降级为可选**：后端 `title_pending` + 8s/16s 定时补刷已覆盖
  事件丢失场景（`useChat.ts` 既有逻辑），全量轮询会造成无谓请求，暂不实施

### Phase 4：配置与文档（0.5 天）

- [x] 4.1 新增 `titleModelId` 配置项到 `backend/data/settings_repo.py`
- [x] 4.2 更新 `docs/technical/` 文档：会话标题生成机制（`docs/technical/102-session-title-generation.md` + README 注册）
- [x] 4.3 更新用户手册：如何配置专用标题模型（`docs/user-manual/20-settings.md` 新增"会话标题模型"子节）

### Phase 5：测试与验证（1 天）

- [x] 5.1 编写集成测试：标题生成 + 事件链路 + 回补机制（`backend/tests/integration/test_chat_title_generation.py`，15 用例全绿，覆盖 TitleGenerator / fallback_title / needs_title / MemoryStorageAdapter.title_attempts / TitleBackfill 跨真实 SQLite / legacy `/api/v1/chat/stream` 的 title_updated NDJSON 事件 + title_pending + DB 落库闭环）
- [ ] 5.2 手动验证：新建会话 → 发消息 → 观察标题生成
- [ ] 5.3 手动验证：启动后回补历史未命名会话
- [ ] 5.4 压力测试：100 个并发会话的标题生成性能

## 5. 风险评估与依赖

### 5.1 风险

| 风险 | 影响 | 缓解措施 |
|---|---|---|
| DB migration 失败 | 无法启动 | 加 `try-except`，migration 失败只 warning 不崩溃 |
| 专用标题模型未配置 | 退回主模型，慢 | 提供默认推荐（`gpt-4o-mini`），文档说明 |
| 启发式兜底质量差 | 标题不美观 | 仅在 LLM 失败时启用，优先 LLM |
| 事件链路修复引入死锁 | 流卡住 | `wait_for` 超时 3s，超时后跳过 |
| 回补任务阻塞启动 | 启动慢 | 延迟 30s 触发，并发 ≤ 3 |

### 5.2 依赖

- 无外部依赖
- 向后兼容：旧数据 `title="新对话"` 保持原样，新数据 `title=null` 表示未生成

## 6. 成功标准

1. **100% 命名成功率**：任何有消息的会话最终都有标题（LLM 或启发式）
2. **生成延迟 <3s**：用户发消息后 3s 内看到标题
3. **UI 无误导**：不再显示"新对话"（除非真的空会话）
4. **历史修复**：启动后自动回补未命名会话
5. **可观测**：标题生成成功率、延迟、模型使用可查询

## 7. 后续演进（P2，本次不做）

- 标题随对话演化（message_count 10/30/100 时重新生成）
- 跨设备同步（evolution log 记录标题生成）
- 手动编辑与回退（右键菜单"重新生成标题"）
- 可观测性仪表盘（telemetry 集成）
