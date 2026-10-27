# 101 — 会话标题生成机制

> 2026-10-27 实施。目标：100% 命名成功率、<3s 延迟、失败可见、零 `None` 标题。

## 概览

Sage 的每个会话在创建时都有一个占位标题「新对话」（SQLite `sessions.title` 的 `NOT NULL DEFAULT`）。当会话产生有意义的首轮对话后，系统调用 LLM 生成简洁、具体的标题，并在 LLM 不可用时降级到启发式标题（取用户首条消息首行）。

设计原则：**永不返回 None**，失败也一定有可读标题；失败可见（`title_attempts` 计数器）；启动后对历史未命名会话批量回补。

## 核心模块

| 模块 | 职责 |
|---|---|
| `backend/chat/title_generator.py` | 单次标题生成：`TitleGenerator.generate()`、`fallback_title()`、`needs_title()`、`load_title_llm_config()` |
| `backend/scheduler/title_backfill.py` | 启动后回补：`TitleBackfill` 调度历史未命名会话批量重生成 |
| `backend/tools/config_tool.py` | LLM 配置入口：`target="general"` 允许写 `titleModelId` |
| `src/pages/settings/ModelsTab.tsx` | 用户界面入口：`TitleModelSelector` 下拉（模型 Tab） |
| `src/entities/setting/{types,storage}.ts` | 前端 `AppSettings.titleModelId` 字段 + 白名单 + 持久化 |

## 标题生成流程

```
[应用层] chat_service.py
  └─ 收到首两轮消息 → 调 SessionService.title_generator.generate(session, messages)
        │
        ├─ needs_title(session) ?
        │     └─ title in (None, "新对话") AND title_attempts < MAX_TITLE_ATTEMPTS (= 3)
        │
        ├─ 用户消息+助手消息字符数 < MIN_CONTENT_FOR_LLM (= 20)?
        │     └─ 是 → 走启发式 fallback_title() → 落库 → 返回
        │
        └─ load_title_llm_config() 拿配置 → TitleModelFactory.build()
              ├─ 配置为空 / 端点不可用 → 走启发式
              └─ 有 → async LLM 调用 → 解析 → 清洗 → 落库（失败 → 启发式）
```

关键点：

- `generate()` 的返回值类型是 `str`（永远非 None）
- 每次尝试（无论成功/失败/启发式）都会递增 `title_attempts`，最多 3 次
- LLM 调用失败时**降级**而不是抛异常

## 触发路径（三种）

1. **Legacy 路径（桌面端实际走这条）**：`backend/api/legacy_routes.py` 的 `/api/v1/chat/stream` producer 在 DONE 事件推送后立即 spawn `_generate_title()` 任务，使用 `asyncio.wait({title_task}, timeout=3.0)` **不取消**等待 —— 3s 内完成则 `session_updated / subtype: title_updated` 事件赶在 `SENTINEL` 前入队，前端即时刷新；超时则任务转入后台继续，落库后由前端 8s/16s 定时补刷兜底。DONE 事件同时带 `title_pending: true` 提示前端等待。
2. **Hex 路径**：`chat_service.py` 的 `run_turn` step 9 在 turn 完成后同步调用 `TitleGenerator(self.llm).generate(...)`（嵌套在 `if self.memory:` 块内，与记忆提取共享生命周期）。桌面端目前不通过此路径。
3. **启动回补**：`TitleBackfill` 在应用启动 30s 后扫描历史 `title == "新对话" AND title_attempts < 3 AND message_count > 0` 的会话，并发 ≤3、速率 10/min 批量补生成，单次最多 100 个会话。

## 标题模型选择

**默认**：复用对话模型（`modelSelections.chatModel`）。

**专用模型**（可选）：用户在「设置 → 模型 → 会话标题模型」下拉选一个，存入 `app_settings.titleModelId`（扁平字符串，裸模型 id）。后端 `load_title_llm_config()` 读取，**复用聊天端点的 `base_url` / `api_key`，只覆盖 `model` 字段**。

约束：标题模型必须位于聊天端点同侧，因为换端点会 404（`llm_factory.py` 只从聊天端点读凭证）。前端 `TitleModelSelector` 把候选限定在 `groupedModels.filter(endpointId === chatModel.endpointId)`，并在发现用户通过 config_tool 写入了一个不在端点发现列表里的 id 时，保留为孤立选项，避免静默抹掉配置。

空串 `""` = 回退到聊天模型（后端 `load_title_llm_config` 返回 `None`）。

## 数据模型

```sql
sessions (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL DEFAULT '新对话',
    title_attempts INTEGER DEFAULT 0,   -- 已尝试生成次数；MAX_TITLE_ATTEMPTS 封顶
    created_at TEXT,
    updated_at TEXT,
    ...
)
```

`title_attempts` 解决 SQLite 无法 `ALTER COLUMN` 的难题：原本想要 `NOT NULL DEFAULT ''` 区分"未生成"与"已生成"，但 `DEFAULT` 是静态的，老数据仍是 `'新对话'`。计数器让「是否尝试过」与「当前值」正交 —— 即使 LLM 失败把标题写成了启发式，也标记为已尝试过。

## 回补调度器约束

`TitleBackfill` 的默认配置：

| 参数 | 默认值 | 说明 |
|---|---|---|
| `STARTUP_DELAY_S` | 30 | 启动后延迟，避开初始化争用 |
| `MAX_BATCH` | 100 | 单次回补上限 |
| `CONCURRENCY` | 3 | 同时生成标题的会话数 |
| `RATE_PER_MINUTE` | 10 | LLM 调用速率上限 |
| `PER_SESSION_TIMEOUT_S` | 15 | 单个标题生成的超时 |
| `MIN_INTERVAL_S` | 6 | 两次启动回补的最小间隔 |

回补不重试已封顶的会话（`title_attempts >= 3`），也不会因为某次 LLM 失败反复启动。

## 配置路径

### 用户界面

设置页 → 模型 Tab → 「会话标题模型」下拉。

- `-- 沿用对话模型 --`：留空，回退默认
- 其它选项：聊天端点已发现的 chat 模型列表

### LLM 工具

```python
update_sage_config(target="general", updates={"titleModelId": "gpt-4o-mini"})
```

`config_tool.py::_ALLOWED_GENERAL_FIELDS` 白名单允许此字段；`_validate_title_model_id` 校验字符串且长度 ≤ 200。

### API

`PUT /api/v1/settings` body 顶层 `titleModelId: Optional[str]`：

- `SettingsPayload` (hex 路由) / `LegacySettingsPayload` (legacy 路由) 都声明了该字段
- `settings_canonicalizer.py::LEGAL_TOP_KEYS` 包含 `"titleModelId"`
- `ALIASES` 有 `"title_model_id": "titleModelId"`（snake→camel）
- 前端 `storage.ts::TOP_KEYS` 允许此字段透传（否则 `sanitizeForBackend` 会丢弃）

## 失败可见性

| 状态 | `title` | `title_attempts` | `needs_title()` |
|---|---|---|---|
| 刚创建 | `"新对话"` | 0 | True |
| LLM 成功 | `"Python 异步编程讨论"` | 1 | False |
| LLM 失败、启发式兜底 | `"帮我写一个 Python…"` | 1 | False |
| 连续 3 次失败（无内容端点） | `"新对话"` | 3 | False（不再重试） |
| 启动回补成功 | `"讨论 Git 合并策略"` | 2 | False |

诊断：`SELECT id, title, title_attempts FROM sessions WHERE title IN (NULL, '新对话') AND title_attempts < 3 AND ...` 即可发现"待命名"会话。

## 与现有模块的交互

- **`SessionRepository.update()`**：新增 `title_attempts` 字段的写入路径，同时更新 title 与 attempts。
- **`chat_service.py`**（hex 路径）：turn 完成后在 step 9 直接实例化 `TitleGenerator(self.llm).generate(user_message.content, response.content)`，并原子 `update_session(session_id, title=..., title_attempts=attempts)`。该路径嵌套在 `if self.memory:` 块内，桌面端不走。
- **`legacy_routes.py`**（legacy 路径，桌面端主链路）：DONE 后 spawn `_generate_title()` → `TitleModelFactory.build()` → `TitleGenerator(title_client).generate(...)` → `session_repo.update(sid, title=..., title_attempts=attempts)`；若 `title != DEFAULT_TITLE` 且流仍 pending/running，则推送 `{type: "session_updated", subtype: "title_updated", session_id, title}` 事件，由 `useChat.ts:642-648` 精确 `updateSession(sid, {title})`。
- **主启动**：`backend/main.py` 创建 `TitleBackfill` 实例并 `schedule()`，shutdown 时 `await stop()`。

## 测试覆盖

| 测试 | 覆盖 |
|---|---|
| `tests/unit/test_title_generator.py` | 生成流程、启发式兜底、clean_title、load_title_llm_config |
| `tests/unit/test_title_backfill.py` | 调度、并发、速率限制、超时、attempt 计数 |
| `tests/unit/test_config_tool.py` | `titleModelId` 校验（字符串、长度、非法值） |
| `tests/contract/test_settings_schema_parity.py` | 前后端 `titleModelId` 字段对齐 |
| `tests/unit/test_settings_canonicalizer.py` | `LEGAL_TOP_KEYS` 包含 `titleModelId` |
| 前端 `src/pages/settings/__tests__/ModelsTab.p172.test.ts` | `TitleModelSelector` 渲染 + orphan 处理 |

## 与 `release/win7` 分支的关系

本特性对 Python 3.8 完全兼容：

- 不使用 `asyncio.to_thread`（3.9+），用 `asyncio.get_running_loop().run_in_executor`
- 不使用 PEP 604 `X | None` 或 PEP 585 `list[str]` 顶层注解（`py38_compat_rewrite` 已同步）
- `asyncio.TimeoutError` vs 内置 `TimeoutError`：使用 `except (asyncio.TimeoutError, TimeoutError)` 双捕获以兼容两种异常对象（py3.8 上两者是**不同对象**）

同步到 `release/win7` 时只需 `git cherry-pick`，pydantic v1 的差异在 `settings_canonicalizer.py` 已有 `conlist` 垫片，不影响标题生成路径。

## 故障排查

| 现象 | 诊断 | 处理 |
|---|---|---|
| 会话一直显示「新对话」 | `SELECT title, title_attempts FROM sessions WHERE id = ?` | 看 attempts：若 < 3，等回补；若 = 3，检查端点是否可用 |
| 设置页下拉为空 | 检查聊天端点是否配置了 `discoveredModels` | 在端点 Tab 重新测试连接 |
| 选了专用模型但标题仍是「新对话」 | 后端日志 `title_generator` 级别 | 检查模型是否在聊天端点的 base_url 上存在 |
| 启动后很久才生成标题 | 设计：`STARTUP_DELAY_S = 30` | 若需调整，改 `backend/scheduler/title_backfill.py::STARTUP_DELAY_S` |
