# g004: Agent 编排 (Agent Orchestration) 验证映射

> Sage Agent 系统 — `SageAgent` ReAct 对话引擎 + `AgentOrchestrator` 多 Agent 协作 +
> `ChatService` 六角架构用例服务，编排 6 个 ports 完成一轮对话。

---

**状态**: 🔴 未验证  
**维护者**: @backend-team  
**最后更新**: 2026-06-19

---

## 1. 范围与职责

### 负责

- 职责 1：**对话循环引擎** — `SageAgent.chat()` 和 `SageAgent.run_loop()` 管理 ReAct 循环（IDLE → THINKING → ACTING → OBSERVING → DONE/FAILED）
- 职责 2：**LLM 调用编排** — 构造 system prompt（含记忆上下文）+ 历史消息 → `LLMClient.chat()` → 处理响应（含 tool_calls）
- 职责 3：**工具调用管理** — 解析 LLM 返回的 `tool_calls`，查找 `ToolRegistry` 执行工具，将结果作为 tool message 回传
- 职责 4：**上下文窗口管理** — `WorkingMemory` 滑动窗口（max_size=20, max_tokens=4000）+ 历史消息截取（最近 5-20 条）
- 职责 5：**多 Agent 协作** — `AgentOrchestrator` 意图分类（5 类：GENERAL/RESEARCH/CODING/MEMORY/MULTI_STEP）+ Agent 选择 + 任务分发 + 结果聚合
- 职责 6：**查询缓存** — `QueryCache`（MD5 键，TTL=5min，max_size=100）避免重复查询
- 职责 7：**六角架构用例服务** — `ChatService.run_turn()` 编排 6 ports 完成一轮对话（PG2.9 单轮工具执行）

### 不负责

- 非职责 1：记忆存储和检索的具体实现（由 g001-memory-system 负责）
- 非职责 2：工具执行的具体实现（由 g002-tool-execution 负责）
- 非职责 3：技能匹配和执行（由 g003-skill-lifecycle 负责）
- 非职责 4：LLM API 的 HTTP 通信（由 `HttpxLLMAdapter` / `LLMClient` 负责）

### 依赖

- 依赖 g001：`MemoryManager` 提供记忆上下文
- 依赖 g002：`ToolRegistry` 提供工具执行
- 依赖 `backend.core.legacy.llm_client.LLMClient`：LLM 调用
- 依赖 `backend.data.session_repo`：会话 / 消息持久化
- 依赖 `backend.data.blackboard_repo`：多 Agent 共享状态

---

## 2. 接口契约

### 2.1 输入断言

| 参数 | 类型 | 约束 | 验证方法 |
|------|------|------|----------|
| `session_id` (chat/run_turn) | `str` | 非空 | `assert session_id and len(session_id) > 0` |
| `message` (chat) | `str` | 非空 | `assert message and isinstance(message, str)` |
| `user_message` (run_turn) | `Message` | `role == Role.USER` | `assert user_message.role == Role.USER` |
| `max_iterations` (run_loop) | `int` | > 0，≤ 50 | `assert 0 < max_iterations <= 50` |
| `history` (orchestrator) | `list[dict] \| None` | 每个 dict 含 `role` + `content` | `assert all('role' in m and 'content' in m for m in history)` |
| `tool_calls` (LLM response) | `list[ToolCall]` | 每个含 `id`, `name` | `assert all(tc.name and tc.id for tc in tool_calls)` |
| `messages` (run_loop) | `list[dict]` | 非空 | `assert len(messages) >= 1` |

### 2.2 输出断言

| 返回值 | 类型 | 约束 | 验证方法 |
|--------|------|------|----------|
| `chat()` → `dict` | `dict` | 含 `message` 和 `session` 键 | `assert 'message' in result` |
| `run_turn()` → `list[Message]` | `list[Message]` | 至少 2 条（user + assistant） | `assert len(result) >= 2` |
| `run_loop()` → yields `AgentEvent` | `Generator[AgentEvent]` | 最终事件为 DONE 或 FAILED | `assert last_event.state in (AgentState.DONE, AgentState.FAILED)` |
| `process_request()` → `dict` | `dict` | 含 `metadata` 键 | `assert 'metadata' in result` |
| `LLMResponse.content` | `str` | 非空（成功时） | `assert response.content and len(response.content) > 0` |

### 2.3 错误处理

| 错误场景 | 错误类型 | 处理方式 |
|----------|----------|----------|
| LLM API 不可用 | `LLMError` | `chat()` 捕获，返回 `{"error": e.to_dict(), "message": None}` |
| LLM 配置缺失 | `AgentError` | `run_loop()` 抛出 `AgentError("LLM 未配置")` |
| 工具不存在 | `ToolCallError` | 返回 `[错误] 工具不存在: {name}` 作为 tool message |
| 工具执行异常 | `Exception` | 返回 `[工具错误] {str(e)}` 作为 tool message |
| 超过最大迭代 | 状态机 | yield `AgentEvent(state=FAILED, error="max_iterations_exceeded")` |
| 消息持久化失败 | `Exception` | WARNING 日志，不阻断对话 |
| LLM 响应含无效 tool_calls | `json.JSONDecodeError` | arguments 解析为 `{}`，继续执行 |

---

## 3. 不变量约束

### 3.1 数据不变量

#### 不变量 1: 对话连续性

**定义**：同一 `session_id` 的多次 `chat()` 调用，消息按时间顺序递增，`message_count` 正确更新。

**验证方法**：
```python
def verify_conversation_continuity(session_id: str) -> bool:
    """验证对话连续性"""
    from backend.data.session_repo import SessionRepository, MessageRepository

    session_repo = SessionRepository()
    message_repo = MessageRepository()

    session = session_repo.get(session_id)
    if not session:
        return False

    messages = message_repo.get_by_session(session_id)
    return session.message_count >= len(messages)
```

**检查频率**：
- [x] 每次 `chat()` 调用后

**测试用例**：
```python
def test_conversation_continuity():
    """测试对话连续性"""
    from backend.data.session_repo import SessionRepository

    session_repo = SessionRepository()
    session_id = session_repo.create(title="test")
    session = session_repo.get(session_id)
    assert session is not None
    assert session.message_count == 0

    session_repo.update(session_id, message_count=2, last_message_at=1234567890)
    updated = session_repo.get(session_id)
    assert updated.message_count == 2
```

#### 不变量 2: 工具调用验证

**定义**：每个 `tool_call` 的 `name` 必须在 `ToolRegistry` 中存在，否则返回错误信息而非崩溃。

**验证方法**：
```python
def verify_tool_call_validation(registry, tool_name: str) -> bool:
    """验证工具调用前检查"""
    if tool_name:
        return registry.exists(tool_name)
    return True
```

**测试用例**：
```python
def test_tool_call_validation():
    """测试工具调用前验证"""
    from backend.tools.registry import ToolRegistry
    from backend.tools import register_all_tools

    registry = ToolRegistry()
    register_all_tools(registry)

    assert registry.exists("calculator")
    assert not registry.exists("nonexistent")
```

#### 不变量 3: 上下文窗口限制

**定义**：`WorkingMemory` 消息数不超过 `max_size`，`run_loop()` 不超过 `max_iterations` 步。

**验证方法**：
```python
def verify_context_window_limit(wm) -> bool:
    """验证上下文窗口未超限"""
    return len(wm.messages) <= wm.max_size
```

**测试用例**：
```python
def test_context_window_limit():
    """测试上下文窗口限制"""
    from backend.memory.working import WorkingMemory

    wm = WorkingMemory(max_size=20, max_tokens=4000)
    for i in range(50):
        wm.add({"role": "user", "content": f"msg {i}"})
    assert len(wm.messages) <= 20
    assert verify_context_window_limit(wm)
```

### 3.2 行为不变量

#### 意图分类一致性

**定义**：`_classify_intent()` 对相同输入返回相同意图。关键词匹配优先于 LLM。

**验证方法**：
```python
import asyncio

def test_intent_classification_consistency():
    """测试意图分类一致性"""
    from backend.core.legacy.orchestrator import AgentOrchestrator, Intent

    orch = AgentOrchestrator(llm_client=None)
    loop = asyncio.new_event_loop()

    assert loop.run_until_complete(
        orch._classify_intent("帮我搜索最新的新闻")
    ) == Intent.RESEARCH
    assert loop.run_until_complete(
        orch._classify_intent("写一个 Python 函数")
    ) == Intent.CODING
    assert loop.run_until_complete(
        orch._classify_intent("记住我喜欢蓝色")
    ) == Intent.MEMORY
    assert loop.run_until_complete(
        orch._classify_intent("你好啊")
    ) == Intent.GENERAL
    loop.close()
```

#### 查询缓存 TTL 有效性

**定义**：TTL 内的条目可命中，超过 TTL 的条目自动失效。

**验证方法**：
```python
import time

def test_cache_ttl():
    """测试查询缓存 TTL"""
    from backend.core.legacy.agent import QueryCache

    cache = QueryCache(ttl=2, max_size=10)
    cache.set("session1", "hello", {"answer": "world"})
    assert cache.get("session1", "hello") is not None

    time.sleep(3)
    assert cache.get("session1", "hello") is None  # 已过期
```

#### ReAct 状态机终止

**定义**：`run_loop()` 在有限步内终止（DONE 或 FAILED）。

**测试用例**：
```python
def test_react_termination():
    """测试 ReAct 循环必然终止"""
    # 通过集成测试验证 run_loop 的有限终止
    # mock LLM 返回无 tool_calls → DONE
    # mock LLM 始终返回 tool_calls → FAILED (max_iterations)
    pass
```

### 3.3 性能不变量

#### ChatService.run_turn 内部开销 < 200ms

**定义**：不含 LLM 调用，run_turn 内部处理延迟低于 200ms。

```python
import time

async def test_run_turn_internal_overhead():
    """测试 run_turn 内部开销"""
    # 使用 mock LLM 测试纯内部开销
    start = time.perf_counter()
    # await chat_service.run_turn(session_id, msg)  # with mock
    elapsed = (time.perf_counter() - start) * 1000
    assert elapsed < 200
```

---

## 4. 失败模式与恢复

### 4.1 失败模式 1: LLM API 失败

**触发条件**：LLM 服务不可用、网络错误、API 限流、认证失败、响应超时。

**影响**：严重性高，对话无法生成回复。

**检测方式**：
```python
def detect_llm_failure(error_type: str) -> bool:
    """检测 LLM 失败类型"""
    from backend.core.errors import LLMErrorType
    return error_type in [
        LLMErrorType.API_ERROR.value,
        LLMErrorType.TIMEOUT.value,
        LLMErrorType.RATE_LIMIT.value,
    ]
```

**恢复策略**：
1. `LLMError` 由 `chat()` 捕获 → 返回结构化错误 `{"error": e.to_dict()}`
2. `ChatService.run_turn()` 记 metric + event 后透传
3. `AgentOrchestrator._run_agent_llm()` 返回错误占位符
4. `ConsolidationPipeline` 回退到启发式摘要

**验证测试**：
```python
def test_llm_failure_handling():
    """测试 LLM 失败时的错误处理"""
    from backend.core.errors import LLMError, LLMErrorType

    error = LLMError(LLMErrorType.API_ERROR, "connection refused")
    error_dict = error.to_dict()
    assert error_dict["type"] == "api_error"
    assert "connection refused" in error_dict["message"]
```

### 4.2 失败模式 2: 工具调用失败

**触发条件**：工具执行异常、工具返回失败、工具不存在。

**影响**：严重性中，单个工具失败不阻断 ReAct 循环。

**恢复策略**：
1. 异常被捕获 → `result_content = f"[工具错误] {str(e)}"`
2. 错误作为 `role=tool` 消息追加到 messages
3. LLM 根据错误信息调整策略
4. `ChatService._execute_tool_calls()` emit `tool_failed` 事件

**验证测试**：
```python
def test_tool_call_failure_recovery():
    """测试工具调用失败恢复"""
    from backend.tools.base import ToolResult

    result = ToolResult(success=False, error="file not found")
    assert not result.success
    assert result.error is not None
```

### 4.3 失败模式 3: 上下文溢出

**触发条件**：`WorkingMemory.total_tokens > max_tokens` 或 `run_loop` 超过 `max_iterations`。

**恢复策略**：
1. `WorkingMemory._evict_if_needed()` 自动淘汰旧消息
2. `ConsolidationPipeline.consolidate()` 压缩为摘要
3. `run_loop()` 超限 → yield `AgentEvent(state=FAILED)`

**验证测试**：
```python
def test_context_overflow_recovery():
    """测试上下文溢出恢复"""
    from backend.memory.working import WorkingMemory
    from backend.memory.consolidation import ConsolidationPipeline

    wm = WorkingMemory(max_size=5, max_tokens=100)
    for i in range(20):
        wm.add({"role": "user", "content": "x" * 50})
    assert len(wm.messages) <= 5

    pipe = ConsolidationPipeline(llm_client=None)
    summary = pipe.compress_working_memory(wm.get_context())
    assert summary is not None
```

### 4.4 失败模式 4: LLM 配置缺失

**触发条件**：`SageAgent.__init__()` 未传入 `llm_config` 且 `run_loop()` 也未传入。

**恢复策略**：
1. `run_loop()` 抛出 `AgentError`
2. `chat()` 返回模拟响应 `f"收到消息: {message}\n\n(LLM 未配置)"`

**验证测试**：
```python
def test_llm_not_configured():
    """测试 LLM 未配置时的行为"""
    from backend.core.legacy.agent import SageAgent

    agent = SageAgent(llm_config=None)
    assert agent.llm_client is None

    import asyncio
    result = asyncio.new_event_loop().run_until_complete(
        agent.chat("test_session", "hello")
    )
    assert "模拟响应" in result["message"]["content"]
```

---

## 5. 验证方法

### 5.1 单元测试

**位置**：`tests/verification/g004/`

**运行命令**：
```bash
/home/fz/anaconda3/envs/sage-backend/bin/pytest tests/verification/g004/ -v \
  --cov=backend/core/legacy --cov=backend/agents --cov=backend/application/services
```

**覆盖范围**：
- [ ] QueryCache get/set/clear/cleanup/TTL 过期
- [ ] SageAgent 初始化 + LLM 配置缺失处理
- [ ] SageAgent.chat() 正常流程 + 缓存命中
- [ ] SageAgent.run_loop() 状态机终止
- [ ] AgentOrchestrator 意图分类（关键词 + LLM）
- [ ] AgentOrchestrator Agent 选择映射
- [ ] ChatService.run_turn() 单轮对话
- [ ] ChatService._execute_tool_calls() 事件/metric
- [ ] AgentProfile 序列化
- [ ] 默认 4 Agent 配置正确性

### 5.2 集成测试

**位置**：`tests/integration/g004/`

**覆盖范围**：
- [ ] 端到端对话流程
- [ ] ReAct 多步循环
- [ ] ChatService 6 ports 编排
- [ ] Agent 间协作（orchestrator → researcher → coder）
- [ ] 记忆上下文注入对话

### 5.3 属性测试

**使用的库**：`hypothesis`

**测试的属性**：
- [ ] ReAct 终止性：run_loop 必然在 max_iterations 步内终止
- [ ] 意图分类一致性：相同输入分类相同
- [ ] 上下文窗口不超限
- [ ] 工具调用安全性

### 5.4 性能测试

**测试的指标**：
- [ ] ChatService.run_turn 内部开销 < 200ms
- [ ] 意图分类延迟 < 100ms
- [ ] QueryCache 命中延迟 < 0.1ms

---

## 6. 监控指标

### 6.1 运行时指标

| 指标 | 类型 | 目标值 | 告警阈值 | 监控方式 |
|------|------|--------|----------|----------|
| LLM 调用延迟 P95 | 直方图 | < 30s | > 60s | Prometheus (`sage_llm_call_duration_seconds`) |
| LLM 调用错误率 | 计数器 | < 5% | > 20% | Prometheus (`sage_llm_calls_total{outcome="error"}`) |
| ReAct 步数分布 | 直方图 | < 5 步 | > 10 步 | Prometheus (`sage_react_steps_per_request`) |
| Token 消耗 | 计数器 | - | > 100k/天 | Prometheus (`sage_tokens_consumed_total`) |
| 活跃会话数 | 仪表 | - | > 100 | Prometheus (`sage_active_sessions`) |
| 缓存命中率 | 比率 | > 20% | < 5% | QueryCache 统计 |

### 6.2 健康检查

**端点**：`GET /health/agent`

**返回格式**：
```json
{
  "status": "healthy",
  "checks": {
    "llm_client": "ok",
    "tool_registry": {"count": 9},
    "memory_manager": "ok",
    "active_sessions": 5,
    "cache": {"size": 12, "max_size": 100, "ttl": 300}
  },
  "agents": {
    "primary": "enabled",
    "researcher": "enabled",
    "coder": "enabled",
    "memory_manager": "enabled"
  },
  "timestamp": "2026-06-19T12:00:00Z"
}
```

---

## 7. 验证状态

### 7.1 测试覆盖率

| 验证类型 | 状态 | 覆盖率 | 最后运行 |
|----------|------|--------|----------|
| 单元测试 | 🔴 | 0% | - |
| 集成测试 | 🔴 | 0% | - |
| 性能测试 | 🔴 | 0% | - |
| 属性测试 | 🔴 | 0% | - |

### 7.2 不变量验证

| 不变量 | 状态 | 最后验证 |
|--------|------|----------|
| 对话连续性 | ❌ | - |
| 工具调用验证 | ❌ | - |
| 上下文窗口限制 | ❌ | - |
| 意图分类一致性 | ❌ | - |
| ReAct 终止性 | ❌ | - |
| 查询缓存 TTL | ❌ | - |

### 7.3 失败模式测试

| 失败模式 | 检测测试 | 恢复测试 | 状态 |
|----------|----------|----------|------|
| LLM API 失败 | ❌ | ❌ | 🔴 |
| 工具调用失败 | ❌ | ❌ | 🔴 |
| 上下文溢出 | ❌ | ❌ | 🔴 |
| LLM 配置缺失 | ❌ | ❌ | 🔴 |

---

## 8. 变更日志

| 日期 | 变更 | 作者 |
|------|------|------|
| 2026-06-19 | 初始版本 | @backend-team |

---

## 9. 参考

- [SageAgent](../../backend/core/legacy/agent.py) — ReAct 对话引擎
- [AgentOrchestrator](../../backend/core/legacy/orchestrator.py) — 多 Agent 编排
- [ChatService](../../backend/application/services/chat_service.py) — 六角架构用例服务
- [AgentProfile / AgentModelConfig](../../backend/agents/profiles.py) — Agent 配置
- [AgentState / AgentEvent](../../backend/core/legacy/agent_state.py) — 状态机定义
- [LLMClient / LLMResponse](../../backend/core/legacy/llm_client.py) — LLM 客户端
- [LLMPort](../../backend/ports/llm.py) — 六角架构 LLM 端口
- [StoragePort](../../backend/ports/storage.py) — 六角架构存储端口
- [QueryCache](../../backend/core/legacy/agent.py) — 查询缓存实现
- [g001 记忆系统](./g001-memory-system.md) — 记忆上下文
- [g002 工具执行](./g002-tool-execution.md) — 工具调用
- [g003 技能生命周期](./g003-skill-lifecycle.md) — 技能系统
