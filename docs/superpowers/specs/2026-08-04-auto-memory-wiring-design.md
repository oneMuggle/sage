# Sage Auto-Memory Wiring Design (2026-08-04)

> 状态: 已通过 brainstorming review · 待用户最终复核 · 进入 writing-plans 阶段

## 背景与目标

Sage 已经在 `backend/memory/` 下实现了相当完备的三层记忆架构（Working / Episodic / Semantic）+ 向量检索 + FTS5 + RRF 融合 + `MemoryExtractor`（借鉴 Mem0 的 fact extraction）+ `MemorySafetyScanner`（借鉴 Hermes 三级威胁扫描），并在 `ChatService._extract_and_store_memory` 主链路上每轮自动抽取事实并写入。但用户反馈"我没看到自动总结和写入"，经调研发现这是因为 6 个具体的功能性缺口让"已有的能力"无法被用户感知或使用。

本设计的目标是**填补这 6 个缺口并引入可观测性 + 生命周期抽象**，参考 Hermes Agent 的 MemoryProvider 生命周期模式，让 sage 的自动记忆沉淀从"代码存在但默默运行"升级为"用户可见、可控、可追溯"。

不实现：F 选项（Hermes 风格的固定 USER.md 始终注入）。该功能依赖单独的开关设计与系统 prompt 模板大改，超出本设计范围，留待后续 spec。

## 涉及的文件与模块

### 新增文件

| 路径 | 用途 |
|---|---|
| `backend/memory/lifecycle.py` | `MemoryLifecycleManager`：wrap 现有 `MemoryManager`，提供 `on_turn_complete` / `on_session_end` / `on_pre_compress` 三个生命周期 hook |
| `backend/memory/hooks.py` | `HookRegistry`：进程内 pub/sub，支持 `memory_written` / `session_ended` / `evolution_completed` 事件 |
| `backend/data/migrations/2026_08_05_add_memory_traceability.sql` | DB schema 迁移（加 `source_turn_id` / `source_message_id` / `memory_category`） |
| `src/pages/Memory.tsx` | 记忆管理页（带溯源信息、Tab 切换、实时 SSE 更新） |
| `src/widgets/memory/MemoryCard.tsx` | 记忆卡片组件 |
| `src/widgets/memory/MemoryTabs.tsx` | 记忆页 Tab 容器 |
| `tests/backend/memory/test_lifecycle.py` | 生命周期 manager 单测 |
| `tests/backend/memory/test_hooks.py` | HookRegistry 单测 |
| `tests/frontend/memory/MemoryList.spec.tsx` | 记忆列表组件单测 |
| `e2e/memory-auto.spec.ts` | E2E：聊一轮 → toast → 列表 → 删除 |

### 修改文件

| 路径 | 改动 |
|---|---|
| `backend/main.py` | lifespan startup 装配 `MemoryLifecycleManager` + `EvolutionScheduler` |
| `backend/application/services/chat_service.py` | `run_turn` 末尾调 `lifecycle.on_turn_complete()` 替代直接调 `_extract_and_store_memory` |
| `backend/ports/memory.py` | `MemoryPort` 加 `find_by_turn` / `find_by_category` 方法 |
| `backend/adapters/out/memory/adapter.py` | `MemoryAdapter` 实现新方法；store 路径加 `source_turn_id` / `memory_category` 参数 |
| `backend/data/database.py` | 启动时执行 schema 迁移（幂等） |
| `backend/memory/extractor.py` | 提取时记录 `source_turn_id` / `memory_category` |
| `backend/scheduler/evolution.py` | `run_once` 后 emit `evolution_completed` hook |
| `backend/scheduler/cron.py` | `EvolutionScheduler.start()` / `.stop()` 在 lifespan 调 |
| `backend/api/legacy_routes.py` | 新增 `GET /memory/events` (SSE) / `GET /memory/by-turn/{turn_id}` / `GET /memory/profile` / `GET /memory/summary/{session_id}` |
| `electron/commands.ts` | 新增 11 个 IPC cmd 映射 |
| `electron/preload.ts` | 新增 `memory_find_by_turn` / `memory_get_profile` / `memory_get_summary` 暴露 |
| `electron/main.ts` | SSE 事件转发到 renderer |
| `src/pages/Settings.tsx` | 新增 Memory 章节 + auto_memory / memory_retrieval_enabled 开关 |
| `src/widgets/Sidebar.tsx` | 新增 Memory 导航入口 |
| `src/pages/Chat.tsx` | 支持 `highlight_turn` query，滚动到指定 turn 并高亮 2s |
| `backend/agents/profiles.py` | `primary` / `researcher` agent profile tools 列表加 `memory_search` / `memory_save` |

## 技术方案

### 架构总览

```
┌─────────────────────────────────────────────────────────┐
│                    Electron Renderer                     │
│  ┌──────────┐  ┌────────────┐  ┌──────────────────┐    │
│  │ Settings │  │ Sidebar    │  │  Memory Page     │    │
│  │ auto_mem │  │ Memory入口 │  │  (溯源+CRUD+Tabs)│    │
│  └────┬─────┘  └─────┬──────┘  └────────┬─────────┘    │
│       │              │                  │               │
│       └──────────────┼──────────────────┘               │
│                      │ IPC: sage:invoke (memory_*)      │
│                      │ EventSource: /memory/events      │
└──────────────────────┼──────────────────────────────────┘
                       │
┌──────────────────────┼──────────────────────────────────┐
│                 Electron Main                            │
│  commands.ts: 11 个 memory_* cmd + 1 个 SSE 转发        │
└──────────────────────┼──────────────────────────────────┘
                       │ HTTP / SSE
┌──────────────────────┼──────────────────────────────────┐
│               FastAPI Backend                            │
│                      │                                   │
│  ┌───────────────────▼─────────────────────────────┐    │
│  │         MemoryLifecycleManager (新增)             │    │
│  │  on_turn_complete → extract → store → emit hook │    │
│  │  on_session_end    → consolidate → emit hook     │    │
│  │  on_pre_compress   → snapshot → emit hook       │    │
│  └─────────────────────┬───────────────────────────┘    │
│            ┌───────────▼────────────┐                   │
│  ┌─────────▼─────────┐  ┌──────────▼──────────┐         │
│  │  MemoryManager    │  │   HookRegistry     │         │
│  │  (已有, 不改)      │  │   (新增)            │         │
│  └─────────┬─────────┘  └──────────┬──────────┘         │
│            │                       │                    │
│  ┌─────────▼─────────┐  ┌──────────▼──────────┐         │
│  │  EvolutionSch.    │  │  SSE endpoint       │         │
│  │  (新装配到 lifespan)│ │  /memory/events     │         │
│  └───────────────────┘  └─────────────────────┘         │
└──────────────────────────────────────────────────────────┘
```

### 核心组件

#### 1. MemoryLifecycleManager

**位置**：`backend/memory/lifecycle.py`

**职责**：wrap 现有 `MemoryManager`，对外暴露三个 hook 方法；内部持有 `MemoryManager` + `HookRegistry` + `auto_memory` flag 缓存。

**关键方法**：

```python
class MemoryLifecycleManager:
    def __init__(self, memory_manager: MemoryManager, hooks: HookRegistry,
                 preferences_repo: PreferencesRepository):
        self._memory = memory_manager
        self._hooks = hooks
        self._prefs = preferences_repo
        self._auto_memory_cache: Optional[bool] = None
        self._cache_timestamp: float = 0
        self._current_turn_id: Optional[str] = None
    
    async def set_current_turn(self, turn_id: str):
        """在 ChatService.run_turn 开始时调用，标记当前 turn_id"""
        self._current_turn_id = turn_id
    
    async def on_turn_complete(self, session_id: str, messages: list[Message]):
        """每轮对话完成后调用：抽取事实 → 写入 → emit hook"""
        if not await self._is_auto_memory_enabled():
            return
        try:
            extracted = await self._memory.remember(
                session_id=session_id,
                messages=messages,
                source_turn_id=self._current_turn_id,
            )
            for mem in extracted:
                await self._hooks.emit("memory_written", MemoryWriteEvent(
                    memory_id=mem.id,
                    content=mem.content,
                    memory_type=mem.type,
                    memory_category=mem.category,
                    session_id=session_id,
                    turn_id=self._current_turn_id,
                    timestamp=utcnow(),
                ))
        except Exception as e:
            logger.exception("lifecycle.on_turn_complete failed", exc_info=e)
            # 永不抛到 ChatService
    
    async def on_session_end(self, session_id: str):
        """Session 真实结束时调用：consolidate → emit"""
        try:
            await self._memory.consolidate(session_id)
            await self._hooks.emit("session_ended", SessionEndEvent(session_id=session_id))
        except Exception as e:
            logger.exception("lifecycle.on_session_end failed", exc_info=e)
    
    async def on_pre_compress(self, session_id: str):
        """压缩工作记忆前调用：snapshot → emit"""
        try:
            await self._memory.snapshot(session_id)
            await self._hooks.emit("pre_compress", PreCompressEvent(session_id=session_id))
        except Exception as e:
            logger.exception("lifecycle.on_pre_compress failed", exc_info=e)
    
    async def _is_auto_memory_enabled(self) -> bool:
        """读 preferences 表 key=auto_memory；带 30s 缓存"""
        now = time.time()
        if self._auto_memory_cache is not None and (now - self._cache_timestamp) < 30:
            return self._auto_memory_cache
        try:
            val = await self._prefs.get("auto_memory")
            enabled = (val is None) or (val.lower() == "true")  # 默认 True
        except Exception:
            enabled = True  # 读取失败默认开
        self._auto_memory_cache = enabled
        self._cache_timestamp = now
        return enabled
```

**关键设计决策**：
- wrap 而非修改 `MemoryManager`（不破坏既有 6 个月的代码）
- 所有 hook 方法 `try/except` 吞掉异常，绝不抛到 `ChatService`
- auto_memory 缓存 30s，平衡一致性和 DB 压力
- 默认 `True`，向后兼容老用户

#### 2. HookRegistry

**位置**：`backend/memory/hooks.py`

```python
class HookRegistry:
    def __init__(self):
        self._listeners: dict[str, list[Callable]] = {}
    
    def on(self, event: str, callback: Callable):
        self._listeners.setdefault(event, []).append(callback)
    
    def off(self, event: str, callback: Callable):
        if event in self._listeners:
            self._listeners[event] = [cb for cb in self._listeners[event] if cb is not callback]
    
    async def emit(self, event: str, payload):
        """串行执行 listener；任一异常不影响其他"""
        listeners = self._listeners.get(event, [])
        for cb in listeners:
            try:
                result = cb(payload)
                if asyncio.iscoroutine(result):
                    await result
            except Exception as e:
                logger.exception(f"hook listener for {event} raised", exc_info=e)
```

**事件类型**：
- `memory_written` — 单条记忆写入
- `session_ended` — session 结束
- `pre_compress` — 压缩前
- `evolution_completed` — 进化任务完成

#### 3. SSE 端点 `/api/v1/memory/events`

**位置**：`backend/api/legacy_routes.py`

```python
@router.get("/memory/events")
async def memory_events(request: Request):
    """SSE 端点：推送 memory_written 等事件到前端"""
    queue: asyncio.Queue = asyncio.Queue(maxsize=100)
    
    async def on_memory_written(event: MemoryWriteEvent):
        try:
            queue.put_nowait(event)
        except asyncio.QueueFull:
            logger.warning("memory events queue full, dropping event")
    
    hooks.on("memory_written", on_memory_written)
    
    async def event_stream():
        try:
            while True:
                if await request.is_disconnected():
                    break
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=15.0)
                    yield f"data: {event.to_json()}\n\n"
                except asyncio.TimeoutError:
                    yield ": heartbeat\n\n"  # 保持连接
        finally:
            hooks.off("memory_written", on_memory_written)
    
    return StreamingResponse(event_stream(), media_type="text/event-stream")
```

#### 4. EvolutionScheduler 装配

**位置**：`backend/main.py` lifespan

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    # ... 已有装配 ...
    
    # 新: MemoryLifecycleManager + HookRegistry
    hooks = HookRegistry()
    lifecycle = MemoryLifecycleManager(
        memory_manager=memory_manager,
        hooks=hooks,
        preferences_repo=preferences_repo,
    )
    app.state.lifecycle = lifecycle
    app.state.hooks = hooks
    
    # 新: EvolutionScheduler
    evolution_scheduler = EvolutionScheduler()
    for task in create_evolution_tasks(memory_manager=memory_manager, hooks=hooks):
        evolution_scheduler.register(task)
    await evolution_scheduler.start()
    app.state.evolution_scheduler = evolution_scheduler
    
    # 已有: Session 结束 watchdog（每 60s 扫一次）
    session_watchdog_task = asyncio.create_task(_session_watchdog(app, lifecycle))
    
    yield
    
    # Shutdown
    session_watchdog_task.cancel()
    await evolution_scheduler.stop()
```

**`_session_watchdog`**：每 60s 扫 `sessions` 表，超过 30 分钟没更新的 session 视为结束，调 `lifecycle.on_session_end(session_id)`。

**任务 cron 映射**：

| 任务 | cron 表达式 | 时段 |
|---|---|---|
| DailySummaryTask | `0 3 * * *` | 每日凌晨 3 点 |
| PreferenceLearningTask | `0 */6 * * *` | 每 6 小时 |
| MemoryPruningTask | `0 4 * * 0` | 每周日 4 点 |
| ImportanceReevaluationTask | `0 5 * * *` | 每日 5 点 |
| MemoryConsolidationTask | `0 6 * * *` + on_session_end | 每日 6 点 + 会话结束 |

#### 5. 数据库 Schema 迁移

**位置**：`backend/data/migrations/2026_08_05_add_memory_traceability.sql`

```sql
ALTER TABLE memories_episodic ADD COLUMN source_turn_id TEXT;
ALTER TABLE memories_episodic ADD COLUMN source_message_id TEXT;
ALTER TABLE memories_episodic ADD COLUMN memory_category TEXT;
CREATE INDEX IF NOT EXISTS idx_mem_episodic_session_turn
    ON memories_episodic(session_id, source_turn_id);
CREATE INDEX IF NOT EXISTS idx_mem_episodic_category
    ON memories_episodic(memory_category);
```

**幂等迁移**：`database.py` 启动时检测 `PRAGMA table_info(memories_episodic)`，缺哪个列就 `ALTER TABLE ADD COLUMN`，缺哪个 index 就 `CREATE INDEX IF NOT EXISTS`。

#### 6. 新增端点

| 端点 | 方法 | 用途 |
|---|---|---|
| `/api/v1/memory/events` | GET (SSE) | 推送 memory_written 等事件 |
| `/api/v1/memory/by-turn/{turn_id}` | GET | 按 turn_id 查记忆（溯源反查） |
| `/api/v1/memory/profile` | GET | 用户档案聚合（user_pref 类别） |
| `/api/v1/memory/summary/{session_id}` | GET | 单 session 摘要聚合 |

#### 7. IPC 映射（`electron/commands.ts` 新增）

```typescript
memory_search: 'GET /api/v1/memory/search',
memory_save: 'POST /api/v1/memory/save',
memory_list: 'GET /api/v1/memory/list',
memory_delete: 'POST /api/v1/memory/delete',
memory_get_auto: 'GET /api/v1/preferences/auto_memory',
memory_set_auto: 'PUT /api/v1/preferences/auto_memory',
trigger_evolution: 'POST /api/v1/evolution/trigger',
memory_events_subscribe: 'GET /api/v1/memory/events',
memory_find_by_turn: 'GET /api/v1/memory/by-turn/{turn_id}',
memory_get_profile: 'GET /api/v1/memory/profile',
memory_get_summary: 'GET /api/v1/memory/summary/{session_id}',
```

#### 8. 前端组件

**Settings 页 Memory 章节**（UI C）：

```
▼ 记忆 (Memory)
  [▣] 自动记忆沉淀       ← auto_memory 开关
  [▣] 记忆检索注入       ← memory_retrieval_enabled 开关
  [查看记忆管理 →]      ← 跳转到 /memory 路由
```

**Sidebar Memory 入口**（UI A）：新增 Brain 图标的导航项，路由 `/memory`。

**Memory 页面 `src/pages/Memory.tsx`**（UI A + D）：

```
┌─ Memory ────────────────────────────┐
│  [🔍 搜索]  类型筛选 ▾                │
│  Tabs: [所有] [用户档案] [会话摘要]    │
│  ┌──────────────────────────────┐  │
│  │ 🧠 用户偏好 · 08-04 17:30    │  │
│  │ 用户偏好 KISS 风格           │  │
│  │ 📍 Session #abc · Turn #42  │  │  ← 溯源（点击跳转 Chat 页）
│  │ importance: 8  [删除]        │  │
│  └──────────────────────────────┘  │
│  ...                                │
└────────────────────────────────────┘
```

**SSE 订阅**：`useEffect` 中 `new EventSource('/api/v1/memory/events')`，收到 `memory_written` 事件：
1. 顶部 toast："🧠 已记住: {content}"
2. 列表顶部插入新卡片（高亮 2s 淡出）
3. SSE 失败时退化到 `setInterval` 30s 轮询 `/memory/list`

**Chat 页溯源跳转**：`/chat?session=abc&highlight_turn=42` 时，加载完消息后 `scrollIntoView` + 加 `ring-2 ring-blue-500` 2s 淡出。

### 数据流（典型场景）

**场景：用户聊一轮对话，LLM 回应涉及用户偏好**

```
1. 用户在 Chat 页发消息
2. ChatService.run_turn() 开始
   ├─ lifecycle.set_current_turn(turn_id="turn-42")
   ├─ memory.retrieve(query) → 注入 system_prompt
   ├─ LLM.chat(messages, tools=[memory_search, memory_save])
   ├─ LLM 返回 response
   └─ lifecycle.on_turn_complete(session_id, messages)
       ├─ 读 preferences "auto_memory" (缓存命中: True)
       ├─ MemoryManager.remember(messages, source_turn_id="turn-42")
       │  ├─ MemoryExtractor.extract(messages)
       │  │  └─ LLM 抽: "用户偏好 KISS 风格" / importance: 8 / category: user_pref
       │  ├─ MemorySafetyScanner.scan_write(content) → 通过
       │  └─ EpisodicMemory.store(content, importance, category, source_turn_id="turn-42")
       ├─ HookRegistry.emit("memory_written", event)
       │  ├─ SSE listener: queue.put_nowait(event)
       │  └─ Evolution logger: log.info(event)
       └─ return

3. SSE 端点 event_stream() 收到 event
   ├─ yield "data: {...}\n\n"
   └─ 推到 Electron main

4. Electron main 转发 SSE 到 renderer

5. Renderer EventSource 收到
   ├─ Toast: "🧠 已记住: 用户偏好 KISS 风格"
   └─ Memory 列表页（如已打开）顶部插入新卡片

6. 用户点 Memory 侧边栏
   ├─ 路由 /memory
   ├─ IPC memory_list → 渲染列表
   └─ 看到刚才那条记忆，卡片显示 "📍 Session #abc · Turn #42"
       └─ 点击溯源 → 跳转到 /chat?session=abc&highlight_turn=42
           └─ Chat 页滚动到对应 turn 并高亮 2s
```

### 错误处理

| 场景 | 策略 | 用户感知 |
|---|---|---|
| MemoryExtractor LLM 失败 | 关键词降级（已有逻辑） | 无 |
| MemorySafetyScanner 拦截 | 拒绝写入 + log warning | 无 |
| EvolutionScheduler 任务异常 | 捕获 + log + 下一周期重试 | 无 |
| SSE 断连 | EventSource 自动重连 | 无 |
| SQLite 写入失败 | log + 重试 1 次 + 跳过 | toast 失败提示 |
| lifecycle hook 异常 | 吞掉 + log，绝不抛 ChatService | 无 |
| find_by_turn 无结果 | 返回 `{"memories": []}` | 无 |
| preferences 读取失败 | 缓存默认值 True | 无 |

**铁律**：所有记忆相关代码 `try/except` 包裹，**永远不阻塞对话主路径**。

### 测试策略

**测试金字塔（80%+ 覆盖率）**：

| 层级 | 框架 | 覆盖目标 |
|---|---|---|
| Unit | pytest | MemoryLifecycleManager 三个 hook / HookRegistry emit/异常隔离 / auto_memory 缓存 / SafetyScanner 边界 |
| Unit | vitest | MemoryCard 渲染 / Toggle 受控 / EventSource mock / 降级轮询 |
| Integration | pytest | `_extract_and_store_memory` → SQLite 端到端 / SSE emit → consume / EvolutionScheduler start/stop |
| E2E | Playwright | 聊一轮 → toast → Memory 页 → 删除 → 列表消失 / 关 auto_memory → 不增加 |

**关键测试**：

```python
# backend/tests/memory/test_lifecycle.py
async def test_on_turn_complete_emits_hook():
async def test_auto_memory_false_skips_extraction():
async def test_session_end_triggers_consolidation():
async def test_hook_listener_exception_does_not_propagate():
async def test_auto_memory_cache_ttl():
```

```typescript
// src/widgets/memory/__tests__/MemoryCard.spec.tsx
test('renders traceability info and navigates on click');
test('subscribes to SSE and prepends new cards');
test('falls back to polling when EventSource fails');
```

## 实施步骤

按优先级 D → B → C → A → E 推进，每步独立 commit + 测试：

- [ ] **D. IPC 接通**（1-2h）— `commands.ts` 加 11 个 cmd 映射；前端 `memoryApi.ts` 不再 404；手动验证 search/save/list/delete 4 个端点
- [ ] **B. auto_memory 开关**（30min）— `MemoryLifecycleManager` 加 `_is_auto_memory_enabled()` + 30s 缓存；ChatService 改调 lifecycle；Settings 页 UI C 落地
- [ ] **C. LLM 工具注册**（1-2h）— `ToolRegistry` 装配 `MemorySearchTool` / `MemorySaveTool`；`ChatService.tools` 参数传递；agent profile 加工具
- [ ] **A. 进化任务自动跑**（1-2d）— DB schema 迁移（`source_turn_id` / `memory_category` / index）；`lifecycle.on_session_end` + watchdog；`EvolutionScheduler` 装配到 lifespan
- [ ] **E. 专用端点 + 溯源增强**（1d）— `MemoryPort.find_by_turn` / `find_by_category`；4 个新端点；前端 UI A 侧边栏 + Memory 列表页 + UI D Tabs；Chat 页 `highlight_turn` query
- [ ] **可观测性收尾**（30min）— HookRegistry 装配 Evolution 任务 emit；Electron main 转发 SSE 到 renderer；前端 EventSource 订阅 + toast + 卡片高亮

每 commit 前 TDD：写测试 → 红灯 → 实施 → 绿灯 → refactor。

## 风险评估

| 风险 | 等级 | 缓解 |
|---|---|---|
| DB schema 迁移失败 | 中 | 启动时幂等检查；测试用 in-memory SQLite |
| SSE 在企业代理环境被禁用 | 中 | EventSource + 轮询双重降级；文档说明 |
| EvolutionScheduler 任务阻塞主事件循环 | 中 | `asyncio.create_task` fire-and-forget；独立 session |
| 记忆失败被吞掉无可见性 | 低 | log 到 `backend/logs/memory_errors.log`；提供 `GET /api/v1/memory/health` |
| auto_memory 缓存 race | 低 | TTL=30s 可接受；提供 cache invalidate 端点 |
| Win7 LTS py3.8 兼容性 | 低 | 借鉴 background_review 经验的 dual-compat 模式，cherry-pick 时验证 |
| SSE 攻击面 | 低 | 只 emit 不 input；同源；本地桌面无认证 |

## 性能影响

| 操作 | 当前 | 加 hook 后 | 增量 |
|---|---|---|---|
| 单轮对话后 | LLM 抽 + 写 DB | + emit hook (1ms) + SSE 推送 | <2% |
| 自动进化任务 | 0（未跑） | cron 每日/6h | 后台 |
| Memory list 查询 | 已有 | +1 列 (source_turn_id) | 0 |
| LLM 工具调用 | 0（未注册） | + tool schema (~200 tokens) | system prompt +200 |

**总评**：性能开销 < 3%，用户不可感知。

## 文档交付

- **`docs/superpowers/specs/2026-08-04-auto-memory-wiring-design.md`** — 本设计文档（实施后归档到 `docs/technical/36-auto-memory-lifecycle.md`）
- **`docs/user-manual/13-memory-management.md`** — 用户手册
- 更新 **`docs/04-memory.md`** — 加 lifecycle / hook / SSE 章节

## 回滚策略

- 单 feature branch `feat/auto-memory-wiring`，6 个 commit 对应 6 步骤
- 任一 commit 失败可独立 revert
- DB schema 迁移 forward-only；回滚需手动 `ALTER TABLE DROP COLUMN`（不影响旧数据，列可保留 NULL）

## 不在本设计范围

- **F 选项**：Hermes 风格的固定 USER.md 始终注入 — 单独 spec
- **记忆编辑界面**：UI D 当前只支持查看/删除，编辑留待后续
- **多用户/多 profile**：当前单用户模型；多用户留待 v2
- **向量召回降级策略**：当前 RRF 固定权重 [0.4, 0.6]；动态权重留待后续
- **记忆导入/导出**：留待后续