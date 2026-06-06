# Sage P2 详细实施计划 — 后端六边形重构

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 把后端从单体 `core/` 迁移到六边形架构（domain / ports / application / adapters / api），不破坏现有 383 个测试

**Phase:** P2 of 4（P0 + P1 已完工）

**周期：** 3-4 周（单人）/ 2-3 周（2 人）

**关联文档：**
- 总体规划：`docs/superpowers/plans/2026-06-05-sage-quality-optimization.md`
- 设计 spec：`docs/superpowers/specs/2026-06-05-sage-quality-optimization-design.md` § 5
- 质量门禁：`docs/technical/15-quality-gates.md`
- 前端质量：`docs/technical/17-frontend-quality.md`

**P1 末基线（2026-06-05）：**
- 后端覆盖率 84%（383 测试；`--cov-fail-under=80` 强制）
- 前端 53/53 通过
- FSD 已上线，enforcement 生效
- 当前 `backend/core/` 仍是单体（agent.py 591 行 + orchestrator.py 383 行 + llm_client.py 306 行 + 4 个其他模块）

---

## P2 验收标准

- [ ] `backend/domain/` 零外部依赖（仅 typing + dataclass + enum + abc）
- [ ] `backend/ports/` 6 个 Protocol 接口定义完成
- [ ] `backend/adapters/` 至少 1 个生产 + 1 个 mock 实现覆盖每个 port
- [ ] `backend/application/services/chat_service.py` 编排 6 个 ports
- [ ] `backend/api/routes.py` 改写为 in-adapter（仅 HTTP 序列化 + 调用 service）
- [ ] `import-linter` 强制 5 层依赖图
- [ ] **双轨保留**：旧路径 `core/agent.py` 等保留为 `core/legacy/`，通过 `API_MODE=legacy` 切换
- [ ] 端到端 383 个测试仍全过
- [ ] 整体覆盖率 ≥ 80%（不下降）
- [ ] `docs/technical/18-hexagonal.md` 发布
- [ ] `docs/technical/02-architecture.md` 重写为六边形视角

---

## P2 任务组概览

| ID | 主题 | 文件 | 验收 |
|----|------|------|------|
| **PG2.1** | domain/ 抽离 | `backend/domain/` | 5 文件；mypy strict 通过 |
| **PG2.2** | ports/ 接口 | `backend/ports/` | 6 个 Protocol |
| **PG2.3** | httpx LLM adapter | `backend/adapters/out/llm/httpx_adapter.py` | 通过现有 LLMClient 测试 |
| **PG2.4** | mock LLM adapter | `backend/adapters/out/llm/mock_adapter.py` | 单元可注入 |
| **PG2.5** | storage adapters | `backend/adapters/out/storage/{sqlite,memory}_adapter.py` | 现有 db 测试通过 |
| **PG2.6** | tool inproc adapter | `backend/adapters/out/tool/inproc_adapter.py` | 工具测试通过 |
| **PG2.7** | metric adapters | `backend/adapters/out/metric/{prometheus,noop}_adapter.py` | 骨架（PG3.1 完善） |
| **PG2.8** | event adapters | `backend/adapters/out/event/{file,stdout}_adapter.py` | 骨架（PG3.2 完善） |
| **PG2.9** | ChatService | `backend/application/services/chat_service.py` | 编排 6 ports + ReAct |
| **PG2.10** | 重写 api/routes.py | `backend/api/routes.py` | 仅 HTTP 序列化 + service 调用 |
| **PG2.11** | import-linter 依赖约束 | `backend/pyproject.toml` | 5 层依赖图通过 |
| **PG2.12** | 端到端回归 | e2e + integration | 383 测试全过 |
| **PG2.13** | 双轨 + API_MODE 切换 | env var | 旧路径可工作 |
| **PG2.14** | 文档更新 | 4 章节 | 发布 |

**总计：14 任务组**

---

## 总体策略：双轨（Dual-Track）

按 spec § 7.2 P2 回滚策略，**P2 全程双轨**：

```
                     ┌─────────────────────────┐
                     │      api/routes.py       │
                     │   (新代码统一入口)        │
                     └────────────┬──────────────┘
                                  │
                ┌─────────────────┴──────────────────┐
                │ API_MODE=hex (默认，新)              │
                │   ↓                                    │
                │ application/services/chat_service.py   │
                │   ↓                                    │
                │ ports (Protocol)                       │
                │   ↓                                    │
                │ adapters/out/ (httpx/sqlite/...)       │
                │                                      │
                │ API_MODE=legacy (回滚)                 │
                │   ↓                                    │
                │ core/legacy/agent.py (旧)              │
                │ core/legacy/llm_client.py              │
                │ core/legacy/orchestrator.py            │
                └──────────────────────────────────────┘
```

**核心原则**：
- 旧 `core/agent.py` 等不删除，移到 `core/legacy/`
- `api/routes.py` 同时支持两种模式（通过 `API_MODE` env var）
- 默认 `hex`，可一键切回 `legacy` 用于回滚
- 旧路径不依赖 domain/ports，所以可以并存

---

## PG2.1 — domain/ 抽离

**目标：** 把 `core/` 中纯领域模型抽到 `domain/`，零外部依赖。

### 任务 2.1.1：读现有 core/ 摸清领域模型

- [ ] Read `core/agent_state.py`（81 行 — 状态枚举）
- [ ] Read `core/errors.py`（46 行 — LLMError / LLMErrorType）
- [ ] Read `core/exceptions.py`（200 行 — 异常体系）
- [ ] Read `core/agent.py` 找出 dataclass（消息、决策等纯数据类）
- [ ] 识别应该迁移的纯模型 vs 应该留在 application 层的服务逻辑

### 任务 2.1.2：创建 domain/ 目录与文件

```bash
mkdir -p /home/fz/project/sage/backend/domain
```

**Files:**
- Create `backend/domain/__init__.py`
- Create `backend/domain/agent.py`（AgentState 枚举 + AgentDecision dataclass）
- Create `backend/domain/message.py`（Message / Role / ToolCall）
- Create `backend/domain/tool.py`（Tool 协议、ToolResult）
- Create `backend/domain/skill.py`（Skill 抽象）
- Create `backend/domain/errors.py`（从 `core/errors.py` 移动 LLMError + LLMErrorType）

### 任务 2.1.3：domain 内容

`backend/domain/agent.py`（基于 spec § PG2.1 关键代码示例）：

```python
"""纯领域模型，零外部依赖。"""
from dataclasses import dataclass
from enum import Enum


class AgentState(str, Enum):
    IDLE = "idle"
    THINKING = "thinking"
    ACTING = "acting"
    OBSERVING = "observing"
    DONE = "done"
    FAILED = "failed"

    @classmethod
    def initial(cls) -> "AgentState":
        return cls.IDLE

    def can_transition_to(self, other: "AgentState") -> bool:
        legal = {
            AgentState.IDLE: {AgentState.THINKING},
            AgentState.THINKING: {AgentState.ACTING, AgentState.DONE, AgentState.FAILED},
            AgentState.ACTING: {AgentState.OBSERVING, AgentState.FAILED},
            AgentState.OBSERVING: {AgentState.THINKING, AgentState.DONE, AgentState.FAILED},
            AgentState.DONE: set(),
            AgentState.FAILED: set(),
        }
        return other in legal.get(self, set())


@dataclass(frozen=True)
class AgentDecision:
    state: AgentState
    final_message: str | None
    action_name: str | None
    action_args: dict | None
```

`backend/domain/message.py`（基于 `core/agent.py` 中发现的 dataclass）：

```python
"""消息领域模型。"""
from dataclasses import dataclass, field
from enum import Enum
from typing import Literal


class Role(str, Enum):
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


@dataclass
class ToolCall:
    name: str
    args: dict
    id: str | None = None


@dataclass
class Message:
    role: Role
    content: str
    tool_calls: list[ToolCall] = field(default_factory=list)
    tool_call_id: str | None = None
```

`backend/domain/tool.py` + `skill.py` + `errors.py` 按实际需要适配。

### 任务 2.1.4：验证 mypy strict

```bash
cd /home/fz/project/sage/backend && \
  /home/fz/anaconda3/envs/sage-backend/bin/mypy backend/domain
```

Expected: 0 errors（domain strict 段已配好 in `mypy.ini` P0）。

### 任务 2.1.5：跑现有测试（不应破坏）

```bash
cd /home/fz/project/sage/backend && \
  /home/fz/anaconda3/envs/sage-backend/bin/pytest --no-cov
```

Expected: 383/383 pass（domain 是新增，不影响旧测试）。

### 任务 2.1.6：commit

```bash
cd /home/fz/project/sage
git add backend/domain
git commit -m "refactor(backend): 抽离 domain/ 纯领域模型（agent/message/tool/skill/errors）

- AgentState 枚举 + can_transition_to 状态机
- AgentDecision 不可变 dataclass
- Message / Role / ToolCall
- LLMError / LLMErrorType 移入
- mypy strict 通过（domain/ 段已配 P0）
- 现有 383 测试不受影响"
```

**退出标准：** `backend/domain/` 5 文件，零外部 import，mypy strict 0 errors

---

## PG2.2 — ports/ 接口定义

**目标：** 定义 6 个 Protocol 接口。

### 任务 2.2.1：创建 ports/ 目录

```bash
mkdir -p /home/fz/project/sage/backend/ports
```

### 任务 2.2.2：6 个 Protocol 文件

**Files:**
- Create `backend/ports/__init__.py`
- Create `backend/ports/llm.py`
- Create `backend/ports/tool.py`
- Create `backend/ports/skill.py`
- Create `backend/ports/storage.py`
- Create `backend/ports/observability.py`（含 MetricPort + EventPort）

`backend/ports/llm.py`（基于 spec § PG2.2）：

```python
from typing import Protocol
from backend.domain.message import Message


class LLMPort(Protocol):
    async def chat(
        self,
        messages: list[Message],
        tools: list | None = None,
        tool_choice: str | dict | None = None,
    ) -> Message: ...

    async def chat_stream(
        self,
        messages: list[Message],
    ): ...  # AsyncIterator[str]
```

`backend/ports/tool.py`、`skill.py`、`storage.py` 类似。

`backend/ports/observability.py`：

```python
from typing import Protocol


class MetricPort(Protocol):
    def counter(self, name: str, labels: dict) -> None: ...
    def histogram(self, name: str, value: float, labels: dict) -> None: ...
    def gauge(self, name: str, value: float, labels: dict) -> None: ...


class EventPort(Protocol):
    def emit(self, event_type: str, payload: dict) -> None: ...
```

### 任务 2.2.3：mypy strict 验证

```bash
cd /home/fz/project/sage/backend && \
  /home/fz/anaconda3/envs/sage-backend/bin/mypy backend/ports
```

Expected: 0 errors.

### 任务 2.2.4：commit

```bash
cd /home/fz/project/sage
git add backend/ports
git commit -m "refactor(backend): 定义 ports/ 6 个 Protocol 接口

- LLMPort (chat / chat_stream)
- ToolPort
- SkillPort
- StoragePort
- MetricPort (counter / histogram / gauge)
- EventPort (emit)

所有接口零运行时影响（仅 typing）；mypy strict 段已就绪"
```

**退出标准：** 6 个 Protocol，mypy strict 0 errors

---

## PG2.3 — adapters/out/llm/httpx 实现

**目标：** 把现有 `core/llm_client.py` 改造为 `adapters/out/llm/httpx_adapter.py`，实现 `LLMPort`。

### 任务 2.3.1：读现有 llm_client.py

- [ ] Read `/home/fz/project/sage/backend/core/llm_client.py` 全文

### 任务 2.3.2：创建 httpx adapter

```bash
mkdir -p /home/fz/project/sage/backend/adapters/out/llm
```

**Files:**
- Create `backend/adapters/out/__init__.py`
- Create `backend/adapters/out/llm/__init__.py`
- Create `backend/adapters/out/llm/httpx_adapter.py`

httpx_adapter.py 实质上是把 `LLMClient` 改造为实现 `LLMPort`：

```python
"""LLM HTTP 客户端 adapter（生产实现）。"""
from backend.core.llm_client import LLMClient as _LLMClient  # 复用现有实现


class HttpxLLMAdapter:
    """实现 LLMPort，包装现有 LLMClient。"""

    def __init__(self, **kwargs):
        self._client = _LLMClient(**kwargs)

    async def chat(self, messages, tools=None, tool_choice=None):
        # 转换 domain.Message → LLMClient 输入 → 返回 domain.Message
        return await self._client.chat(messages, tools=tools, tool_choice=tool_choice)
```

**关键：** 不要重写 LLMClient！先包装它。PG2.3 只是把"在 ports 视角"接好。

### 任务 2.3.3：写 adapter 单元测试

**Files:**
- Create `backend/tests/unit/test_httpx_llm_adapter.py`

测试 adapter 是否正确委派给 LLMClient（可用 P0 mock fixture）。

### 任务 2.3.4：跑现有测试

```bash
cd /home/fz/project/sage/backend && \
  /home/fz/anaconda3/envs/sage-backend/bin/pytest --no-cov
```

Expected: 383 + N (新 adapter 测试) pass.

### 任务 2.3.5：commit

```bash
cd /home/fz/project/sage
git add backend/adapters
git commit -m "refactor(backend): 实现 httpx LLM adapter（包装现有 LLMClient）"
```

---

## PG2.4 — adapters/out/llm/mock 实现

**目标：** 单元测试可注入的 mock LLM adapter。

### 任务 2.4.1：写 mock adapter

**Files:**
- Create `backend/adapters/out/llm/mock_adapter.py`

```python
"""Mock LLM adapter（测试用，可注入固定响应）。"""
from backend.domain.message import Message, Role, ToolCall


class MockLLMAdapter:
    def __init__(self, responses: list[Message] | None = None):
        self._responses = list(responses or [])
        self._index = 0
        self.calls: list[dict] = []

    async def chat(self, messages, tools=None, tool_choice=None):
        self.calls.append({"messages": messages, "tools": tools})
        if self._index < len(self._responses):
            resp = self._responses[self._index]
            self._index += 1
            return resp
        return Message(role=Role.ASSISTANT, content="[mock default]")

    async def chat_stream(self, messages):
        async def gen():
            yield "[mock stream]"
        return gen()
```

### 任务 2.4.2：写单元测试

**Files:**
- Create `backend/tests/unit/test_mock_llm_adapter.py`

测试：返回固定响应、调用记录、默认响应、流式。

### 任务 2.4.3：commit

```bash
cd /home/fz/project/sage
git add backend/adapters/out/llm/mock_adapter.py backend/tests/unit/test_mock_llm_adapter.py
git commit -m "refactor(backend): 实现 mock LLM adapter（测试用）"
```

---

## PG2.5 — storage adapters

**目标：** SQLite + memory 双实现。

### 任务 2.5.1：识别现有 storage

- [ ] Read `backend/data/database.py`、`backend/memory/*` 找到所有 sqlite 访问点
- [ ] 列出 StoragePort 需要的操作

### 任务 2.5.2：定义 StoragePort

（在 PG2.2 已有基础上补充具体方法）

### 任务 2.5.3：实现 SqliteStorageAdapter

**Files:**
- Create `backend/adapters/out/storage/sqlite_adapter.py`

包装现有 SQLite 访问，实现 StoragePort。

### 任务 2.5.4：实现 MemoryStorageAdapter（in-memory）

**Files:**
- Create `backend/adapters/out/storage/memory_adapter.py`

用于单元测试的内存版实现。

### 任务 2.5.5：测试 + commit

```bash
cd /home/fz/project/sage
git add backend/adapters/out/storage backend/tests/unit/test_storage_*.py
git commit -m "refactor(backend): 实现 storage adapters（sqlite + memory）"
```

---

## PG2.6 — tool inproc adapter

**目标：** 把 `tools/registry.py` 改造为 `ToolPort` 实现。

### 任务 2.6.1：读 tools/registry.py

- [ ] Read `/home/fz/project/sage/backend/tools/registry.py`

### 任务 2.6.2：实现 InprocToolAdapter

**Files:**
- Create `backend/adapters/out/tool/inproc_adapter.py`

```python
"""进程内 tool registry adapter。"""
from backend.tools.registry import ToolRegistry as _ToolRegistry


class InprocToolAdapter:
    def __init__(self, registry: _ToolRegistry | None = None):
        self._registry = registry or _ToolRegistry()

    async def execute(self, name: str, args: dict) -> dict:
        result = self._registry.execute(name, args)
        return {"success": result.success, "output": result.output, "error": result.error}
```

### 任务 2.6.3：测试 + commit

---

## PG2.7 — metric adapters（骨架）

### 任务 2.7.1：实现 PrometheusMetricAdapter（骨架）

**Files:**
- Create `backend/adapters/out/metric/prometheus_adapter.py`

骨架实现，P3.1 完善（注册 9 个指标）。

### 任务 2.7.2：实现 NoopMetricAdapter

**Files:**
- Create `backend/adapters/out/metric/noop_adapter.py`

什么都不做，用于测试。

### 任务 2.7.3：commit

```bash
cd /home/fz/project/sage
git add backend/adapters/out/metric
git commit -m "refactor(backend): 实现 metric adapters 骨架（prometheus + noop）"
```

---

## PG2.8 — event adapters（骨架）

### 任务 2.8.1：FileEventAdapter

**Files:**
- Create `backend/adapters/out/event/file_adapter.py`

写 `backend/data/audit/audit.jsonl`，P3.2 完善（5 类事件）。

### 任务 2.8.2：StdoutEventAdapter

### 任务 2.8.3：commit

---

## PG2.9 — application/services/chat_service.py

**目标：** 编排 6 个 ports，实现 ReAct 循环。

### 任务 2.9.1：创建 services 目录

```bash
mkdir -p /home/fz/project/sage/backend/application/services
```

### 任务 2.9.2：实现 ChatService

**Files:**
- Create `backend/application/__init__.py`
- Create `backend/application/services/__init__.py`
- Create `backend/application/services/chat_service.py`

```python
"""ChatService — 编排 LLM / Tool / Storage / Metrics / Events ports。"""
from backend.domain.message import Message, Role
from backend.domain.agent import AgentState, AgentDecision
from backend.ports.llm import LLMPort
from backend.ports.tool import ToolPort
from backend.ports.storage import StoragePort
from backend.ports.observability import MetricPort, EventPort


class ChatService:
    def __init__(
        self,
        llm: LLMPort,
        tools: ToolPort,
        storage: StoragePort,
        metrics: MetricPort,
        events: EventPort,
    ):
        self.llm = llm
        self.tools = tools
        self.storage = storage
        self.metrics = metrics
        self.events = events

    async def run_turn(self, session_id: str, user_message: Message) -> list[Message]:
        """执行一轮对话（可能含多次 ReAct 迭代）。"""
        # 简化实现：先做单次 LLM 调用，ReAct 循环在 P2 末或 P3 加
        await self.storage.append_message(session_id, user_message)
        self.events.emit("chat_message_sent", {"session_id": session_id})

        response = await self.llm.chat([user_message])
        await self.storage.append_message(session_id, response)
        self.events.emit("chat_response_completed", {"session_id": session_id})

        return [user_message, response]
```

### 任务 2.9.3：写单元测试

用 MockLLMAdapter + MemoryStorageAdapter 注入，验证基本流。

### 任务 2.9.4：commit

```bash
cd /home/fz/project/sage
git add backend/application
git commit -m "refactor(backend): 实现 ChatService（编排 6 ports 的基础结构）"
```

---

## PG2.10 — 重写 api/routes.py 为 in-adapter

**目标：** 路由层只做 HTTP 序列化 + 调用 service。

### 任务 2.10.1：读现有 routes.py

- [ ] Read `/home/fz/project/sage/backend/api/routes.py`

### 任务 2.10.2：双轨实现

**策略：** 在 `api/routes.py` 顶部加 `API_MODE` 选择：

```python
import os

API_MODE = os.environ.get("API_MODE", "hex")  # "hex" | "legacy"

if API_MODE == "hex":
    from backend.application.services.chat_service import ChatService
    # ... use new ChatService
else:
    from backend.core.legacy.agent import SageAgent
    # ... use old path
```

**风险：** 单一文件 500+ 行 + 双轨会让文件 ≥ 1000 行。**更稳妥**是拆为 `api/hex_routes.py` + `api/legacy_routes.py` + `api/routes.py`（仅做 dispatch）。

### 任务 2.10.3：写 ChatService 路由

`backend/api/hex_routes.py`：
```python
"""新六边形 API 路由。"""
from fastapi import APIRouter, Depends
from backend.application.services.chat_service import ChatService

router = APIRouter()

def get_chat_service() -> ChatService:
    # DI：在 main.py 注入
    raise NotImplementedError("Wire up in main.py")

@router.post("/chat/stream")
async def chat_stream(req: ChatRequest, svc: ChatService = Depends(get_chat_service)):
    # 转换 + 调用
    msgs = await svc.run_turn(req.session_id, req.message)
    return {"messages": msgs}
```

### 任务 2.10.4：写 legacy_routes.py

`backend/api/legacy_routes.py` — 现有 routes.py 的副本（move 即可）。

### 任务 2.10.5：routes.py 改 dispatch

```python
import os
from fastapi import APIRouter

API_MODE = os.environ.get("API_MODE", "hex")

if API_MODE == "hex":
    from backend.api.hex_routes import router
else:
    from backend.api.legacy_routes import router
```

### 任务 2.10.6：测试 + commit

```bash
cd /home/fz/project/sage
git add backend/api
git commit -m "refactor(backend): api/routes.py 双轨（hex / legacy）

- hex: 调用 ChatService（新）
- legacy: 旧路径（保留）
- API_MODE env var 切换
- 默认 hex，legacy 用于回滚"
```

---

## PG2.11 — import-linter 依赖约束

### 任务 2.11.1：创建 pyproject.toml

**Files:**
- Create `backend/pyproject.toml`（如果还不存在；用 ruff 配置集中化）

```toml
[tool.importlinter:contract:domain-purity]
type = layers
layers = [
    'backend.domain',
    'backend.ports',
    'backend.application',
    'backend.adapters',
    'backend.api',
]
```

### 任务 2.11.2：跑 import-linter

```bash
cd /home/fz/project/sage/backend && \
  /home/fz/anaconda3/envs/sage-backend/bin/lint-imports
```

Expected: 0 violations.

### 任务 2.11.3：commit

```bash
cd /home/fz/project/sage
git add backend/pyproject.toml
git commit -m "chore(backend): 配置 import-linter 5 层依赖图

- domain（最纯）→ ports → application → adapters → api
- domain 不能 import 任何上层
- 任何逆向 import 立即 fail"
```

---

## PG2.12 — 端到端回归

### 任务 2.12.1：跑全部测试

```bash
cd /home/fz/project/sage/backend && \
  /home/fz/anaconda3/envs/sage-backend/bin/pytest --cov=backend --cov-fail-under=80
```

Expected: 383 + 新增 pass, 覆盖率 ≥ 80%。

### 任务 2.12.2：测试 legacy 路径

```bash
cd /home/fz/project/sage/backend && \
  API_MODE=legacy /home/fz/anaconda3/envs/sage-backend/bin/pytest --no-cov
```

Expected: 全过（旧路径仍工作）。

### 任务 2.12.3：测试 hex 路径

```bash
cd /home/fz/project/sage/backend && \
  API_MODE=hex /home/fz/anaconda3/envs/sage-backend/bin/pytest --no-cov
```

Expected: 全过。

### 任务 2.12.4：CI 同步

更新 `.github/workflows/ci.yml` 跑两次（hex + legacy）。

### 任务 2.12.5：commit

```bash
cd /home/fz/project/sage
git add .github/workflows/ci.yml
git commit -m "ci: 双轨测试 hex + legacy 路径"
```

---

## PG2.13 — 双轨 + API_MODE 切换

### 任务 2.13.1：旧路径移入 core/legacy/

```bash
mkdir -p /home/fz/project/sage/backend/core/legacy
git mv backend/core/agent.py backend/core/legacy/agent.py
git mv backend/core/agent_state.py backend/core/legacy/agent_state.py
git mv backend/core/orchestrator.py backend/core/legacy/orchestrator.py
git mv backend/core/llm_client.py backend/core/legacy/llm_client.py
# 保留 errors.py、exceptions.py、conventions.py（仍在用）
```

**更新所有 import：**

```bash
# 在 backend/ 内全局搜索替换
grep -rl "from backend.core.agent" backend/ --include="*.py" | xargs sed -i 's|backend.core.agent|backend.core.legacy.agent|g'
# ... 类似其他
```

### 任务 2.13.2：测试 import 替换正确

```bash
cd /home/fz/project/sage/backend && \
  /home/fz/anaconda3/envs/sage-backend/bin/pytest --no-cov
```

Expected: 383 + 新增 pass（API_MODE=hex）。

### 任务 2.13.3：验证 legacy 仍可用

```bash
cd /home/fz/project/sage/backend && \
  API_MODE=legacy /home/fz/anaconda3/envs/sage-backend/bin/pytest --no-cov
```

Expected: 全过。

### 任务 2.13.4：commit

```bash
cd /home/fz/project/sage
git add backend/core
git commit -m "refactor(backend): 旧 core/ 路径迁入 legacy/

- core/legacy/{agent,agent_state,orchestrator,llm_client}.py
- 全部 import 路径更新
- core/ 仍保留 errors / exceptions / conventions
- API_MODE=legacy 仍可工作（一键回滚）"
```

---

## PG2.14 — 文档更新

### 任务 2.14.1：写 18-hexagonal.md

**Files:** Create `docs/technical/18-hexagonal.md`

包含：
- 架构图
- domain / ports / application / adapters / api 五层职责
- 6 个 Protocol 接口
- 双轨策略
- import-linter 约束
- 切换与回滚

### 任务 2.14.2：重写 02-architecture.md

**Files:** Modify `docs/technical/02-architecture.md`

把整体架构描述改为六边形视角。

### 任务 2.14.3：更新 05/06/07 agent/tools/skills

**Files:** Modify `docs/technical/05-agent.md`、`06-tools.md`、`07-skills.md`

更新模块引用路径（从 `core/agent.py` 改为 `domain/agent.py` + `application/services/chat_service.py`）。

### 任务 2.14.4：更新 README.md

**Files:** Modify `docs/technical/README.md`

把 18-hexagonal.md 加入章节目录。

### 任务 2.14.5：commit

```bash
cd /home/fz/project/sage
git add docs/technical/
git commit -m "docs(technical): 18-hexagonal.md + 02-architecture 重写 + 05/06/07 引用更新"
```

---

## 自审（Self-Review）

### Spec 覆盖

| Spec 节 | 对应 PG | 状态 |
|---------|--------|------|
| § 5.1 domain/ 抽离 | PG2.1 | ✅ |
| § 5.2 ports/ 接口 | PG2.2 | ✅ |
| § 5.3 adapters | PG2.3-PG2.8 | ✅ |
| § 5.4 application/services | PG2.9 | ✅ |
| § 5.5 api/ 改写 | PG2.10 | ✅ |
| § 5.6 import-linter | PG2.11 | ✅ |
| § 5.7 文档 | PG2.14 | ✅ |
| § 7.2 回滚策略（双轨） | PG2.13 | ✅ |

### 类型/接口一致性

- `LLMPort` 在 spec / ports/llm.py / ChatService / httpx adapter 四处签名一致
- `MetricPort` 三方法（counter/histogram/gauge）在 spec / ports / adapters 一致
- 双轨策略一致：API_MODE 在 routes.py dispatch + CI 测试两处

### 范围检查

- 14 任务组完整
- 双轨保护降低回滚风险
- 每步可独立 commit + 测试

**无缺口，可执行。**

---

## 实施步骤追踪

### P2 阶段
- [ ] PG2.1: domain/ 抽离（5 文件）
- [ ] PG2.2: ports/ 接口（6 Protocol）
- [ ] PG2.3: httpx LLM adapter
- [ ] PG2.4: mock LLM adapter
- [ ] PG2.5: storage adapters (sqlite + memory)
- [ ] PG2.6: tool inproc adapter
- [ ] PG2.7: metric adapters (骨架)
- [ ] PG2.8: event adapters (骨架)
- [ ] PG2.9: ChatService
- [ ] PG2.10: 重写 api/routes.py 为双轨
- [ ] PG2.11: import-linter 5 层依赖图
- [ ] PG2.12: 端到端回归（hex + legacy）
- [ ] PG2.13: 旧 core/ 移入 legacy/
- [ ] PG2.14: 文档更新（18-hexagonal + 02 重写）

**总计：14 任务组**
