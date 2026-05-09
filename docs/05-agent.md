# Sage - Agent 引擎

## 5.1 Agent 概述

### 5.1.1 设计目标

Sage Agent 是核心对话引擎，负责:
1. 处理用户消息
2. 管理对话上下文
3. 调用工具和技能
4. 与记忆系统交互

### 5.1.2 核心特性

| 特性 | 说明 |
|-----|------|
| **多轮对话** | 支持多轮上下文对话 |
| **工具调用** | 支持自定义工具执行 |
| **技能调度** | 支持技能系统集成 |
| **记忆集成** | 自动检索和保存记忆 |
| **流式输出** | 支持流式响应 |
| **可中断** | 支持中断长时间运行 |

---

## 5.2 Agent 架构

### 5.2.1 类结构

```
┌─────────────────────────────────────────────────────────────┐
│                        SageAgent                             │
│                      (主入口类)                               │
├─────────────────────────────────────────────────────────────┤
│ Attributes:                                                  │
│   - model: ChatModel              # LLM 适配器               │
│   - memory: MemoryManager         # 记忆管理器               │
│   - tool_registry: ToolRegistry   # 工具注册表               │
│   - skill_manager: SkillManager   # 技能管理器               │
│   - config: AgentConfig           # 配置                     │
│                                                              │
│ Methods:                                                     │
│   + chat(message) -> str           # 简单对话                │
│   + run_conversation() -> dict     # 完整对话                │
│   + interrupt()                    # 中断执行                │
│   + reset()                        # 重置状态                │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                     MessageBuilder                            │
│                    (消息构建器)                                │
├─────────────────────────────────────────────────────────────┤
│ + build_system_prompt() -> str                              │
│ + build_messages() -> list[dict]                           │
│ + build_tool_schemas() -> list[dict]                        │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                     ToolExecutor                             │
│                      (工具执行器)                             │
├─────────────────────────────────────────────────────────────┤
│ + execute(tool_call) -> ToolResult                          │
│ + validate_args(tool_name, args) -> bool                    │
└─────────────────────────────────────────────────────────────┘
```

### 5.2.2 核心流程

```
User Input
    │
    ▼
┌─────────────────────────────────────────────────────────────┐
│ 1. Preprocessing                                             │
│    - 输入清洗                                                │
│    - 特殊指令检测 (技能触发、工具强制调用)                    │
│    - 意图初判                                                │
└────────────────────────────┬────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────┐
│ 2. Context Building                                          │
│                                                              │
│    - 记忆检索 (remember)                                     │
│    - 对话历史组装                                            │
│    - System Prompt 构建                                      │
│    - Tool Schemas 注册                                       │
└────────────────────────────┬────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────┐
│ 3. Model Inference                                           │
│                                                              │
│    ┌─────────────────────────────────────────────────────┐  │
│    │  while iterations < max_iterations:                  │  │
│    │      response = model.complete(messages)            │  │
│    │      if response.tool_calls:                         │  │
│    │          results = executor.execute_all(response)   │  │
│    │          messages.extend(results)                    │  │
│    │      else:                                           │  │
│    │          return response.content                     │  │
│    └─────────────────────────────────────────────────────┘  │
└────────────────────────────┬────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────┐
│ 4. Postprocessing                                            │
│                                                              │
│    - 记忆保存 (memorize)                                     │
│    - 进化检查                                                │
│    - 统计更新                                                │
└────────────────────────────┬────────────────────────────────┘
                             │
                             ▼
                       Final Response
```

---

## 5.3 核心实现

### 5.3.1 SageAgent 主类

```python
# backend/core/agent.py
import asyncio
import time
import uuid
import logging
from typing import List, Optional, Dict, Callable, AsyncIterator
from dataclasses import dataclass, field

from .message_builder import MessageBuilder
from .tool_executor import ToolExecutor
from .exceptions import AgentError, ToolCallError, MaxIterationsError

logger = logging.getLogger(__name__)

@dataclass
class AgentConfig:
    """Agent 配置"""
    model: str = "gpt-3.5-turbo"
    provider: str = "openai"
    temperature: float = 0.7
    max_tokens: int = 4096
    max_iterations: int = 10
    timeout: int = 120
    system_prompt: str = ""

@dataclass
class ToolCall:
    """工具调用"""
    id: str
    name: str
    arguments: Dict

@dataclass
class AgentResponse:
    """Agent 响应"""
    content: str
    tool_calls: List[ToolCall] = field(default_factory=list)
    finish_reason: str = "stop"
    usage: Dict = field(default_factory=dict)
    metadata: Dict = field(default_factory=dict)

class SageAgent:
    """
    Sage Agent - 核心对话引擎

    参考 Hermes run_agent.py 实现，简化用于桌面应用
    """

    def __init__(
        self,
        model_client,
        memory_manager,
        tool_registry,
        skill_manager,
        config: AgentConfig
    ):
        self.model = model_client
        self.memory = memory_manager
        self.tools = tool_registry
        self.skills = skill_manager
        self.config = config

        self.message_builder = MessageBuilder(
            system_prompt=config.system_prompt,
            memory_manager=memory_manager
        )
        self.executor = ToolExecutor(tool_registry)

        # 状态
        self._interrupt_requested = False
        self._current_session_id = None

    async def chat(
        self,
        message: str,
        session_id: str,
        stream: bool = False
    ) -> AgentResponse:
        """
        处理用户消息

        Args:
            message: 用户输入
            session_id: 会话 ID
            stream: 是否流式输出

        Returns:
            AgentResponse: 响应
        """
        self._current_session_id = session_id
        self._interrupt_requested = False

        # 1. 构建消息列表
        messages = await self.message_builder.build(
            user_message=message,
            session_id=session_id
        )

        # 2. 执行推理循环
        try:
            response = await self._run_loop(
                messages,
                stream=stream
            )
        except asyncio.CancelledError:
            response = AgentResponse(
                content="[中断] 对话已被中断",
                finish_reason="interrupt"
            )

        # 3. 后处理 - 保存记忆
        await self._postprocess(message, response, session_id)

        return response

    async def _run_loop(
        self,
        messages: List[dict],
        stream: bool = False
    ) -> AgentResponse:
        """推理循环"""
        iterations = 0
        start_time = time.time()

        while iterations < self.config.max_iterations:
            # 检查中断
            if self._interrupt_requested:
                raise asyncio.CancelledError()

            # 检查超时
            if time.time() - start_time > self.config.timeout:
                raise TimeoutError("Agent 执行超时")

            # LLM 调用
            response = await self.model.complete(
                messages=messages,
                tools=self.tools.get_schemas() if self.tools else None,
                stream=stream,
                temperature=self.config.temperature,
                max_tokens=self.config.max_tokens
            )

            # 无工具调用 - 返回结果
            if not response.tool_calls:
                return AgentResponse(
                    content=response.content,
                    usage=response.usage,
                    finish_reason=response.finish_reason
                )

            # 处理工具调用
            for tool_call in response.tool_calls:
                try:
                    result = await self.executor.execute(tool_call)

                    messages.append({
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": result.content
                    })
                except Exception as e:
                    logger.error(f"工具执行失败: {e}")
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": f"错误: {str(e)}"
                    })

            iterations += 1

        raise MaxIterationsError(f"达到最大迭代次数 {self.config.max_iterations}")

    async def _postprocess(
        self,
        user_message: str,
        response: AgentResponse,
        session_id: str
    ):
        """后处理"""
        # 保存对话记忆
        await self.memory.memorize(
            content=f"用户: {user_message}\n助手: {response.content}",
            memory_type="episodic",
            importance=5,
            metadata={"session_id": session_id}
        )

    def interrupt(self):
        """请求中断"""
        self._interrupt_requested = True
        logger.info("Agent 中断请求已发送")

    def reset(self):
        """重置状态"""
        self._interrupt_requested = False
        self._current_session_id = None
```

### 5.3.2 MessageBuilder

```python
# backend/core/message_builder.py
class MessageBuilder:
    """消息构建器"""

    def __init__(
        self,
        system_prompt: str,
        memory_manager
    ):
        self.system_prompt = system_prompt or self._default_system_prompt()
        self.memory = memory_manager

    async def build(
        self,
        user_message: str,
        session_id: str,
        history: List[dict] = None
    ) -> List[dict]:
        """构建消息列表"""
        messages = []

        # 1. System Prompt
        messages.append({
            "role": "system",
            "content": await self._build_system_prompt(session_id)
        })

        # 2. 对话历史
        if history:
            messages.extend(history)

        # 3. 当前消息
        messages.append({
            "role": "user",
            "content": user_message
        })

        return messages

    async def _build_system_prompt(self, session_id: str) -> str:
        """构建系统提示词"""
        prompt_parts = [self.system_prompt]

        # 添加记忆上下文
        memory_context = await self.memory.remember(
            query="用户偏好和背景",
            context={"session_id": session_id}
        )

        if memory_context:
            prompt_parts.append(f"\n\n【记忆上下文】\n{memory_context}")

        # 添加日期时间
        from datetime import datetime
        prompt_parts.append(f"\n\n当前时间: {datetime.now().strftime('%Y-%m-%d %H:%M')}")

        return "\n".join(prompt_parts)

    def _default_system_prompt(self) -> str:
        """默认系统提示词"""
        return """你叫 Sage，是一个友善、智慧的 AI 助手。

你的特点:
- 有记忆能力，可以记住之前的对话内容
- 善于理解和回答各种问题
- 可以使用工具来完成复杂任务
- 乐于助人，耐心解答

请用简洁、有帮助的方式回复。"""
```

### 5.3.3 ToolExecutor

```python
# backend/core/tool_executor.py
import json
import logging
from typing import Dict, Any
from dataclasses import dataclass

from .exceptions import ToolExecutionError

logger = logging.getLogger(__name__)

@dataclass
class ToolResult:
    """工具执行结果"""
    tool_call_id: str
    success: bool
    content: str
    error: str = None

class ToolExecutor:
    """工具执行器"""

    def __init__(self, tool_registry):
        self.registry = tool_registry

    async def execute(self, tool_call) -> ToolResult:
        """执行单个工具调用"""
        tool_name = tool_call.name
        tool_args = tool_call.arguments

        logger.info(f"执行工具: {tool_name}, 参数: {tool_args}")

        try:
            tool = self.registry.get(tool_name)
            if not tool:
                return ToolResult(
                    tool_call_id=tool_call.id,
                    success=False,
                    content="",
                    error=f"工具不存在: {tool_name}"
                )

            # 执行工具
            result = await tool.execute(**tool_args)

            return ToolResult(
                tool_call_id=tool_call.id,
                success=True,
                content=json.dumps(result, ensure_ascii=False)
            )

        except Exception as e:
            logger.error(f"工具执行错误: {e}")
            return ToolResult(
                tool_call_id=tool_call.id,
                success=False,
                content="",
                error=str(e)
            )

    async def execute_all(self, tool_calls) -> List[ToolResult]:
        """并行执行多个工具调用"""
        results = await asyncio.gather(
            *[self.execute(tc) for tc in tool_calls],
            return_exceptions=True
        )
        return [r if isinstance(r, ToolResult) else ToolResult(
            tool_call_id="error",
            success=False,
            content="",
            error=str(r)
        ) for r in results]
```

---

## 5.4 工具注册表

### 5.4.1 工具基类

```python
# backend/tools/base.py
from abc import ABC, abstractmethod
from typing import Dict, Any, List
from dataclasses import dataclass

@dataclass
class ToolSchema:
    """工具 schema 定义"""
    name: str
    description: str
    parameters: Dict[str, Any]  # JSON Schema

class BaseTool(ABC):
    """工具基类"""

    def __init__(self):
        self._schema = self._build_schema()

    @property
    def schema(self) -> ToolSchema:
        return self._schema

    @abstractmethod
    def _build_schema(self) -> ToolSchema:
        """构建工具 schema"""
        pass

    @abstractmethod
    async def execute(self, **kwargs) -> Any:
        """执行工具"""
        pass

    def validate_args(self, args: Dict) -> bool:
        """验证参数"""
        # TODO: JSON Schema 验证
        return True
```

### 5.4.2 内置工具

| 工具名 | 功能 | 权限 |
|-------|------|------|
| terminal | 执行 shell 命令 | terminal |
| read_file | 读取文件 | file:read |
| write_file | 写入文件 | file:write |
| web_search | 网络搜索 | network |
| calculator | 计算器 | none |
| memory_search | 搜索记忆 | memory |
| memory_save | 保存记忆 | memory |

### 5.4.3 工具注册表

```python
# backend/tools/registry.py
from typing import Dict, Optional, List
import logging

logger = logging.getLogger(__name__)

class ToolRegistry:
    """工具注册表"""

    def __init__(self):
        self._tools: Dict[str, BaseTool] = {}

    def register(self, tool: BaseTool):
        """注册工具"""
        self._tools[tool.schema.name] = tool
        logger.info(f"注册工具: {tool.schema.name}")

    def unregister(self, name: str):
        """取消注册"""
        if name in self._tools:
            del self._tools[name]

    def get(self, name: str) -> Optional[BaseTool]:
        """获取工具"""
        return self._tools.get(name)

    def list(self) -> List[str]:
        """列出所有工具"""
        return list(self._tools.keys())

    def get_schemas(self) -> List[Dict]:
        """获取所有工具 schema"""
        return [
            {
                "type": "function",
                "function": {
                    "name": tool.schema.name,
                    "description": tool.schema.description,
                    "parameters": tool.schema.parameters
                }
            }
            for tool in self._tools.values()
        ]
```

---

## 5.5 对话管理

### 5.5.1 会话状态

```python
# backend/core/session.py
from typing import List, Optional
from dataclasses import dataclass, field
from datetime import datetime

@dataclass
class Session:
    """会话"""
    id: str
    title: str
    created_at: datetime
    updated_at: datetime
    message_count: int = 0
    metadata: dict = field(default_factory=dict)

@dataclass
class Message:
    """消息"""
    id: str
    session_id: str
    role: str  # 'user' | 'assistant' | 'system' | 'tool'
    content: str
    tool_calls: List[dict] = field(default_factory=list)
    created_at: datetime
    tokens: int = 0
```

### 5.5.2 会话管理器

```python
# backend/core/session_manager.py
class SessionManager:
    """会话管理器"""

    def __init__(self, db):
        self.db = db

    async def create_session(self, title: str = None) -> Session:
        """创建会话"""
        session_id = str(uuid.uuid4())
        now = datetime.now()

        cursor = self.db.cursor()
        cursor.execute("""
            INSERT INTO sessions (id, title, created_at, updated_at)
            VALUES (?, ?, ?, ?)
        """, (session_id, title or "新对话", now, now))

        self.db.commit()

        return Session(
            id=session_id,
            title=title or "新对话",
            created_at=now,
            updated_at=now
        )

    async def get_session(self, session_id: str) -> Optional[Session]:
        """获取会话"""
        cursor = self.db.cursor()
        cursor.execute("SELECT * FROM sessions WHERE id = ?", (session_id,))

        row = cursor.fetchone()
        if not row:
            return None

        return Session(**dict(row))

    async def list_sessions(self, limit: int = 50) -> List[Session]:
        """列出会话"""
        cursor = self.db.cursor()
        cursor.execute("""
            SELECT * FROM sessions
            WHERE isarchived = 0
            ORDER BY updated_at DESC
            LIMIT ?
        """, (limit,))

        return [Session(**dict(row)) for row in cursor.fetchall()]

    async def save_message(self, message: Message):
        """保存消息"""
        cursor = self.db.cursor()
        cursor.execute("""
            INSERT INTO messages
            (id, session_id, role, content, created_at)
            VALUES (?, ?, ?, ?, ?)
        """, (
            message.id,
            message.session_id,
            message.role,
            message.content,
            message.created_at
        ))

        # 更新会话
        cursor.execute("""
            UPDATE sessions
            SET updated_at = ?, message_count = message_count + 1
            WHERE id = ?
        """, (message.created_at, message.session_id))

        self.db.commit()
```

---

## 5.6 流式输出

### 5.6.1 流式实现

```python
async def chat_stream(
    self,
    message: str,
    session_id: str
) -> AsyncIterator[str]:
    """流式对话"""
    messages = await self.message_builder.build(
        user_message=message,
        session_id=session_id
    )

    async for chunk in self.model.complete_stream(
        messages=messages,
        tools=self.tools.get_schemas() if self.tools else None
    ):
        yield chunk
```

### 5.6.2 Tauri 流式调用

```rust
// src-tauri/src/main.rs
#[tauri::command]
async fn agent_chat_stream(
    state: State<'_, AppState>,
    session_id: String,
    message: String,
) -> Result<impl Stream<Item = String>, String> {
    let agent = state.agent.clone();

    let stream = async_stream::stream! {
        let mut stream = agent.chat_stream(message, session_id).await;
        while let Some(chunk) = stream.next().await {
            yield chunk;
        }
    };

    Ok(stream)
}
```

---

## 5.7 Hermes Agent 参考

### 5.7.1 Hermes run_agent.py 关键逻辑

```python
# Hermes run_agent.py (简化)
class AIAgent:
    def run_conversation(self, user_message, system_message=None, history=None):
        messages = []

        # System
        if system_message:
            messages.append({"role": "system", "content": system_message})

        # History
        if history:
            messages.extend(history)

        # User
        messages.append({"role": "user", "content": user_message})

        # Loop
        while self.iteration_budget.remaining > 0:
            response = self.client.complete(messages, tools=self.tool_schemas)

            if response.tool_calls:
                for tc in response.tool_calls:
                    result = handle_function_call(tc.name, tc.args)
                    messages.append(tool_result_message(result))
                self.iteration_budget.use(len(response.tool_calls))
            else:
                return response.content

        raise MaxIterationsError()
```

---

*文档版本: v1.0*
