# Sage LLM 链路打通 + 工具系统设计

**日期**：2026-06-04
**状态**：待用户审阅
**关联计划**：`docs/plans/2026-06-01_sage-next-features.md`（阶段一已通过提交 `27af741` 完成；本次设计覆盖阶段二、阶段三，并在最前增加阶段零修复遗留 Bug）

---

## 1. 背景与目标

Sage 是 React + Tauri + FastAPI 架构的 LLM 对话应用。`docs/plans/2026-06-01_sage-next-features.md` 中规划的三阶段共 9 项功能：

- **阶段一**（4 项）已通过提交 `27af741` 完成（消息代码高亮、侧边栏会话管理、连接测试增强、记忆页面修复）
- **阶段二**（错误处理与稳定性）**未完成**
- **阶段三**（工具系统）**未完成**

此外，**上一会话遗留关键 Bug**：用户在浏览器发送消息后无响应，但历史记录会新增一条。该 Bug 阻碍所有后续功能验证。

**目标**：

1. **阶段零**：定位并修复"发送消息无响应" Bug，建立可工作的端到端对话链路
2. **阶段二**：实现 6 类 LLM 错误的分类与中文化友好提示
3. **阶段三**：实现 OpenAI 工具调用 schema 透传 + ReAct 循环 + 工具执行 UI

**成功标准**：

- 端到端对话可见助手回复
- 6 种错误类型有独立单元测试
- 至少 1 个内置工具（calculator）可在 UI 中端到端调用
- 整体单元测试覆盖率 ≥ 80%

---

## 2. 架构总览

### 2.1 整体数据流

```
┌─────────────┐     ┌────────────┐     ┌─────────────┐     ┌──────────┐
│ React UI    │ ──> │ Tauri Cmd  │ ──> │ FastAPI     │ ──> │ LLM API  │
│ useChat     │     │ agent_chat │     │ /chat       │     │ 端点     │
└─────────────┘     └────────────┘     └─────────────┘     └──────────┘
       │                  │                  │
       └── 结构化日志 ────┴──── 结构化日志 ──┘
                  (request_id 贯穿四边界)
```

### 2.2 三阶段结构

| 阶段 | 名称     | 关键产出                 | 验证手段            |
| ---- | -------- | ------------------------ | ------------------- |
| 0    | Bug 修复 | 端到端可对话             | 手动 + 单元回归测试 |
| 2    | 错误处理 | 错误分类 + 友好提示      | 单元 + 集成测试     |
| 3    | 工具系统 | Tool schema + ReAct + UI | 单元 + 集成 + E2E   |

### 2.3 关键技术决策

1. **结构化日志是 Bug 修复的核心** — 在 useChat、Tauri cmd、Python route、LLMClient 四个边界加 `request_id` 贯穿
2. **错误分类枚举化** — `LLMErrorType` 枚举（401/429/500/Network/Timeout/Parsing）替代散落的字符串判断
3. **ReAct 循环状态机** — `agent.run_loop()` 显式状态：`IDLE → THINKING → ACTING → OBSERVING → DONE/FAILED`
4. **TDD 严格分层** — 每个 `run_*` 函数先写测试，再写实现；mock LLM 用固定 fixture 响应
5. **串行门控**：阶段 0 → 2 → 3 严格顺序，每阶段必须 CI 通过 + 覆盖率达标才能进入下一阶段

---

## 3. 阶段零：Bug 修复设计

### 3.1 Bug 现象

- API 端点：`https://gcli.ggchan.dev/`
- 浏览器控制台仅有 `[vite] connecting... connected.`
- 行为：用户发送消息后，UI 历史记录新增一条（用户消息），但**助手无响应**
- 提交 `8830957`（实现完整 LLM 对话链路）后未在本机端到端验证

### 3.2 诊断策略：四边界日志注入

按数据流方向加 `request_id` 与"到达"日志，定位断裂点：

```python
# 边界 1：useChat.ts  — 前端发出
console.log(`[REQ ${request_id}] useChat.send() payload:`, { apiKey: '***', model, message });

# 边界 2：Tauri commands.rs  — 边界进入
log::info!("[REQ {}] agent_chat called: model={}, msg_len={}", request_id, model, message.len());

# 边界 3：backend/api/routes.py  — Python 收到
logger.info(f"[REQ {request_id}] /chat received: session_id={session_id}, api_key={'***' if api_key else 'MISSING'}");

# 边界 4：backend/core/llm_client.py  — LLM 调用
logger.info(f"[REQ {request_id}] calling LLM: base_url={base_url}, model={model}");
```

### 3.3 根因假设（按概率排序）

| #   | 假设                                                 | 修复方向                                                          |
| --- | ---------------------------------------------------- | ----------------------------------------------------------------- |
| 1   | `apiKey` 未透传到 `useChat`（settings 读取时机问题） | 修 `src/lib/settings.ts` 的读取顺序                               |
| 2   | Tauri invoke 序列化丢失 `apiKey` 字段                | 修 `src-tauri/src/models.rs` 的字段命名（snake_case ↔ camelCase） |
| 3   | Python 端 `ChatRequest.api_key` 字段未正确绑定       | 修 Pydantic model + 透传                                          |
| 4   | LLM 端点返回非标准响应导致解析失败（被静默 swallow） | 修 `llm_client.py` 显式 raise + 阶段二错误分类                    |

### 3.4 修复流程

```
1. 注入四边界日志
2. 复现 Bug：发送消息
3. 查看日志，确认 request_id 在哪一阶段丢失
4. 定位根因（对照 3.3 假设表）
5. 修复
6. 复测，确认四边界日志完整 + 助手回复
7. 添加回归测试
```

### 3.5 Bug 修复完成的判定标准

- [ ] 发送消息后能收到非空 assistant 消息
- [ ] 四边界日志完整可追溯（同一 request_id）
- [ ] 新增至少 1 个回归测试
- [ ] CI 通过

---

## 4. 阶段二：错误处理设计

### 4.1 错误分类枚举

新建 `backend/core/errors.py`：

```python
from enum import Enum
from dataclasses import dataclass

class LLMErrorType(str, Enum):
    AUTH_FAILED = "auth_failed"          # 401
    RATE_LIMITED = "rate_limited"        # 429
    SERVER_ERROR = "server_error"        # 5xx
    NETWORK = "network_error"            # 连接失败
    TIMEOUT = "timeout"                  # 超时
    PARSING = "parsing_error"            # 响应解析失败
    UNKNOWN = "unknown"


@dataclass
class LLMError(Exception):
    type: LLMErrorType
    message: str
    status_code: int | None = None
    retry_after: int | None = None
```

### 4.2 错误捕获点

修改 `backend/core/llm_client.py`：

```python
try:
    resp = await client.post(...)
except httpx.TimeoutException:
    raise LLMError(LLMErrorType.TIMEOUT, "请求 LLM 超时")
except httpx.ConnectError as e:
    raise LLMError(LLMErrorType.NETWORK, f"无法连接 LLM: {e}")
except httpx.HTTPStatusError as e:
    if e.response.status_code == 401:
        raise LLMError(LLMErrorType.AUTH_FAILED, "API Key 无效", status_code=401)
    elif e.response.status_code == 429:
        raise LLMError(LLMErrorType.RATE_LIMITED, "请求过于频繁", retry_after=...)
    elif 500 <= e.response.status_code < 600:
        raise LLMError(LLMErrorType.SERVER_ERROR, "LLM 服务端错误", status_code=...)
```

### 4.3 修复 `agent.py` 的 `assistant_message` 未定义 bug

原代码在 except 块中引用 `assistant_message`，但成功分支后才定义。改为：

```python
assistant_message: Message | None = None
try:
    assistant_message = await self._call_llm(...)
except LLMError as e:
    # assistant_message 为 None，可安全引用
    self.messages.append(Message(
        role="system",
        content=f"[错误:{e.type.value}] {e.message}",
    ))
    raise  # 重新抛出，路由层处理
```

### 4.4 前端错误展示

`src/hooks/useChat.ts` + `src/components/chat/Message.tsx`：

```typescript
const errorTypeToText: Record<string, string> = {
  auth_failed: 'API Key 无效，请检查设置',
  rate_limited: '请求过于频繁，请稍后再试',
  server_error: 'LLM 服务端错误，请稍后再试',
  network_error: '无法连接到 LLM，请检查网络',
  timeout: '请求超时，请重试',
  parsing_error: 'LLM 响应格式异常',
};
```

`Message.tsx` 用红色边框 + 错误图标区分。

### 4.5 Tauri 启动失败 UI

`src/App.tsx` 启动时调用 `await invoke('check_python_backend')`，失败则渲染友好页面（含"重试"按钮），不显示红屏。

### 4.6 错误处理完成的判定标准

- [ ] 6 种错误类型单元测试覆盖（边界 + 转换）
- [ ] 前端对每种错误有中文化提示
- [ ] Python 后端不可达时显示友好页面
- [ ] `assistant_message` 未定义 bug 已修复

---

## 5. 阶段三：工具系统设计（核心 AI 能力）

### 5.1 ReAct 循环数据流

```
User Message
   ↓
[THINKING] LLM 收到 prompt（含 tools schema）
   ↓
[DECISION] LLM 返回 tool_calls 或 text
   ↓
   ├─ text → [DONE] 返回给用户
   └─ tool_calls → [ACTING] 执行工具
                        ↓
                    [OBSERVING] 把工具结果追加到 messages
                        ↓
                    [THINKING] 回到开头（直到无 tool_calls 或达 max_iterations）
```

### 5.2 状态机实现

`backend/core/agent.py` 新增：

```python
class AgentState(str, Enum):
    IDLE = "idle"
    THINKING = "thinking"
    ACTING = "acting"
    OBSERVING = "observing"
    DONE = "done"
    FAILED = "failed"


class ToolCall(TypedDict):
    id: str
    name: str
    arguments: dict


async def run_loop(
    self,
    user_message: str,
    max_iterations: int = 5,
) -> AsyncIterator[AgentEvent]:
    """ReAct 主循环，yield 事件流供前端展示。"""
    self.messages.append(Message(role="user", content=user_message))

    for i in range(max_iterations):
        yield AgentEvent(state=AgentState.THINKING, iteration=i)

        response = await self._call_llm()  # 含 tools 参数

        if not response.tool_calls:
            # LLM 决定不调用工具 → 文本回复
            self.messages.append(Message(
                role="assistant",
                content=response.text,
            ))
            yield AgentEvent(state=AgentState.DONE, content=response.text)
            return

        # 记录 assistant 的工具调用
        self.messages.append(Message(
            role="assistant",
            tool_calls=response.tool_calls,
        ))

        for tool_call in response.tool_calls:
            yield AgentEvent(state=AgentState.ACTING, tool_call=tool_call)

            try:
                result = await self.execute_tool(tool_call)
            except Exception as e:
                result = f"[Tool Error] {e}"

            yield AgentEvent(state=AgentState.OBSERVING, tool_call=tool_call, result=result)

            self.messages.append(Message(
                role="tool",
                tool_call_id=tool_call["id"],
                content=result,
            ))

    yield AgentEvent(state=AgentState.FAILED, reason="max_iterations_exceeded")
```

### 5.3 LLM Client 扩展：传递 tools

`backend/core/llm_client.py` 新增 `tools` 参数：

```python
async def chat(
    self,
    messages: list[dict],
    tools: list[dict] | None = None,
    tool_choice: str | None = None,  # "auto" | "none" | "required"
) -> LLMResponse:
    payload = {"model": self.model, "messages": messages}
    if tools:
        payload["tools"] = tools
        payload["tool_choice"] = tool_choice or "auto"
    resp = await client.post("/chat/completions", json=payload)
    ...
```

### 5.4 工具注册表

`backend/tools/registry.py`：

```python
from typing import Callable, Any

class ToolRegistry:
    def __init__(self):
        self._tools: dict[str, dict] = {}  # name → {schema, handler}

    def register(self, name: str, description: str, parameters: dict, handler: Callable):
        self._tools[name] = {
            "schema": {
                "type": "function",
                "function": {
                    "name": name,
                    "description": description,
                    "parameters": parameters,
                },
            },
            "handler": handler,
        }

    def get_schemas(self) -> list[dict]:
        return [t["schema"] for t in self._tools.values()]

    async def execute(self, name: str, arguments: dict) -> Any:
        if name not in self._tools:
            raise ValueError(f"Unknown tool: {name}")
        return await self._tools[name]["handler"](**arguments)


# 内置工具：先实现 1 个示例（calculator），后续扩展
registry = ToolRegistry()
registry.register(
    name="calculator",
    description="执行数学运算，例如 2+3*4",
    parameters={
        "type": "object",
        "properties": {
            "expression": {"type": "string", "description": "数学表达式"},
        },
        "required": ["expression"],
    },
    handler=_safe_calculate,  # 使用 asteval 安全表达式解析器（不直接用 eval）
)


def _safe_calculate(expression: str) -> str:
    """使用 asteval 安全求值，禁止任意 Python 代码执行。"""
    from asteval import Interpreter
    aeval = Interpreter()
    result = aeval(expression)
    if aeval.error:
        return f"[计算错误] {aeval.error[0].get_error()}"
    return str(result)
```

### 5.5 前端：工具执行 UI

`src/components/chat/Message.tsx` 接收 `events` 数组，按状态渲染：

```
[用户] 1+2*3 等于多少？
[助手] ⏳ 思考中...
[工具] 🔧 calculator({"expression": "1+2*3"}) → 7
[助手] 答案是 7
```

每个事件类型对应一种渲染：thinking/acting/observing/final。

### 5.6 测试策略（TDD）

| 测试层级 | 覆盖范围                    | Mock 策略                            |
| -------- | --------------------------- | ------------------------------------ |
| 单元     | `run_loop` 状态转换         | mock `_call_llm` 返回预设 tool_calls |
| 单元     | `execute_tool` 参数校验     | mock registry                        |
| 单元     | `LLMResponse` 解析          | fixture 真实 LLM 响应样本            |
| 集成     | `/chat` 流式返回 AgentEvent | mock LLMClient 端到端                |
| E2E      | 浏览器中调用 calculator     | 真实 Tauri + Python + mock LLM       |

### 5.7 工具系统完成的判定标准

- [ ] 至少 1 个内置工具（calculator）端到端可调用
- [ ] 工具执行过程在 UI 可见
- [ ] `max_iterations` 上限生效
- [ ] 工具执行错误不导致 agent 崩溃
- [ ] 单元测试覆盖 ≥ 80%

---

## 6. 整体测试策略

### 6.1 测试覆盖目标

- 整体单元测试覆盖率 ≥ 80%
- 阶段零：关键链路有回归测试
- 阶段二：6 种错误类型全覆盖
- 阶段三：状态机转换 + 至少 1 个 E2E 工具调用

### 6.2 TDD 节奏

```
1. 写失败的测试（描述期望行为）
2. 跑测试，确认失败
3. 写最小实现让测试通过
4. 跑测试，确认通过
5. 重构，保留测试通过
6. 检查覆盖率 ≥ 80%
```

### 6.3 测试夹具与 Mock

- **LLMClient mock**：用 `pytest-mock` 替换 `_call_llm`，返回预设 `LLMResponse`
- **真实 LLM 响应样本**：保存为 `tests/fixtures/llm_responses/*.json` 用于解析测试
- **Tauri invoke mock**：`tests/mocks/tauri.ts` 提供 `invoke` 的可控 mock

---

## 7. 实施计划

### 7.1 阶段零：Bug 修复（预计 0.5 天）

- [ ] 步骤 1：在 useChat.ts 注入 `[REQ ${id}]` 日志
- [ ] 步骤 2：在 Tauri commands.rs 注入 `log::info!`
- [ ] 步骤 3：在 Python routes.py 与 llm_client.py 注入 logger.info
- [ ] 步骤 4：复现 Bug，对照 3.3 假设表定位根因
- [ ] 步骤 5：修复根因
- [ ] 步骤 6：复测 + 添加回归测试 + CI 通过

### 7.2 阶段二：错误处理（预计 1 天）

- [ ] 步骤 7：创建 `backend/core/errors.py`，定义 `LLMErrorType` + `LLMError`
- [ ] 步骤 8：单元测试 `test_errors.py` 覆盖 6 种类型（先 RED）
- [ ] 步骤 9：实现 `LLMError` 抛出的所有路径（GREEN）
- [ ] 步骤 10：修改 `agent.py`，修复 `assistant_message` 未定义 bug
- [ ] 步骤 11：在 `routes.py` 捕获 `LLMError` 并返回结构化 JSON 响应
- [ ] 步骤 12：前端 `useChat.ts` 接收错误响应并 `errorTypeToText` 映射
- [ ] 步骤 13：`Message.tsx` 添加错误样式（红色边框 + 图标）
- [ ] 步骤 14：`App.tsx` + Tauri 添加 `check_python_backend` 友好页面

### 7.3 阶段三：工具系统（预计 2 天）

- [ ] 步骤 15：扩展 `LLMResponse` 支持 `tool_calls` 字段
- [ ] 步骤 16：单元测试 `test_llm_response.py` 解析 tool_calls（RED）
- [ ] 步骤 17：实现 `LLMResponse.tool_calls` 解析（GREEN）
- [ ] 步骤 18：扩展 `LLMClient.chat()` 支持 `tools` 参数
- [ ] 步骤 19：单元测试 `test_llm_client.py` 验证 tools 透传
- [ ] 步骤 20：创建 `backend/tools/registry.py`（ToolRegistry 类）
- [ ] 步骤 21：注册内置 calculator 工具（用安全表达式解析器，不用 eval）
- [ ] 步骤 22：单元测试 `test_registry.py`
- [ ] 步骤 23：实现 `agent.run_loop()` 状态机（先 RED 写状态转换测试）
- [ ] 步骤 24：实现 `run_loop()` 完整逻辑（GREEN）
- [ ] 步骤 25：扩展 `/chat` 端点为流式响应（SSE 或 NDJSON），yield `AgentEvent`
- [ ] 步骤 26：前端 `useChat.ts` 接收事件流，状态机驱动 UI 更新
- [ ] 步骤 27：`Message.tsx` 添加工具执行渲染（thinking/acting/observing/final）
- [ ] 步骤 28：E2E 手动测试 calculator 端到端调用

### 7.4 验证与归档（预计 0.5 天）

- [ ] 步骤 29：跑全量测试，验证覆盖率 ≥ 80%
- [ ] 步骤 30：更新 `docs/plans/2026-06-01_sage-next-features.md` 标记 `[x]`
- [ ] 步骤 31：归档技术文档 `docs/13-tool-system.md` + `docs/14-error-handling.md`（沿用项目扁平 docs 结构）

---

## 8. 风险与缓解

| 风险                                | 概率 | 影响 | 缓解措施                                               |
| ----------------------------------- | ---- | ---- | ------------------------------------------------------ |
| Bug 修复引入新回归                  | 中   | 高   | 每修复配 1 个回归测试 + CI 门控                        |
| ReAct 循环死循环                    | 低   | 高   | `max_iterations=5` 硬上限 + 单元测试                   |
| 工具执行安全（eval 等）             | 中   | 中   | 阶段三仅做 calculator，使用 `asteval` 或类似安全解析器 |
| 流式响应协议选择                    | 中   | 中   | 优先 NDJSON（简单），必要时升级到 SSE                  |
| Tauri 启动失败 UI 改动牵动 Tauri 端 | 中   | 中   | 阶段二第 14 步可降级为仅前端检测（探测 /health 端点）  |

### 8.1 回滚策略

- 每个阶段独立 commit（`<type>(scope): ...`）
- CI 失败可 `git revert` 单个阶段不影响其他阶段
- 关键路径（错误处理、工具）保留在 Python 后端，前端降级也能工作

---

## 9. YAGNI：不在本期范围

- 多工具支持（仅做 1 个示例 calculator）
- 工具权限系统
- 工具市场 / 动态加载
- 流式响应分块渲染（先做完整响应或 NDJSON）
- 工具结果缓存
- 工具调用审计日志
- 工具执行的取消机制

---

## 10. 参考资料

- OpenAI Function Calling 规范：https://platform.openai.com/docs/guides/function-calling
- ReAct 论文：https://arxiv.org/abs/2210.03629
- httpx 异常处理：https://www.python-httpx.org/exceptions/
- 上一会话遗留上下文：提交 `27af741`、`8830957`
- 关联计划：`docs/plans/2026-06-01_sage-next-features.md`
