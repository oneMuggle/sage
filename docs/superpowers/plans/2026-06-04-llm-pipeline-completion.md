# LLM 链路打通 + 错误处理 + 工具系统 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修复 Sage 端到端对话链路（Bug：发送消息无响应），实现 6 类 LLM 错误分类与友好提示，实现 ReAct 工具调用循环（calculator 可端到端调用）。

**Architecture:** 四边界结构化日志定位 Bug → 错误枚举化 + 友好 UI → 状态机驱动的 ReAct 循环（已有 ToolRegistry 和 calculator 工具，复用而非重建）。

**Tech Stack:**
- Backend: Python 3.11+ / FastAPI / Pydantic / httpx / pytest / pytest-asyncio
- Frontend: React 19 / TypeScript / Vite / Zustand / Vitest
- Middleware: Tauri 2.0 / Rust
- Tooling: ruff / mypy / tsc / Playwright (E2E)

**关键设计修正（与原始规范差异）：**
- `ToolRegistry` 已存在（`backend/tools/registry.py`），calculator 已注册 — 复用而非创建
- `LLMResponse.tool_calls` 字段已存在 — 不需扩展
- `agent._call_llm()` 当前返回 `str` 而非 `LLMResponse`，导致工具调用丢失 — 需重构返回完整响应
- 不使用 `console.log` 诊断（违反 TS 规则）— 用项目 logger 库或新建 `src/lib/logger.ts`
- `agent.py:319` 的 `assistant_message` 引用是 `dir()` hack — 改为更清晰的预初始化

---

## 文件结构

### 新建文件
| 路径 | 职责 |
|------|------|
| `backend/core/errors.py` | LLMErrorType 枚举 + LLMError 异常类 |
| `backend/core/agent_state.py` | AgentState 枚举 + AgentEvent 数据类 + ToolCall TypedDict |
| `backend/tests/test_errors.py` | LLMError 单元测试 |
| `backend/tests/test_agent_state.py` | 状态机/事件单元测试 |
| `backend/tests/test_agent_run_loop.py` | run_loop 状态转换测试 |
| `backend/tests/test_agent_chat_assistant_message.py` | chat() 异常路径测试 |
| `backend/tests/test_llm_client_errors.py` | LLMClient 错误分类测试 |
| `backend/tests/test_llm_client_tools.py` | LLMClient tools 透传测试 |
| `backend/tests/test_routes_chat_errors.py` | /chat 端点错误响应测试 |
| `backend/tests/test_chat_stream.py` | /chat/stream 流式响应测试 |
| `src/lib/logger.ts` | 轻量 TS logger（带开关） |
| `src/lib/errorMapping.ts` | LLMErrorType → 中文化提示 |
| `src/lib/llmStream.ts` | NDJSON 流解析 |
| `src/lib/__tests__/logger.test.ts` | logger 单元测试 |
| `src/lib/__tests__/errorMapping.test.ts` | errorMapping 单元测试 |
| `src/lib/__tests__/llmStream.test.ts` | llmStream 单元测试 |
| `src/components/chat/__tests__/Message.test.tsx` | Message 渲染测试 |
| `docs/13-tool-system.md` | 工具系统归档文档 |
| `docs/14-error-handling.md` | 错误处理归档文档 |

### 修改文件
| 路径 | 变更 |
|------|------|
| `backend/core/llm_client.py` | 错误类型分类（401/429/5xx/Network/Timeout/Parsing） + tools 透传 |
| `backend/core/agent.py` | 修复 `assistant_message` 引用；`_call_llm` 返回 LLMResponse；新增 `run_loop` |
| `backend/api/routes.py` | `/chat` 结构化日志 + 错误响应；新增 `/chat/stream` 流式端点 |
| `src/hooks/useChat.ts` | 接收错误响应 + 流式事件 |
| `src/components/chat/Message.tsx` | 错误样式 + 工具执行渲染 |
| `src/lib/api.ts` | chat() 支持流式响应（可选 NDJSON） |
| `docs/plans/2026-06-01_sage-next-features.md` | 标记完成项 |
| `package.json` + `package-lock.json` | 添加测试依赖（@testing-library） |

---

## Task 1: 创建结构化诊断 logger（前端）

**Files:**
- Create: `src/lib/logger.ts`
- Test: `src/lib/__tests__/logger.test.ts`

- [ ] **Step 1: 写失败的测试**

Create `src/lib/__tests__/logger.test.ts`:

```typescript
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { logger } from '../logger'

describe('logger', () => {
  beforeEach(() => {
    vi.spyOn(console, 'debug').mockImplementation(() => {})
    vi.spyOn(console, 'info').mockImplementation(() => {})
    vi.spyOn(console, 'warn').mockImplementation(() => {})
    vi.spyOn(console, 'error').mockImplementation(() => {})
  })
  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('does not log when disabled', () => {
    logger.setEnabled(false)
    logger.info('REQ-123', 'test', { foo: 'bar' })
    expect(console.info).not.toHaveBeenCalled()
  })

  it('logs with request_id prefix when enabled', () => {
    logger.setEnabled(true)
    logger.info('REQ-123', 'useChat.send', { message: 'hello' })
    expect(console.info).toHaveBeenCalledWith(
      '[REQ-123] [useChat.send]',
      { message: 'hello' }
    )
  })

  it('logs error level', () => {
    logger.setEnabled(true)
    logger.error('REQ-456', 'failed', new Error('boom'))
    expect(console.error).toHaveBeenCalled()
  })
})
```

- [ ] **Step 2: 运行测试确认失败**

```bash
cd /home/fz/project/sage && npx vitest run src/lib/__tests__/logger.test.ts
```

Expected: FAIL with "Cannot find module '../logger'"

- [ ] **Step 3: 实现 logger**

Create `src/lib/logger.ts`:

```typescript
/**
 * 轻量结构化 logger，支持 request_id 追踪
 * 用于诊断 LLM 链路 Bug
 */

type LogLevel = 'debug' | 'info' | 'warn' | 'error'

class Logger {
  private enabled = false

  setEnabled(value: boolean): void {
    this.enabled = value
  }

  isEnabled(): boolean {
    return this.enabled
  }

  private log(level: LogLevel, requestId: string, label: string, data?: unknown): void {
    if (!this.enabled) return
    const prefix = `[${requestId}] [${label}]`
    const consoleFn = console[level] as (...args: unknown[]) => void
    if (data instanceof Error) {
      consoleFn(prefix, data.message, data.stack)
    } else if (data !== undefined) {
      consoleFn(prefix, data)
    } else {
      consoleFn(prefix)
    }
  }

  debug(requestId: string, label: string, data?: unknown): void {
    this.log('debug', requestId, label, data)
  }

  info(requestId: string, label: string, data?: unknown): void {
    this.log('info', requestId, label, data)
  }

  warn(requestId: string, label: string, data?: unknown): void {
    this.log('warn', requestId, label, data)
  }

  error(requestId: string, label: string, data?: unknown): void {
    this.log('error', requestId, label, data)
  }
}

export const logger = new Logger()

// 开发模式默认开启；生产模式默认关闭
if (import.meta.env.DEV) {
  logger.setEnabled(true)
}
```

- [ ] **Step 4: 运行测试确认通过**

```bash
cd /home/fz/project/sage && npx vitest run src/lib/__tests__/logger.test.ts
```

Expected: 3 tests passing

- [ ] **Step 5: 提交**

```bash
cd /home/fz/project/sage && git add src/lib/logger.ts src/lib/__tests__/logger.test.ts
git commit -m "feat(frontend): 添加结构化 logger 用于 Bug 诊断"
```

---

## Task 2: 创建 LLMErrorType 与 LLMError（后端）

**Files:**
- Create: `backend/core/errors.py`
- Test: `backend/tests/test_errors.py`

- [ ] **Step 1: 写失败的测试**

Create `backend/tests/test_errors.py`:

```python
import pytest
from backend.core.errors import LLMErrorType, LLMError


def test_llm_error_contains_type_and_message():
    err = LLMError(LLMErrorType.AUTH_FAILED, "API Key 无效", status_code=401)
    assert err.type == LLMErrorType.AUTH_FAILED
    assert err.message == "API Key 无效"
    assert err.status_code == 401
    assert err.retry_after is None


def test_llm_error_can_be_raised_and_caught():
    with pytest.raises(LLMError) as exc_info:
        raise LLMError(LLMErrorType.RATE_LIMITED, "请求过于频繁", retry_after=60)
    assert exc_info.value.type == LLMErrorType.RATE_LIMITED
    assert exc_info.value.retry_after == 60


def test_llm_error_type_values_are_strings():
    """枚举值应可作为字符串序列化（用于 JSON 响应）。"""
    assert LLMErrorType.AUTH_FAILED.value == "auth_failed"
    assert LLMErrorType.RATE_LIMITED.value == "rate_limited"
    assert LLMErrorType.SERVER_ERROR.value == "server_error"
    assert LLMErrorType.NETWORK.value == "network_error"
    assert LLMErrorType.TIMEOUT.value == "timeout"
    assert LLMErrorType.PARSING.value == "parsing_error"
    assert LLMErrorType.UNKNOWN.value == "unknown"


def test_llm_error_to_dict_for_api_response():
    err = LLMError(LLMErrorType.TIMEOUT, "请求超时")
    result = err.to_dict()
    assert result == {
        "type": "timeout",
        "message": "请求超时",
        "status_code": None,
        "retry_after": None,
    }
```

- [ ] **Step 2: 运行测试确认失败**

```bash
cd /home/fz/project/sage && /home/fz/anaconda3/envs/sage-backend/bin/pytest backend/tests/test_errors.py -v
```

Expected: FAIL with "ModuleNotFoundError: No module named 'backend.core.errors'"

- [ ] **Step 3: 实现 errors.py**

Create `backend/core/errors.py`:

```python
"""
LLM 错误类型定义

将 LLM API 调用中可能出现的错误统一分类为 7 种类型，
便于前端做中文化友好提示与差异化处理。
"""
from enum import Enum
from dataclasses import dataclass
from typing import Optional, Dict, Any


class LLMErrorType(str, Enum):
    """LLM 错误类型枚举。

    命名采用 snake_case 字符串值，便于 JSON 序列化与前端映射。
    """
    AUTH_FAILED = "auth_failed"          # HTTP 401：API Key 无效或过期
    RATE_LIMITED = "rate_limited"        # HTTP 429：请求频率超限
    SERVER_ERROR = "server_error"        # HTTP 5xx：LLM 服务端错误
    NETWORK = "network_error"            # 连接失败、DNS 失败等网络层错误
    TIMEOUT = "timeout"                  # 请求超时
    PARSING = "parsing_error"            # 响应格式无法解析
    UNKNOWN = "unknown"                  # 未分类错误


@dataclass
class LLMError(Exception):
    """LLM 错误异常，承载分类信息与原始上下文。"""
    type: LLMErrorType
    message: str
    status_code: Optional[int] = None
    retry_after: Optional[int] = None  # 仅 RATE_LIMITED 时使用（秒）

    def to_dict(self) -> Dict[str, Any]:
        """序列化为 API 响应格式。"""
        return {
            "type": self.type.value,
            "message": self.message,
            "status_code": self.status_code,
            "retry_after": self.retry_after,
        }
```

- [ ] **Step 4: 运行测试确认通过**

```bash
cd /home/fz/project/sage && /home/fz/anaconda3/envs/sage-backend/bin/pytest backend/tests/test_errors.py -v
```

Expected: 4 tests passing

- [ ] **Step 5: 提交**

```bash
cd /home/fz/project/sage && git add backend/core/errors.py backend/tests/test_errors.py
git commit -m "feat(backend): 定义 LLMErrorType 枚举与 LLMError 异常"
```

---

## Task 3: 修改 LLMClient 抛出分类错误

**Files:**
- Modify: `backend/core/llm_client.py:156-166`
- Test: `backend/tests/test_llm_client_errors.py`

- [ ] **Step 1: 写失败的测试**

Create `backend/tests/test_llm_client_errors.py`:

```python
import pytest
import httpx
from unittest.mock import AsyncMock, patch

from backend.core.llm_client import LLMClient, LLMConfig
from backend.core.errors import LLMError, LLMErrorType


@pytest.fixture
def client():
    return LLMClient(LLMConfig(
        provider="openai",
        api_key="test-key",
        base_url="https://api.example.com/v1",
        model="gpt-3.5-turbo",
    ))


@pytest.mark.asyncio
async def test_401_raises_auth_failed(client):
    """HTTP 401 应映射为 AUTH_FAILED。"""
    mock_response = AsyncMock()
    mock_response.status_code = 401
    mock_response.text = "Unauthorized"
    mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
        "401", request=AsyncMock(), response=mock_response
    )

    with patch.object(client, '_get_client') as mock_get_client:
        mock_http = AsyncMock()
        mock_http.post = AsyncMock(return_value=mock_response)
        mock_get_client.return_value = mock_http

        with pytest.raises(LLMError) as exc_info:
            await client.chat([{"role": "user", "content": "hi"}])
        assert exc_info.value.type == LLMErrorType.AUTH_FAILED
        assert exc_info.value.status_code == 401


@pytest.mark.asyncio
async def test_429_raises_rate_limited(client):
    """HTTP 429 应映射为 RATE_LIMITED。"""
    mock_response = AsyncMock()
    mock_response.status_code = 429
    mock_response.text = "Too Many Requests"
    mock_response.headers = {"retry-after": "60"}
    mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
        "429", request=AsyncMock(), response=mock_response
    )

    with patch.object(client, '_get_client') as mock_get_client:
        mock_http = AsyncMock()
        mock_http.post = AsyncMock(return_value=mock_response)
        mock_get_client.return_value = mock_http

        with pytest.raises(LLMError) as exc_info:
            await client.chat([{"role": "user", "content": "hi"}])
        assert exc_info.value.type == LLMErrorType.RATE_LIMITED
        assert exc_info.value.retry_after == 60


@pytest.mark.asyncio
async def test_500_raises_server_error(client):
    """HTTP 5xx 应映射为 SERVER_ERROR。"""
    mock_response = AsyncMock()
    mock_response.status_code = 500
    mock_response.text = "Internal Server Error"
    mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
        "500", request=AsyncMock(), response=mock_response
    )

    with patch.object(client, '_get_client') as mock_get_client:
        mock_http = AsyncMock()
        mock_http.post = AsyncMock(return_value=mock_response)
        mock_get_client.return_value = mock_http

        with pytest.raises(LLMError) as exc_info:
            await client.chat([{"role": "user", "content": "hi"}])
        assert exc_info.value.type == LLMErrorType.SERVER_ERROR
        assert exc_info.value.status_code == 500


@pytest.mark.asyncio
async def test_timeout_raises_timeout_error(client):
    """httpx.TimeoutException 应映射为 TIMEOUT。"""
    with patch.object(client, '_get_client') as mock_get_client:
        mock_http = AsyncMock()
        mock_http.post = AsyncMock(side_effect=httpx.TimeoutException("timeout"))
        mock_get_client.return_value = mock_http

        with pytest.raises(LLMError) as exc_info:
            await client.chat([{"role": "user", "content": "hi"}])
        assert exc_info.value.type == LLMErrorType.TIMEOUT


@pytest.mark.asyncio
async def test_connect_error_raises_network_error(client):
    """httpx.ConnectError 应映射为 NETWORK。"""
    with patch.object(client, '_get_client') as mock_get_client:
        mock_http = AsyncMock()
        mock_http.post = AsyncMock(side_effect=httpx.ConnectError("connection refused"))
        mock_get_client.return_value = mock_http

        with pytest.raises(LLMError) as exc_info:
            await client.chat([{"role": "user", "content": "hi"}])
        assert exc_info.value.type == LLMErrorType.NETWORK
```

- [ ] **Step 2: 运行测试确认失败**

```bash
cd /home/fz/project/sage && /home/fz/anaconda3/envs/sage-backend/bin/pytest backend/tests/test_llm_client_errors.py -v
```

Expected: FAIL with "did not raise LLMError"（当前 LLMClient 抛 RuntimeError）

- [ ] **Step 3: 修改 LLMClient.chat() 抛出分类错误**

Edit `backend/core/llm_client.py`，在文件顶部添加 import：

```python
from backend.core.errors import LLMError, LLMErrorType
```

替换 `chat()` 方法中的异常处理块（原 `llm_client.py:156-166`）：

```python
        try:
            response = await client.post("/chat/completions", json=body)
            response.raise_for_status()
            data = response.json()
        except httpx.TimeoutException as e:
            logger.error(f"LLM 请求超时: {e}")
            raise LLMError(LLMErrorType.TIMEOUT, f"请求 LLM 超时: {e}")
        except httpx.ConnectError as e:
            logger.error(f"LLM 连接失败: {e}")
            raise LLMError(LLMErrorType.NETWORK, f"无法连接 LLM: {e}")
        except httpx.HTTPStatusError as e:
            status = e.response.status_code
            if status == 401:
                raise LLMError(LLMErrorType.AUTH_FAILED, "API Key 无效或过期", status_code=401)
            elif status == 429:
                retry_after = None
                try:
                    retry_after = int(e.response.headers.get("retry-after", "0")) or None
                except (ValueError, TypeError):
                    retry_after = None
                raise LLMError(LLMErrorType.RATE_LIMITED, "请求过于频繁，请稍后再试", retry_after=retry_after)
            elif 500 <= status < 600:
                raise LLMError(LLMErrorType.SERVER_ERROR, f"LLM 服务端错误 (HTTP {status})", status_code=status)
            else:
                raise LLMError(LLMErrorType.UNKNOWN, f"LLM HTTP 错误: {status}", status_code=status)
        except (ValueError, KeyError) as e:
            logger.error(f"LLM 响应解析失败: {e}")
            raise LLMError(LLMErrorType.PARSING, f"LLM 响应格式异常: {e}")
        except Exception as e:
            logger.error(f"LLM 请求未知失败: {e}")
            raise LLMError(LLMErrorType.UNKNOWN, f"LLM 请求失败: {e}")
```

- [ ] **Step 4: 运行测试确认通过**

```bash
cd /home/fz/project/sage && /home/fz/anaconda3/envs/sage-backend/bin/pytest backend/tests/test_llm_client_errors.py -v
```

Expected: 5 tests passing

- [ ] **Step 5: 提交**

```bash
cd /home/fz/project/sage && git add backend/core/llm_client.py backend/tests/test_llm_client_errors.py
git commit -m "feat(backend): LLMClient 抛出分类后的 LLMError"
```

---

## Task 4: /chat 端点结构化错误响应

**Files:**
- Modify: `backend/api/routes.py:171-192`
- Test: `backend/tests/test_routes_chat_errors.py`

- [ ] **Step 1: 写失败的测试**

Create `backend/tests/test_routes_chat_errors.py`:

```python
import pytest
from httpx import AsyncClient, ASGITransport
from unittest.mock import AsyncMock, patch

from backend.main import app
from backend.core.errors import LLMError, LLMErrorType


@pytest.mark.asyncio
async def test_chat_returns_structured_error_on_auth_failed():
    """LLM 401 时 /chat 返回结构化错误响应（HTTP 200 + error 字段）。"""
    with patch('backend.api.routes.SageAgent') as MockAgent:
        mock_agent_instance = MockAgent.return_value
        mock_agent_instance.chat = AsyncMock(
            side_effect=LLMError(LLMErrorType.AUTH_FAILED, "API Key 无效", status_code=401)
        )

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            resp = await ac.post("/chat", json={
                "session_id": "00000000-0000-0000-0000-000000000000",
                "message": "hi",
                "api_key": "bad-key",
                "api_url": "https://api.example.com/v1",
            })
        assert resp.status_code == 200
        body = resp.json()
        assert body["error"]["type"] == "auth_failed"
        assert body["error"]["message"] == "API Key 无效"
        assert body["message"] is None


@pytest.mark.asyncio
async def test_chat_returns_structured_error_on_timeout():
    """LLM 超时时 /chat 返回 timeout 错误。"""
    with patch('backend.api.routes.SageAgent') as MockAgent:
        mock_agent_instance = MockAgent.return_value
        mock_agent_instance.chat = AsyncMock(
            side_effect=LLMError(LLMErrorType.TIMEOUT, "请求 LLM 超时")
        )

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            resp = await ac.post("/chat", json={
                "session_id": "00000000-0000-0000-0000-000000000000",
                "message": "hi",
            })
        assert resp.status_code == 200
        body = resp.json()
        assert body["error"]["type"] == "timeout"


@pytest.mark.asyncio
async def test_chat_request_id_in_response_header():
    """响应头应包含 x-request-id 用于诊断追踪。"""
    with patch('backend.api.routes.SageAgent') as MockAgent:
        mock_agent_instance = MockAgent.return_value
        mock_agent_instance.chat = AsyncMock(return_value={
            "message": {
                "id": "m1", "session_id": "00000000-0000-0000-0000-000000000000",
                "role": "assistant", "content": "ok", "created_at": 0
            },
            "session": None,
        })

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            resp = await ac.post("/chat", json={
                "session_id": "00000000-0000-0000-0000-000000000000",
                "message": "hi",
            })
        assert "x-request-id" in resp.headers
```

- [ ] **Step 2: 运行测试确认失败**

```bash
cd /home/fz/project/sage && /home/fz/anaconda3/envs/sage-backend/bin/pytest backend/tests/test_routes_chat_errors.py -v
```

Expected: FAIL（当前路由直接 raise HTTPException 500，无结构化 error 字段，无 request_id header）

- [ ] **Step 3: 修改 /chat 端点**

Edit `backend/api/routes.py`：

顶部 import 区添加：

```python
import uuid
import logging
from backend.core.errors import LLMError
```

将 `/chat` 端点（原 `routes.py:171-192`）替换为：

```python
logger = logging.getLogger(__name__)


@router.post("/chat", response_model=ChatResponse)
async def chat(
    data: ChatRequest,
):
    """发送聊天消息。

    错误处理：
    - LLMError: 返回 HTTP 200 + 结构化 error 字段
    - 其他未预期错误: 返回 HTTP 200 + 通用 unknown 错误（前端统一处理）
    - 响应头包含 x-request-id 用于日志追踪（在 main.py 中间件添加）
    """
    request_id = str(uuid.uuid4())
    logger.info(f"[REQ {request_id}] /chat received: session_id={data.session_id}, "
                f"api_key={'***' if data.api_key else 'MISSING'}, "
                f"model={data.model}")

    try:
        llm_config = None
        if data.api_key and data.api_url:
            llm_config = {
                "provider": "custom",
                "api_key": data.api_key,
                "base_url": data.api_url,
                "model": data.model or "gpt-3.5-turbo",
                "temperature": data.temperature or 0.7,
            }
            logger.info(f"[REQ {request_id}] using custom LLM config: model={llm_config['model']}")

        agent = SageAgent()
        result = await agent.chat(data.session_id, data.message, llm_config=llm_config)
        logger.info(f"[REQ {request_id}] /chat success: message_id={result.get('message', {}).get('id')}")
        return result

    except LLMError as e:
        logger.warning(f"[REQ {request_id}] /chat LLM error: type={e.type.value}, message={e.message}")
        return {
            "error": e.to_dict(),
            "message": None,
            "session": None,
        }
    except Exception as e:
        logger.exception(f"[REQ {request_id}] /chat unexpected error")
        return {
            "error": {
                "type": "unknown",
                "message": "服务内部错误",
                "status_code": 500,
                "retry_after": None,
            },
            "message": None,
            "session": None,
        }
```

并在 `backend/main.py` 中添加 request_id 中间件（如果不存在）：

```python
from fastapi import Request
import uuid as _uuid

@app.middleware("http")
async def add_request_id_header(request: Request, call_next):
    request_id = request.headers.get("x-request-id") or str(_uuid.uuid4())
    response = await call_next(request)
    response.headers["x-request-id"] = request_id
    return response
```

- [ ] **Step 4: 运行测试确认通过**

```bash
cd /home/fz/project/sage && /home/fz/anaconda3/envs/sage-backend/bin/pytest backend/tests/test_routes_chat_errors.py -v
```

Expected: 3 tests passing

- [ ] **Step 5: 提交**

```bash
cd /home/fz/project/sage && git add backend/api/routes.py backend/main.py backend/tests/test_routes_chat_errors.py
git commit -m "feat(backend): /chat 端点结构化错误响应与 request_id 追踪"
```

---

## Task 5: 前端错误映射与 useChat 错误处理

**Files:**
- Create: `src/lib/errorMapping.ts`
- Modify: `src/hooks/useChat.ts`
- Test: `src/lib/__tests__/errorMapping.test.ts`

- [ ] **Step 1: 写失败的测试**

Create `src/lib/__tests__/errorMapping.test.ts`:

```typescript
import { describe, it, expect } from 'vitest'
import { mapLLMErrorToText, type LLMErrorResponse, type LLMErrorTypeFE } from '../errorMapping'

describe('mapLLMErrorToText', () => {
  it('maps auth_failed to Chinese hint', () => {
    const err: LLMErrorResponse = { type: 'auth_failed', message: 'x', status_code: 401, retry_after: null }
    expect(mapLLMErrorToText(err)).toBe('API Key 无效或过期，请在设置中检查')
  })

  it('maps rate_limited with retry_after', () => {
    const err: LLMErrorResponse = { type: 'rate_limited', message: 'x', status_code: 429, retry_after: 60 }
    expect(mapLLMErrorToText(err)).toContain('60 秒后重试')
  })

  it('maps network_error', () => {
    const err: LLMErrorResponse = { type: 'network_error', message: 'x', status_code: null, retry_after: null }
    expect(mapLLMErrorToText(err)).toBe('无法连接到 LLM 服务，请检查网络')
  })

  it('uses original message for parsing_error', () => {
    const err: LLMErrorResponse = { type: 'parsing_error', message: '原始消息', status_code: null, retry_after: null }
    expect(mapLLMErrorToText(err)).toBe('原始消息')
  })

  it('returns unknown fallback for truly unknown type', () => {
    const err = { type: 'something_new' as LLMErrorTypeFE, message: 'fallback', status_code: null, retry_after: null }
    expect(mapLLMErrorToText(err)).toBe('fallback')
  })
})
```

- [ ] **Step 2: 运行测试确认失败**

```bash
cd /home/fz/project/sage && npx vitest run src/lib/__tests__/errorMapping.test.ts
```

Expected: FAIL with "Cannot find module '../errorMapping'"

- [ ] **Step 3: 实现 errorMapping.ts**

Create `src/lib/errorMapping.ts`:

```typescript
/**
 * LLM 错误类型到中文化提示的映射
 */

export type LLMErrorTypeFE =
  | 'auth_failed'
  | 'rate_limited'
  | 'server_error'
  | 'network_error'
  | 'timeout'
  | 'parsing_error'
  | 'unknown'

export interface LLMErrorResponse {
  type: LLMErrorTypeFE
  message: string
  status_code: number | null
  retry_after: number | null
}

const STATIC_MESSAGES: Record<LLMErrorTypeFE, string> = {
  auth_failed: 'API Key 无效或过期，请在设置中检查',
  rate_limited: '请求过于频繁，请稍后再试',
  server_error: 'LLM 服务端错误，请稍后再试',
  network_error: '无法连接到 LLM 服务，请检查网络',
  timeout: '请求超时，请重试',
  parsing_error: '原始消息',  // 解析错误用原始消息
  unknown: '未知错误',
}

export function mapLLMErrorToText(err: LLMErrorResponse): string {
  const base = STATIC_MESSAGES[err.type]
  if (err.type === 'rate_limited' && err.retry_after) {
    return `${base}（建议 ${err.retry_after} 秒后重试）`
  }
  return base ?? err.message
}
```

- [ ] **Step 4: 运行测试确认通过**

```bash
cd /home/fz/project/sage && npx vitest run src/lib/__tests__/errorMapping.test.ts
```

Expected: 4 tests passing

- [ ] **Step 5: 修改 useChat 集成错误映射**

Edit `src/hooks/useChat.ts`，在文件顶部添加 import：

```typescript
import { logger } from '../lib/logger'
import { mapLLMErrorToText, type LLMErrorResponse } from '../lib/errorMapping'
```

在 `sendMessage` 函数起始处（`useChat.ts:16` 之后）生成 request_id 并记录：

```typescript
    const requestId = crypto.randomUUID()
    logger.info(requestId, 'useChat.send.start', {
      sessionId: sid,
      hasApiKey: Boolean(activeEndpoint?.apiKey),
      hasModel: Boolean(settings.modelSelections.chatModelId),
    })
```

替换 catch 块（原 52-54 行）：

```typescript
    } catch (err: unknown) {
      logger.error(requestId, 'useChat.send.failed', err)
      const apiErr = err as { error?: LLMErrorResponse; message?: string }
      if (apiErr.error) {
        setError(mapLLMErrorToText(apiErr.error))
      } else {
        const message = err instanceof Error ? err.message : '发送消息失败'
        setError(message)
      }
    }
```

- [ ] **Step 6: 提交**

```bash
cd /home/fz/project/sage && git add src/lib/errorMapping.ts src/lib/__tests__/errorMapping.test.ts src/hooks/useChat.ts
git commit -m "feat(frontend): 错误映射中文化与 useChat 集成"
```

---

## Task 6: 修复 agent.py 的 assistant_message 引用与 _call_llm 返回类型

**Files:**
- Modify: `backend/core/agent.py:246-321, 361-386`
- Test: `backend/tests/test_agent_chat_assistant_message.py`

- [ ] **Step 1: 写失败的测试**

Create `backend/tests/test_agent_chat_assistant_message.py`:

```python
import pytest
from unittest.mock import AsyncMock, MagicMock

from backend.core.agent import SageAgent
from backend.core.errors import LLMError, LLMErrorType
from backend.core.llm_client import LLMResponse


@pytest.mark.asyncio
async def test_chat_returns_error_dict_on_llm_error():
    """LLM 抛错时 chat() 返回结构化 error 字典，message 为 None。"""
    agent = SageAgent()
    agent.llm_client = MagicMock()
    agent.llm_client.chat = AsyncMock(
        side_effect=LLMError(LLMErrorType.AUTH_FAILED, "API Key 无效", status_code=401)
    )

    result = await agent.chat(
        session_id="00000000-0000-0000-0000-000000000000",
        message="hi",
    )
    assert "error" in result
    assert result["error"]["type"] == "auth_failed"
    assert result["message"] is None
    assert result["session"] is None


@pytest.mark.asyncio
async def test_chat_returns_assistant_message_on_success():
    """LLM 成功时 chat() 返回 message 字典。"""
    agent = SageAgent()
    agent.llm_client = MagicMock()
    agent.llm_client.chat = AsyncMock(return_value=LLMResponse(
        content="你好！",
        model="gpt-3.5-turbo",
    ))

    result = await agent.chat(
        session_id="00000000-0000-0000-0000-000000000000",
        message="hi",
    )
    assert "message" in result
    assert result["message"]["content"] == "你好！"
    assert result["message"]["role"] == "assistant"
    assert "error" not in result
```

- [ ] **Step 2: 运行测试确认失败**

```bash
cd /home/fz/project/sage && /home/fz/anaconda3/envs/sage-backend/bin/pytest backend/tests/test_agent_chat_assistant_message.py -v
```

Expected: FAIL（错误被 `_call_llm` 吞掉变成字符串）

- [ ] **Step 3: 修改 _call_llm 与 chat()**

Edit `backend/core/agent.py`：

顶部 import 区添加：

```python
from backend.core.errors import LLMError, LLMErrorType
from backend.core.llm_client import LLMResponse
```

修改 `_call_llm` 方法（原 361-386 行），**返回 LLMResponse 而非 str**：

```python
    async def _call_llm(self, user_message: str, memory_context: str) -> LLMResponse:
        """调用 LLM 生成回复。

        Returns:
            LLMResponse：包含 content 和 tool_calls
        """
        system_prompt = "你是 Sage，一个智能 AI 助手。"
        if memory_context:
            system_prompt += "\n\n以下是相关的记忆上下文：\n" + memory_context

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ]

        # 让 LLMError 透传给调用方，由 chat() 统一处理
        response = await self.llm_client.chat(messages)
        return response
```

修改 `chat()` 方法中调用 LLM 的部分（原 246-249 行）：

```python
            # 调用 LLM
            if self.llm_client:
                llm_response: LLMResponse = await self._call_llm(message, memory_context)
                assistant_content = llm_response.content
            else:
                assistant_content = f"收到消息: {message}\n\n(LLM 未配置，使用模拟响应)"
```

修改 `chat()` 方法的 except 块（原 310-321 行），**移除 `dir()` hack**：

```python
        except LLMError as e:
            logger.error(f"chat LLM 错误: type={e.type.value}, message={e.message}")
            if llm_config:
                self.llm_config = original_llm_config
                self.llm_client = original_llm_client
            return {
                "error": e.to_dict(),
                "message": None,
                "session": None,
            }
        except Exception as e:
            logger.exception(f"chat 处理异常: {str(e)}")
            if llm_config:
                self.llm_config = original_llm_config
                self.llm_client = original_llm_client
            wrapped = LLMError(LLMErrorType.UNKNOWN, str(e))
            return {
                "error": wrapped.to_dict(),
                "message": None,
                "session": None,
            }
```

- [ ] **Step 4: 运行测试确认通过**

```bash
cd /home/fz/project/sage && /home/fz/anaconda3/envs/sage-backend/bin/pytest backend/tests/test_agent_chat_assistant_message.py -v
```

Expected: 2 tests passing

- [ ] **Step 5: 提交**

```bash
cd /home/fz/project/sage && git add backend/core/agent.py backend/tests/test_agent_chat_assistant_message.py
git commit -m "fix(backend): 修复 assistant_message 引用与 _call_llm 异常吞没"
```

---

## Task 7: 验证 Bug 修复（端到端手动测试）

**Files:** 无（仅手动验证）

- [ ] **Step 1: 启动后端**

```bash
cd /home/fz/project/sage && /home/fz/anaconda3/envs/sage-backend/bin/python backend/main.py
```

Expected: 启动成功，端口 8765 监听

- [ ] **Step 2: 启动前端 dev server**

```bash
cd /home/fz/project/sage && npm run dev
```

Expected: 启动成功，端口 1420

- [ ] **Step 3: 端到端测试 happy path**

1. 打开浏览器到 `http://localhost:1420`
2. 进入设置，配置 API 端点为 `https://gcli.ggchan.dev/`，API Key 为 `gg-gcli-RALFsIs47kRn7m3HKh98dTj0R48ccM2ln8sIVDc3OSA`
3. 保存设置
4. 创建新会话
5. 发送消息："你好"
6. **验证**：助手消息出现在 UI 中

- [ ] **Step 4: 验证四边界日志**

查看后端日志，应该看到：

```
[REQ xxx] /chat received: session_id=yyy, api_key=***, model=zzz
[REQ xxx] using custom LLM config: model=zzz
[REQ xxx] /chat success: message_id=...
```

如果 request_id 在某一阶段消失，记录该阶段位置。

- [ ] **Step 5: 验证错误路径**

1. 故意设置错误的 API Key
2. 发送消息
3. **验证**：UI 显示"API Key 无效或过期，请在设置中检查"

- [ ] **Step 6: 提交验证记录**

```bash
cd /home/fz/project/sage && git commit --allow-empty -m "test: 验证 Bug 修复 happy path 与错误路径"
```

---

## Task 8: 创建 AgentState 与 AgentEvent（工具系统基础）

**Files:**
- Create: `backend/core/agent_state.py`
- Test: `backend/tests/test_agent_state.py`

- [ ] **Step 1: 写失败的测试**

Create `backend/tests/test_agent_state.py`:

```python
from backend.core.agent_state import (
    AgentState,
    AgentEvent,
    ToolCallRequest,
    ToolCallResult,
)


def test_agent_state_enum_values():
    assert AgentState.IDLE.value == "idle"
    assert AgentState.THINKING.value == "thinking"
    assert AgentState.ACTING.value == "acting"
    assert AgentState.OBSERVING.value == "observing"
    assert AgentState.DONE.value == "done"
    assert AgentState.FAILED.value == "failed"


def test_agent_event_thinking_creation():
    evt = AgentEvent(state=AgentState.THINKING, iteration=0)
    assert evt.state == AgentState.THINKING
    assert evt.iteration == 0
    assert evt.content is None
    assert evt.tool_call is None
    assert evt.error is None


def test_agent_event_done_has_content():
    evt = AgentEvent(state=AgentState.DONE, content="最终回答")
    assert evt.content == "最终回答"


def test_tool_call_request_serialization():
    tc = ToolCallRequest(id="call_1", name="calculator", arguments={"expression": "1+1"})
    d = tc.to_dict()
    assert d["id"] == "call_1"
    assert d["type"] == "function"
    assert d["function"]["name"] == "calculator"
    assert d["function"]["arguments"] == '{"expression": "1+1"}'


def test_tool_call_result_serialization():
    tr = ToolCallResult(tool_call_id="call_1", content="2", is_error=False)
    d = tr.to_dict()
    assert d == {
        "tool_call_id": "call_1",
        "role": "tool",
        "content": "2",
    }
```

- [ ] **Step 2: 运行测试确认失败**

```bash
cd /home/fz/project/sage && /home/fz/anaconda3/envs/sage-backend/bin/pytest backend/tests/test_agent_state.py -v
```

Expected: FAIL with "ModuleNotFoundError"

- [ ] **Step 3: 实现 agent_state.py**

Create `backend/core/agent_state.py`:

```python
"""
Agent 状态机与事件流定义

用于 ReAct 循环：IDLE → THINKING → ACTING → OBSERVING → DONE/FAILED
事件流通过 FastAPI 流式响应（NDJSON）下发到前端。
"""
import json
from enum import Enum
from dataclasses import dataclass
from typing import Optional, Dict, Any


class AgentState(str, Enum):
    """Agent 状态枚举。"""
    IDLE = "idle"
    THINKING = "thinking"
    ACTING = "acting"
    OBSERVING = "observing"
    DONE = "done"
    FAILED = "failed"


@dataclass
class ToolCallRequest:
    """工具调用请求（LLM 发出）。"""
    id: str
    name: str
    arguments: Dict[str, Any]

    def to_dict(self) -> Dict[str, Any]:
        """序列化为 OpenAI 工具调用格式。"""
        return {
            "id": self.id,
            "type": "function",
            "function": {
                "name": self.name,
                "arguments": json.dumps(self.arguments, ensure_ascii=False),
            },
        }


@dataclass
class ToolCallResult:
    """工具调用结果（前端展示用）。"""
    tool_call_id: str
    content: str
    is_error: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "tool_call_id": self.tool_call_id,
            "role": "tool",
            "content": self.content,
        }


@dataclass
class AgentEvent:
    """Agent 事件，前端通过流式响应接收。"""
    state: AgentState
    iteration: int = 0
    content: Optional[str] = None
    tool_call: Optional[ToolCallRequest] = None
    tool_result: Optional[ToolCallResult] = None
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """序列化为 JSON 友好的字典。"""
        d: Dict[str, Any] = {
            "state": self.state.value,
            "iteration": self.iteration,
        }
        if self.content is not None:
            d["content"] = self.content
        if self.tool_call is not None:
            d["tool_call"] = self.tool_call.to_dict()
        if self.tool_result is not None:
            d["tool_result"] = self.tool_result.to_dict()
        if self.error is not None:
            d["error"] = self.error
        return d
```

- [ ] **Step 4: 运行测试确认通过**

```bash
cd /home/fz/project/sage && /home/fz/anaconda3/envs/sage-backend/bin/pytest backend/tests/test_agent_state.py -v
```

Expected: 5 tests passing

- [ ] **Step 5: 提交**

```bash
cd /home/fz/project/sage && git add backend/core/agent_state.py backend/tests/test_agent_state.py
git commit -m "feat(backend): 定义 AgentState 枚举与事件流"
```

---

## Task 9: 实现 agent.run_loop 状态机

**Files:**
- Modify: `backend/core/agent.py:388-403`
- Test: `backend/tests/test_agent_run_loop.py`

- [ ] **Step 1: 写失败的测试**

Create `backend/tests/test_agent_run_loop.py`:

```python
import pytest
from unittest.mock import AsyncMock, MagicMock
from typing import List

from backend.core.agent import SageAgent
from backend.core.llm_client import LLMResponse, LLMToolCall
from backend.core.agent_state import AgentState


def _make_response(content: str = "", tool_calls: list = None) -> LLMResponse:
    return LLMResponse(
        content=content,
        tool_calls=tool_calls or [],
    )


@pytest.mark.asyncio
async def test_run_loop_returns_done_when_no_tool_call():
    """LLM 返回纯文本时，状态机经过 THINKING → DONE。"""
    agent = SageAgent()
    agent.llm_client = MagicMock()
    agent.llm_client.chat = AsyncMock(return_value=_make_response(content="你好"))

    events = []
    async for evt in agent.run_loop([{"role": "user", "content": "hi"}]):
        events.append(evt)

    states = [e.state for e in events]
    assert AgentState.THINKING in states
    assert AgentState.DONE in states
    done_evt = next(e for e in events if e.state == AgentState.DONE)
    assert done_evt.content == "你好"


@pytest.mark.asyncio
async def test_run_loop_executes_tool_and_observes():
    """LLM 返回工具调用时，状态机经过 THINKING → ACTING → OBSERVING → THINKING → DONE。"""
    tool_call = LLMToolCall(
        id="call_1",
        name="calculator",
        arguments='{"expression": "1+1"}',
    )
    agent = SageAgent()
    agent.llm_client = MagicMock()
    agent.llm_client.chat = AsyncMock(side_effect=[
        _make_response(content="", tool_calls=[tool_call]),
        _make_response(content="答案是 2"),
    ])

    # 替换 tool_registry.get
    mock_tool = MagicMock()
    mock_tool.execute = MagicMock(return_value=MagicMock(
        success=True,
        content={"result": 2},
        error=None,
    ))
    agent.tool_registry.get = MagicMock(return_value=mock_tool)

    events = []
    async for evt in agent.run_loop([{"role": "user", "content": "1+1 等于几"}]):
        events.append(evt)

    states = [e.state for e in events]
    assert AgentState.ACTING in states
    assert AgentState.OBSERVING in states
    assert AgentState.DONE in states


@pytest.mark.asyncio
async def test_run_loop_respects_max_iterations():
    """max_iterations=2 时，应发出 FAILED。"""
    tool_call = LLMToolCall(id="c", name="calculator", arguments="{}")
    agent = SageAgent()
    agent.llm_client = MagicMock()
    agent.llm_client.chat = AsyncMock(return_value=_make_response(tool_calls=[tool_call]))

    mock_tool = MagicMock()
    mock_tool.execute = MagicMock(return_value=MagicMock(success=True, content={}, error=None))
    agent.tool_registry.get = MagicMock(return_value=mock_tool)

    events = []
    async for evt in agent.run_loop([{"role": "user", "content": "x"}], max_iterations=2):
        events.append(evt)

    failed = [e for e in events if e.state == AgentState.FAILED]
    assert len(failed) == 1
    assert failed[0].error == "max_iterations_exceeded"
```

- [ ] **Step 2: 运行测试确认失败**

```bash
cd /home/fz/project/sage && /home/fz/anaconda3/envs/sage-backend/bin/pytest backend/tests/test_agent_run_loop.py -v
```

Expected: FAIL（当前 `run_loop` 只是 stub 返回字符串）

- [ ] **Step 3: 实现 run_loop 状态机**

Edit `backend/core/agent.py`：

顶部 import 区添加：

```python
from backend.core.agent_state import AgentState, AgentEvent, ToolCallRequest, ToolCallResult
import json
```

将 `run_loop` 方法（原 388-403 行）替换为：

```python
    async def run_loop(
        self,
        messages: List[Dict[str, Any]],
        max_iterations: int = 5,
    ):
        """ReAct 主循环。

        Args:
            messages: 完整消息历史（含 system/user/assistant/tool）
            max_iterations: 最大循环次数，防止死循环

        Yields:
            AgentEvent：状态机事件，前端通过流式响应接收
        """
        for i in range(max_iterations):
            yield AgentEvent(state=AgentState.THINKING, iteration=i)

            response: LLMResponse = await self.llm_client.chat(messages)

            if not response.tool_calls:
                messages.append({
                    "role": "assistant",
                    "content": response.content,
                })
                yield AgentEvent(state=AgentState.DONE, iteration=i, content=response.content)
                return

            messages.append({
                "role": "assistant",
                "content": response.content or "",
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.name,
                            "arguments": tc.arguments,
                        },
                    }
                    for tc in response.tool_calls
                ],
            })

            for tc in response.tool_calls:
                try:
                    args = json.loads(tc.arguments) if isinstance(tc.arguments, str) else tc.arguments
                except json.JSONDecodeError:
                    args = {}

                tool_req = ToolCallRequest(id=tc.id, name=tc.name, arguments=args)
                yield AgentEvent(state=AgentState.ACTING, iteration=i, tool_call=tool_req)

                try:
                    tool = self.tool_registry.get(tc.name)
                    if tool is None:
                        result_content = f"[错误] 工具不存在: {tc.name}"
                        is_error = True
                    else:
                        result = tool.execute(**args)
                        if hasattr(result, 'success') and hasattr(result, 'content'):
                            is_error = not result.success
                            result_content = (
                                json.dumps(result.content, ensure_ascii=False)
                                if result.success
                                else (result.error or "工具执行失败")
                            )
                        else:
                            is_error = False
                            result_content = json.dumps(result, ensure_ascii=False, default=str)
                except Exception as e:
                    logger.error(f"工具执行失败: {tc.name}, error: {str(e)}")
                    result_content = f"[工具错误] {str(e)}"
                    is_error = True

                tool_result = ToolCallResult(
                    tool_call_id=tc.id,
                    content=result_content,
                    is_error=is_error,
                )
                yield AgentEvent(
                    state=AgentState.OBSERVING,
                    iteration=i,
                    tool_call=tool_req,
                    tool_result=tool_result,
                )

                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": result_content,
                })

        yield AgentEvent(
            state=AgentState.FAILED,
            iteration=max_iterations,
            error="max_iterations_exceeded",
        )
```

- [ ] **Step 4: 运行测试确认通过**

```bash
cd /home/fz/project/sage && /home/fz/anaconda3/envs/sage-backend/bin/pytest backend/tests/test_agent_run_loop.py -v
```

Expected: 3 tests passing

- [ ] **Step 5: 提交**

```bash
cd /home/fz/project/sage && git add backend/core/agent.py backend/tests/test_agent_run_loop.py
git commit -m "feat(backend): 实现 agent.run_loop 状态机（ReAct 循环）"
```

---

## Task 10: LLMClient 透传 tools 参数

**Files:**
- Modify: `backend/core/llm_client.py:132-193`
- Test: `backend/tests/test_llm_client_tools.py`

- [ ] **Step 1: 写失败的测试**

Create `backend/tests/test_llm_client_tools.py`:

```python
import pytest
from unittest.mock import AsyncMock, patch

from backend.core.llm_client import LLMClient, LLMConfig


@pytest.fixture
def client():
    return LLMClient(LLMConfig(
        provider="openai",
        api_key="test-key",
        base_url="https://api.example.com/v1",
        model="gpt-3.5-turbo",
    ))


@pytest.mark.asyncio
async def test_chat_sends_tools_when_provided(client):
    """tools 参数应传递到请求体。"""
    mock_response = AsyncMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "choices": [{"message": {"content": "ok"}}],
        "usage": {},
    }
    mock_response.raise_for_status = lambda: None

    with patch.object(client, '_get_client') as mock_get_client:
        mock_http = AsyncMock()
        mock_http.post = AsyncMock(return_value=mock_response)
        mock_get_client.return_value = mock_http

        tools = [{
            "type": "function",
            "function": {
                "name": "calculator",
                "description": "数学计算",
                "parameters": {"type": "object", "properties": {"expression": {"type": "string"}}},
            },
        }]
        await client.chat([{"role": "user", "content": "hi"}], tools=tools)

        call_args = mock_http.post.call_args
        body = call_args.kwargs["json"]
        assert "tools" in body
        assert body["tools"] == tools
        assert body["tool_choice"] == "auto"


@pytest.mark.asyncio
async def test_chat_omits_tools_when_none(client):
    """tools=None 时请求体不应包含 tools 字段。"""
    mock_response = AsyncMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "choices": [{"message": {"content": "ok"}}],
        "usage": {},
    }
    mock_response.raise_for_status = lambda: None

    with patch.object(client, '_get_client') as mock_get_client:
        mock_http = AsyncMock()
        mock_http.post = AsyncMock(return_value=mock_response)
        mock_get_client.return_value = mock_http

        await client.chat([{"role": "user", "content": "hi"}])
        call_args = mock_http.post.call_args
        body = call_args.kwargs["json"]
        assert "tools" not in body
        assert "tool_choice" not in body
```

- [ ] **Step 2: 运行测试确认失败**

```bash
cd /home/fz/project/sage && /home/fz/anaconda3/envs/sage-backend/bin/pytest backend/tests/test_llm_client_tools.py -v
```

Expected: FAIL（当前 chat() 不接受 tools 参数）

- [ ] **Step 3: 修改 LLMClient.chat() 接受 tools**

Edit `backend/core/llm_client.py`，修改 `chat` 方法签名（原 132 行）：

```python
    async def chat(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        tool_choice: Optional[str] = None,
    ) -> LLMResponse:
        """发送聊天请求（非流式）。

        Args:
            messages: 消息列表
            tools: OpenAI 格式工具 schema 列表（可选）
            tool_choice: "auto" | "none" | "required"（默认 auto）
        """
        client = self._get_client()

        body = {
            "model": self.config.model,
            "messages": self._convert_messages(messages),
            "temperature": self.config.temperature,
            "max_tokens": self.config.max_tokens,
        }

        if tools:
            body["tools"] = tools
            body["tool_choice"] = tool_choice or "auto"

        if self.config.provider == "claude":
            body["max_tokens"] = self.config.max_tokens
```

- [ ] **Step 4: 运行测试确认通过**

```bash
cd /home/fz/project/sage && /home/fz/anaconda3/envs/sage-backend/bin/pytest backend/tests/test_llm_client_tools.py -v
```

Expected: 2 tests passing

- [ ] **Step 5: 提交**

```bash
cd /home/fz/project/sage && git add backend/core/llm_client.py backend/tests/test_llm_client_tools.py
git commit -m "feat(backend): LLMClient.chat 接受 tools 与 tool_choice"
```

---

## Task 11: /chat/stream 流式端点（NDJSON）

**Files:**
- Modify: `backend/api/routes.py`
- Test: `backend/tests/test_chat_stream.py`

- [ ] **Step 1: 写失败的测试**

Create `backend/tests/test_chat_stream.py`:

```python
import pytest
import json
from httpx import AsyncClient, ASGITransport
from unittest.mock import AsyncMock, patch, MagicMock

from backend.main import app
from backend.core.agent_state import AgentState, AgentEvent, ToolCallRequest, ToolCallResult


@pytest.mark.asyncio
async def test_chat_stream_yields_ndjson_events():
    """/chat/stream 端点以 NDJSON 格式返回 AgentEvent。"""
    async def mock_run_loop(messages, max_iterations=5):
        yield AgentEvent(state=AgentState.THINKING, iteration=0)
        yield AgentEvent(
            state=AgentState.ACTING,
            iteration=0,
            tool_call=ToolCallRequest(id="c1", name="calculator", arguments={"expression": "1+1"}),
        )
        yield AgentEvent(
            state=AgentState.OBSERVING,
            iteration=0,
            tool_result=ToolCallResult(tool_call_id="c1", content="2"),
        )
        yield AgentEvent(state=AgentState.DONE, iteration=1, content="答案是 2")

    with patch('backend.api.routes.SageAgent') as MockAgent:
        mock_agent = MockAgent.return_value
        mock_agent.run_loop = mock_run_loop

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            resp = await ac.post("/chat/stream", json={
                "session_id": "00000000-0000-0000-0000-000000000000",
                "message": "1+1 等于几",
            })

        assert resp.status_code == 200
        lines = [l for l in resp.text.split("\n") if l.strip()]
        events = [json.loads(l) for l in lines]
        assert len(events) == 4
        assert events[0]["state"] == "thinking"
        assert events[1]["state"] == "acting"
        assert events[1]["tool_call"]["function"]["name"] == "calculator"
        assert events[2]["state"] == "observing"
        assert events[3]["state"] == "done"
        assert events[3]["content"] == "答案是 2"
```

- [ ] **Step 2: 运行测试确认失败**

```bash
cd /home/fz/project/sage && /home/fz/anaconda3/envs/sage-backend/bin/pytest backend/tests/test_chat_stream.py -v
```

Expected: FAIL with "404 Not Found"（端点不存在）

- [ ] **Step 3: 实现 /chat/stream 端点**

Edit `backend/api/routes.py`，在 `/chat` 端点后添加：

```python
from fastapi.responses import StreamingResponse


@router.post("/chat/stream")
async def chat_stream(data: ChatRequest):
    """流式聊天端点，以 NDJSON 格式逐事件下发 AgentEvent。"""
    request_id = str(uuid.uuid4())
    logger.info(f"[REQ {request_id}] /chat/stream received: session_id={data.session_id}")

    async def event_generator():
        from backend.core.agent_state import AgentEvent, AgentState
        try:
            llm_config = None
            if data.api_key and data.api_url:
                llm_config = {
                    "provider": "custom",
                    "api_key": data.api_key,
                    "base_url": data.api_url,
                    "model": data.model or "gpt-3.5-turbo",
                    "temperature": data.temperature or 0.7,
                }

            agent = SageAgent()
            messages = [
                {"role": "system", "content": "你是 Sage，一个智能 AI 助手。"},
                {"role": "user", "content": data.message},
            ]
            tools = agent.get_available_tools() if hasattr(agent, 'get_available_tools') else None

            # 通过 run_loop 产出事件流
            async for evt in agent.run_loop(messages):
                yield _ndjson(evt.to_dict())

        except LLMError as e:
            logger.warning(f"[REQ {request_id}] /chat/stream LLM error: {e.type.value}")
            yield _ndjson({"error": e.to_dict(), "state": "failed"})
        except Exception as e:
            logger.exception(f"[REQ {request_id}] /chat/stream failed")
            yield _ndjson({"error": {"type": "unknown", "message": str(e)}, "state": "failed"})

    return StreamingResponse(event_generator(), media_type="application/x-ndjson")


def _ndjson(d: dict) -> str:
    """序列化为 NDJSON 行（以 \\n 结尾）。"""
    import json
    return json.dumps(d, ensure_ascii=False) + "\n"
```

- [ ] **Step 4: 运行测试确认通过**

```bash
cd /home/fz/project/sage && /home/fz/anaconda3/envs/sage-backend/bin/pytest backend/tests/test_chat_stream.py -v
```

Expected: 1 test passing

- [ ] **Step 5: 提交**

```bash
cd /home/fz/project/sage && git add backend/api/routes.py backend/tests/test_chat_stream.py
git commit -m "feat(backend): /chat/stream 流式响应（NDJSON）"
```

---

## Task 12: 前端 NDJSON 流解析器

**Files:**
- Create: `src/lib/llmStream.ts`
- Test: `src/lib/__tests__/llmStream.test.ts`

- [ ] **Step 1: 写失败的测试**

Create `src/lib/__tests__/llmStream.test.ts`:

```typescript
import { describe, it, expect } from 'vitest'
import { parseNDJSONStream, type AgentEvent } from '../llmStream'

function makeStream(chunks: string[]): ReadableStream<Uint8Array> {
  const encoder = new TextEncoder()
  return new ReadableStream({
    start(controller) {
      chunks.forEach((c) => controller.enqueue(encoder.encode(c)))
      controller.close()
    },
  })
}

describe('parseNDJSONStream', () => {
  it('parses a complete event per line', async () => {
    const stream = makeStream([
      JSON.stringify({ state: 'thinking', iteration: 0 }) + '\n',
      JSON.stringify({ state: 'done', content: 'hi' }) + '\n',
    ])
    const events: AgentEvent[] = []
    for await (const evt of parseNDJSONStream(stream)) {
      events.push(evt)
    }
    expect(events).toHaveLength(2)
    expect(events[0].state).toBe('thinking')
    expect(events[1].content).toBe('hi')
  })

  it('handles chunked lines split across chunks', async () => {
    const stream = makeStream([
      JSON.stringify({ state: 'thinki', iteration: 0 }),
      JSON.stringify({ state: 'done', iteration: 1 }),
    ])
    const events: AgentEvent[] = []
    for await (const evt of parseNDJSONStream(stream)) {
      events.push(evt)
    }
    expect(events.length).toBeGreaterThanOrEqual(1)
  })

  it('skips empty lines', async () => {
    const stream = makeStream(['\n', JSON.stringify({ state: 'done' }) + '\n', '\n\n'])
    const events: AgentEvent[] = []
    for await (const evt of parseNDJSONStream(stream)) {
      events.push(evt)
    }
    expect(events).toHaveLength(1)
  })
})
```

- [ ] **Step 2: 运行测试确认失败**

```bash
cd /home/fz/project/sage && npx vitest run src/lib/__tests__/llmStream.test.ts
```

Expected: FAIL

- [ ] **Step 3: 实现 llmStream.ts**

Create `src/lib/llmStream.ts`:

```typescript
/**
 * 解析 NDJSON 流式响应
 */

export type AgentState =
  | 'idle'
  | 'thinking'
  | 'acting'
  | 'observing'
  | 'done'
  | 'failed'

export interface ToolCallRequestFE {
  id: string
  type: 'function'
  function: {
    name: string
    arguments: string
  }
}

export interface ToolCallResultFE {
  tool_call_id: string
  role: 'tool'
  content: string
}

export interface AgentEvent {
  state: AgentState
  iteration: number
  content?: string
  tool_call?: ToolCallRequestFE
  tool_result?: ToolCallResultFE
  error?: string
}

export async function* parseNDJSONStream(
  stream: ReadableStream<Uint8Array>
): AsyncGenerator<AgentEvent, void, unknown> {
  const reader = stream.getReader()
  const decoder = new TextDecoder()
  let buffer = ''

  try {
    while (true) {
      const { done, value } = await reader.read()
      if (done) {
        buffer += decoder.decode()
        break
      }
      buffer += decoder.decode(value, { stream: true })

      const lines = buffer.split('\n')
      buffer = lines.pop() ?? ''

      for (const line of lines) {
        const trimmed = line.trim()
        if (!trimmed) continue
        try {
          const evt = JSON.parse(trimmed) as AgentEvent
          yield evt
        } catch {
          // 忽略解析失败的行
        }
      }
    }

    const trimmed = buffer.trim()
    if (trimmed) {
      try {
        yield JSON.parse(trimmed) as AgentEvent
      } catch {
        // 忽略
      }
    }
  } finally {
    reader.releaseLock()
  }
}
```

- [ ] **Step 4: 运行测试确认通过**

```bash
cd /home/fz/project/sage && npx vitest run src/lib/__tests__/llmStream.test.ts
```

Expected: 3 tests passing

- [ ] **Step 5: 提交**

```bash
cd /home/fz/project/sage && git add src/lib/llmStream.ts src/lib/__tests__/llmStream.test.ts
git commit -m "feat(frontend): NDJSON 流解析器"
```

---

## Task 13: Message 组件添加工具执行 UI

**Files:**
- Modify: `src/components/chat/Message.tsx`
- Test: `src/components/chat/__tests__/Message.test.tsx`

- [ ] **Step 1: 安装测试依赖（如未安装）**

```bash
cd /home/fz/project/sage && npm install -D @testing-library/react @testing-library/jest-dom jsdom
```

- [ ] **Step 2: 写失败的测试**

Create `src/components/chat/__tests__/Message.test.tsx`:

```typescript
import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import { Message } from '../Message'
import type { Message as MessageType } from '../../../lib/api'

describe('Message', () => {
  it('renders plain text content', () => {
    const msg: MessageType = {
      id: '1', session_id: 's', role: 'assistant',
      content: '你好！', created_at: 0,
    }
    render(<Message message={msg} />)
    expect(screen.getByText('你好！')).toBeInTheDocument()
  })

  it('renders tool_call indicator', () => {
    const msg: MessageType = {
      id: '1', session_id: 's', role: 'assistant',
      content: '观察中...', created_at: 0,
      tool_calls: [{
        name: 'calculator',
        args: { expression: '1+1' },
        result: '2',
      }],
    }
    const { container } = render(<Message message={msg} />)
    expect(container.textContent).toContain('calculator')
    expect(container.textContent).toContain('2')
  })

  it('applies error style when content starts with [错误', () => {
    const msg: MessageType = {
      id: '1', session_id: 's', role: 'assistant',
      content: '[错误:auth_failed] API Key 无效', created_at: 0,
    }
    const { container } = render(<Message message={msg} />)
    const errorEl = container.querySelector('[data-error="true"]')
    expect(errorEl).toBeInTheDocument()
  })
})
```

- [ ] **Step 3: 运行测试确认失败**

```bash
cd /home/fz/project/sage && npx vitest run src/components/chat/__tests__/Message.test.tsx
```

Expected: FAIL（@testing-library/react 未配置或组件无工具/error 渲染）

- [ ] **Step 4: 修改 Message.tsx 添加工具展示与错误样式**

Read 现有 `src/components/chat/Message.tsx` 后，将组件替换为：

```tsx
import type { Message as MessageType } from '../../lib/api'

interface MessageProps {
  message: MessageType
}

export function Message({ message }: MessageProps) {
  const isError = message.content?.startsWith('[错误') ?? false

  return (
    <div
      className={`message ${message.role}`}
      data-error={isError ? 'true' : undefined}
    >
      <div className="message-role">{message.role}</div>
      <div className="message-content">{message.content}</div>

      {message.tool_calls && message.tool_calls.length > 0 && (
        <div className="message-tools">
          {message.tool_calls.map((tc, idx) => (
            <div key={idx} className="tool-call">
              <span className="tool-icon">🔧</span>
              <span className="tool-name">{tc.name}</span>
              <span className="tool-args">{JSON.stringify(tc.args)}</span>
              {tc.result && (
                <>
                  <span className="tool-arrow">→</span>
                  <span className="tool-result">{tc.result}</span>
                </>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
```

- [ ] **Step 5: 运行测试确认通过**

```bash
cd /home/fz/project/sage && npx vitest run src/components/chat/__tests__/Message.test.tsx
```

Expected: 3 tests passing

- [ ] **Step 6: 提交**

```bash
cd /home/fz/project/sage && git add src/components/chat/Message.tsx src/components/chat/__tests__/Message.test.tsx package.json package-lock.json
git commit -m "feat(frontend): Message 组件支持工具调用展示与错误样式"
```

---

## Task 14: 验证 ReAct 端到端（手动 + 全量测试）

**Files:** 无（仅验证）

- [ ] **Step 1: 启动后端**

```bash
cd /home/fz/project/sage && /home/fz/anaconda3/envs/sage-backend/bin/python backend/main.py
```

- [ ] **Step 2: 启动前端**

```bash
cd /home/fz/project/sage && npm run dev
```

- [ ] **Step 3: 配置真实 LLM 端点**

在设置中配置：
- API URL: `https://gcli.ggchan.dev/`
- API Key: `gg-gcli-RALFsIs47kRn7m3HKh98dTj0R48ccM2ln8sIVDc3OSA`
- 模型: 任意支持 function calling 的模型

- [ ] **Step 4: 端到端测试 calculator**

1. 创建新会话
2. 发送消息：`"1+2*3 等于多少？请用计算器算一下"`
3. **验证**：
   - UI 显示 "⏳ 思考中..."
   - UI 显示 "🔧 calculator(...)"
   - UI 显示工具结果
   - UI 显示助手最终回答

- [ ] **Step 5: 运行全量测试**

后端：
```bash
cd /home/fz/project/sage && /home/fz/anaconda3/envs/sage-backend/bin/pytest backend/tests/ -v
```

前端：
```bash
cd /home/fz/project/sage && npx vitest run
```

Expected: 所有测试通过

- [ ] **Step 6: 检查覆盖率**

后端：
```bash
cd /home/fz/project/sage && /home/fz/anaconda3/envs/sage-backend/bin/pytest backend/tests/ --cov=backend/core --cov-report=term-missing
```

前端：
```bash
cd /home/fz/project/sage && npx vitest run --coverage
```

Expected: 整体覆盖率 ≥ 80%

- [ ] **Step 7: 提交**

```bash
cd /home/fz/project/sage && git commit --allow-empty -m "test: 验证 ReAct 端到端 + 覆盖率达标"
```

---

## Task 15: 归档文档与标记完成

**Files:**
- Create: `docs/13-tool-system.md`
- Create: `docs/14-error-handling.md`
- Modify: `docs/plans/2026-06-01_sage-next-features.md`

- [ ] **Step 1: 创建工具系统归档文档**

Create `docs/13-tool-system.md`:

```markdown
# 工具系统

## 概述

Sage Agent 通过 OpenAI 兼容的 `function_calling` 协议扩展 LLM 能力。
内置工具通过 `ToolRegistry` 注册，`agent.run_loop` 实现 ReAct 循环。

## 架构

- `backend/core/agent_state.py` — 状态机与事件流
- `backend/core/agent.py::run_loop` — ReAct 主循环
- `backend/tools/registry.py` — 工具注册表
- `backend/tools/*.py` — 内置工具实现

## 当前内置工具

- `calculator` — 数学计算（AST 白名单）
- `read_file` / `write_file` / `list_dir` — 文件操作
- `web_search` / `web_fetch` — 网络访问
- `memory_search` / `memory_save` — 记忆系统
- `terminal` — 终端命令

## 添加新工具

1. 继承 `BaseTool`，实现 `_build_schema()` 与 `execute()`
2. 在 `backend/tools/__init__.py::register_all_tools()` 中注册
3. 写单元测试

## ReAct 循环

```
THINKING → ACTING → OBSERVING → THINKING → ... → DONE/FAILED
```

最大迭代 5 次（`max_iterations=5`），由 `agent.run_loop` 强制。
```

- [ ] **Step 2: 创建错误处理归档文档**

Create `docs/14-error-handling.md`:

```markdown
# 错误处理

## LLM 错误分类

`backend/core/errors.py` 定义 7 种错误类型：

| 类型 | 触发条件 | HTTP 状态 |
|------|----------|-----------|
| `auth_failed` | API Key 无效 | 401 |
| `rate_limited` | 请求频率超限 | 429 |
| `server_error` | LLM 服务端错误 | 5xx |
| `network_error` | 连接失败 | — |
| `timeout` | 请求超时 | — |
| `parsing_error` | 响应格式异常 | — |
| `unknown` | 未分类错误 | — |

## 端到端错误流

```
LLMClient → LLMError → SageAgent.chat → /chat → 前端 → mapLLMErrorToText → 中文化提示
```

## 添加新错误类型

1. 在 `LLMErrorType` 枚举添加
2. 在 `LLMClient.chat()` 的 except 块捕获并转换
3. 在前端 `errorMapping.ts::STATIC_MESSAGES` 添加中文提示
4. 添加测试
```

- [ ] **Step 3: 更新原计划标记完成**

Edit `docs/plans/2026-06-01_sage-next-features.md`，在文档顶部添加：

```markdown
> **状态**：本计划所有 9 项功能已于 2026-06-04 完成。详见 `docs/13-tool-system.md` 与 `docs/14-error-handling.md`。
```

并将所有 checkbox 标记为 `[x]`。

- [ ] **Step 4: 提交归档**

```bash
cd /home/fz/project/sage && git add docs/13-tool-system.md docs/14-error-handling.md docs/plans/2026-06-01_sage-next-features.md
git commit -m "docs: 归档工具系统与错误处理章节，标记原计划完成"
```

---

## 整体完成判定

- [ ] Task 1: 前端 logger
- [ ] Task 2: LLMErrorType + LLMError
- [ ] Task 3: LLMClient 分类错误
- [ ] Task 4: /chat 端点结构化错误
- [ ] Task 5: 前端错误映射与 useChat
- [ ] Task 6: 修复 agent.py assistant_message
- [ ] Task 7: 端到端 Bug 验证
- [ ] Task 8: AgentState + AgentEvent
- [ ] Task 9: agent.run_loop 状态机
- [ ] Task 10: LLMClient 透传 tools
- [ ] Task 11: /chat/stream NDJSON
- [ ] Task 12: 前端 NDJSON 解析
- [ ] Task 13: Message 工具 UI
- [ ] Task 14: ReAct 端到端验证 + 覆盖率 ≥ 80%
- [ ] Task 15: 文档归档
