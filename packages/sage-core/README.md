# sage-core

**Sage 核心领域模型** - 零外部依赖的纯 Python 实现

---

## 概述

`sage-core` 是 Sage 项目的核心领域模型包，包含：

- **领域实体**（entities）：不可变的核心业务对象
- **值对象**（value_objects）：描述领域概念的值类型
- **仓库接口**（repositories）：数据访问的抽象接口
- **领域服务**（services）：无状态的领域逻辑
- **领域事件**（events）：领域事件的定义
- **异常**（exceptions）：领域特定的异常类型

## 设计原则

1. **零外部依赖**：仅使用 Python 标准库，可独立发布和测试
2. **不可变性**：所有实体和值对象都是不可变的（frozen dataclass）
3. **类型安全**：完整的类型注解，支持 mypy 严格模式
4. **可测试性**：纯函数式设计，易于单元测试
5. **可移植性**：可绑定到 Rust/JS 等其他语言

## 安装

```bash
pip install sage-core
```

## 快速开始

### 领域实体

```python
from sage_core.entities import Agent, AgentState, AgentDecision

# 创建 Agent 状态机
state = AgentState.IDLE
print(state.can_transition_to(AgentState.THINKING))  # True

# 创建决策
decision = AgentDecision(
    state=AgentState.ACTING,
    action_name="search_web",
    action_args={"query": "Python tutorial"}
)
```

### 消息系统

```python
from sage_core.entities import Message, Role, ToolCall

# 创建用户消息
user_msg = Message(role=Role.USER, content="你好")

# 创建工具调用
tool_call = ToolCall(
    name="get_weather",
    args={"city": "北京"},
    id="call_123"
)

# 创建助手消息（带工具调用）
assistant_msg = Message(
    role=Role.ASSISTANT,
    content="",
    tool_calls=[tool_call]
)
```

### 仓库接口

```python
from sage_core.repositories import StoragePort
from typing import Protocol

class MyStorageAdapter(StoragePort):
    """实现存储适配器"""
    
    async def save(self, key: str, value: bytes) -> None:
        # 实现保存逻辑
        pass
    
    async def load(self, key: str) -> bytes | None:
        # 实现加载逻辑
        pass
```

## 核心模块

### entities（领域实体）

- `Agent` - Agent 状态机和决策
- `Message` - 对话消息
- `Skill` - 技能规格和结果

### value_objects（值对象）

- `AgentState` - Agent 状态枚举
- `AgentDecision` - Agent 决策值对象
- `Role` - 消息角色枚举
- `ToolCall` - 工具调用请求

### repositories（仓库接口）

- `StoragePort` - 存储接口
- `LLMPort` - LLM 接口
- `ToolPort` - 工具接口
- `SkillPort` - 技能接口

### exceptions（异常）

- `SageCoreError` - 基础异常
- `ValidationError` - 验证错误
- `StateTransitionError` - 状态转换错误

## 与后端集成

```python
# backend/main.py
from sage_core.entities import Agent, AgentState
from backend.adapters import SqliteStorageAdapter

# 使用核心包
agent = Agent(state=AgentState.IDLE)

# 使用适配器实现
storage = SqliteStorageAdapter("data/sage.db")
```

## 开发

```bash
# 安装开发依赖
pip install -e ".[dev]"

# 运行测试
pytest

# 类型检查
mypy sage_core

# 格式化
black sage_core
isort sage_core
```

## 许可证

MIT License
