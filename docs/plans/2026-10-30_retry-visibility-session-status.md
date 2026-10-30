# 重试可见性与会话状态徽章 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 504 等可重试故障在聊天区与会话列表中都"看得见"，并把代理上游超时 504 变成可操作提示 + 有总时长上限的重试。

**Architecture:** 后端在 `LLMClient` 的重试循环里补三件事：(1) 非流式路径失败时也要补发已发生的重试事件；(2) 识别 Sage 代理的 `upstream_timeout` 504 并给出可操作文案；(3) 给自动重试加墙钟预算（默认 180s）。前端 `SessionItem` 从已有的流槽位 `retryInfo` 派生「重试中」徽章，并补上「数据库 running 但本地无流」的「后台运行中」徽章。全部为增量改动，不改协议字段。

**Tech Stack:** Python 3.10（backend，代码需保持 py3.8 兼容）、FastAPI、httpx、pytest；React + TypeScript + Zustand + Vitest；Electron。

**Spec:** 本次分析结论见 `docs/technical/101-llm-error-classification-retry.md`（错误分类与重试契约）；本计划是该分析的落地规格。计划完成后把新增行为并入该文档，并按仓库规则删除本计划文件。

## Global Constraints

- 后端共享文件必须保持 **Python 3.8 语法兼容**（不用 PEP 604 `X | Y` 注解/运行时 isinstance、不用 `list[...]` 泛型注解；沿用 `typing.List/Dict/Optional/Tuple`）。改动会 cherry-pick 到 `release/win7`。
- ruff：双引号字符串、提交前跑 `ruff check`；若新增元组 isinstance 需 `# noqa: UP038`。
- 前端 i18n：zh/en 两份语言包必须同时改；会话徽章 i18n key 放在 `workspaceAndTools.ts` 的 `session.status_*` 区块。
- 架构护栏 ratchet：`architecture-baseline.json` 只升不降；改动后跑 `node scripts/architecture-check.mjs` 并同步 `agent.py` / `llm_client.py` 条目。
- 不新增用户设置项（本计划刻意不引入新配置键，重试预算用常量 + 环境变量）。
- 所有后端测试用 `/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest`；前端测试用 `npx vitest run <file>`。

## 范围

**做：**
1. 非流式 `chat()` 重试事件在失败路径也补发（修复"重试了但完全不可见"）。
2. Sage 代理 `upstream_timeout` 504 → `TIMEOUT` 分类 + 可操作提示（调大「LLM 代理超时」）。
3. 自动重试墙钟预算 `SAGE_LLM_RETRY_TOTAL_BUDGET_S`（默认 180s，0=不限），两条重试循环都生效。
4. 会话列表「重试中」徽章（消费 `slots.streaming.retryInfo`）。
5. 会话列表「后台运行中」徽章（`run_status==='running'` 且本地无流）。
6. 技术文档并入 + 架构基线 bump。

**不做：**
- 不新增「已中断 / 已取消 / 排队中」状态（分析结论：收益低，留作后续）。
- 不改 LLM 代理层本身的重试策略。
- 不做流式续写（Resumable Streaming）。

---

### Task 1: 非流式重试事件在失败路径可见

**Files:**
- Modify: `backend/core/legacy/agent.py`（run_loop 非流式分支，约 1697-1719 行；导入行 36）
- Create: `backend/tests/unit/test_agent_retry_visibility.py`

**Interfaces:**
- Consumes: `LLMClient.chat(..., retry_callback=...)` 的 `RetryEvent`（字段 `attempt/max_attempts/error_type/error_message/delay`）
- Produces: `AgentEvent(state=AgentState.RETRY, retry_info={...})` 在失败前下发

- [ ] **Step 1: 写失败测试**

创建 `backend/tests/unit/test_agent_retry_visibility.py`：

```python
"""非流式路径重试事件可见性回归测试（2026-10-30）。

背景：agent.run_loop 的非流式分支把 retry 回调暂存在 pending_retries，
只有 chat() 正常返回后才补发；重试耗尽抛异常时补发代码不执行，
前端完全看不到"重试中"。本用例锁定"失败前也要补发"。
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.core.errors import LLMError, LLMErrorType
from backend.core.legacy.agent import SageAgent
from backend.core.legacy.agent_state import AgentState
from backend.core.legacy.llm_client import RetryEvent

pytestmark = pytest.mark.unit


@pytest.mark.asyncio()
async def test_non_stream_retry_events_emitted_before_failure():
    agent = SageAgent()
    # MagicMock 未声明的 stream_unsupported 为真值 → _should_stream 返回 False，
    # 强制走非流式 chat() 分支（与 test_agent_run_loop.py 既有做法一致）。
    agent.llm_client = MagicMock()
    retry_event = RetryEvent(
        attempt=1,
        max_attempts=3,
        error_type="server_error",
        error_message="LLM 服务端错误 (HTTP 504)",
        delay=2.0,
    )

    async def _chat(messages, tools=None, tool_choice=None, retry_callback=None):
        if retry_callback is not None:
            retry_callback(retry_event)
        raise LLMError(
            LLMErrorType.SERVER_ERROR, "LLM 服务端错误 (HTTP 504)", status_code=504
        )

    agent.llm_client.chat = AsyncMock(side_effect=_chat)

    events = []
    with pytest.raises(LLMError):
        async for evt in agent.run_loop(
            [{"role": "user", "content": "hi"}], max_iterations=1
        ):
            events.append(evt)

    retry_events = [e for e in events if e.state == AgentState.RETRY]
    assert len(retry_events) == 1
    info = retry_events[0].retry_info
    assert info["attempt"] == 1
    assert info["max_attempts"] == 3
    assert info["error_type"] == "server_error"
```

- [ ] **Step 2: 跑测试确认失败**

```bash
cd /home/fz/project/sage/.worktrees/feat-retry-visibility-session-status
/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/test_agent_retry_visibility.py -q
```
Expected: FAIL — `len(retry_events) == 0`（事件从未发出）。

- [ ] **Step 3: 实现修复**

在 `agent.py` 导入行（36 行）补 `RetryEvent`：

```python
from backend.core.legacy.llm_client import LLMClient, LLMConfig, LLMResponse, RetryEvent
```

在 `run_loop` 的 `while True:` 循环体里（`if response is None:` 之前）定义局部帮助函数：

```python
                def _retry_events(retry_events: List[RetryEvent]) -> List[AgentEvent]:
                    """把 LLMClient 的 RetryEvent 转成 AgentEvent(RETRY) 列表。"""
                    return [
                        AgentEvent(
                            state=AgentState.RETRY,
                            iteration=i,
                            retry_info={
                                "attempt": ev.attempt,
                                "max_attempts": ev.max_attempts,
                                "error_type": ev.error_type,
                                "error_message": ev.error_message,
                                "delay": ev.delay,
                            },
                            agent_id=self.agent_id,
                        )
                        for ev in retry_events
                    ]
```

把非流式分支改成（替换原 1697-1719 的 `pending_retries` 段）：

```python
                        if response is None:
                            # 非流式回退路径：chat() 是单次 await，回调里无法
                            # yield（会打断协程），因此先把重试事件暂存；无论
                            # 成功还是最终失败，都要在返回/抛出前补发——否则
                            # "重试耗尽后失败"的会话完全看不到重试发生过。
                            pending_retries: List[RetryEvent] = []
                            try:
                                response = await self.llm_client.chat(
                                    messages,
                                    tools=available_tools or None,
                                    retry_callback=pending_retries.append,
                                )
                            except LLMError:
                                for retry_evt in _retry_events(pending_retries):
                                    yield retry_evt
                                raise
                            for retry_evt in _retry_events(pending_retries):
                                yield retry_evt
                            # 如果 LLM 返回了 reasoning_content，yield REASONING 事件
                            if response.reasoning_content:
                                yield AgentEvent(
                                    state=AgentState.REASONING,
                                    iteration=i,
                                    reasoning=response.reasoning_content,
                                    agent_id=self.agent_id,
                                )
```

- [ ] **Step 4: 跑测试确认通过**

```bash
/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/test_agent_retry_visibility.py backend/tests/unit/test_chat_steer.py backend/tests/unit/test_agent_run_loop.py -q
```
Expected: 全部 PASS（既有用例不受影响）。

- [ ] **Step 5: 提交**

```bash
git add backend/core/legacy/agent.py backend/tests/unit/test_agent_retry_visibility.py
git commit -m "fix(agent): 非流式重试事件在失败路径也补发，修复重试不可见"
```

---

### Task 2: 代理 upstream_timeout 504 → TIMEOUT + 可操作提示

**Files:**
- Modify: `backend/core/legacy/llm_client.py`（`_raise_classified_error` 5xx 分支约 562-565 行；流式循环 `raise_for_status` 处约 1069-1072 行）
- Modify: `backend/tests/unit/test_llm_client_errors.py`
- Modify: `backend/tests/unit/test_llm_client_stream_errors.py`
- Modify: `backend/tests/unit/test_llm_retry.py`（`_sse_ctx` 补 `status_code = 200`）
- Modify: `backend/tests/unit/test_agent_retry_heartbeat.py`（同上）

**Interfaces:**
- Produces: `LLMError(LLMErrorType.TIMEOUT, "<含『LLM 代理超时』的可操作文案>", status_code=504)`；`RetryEvent.error_type == "timeout"`

- [ ] **Step 1: 写失败测试（非流式）**

在 `backend/tests/unit/test_llm_client_errors.py` 追加（沿用该文件已有 `_make_client` / `_http_status_error` 风格；若无 text 参数则扩展 helper 接受 `text=""`）：

```python
def test_proxy_upstream_timeout_504_classified_as_timeout():
    """Sage 代理的 upstream_timeout 504 → TIMEOUT + 可操作提示。"""
    response = MagicMock(
        status_code=504,
        headers={},
        text='{"detail":{"type":"upstream_timeout","message":"upstream timed out"}}',
    )
    err = httpx.HTTPStatusError("504", request=MagicMock(), response=response)
    client = _make_client()

    with pytest.raises(LLMError) as exc_info:
        client._raise_classified_error(err)

    assert exc_info.value.type == LLMErrorType.TIMEOUT
    assert "LLM 代理超时" in exc_info.value.message
    assert "设置" in exc_info.value.message  # 文案包含可操作提示（设置路径）
    assert exc_info.value.status_code == 504


def test_plain_504_remains_server_error():
    """普通 504（无 upstream_timeout 标记）仍归 SERVER_ERROR。"""
    err = httpx.HTTPStatusError(
        "504",
        request=MagicMock(),
        response=MagicMock(
            status_code=504, headers={}, text="<html>gateway timeout</html>"
        ),
    )
    client = _make_client()

    with pytest.raises(LLMError) as exc_info:
        client._raise_classified_error(err)

    assert exc_info.value.type == LLMErrorType.SERVER_ERROR
```

- [ ] **Step 2: 写失败测试（流式）**

在 `backend/tests/unit/test_llm_client_stream_errors.py` 追加：

```python
@pytest.mark.asyncio()
async def test_stream_proxy_upstream_timeout_classified_as_timeout(monkeypatch):
    """流式 504 代理超时：分类为 TIMEOUT，且错误体已预读。"""
    monkeypatch.setenv("SAGE_LLM_RETRY_MAX_ATTEMPTS", "1")
    monkeypatch.setenv("SAGE_LLM_RETRY_BASE_DELAY_S", "0")
    client = LLMClient(
        LLMConfig(provider="openai", api_key="k", base_url="https://x/v1", model="m")
    )
    response = AsyncMock()
    response.status_code = 504
    response.text = '{"detail":{"type":"upstream_timeout","message":"x"}}'
    response.headers = {}
    response.raise_for_status = Mock(
        side_effect=httpx.HTTPStatusError("504", request=AsyncMock(), response=response)
    )
    patcher = _patch_stream(client, response=response)
    try:
        with pytest.raises(LLMError) as exc_info:
            async for _kind, _payload in client.chat_stream_events(
                [{"role": "user", "content": "x"}]
            ):
                pass
    finally:
        patcher.stop()

    assert exc_info.value.type == LLMErrorType.TIMEOUT
    assert "LLM 代理超时" in exc_info.value.message
```

- [ ] **Step 3: 跑测试确认失败**

```bash
/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest \
  backend/tests/unit/test_llm_client_errors.py::test_proxy_upstream_timeout_504_classified_as_timeout \
  backend/tests/unit/test_llm_client_errors.py::test_plain_504_remains_server_error \
  backend/tests/unit/test_llm_client_stream_errors.py::test_stream_proxy_upstream_timeout_classified_as_timeout -q
```
Expected: FAIL（504 目前归 `SERVER_ERROR`，文案不含「代理超时」）。

- [ ] **Step 4: 实现分类**

`llm_client.py` 的 `_raise_classified_error`，把 5xx 分支改为：

```python
            if 500 <= status < 600:
                # Sage 自己的 LLM 代理在等待上游超时时回 504，并在 detail.type
                # 标注 upstream_timeout。识别它 → 给出可操作提示（代理超时可配）。
                body_text = ""
                try:
                    body_text = exc.response.text or ""
                except Exception:  # noqa: BLE001 — 流式/未读取响应体，按空处理
                    body_text = ""
                if status == 504 and "upstream_timeout" in body_text:
                    raise LLMError(
                        LLMErrorType.TIMEOUT,
                        "LLM 代理超时：上游长时间未返回任何数据。"
                        "可在「设置 → 基础 → LLM 代理超时」中调大超时时间，"
                        "或检查上游服务与网络。",
                        status_code=504,
                    )
                raise LLMError(
                    LLMErrorType.SERVER_ERROR, f"LLM 服务端错误 (HTTP {status})", status_code=status
                )
```

- [ ] **Step 5: 流式路径预读错误体**

`chat_stream_events` 的 `async with client.stream(...) as response:` 内，把：

```python
                    response.raise_for_status()
```

改为：

```python
                    if response.status_code >= 400:
                        # 预读错误体：代理的 upstream_timeout 标记在 body 里；
                        # 流式响应不预读则 .text 抛 ResponseNotRead，分类拿不到标记。
                        await response.aread()
                    response.raise_for_status()
```

- [ ] **Step 6: 修正测试替身的状态码**

`MagicMock` 作响应时 `response.status_code` 是 MagicMock，`>= 400` 会抛 TypeError。给以下两处 `_sse_ctx` 里的 response 补 `response.status_code = 200`：

- `backend/tests/unit/test_llm_retry.py` 的 `_sse_ctx`
- `backend/tests/unit/test_agent_retry_heartbeat.py` 的 `_sse_ctx`

然后全量跑相关测试，若有其它文件报同类 TypeError，同样补 `status_code = 200`：

```bash
/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest \
  backend/tests/unit/test_llm_client_errors.py backend/tests/unit/test_llm_client_stream_errors.py \
  backend/tests/unit/test_llm_retry.py backend/tests/unit/test_agent_retry_heartbeat.py \
  backend/tests/unit/test_llm_client_fallback.py backend/tests/unit/test_llm_client_remaining.py \
  backend/tests/unit/test_llm_stream_tool_calling.py backend/tests/unit/test_llm_context.py -q
```
Expected: 全部 PASS。

- [ ] **Step 7: 提交**

```bash
git add backend/core/legacy/llm_client.py backend/tests/unit/test_llm_client_errors.py \
  backend/tests/unit/test_llm_client_stream_errors.py backend/tests/unit/test_llm_retry.py \
  backend/tests/unit/test_agent_retry_heartbeat.py
git commit -m "feat(llm): 代理 upstream_timeout 504 归 TIMEOUT 并给出可操作提示"
```

---

### Task 3: 自动重试墙钟预算（默认 180s）

**Files:**
- Modify: `backend/core/legacy/llm_client.py`（常量区 ~30 行、`_retry_settings` ~72-126 行、`chat` 循环 ~727-783、`chat_stream_events` 循环 ~1060-1188）
- Modify: `backend/tests/unit/test_llm_retry.py`

**Interfaces:**
- Produces: `_retry_settings() -> Tuple[int, float, float, float]`（第 4 项为总预算秒数，0=不限）
- Produces: `_retry_now() -> float`（可被测试 monkeypatch 的单调时钟）

- [ ] **Step 1: 写失败测试**

在 `backend/tests/unit/test_llm_retry.py` 追加：

```python
@pytest.mark.asyncio()
async def test_retry_total_budget_stops_retries(monkeypatch):
    """退避累计超过总时长预算 → 停止重试并用最后一次错误类型抛出。"""
    monkeypatch.setenv("SAGE_LLM_RETRY_MAX_ATTEMPTS", "10")
    monkeypatch.setenv("SAGE_LLM_RETRY_BASE_DELAY_S", "60")
    monkeypatch.setenv("SAGE_LLM_RETRY_MAX_DELAY_S", "60")
    monkeypatch.setenv("SAGE_LLM_RETRY_TOTAL_BUDGET_S", "100")

    clock = {"t": 0.0}
    monkeypatch.setattr("backend.core.legacy.llm_client._retry_now", lambda: clock["t"])

    async def fake_sleep(delay: float) -> None:
        clock["t"] += delay

    monkeypatch.setattr("backend.core.legacy.llm_client.asyncio.sleep", fake_sleep)

    client = _make_client()
    mock_http = _wire_post(client, [_http_status_error(504)] * 10)

    with pytest.raises(LLMError) as exc_info:
        await client.chat([{"role": "user", "content": "hi"}])

    # 第 1 次失败后 0+60 <= 100 → 重试；第 2 次失败后 60+60 > 100 → 停止
    assert mock_http.post.await_count == 2
    assert exc_info.value.type == LLMErrorType.SERVER_ERROR
    assert "预算" in exc_info.value.message


@pytest.mark.asyncio()
async def test_retry_total_budget_disabled_when_zero(monkeypatch):
    """预算 0 = 不限，按 max_attempts 正常耗尽。"""
    monkeypatch.setenv("SAGE_LLM_RETRY_MAX_ATTEMPTS", "3")
    monkeypatch.setenv("SAGE_LLM_RETRY_BASE_DELAY_S", "0")
    monkeypatch.setenv("SAGE_LLM_RETRY_TOTAL_BUDGET_S", "0")
    client = _make_client()
    mock_http = _wire_post(client, [_http_status_error(500)] * 3)

    with pytest.raises(LLMError):
        await client.chat([{"role": "user", "content": "hi"}])

    assert mock_http.post.await_count == 3
```

- [ ] **Step 2: 跑测试确认失败**

```bash
/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest \
  backend/tests/unit/test_llm_retry.py::test_retry_total_budget_stops_retries \
  backend/tests/unit/test_llm_retry.py::test_retry_total_budget_disabled_when_zero -q
```
Expected: FAIL（`_retry_now` 不存在 / 无预算逻辑，10 次重试耗尽）。

- [ ] **Step 3: 实现常量、时钟与设置读取**

常量区（`_LLM_RETRY_MAX_DELAY_S = 15.0` 之后）加：

```python
#: 自动重试的总时长预算（秒）：从首次尝试起算，退避前的累计耗时超预算即停止。
#: 0 表示不限制；env ``SAGE_LLM_RETRY_TOTAL_BUDGET_S`` 覆盖（调试/测试用）。
_LLM_RETRY_TOTAL_BUDGET_S = 180.0
```

新增函数（放在 `_retry_backoff_seconds` 之前）：

```python
def _retry_now() -> float:
    """单调时钟（独立函数以便测试 monkeypatch 预算判定）。"""
    return time.monotonic()
```

`_retry_settings` 返回值改为 4 元组，并加 env 读取：

```python
    total_budget = _LLM_RETRY_TOTAL_BUDGET_S
    ...
    raw_budget = os.environ.get("SAGE_LLM_RETRY_TOTAL_BUDGET_S", "").strip()
    if raw_budget:
        try:
            value = float(raw_budget)
            if value >= 0:
                total_budget = value
        except ValueError:
            logger.warning("env SAGE_LLM_RETRY_TOTAL_BUDGET_S=%r 非法,回退默认", raw_budget)

    return max_attempts, base_delay, max_delay, total_budget
```

同步更新函数 docstring 的 Returns 说明。

- [ ] **Step 4: 两条重试循环接入预算**

`chat()`：

```python
        max_attempts, base_delay, max_delay, total_budget = _retry_settings()
        attempt = 0
        fallback_used = False
        retry_started = _retry_now()
```

在 `delay = _retry_backoff_seconds(...)` 之后、写日志/回调之前插入：

```python
                    if (
                        total_budget > 0
                        and (_retry_now() - retry_started) + delay > total_budget
                    ):
                        raise LLMError(
                            llm_err.type,
                            f"{llm_err.message}（自动重试累计超过 "
                            f"{total_budget:.0f}s 总时长预算，已停止）",
                            status_code=llm_err.status_code,
                            retry_after=llm_err.retry_after,
                        )
```

`chat_stream_events()` 同样改 4 元组解包，并在循环前加 `retry_started = _retry_now()`；在 `delay = _retry_backoff_seconds(...)` 之后、`yield ("retry", ...)` 与 heartbeat 退避之前插入同一段检查（文案一致）。

- [ ] **Step 5: 跑测试确认通过**

```bash
/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/test_llm_retry.py backend/tests/unit/test_agent_retry_heartbeat.py backend/tests/unit/test_llm_client_stream_errors.py -q
```
Expected: PASS。确认 `_retry_settings()` 的两个调用点都已改为 4 元组（`grep -n "_retry_settings()" backend/core/legacy/llm_client.py` 应只有两处且均解包 4 项）。

- [ ] **Step 6: 提交**

```bash
git add backend/core/legacy/llm_client.py backend/tests/unit/test_llm_retry.py
git commit -m "feat(llm): 自动重试增加 180s 墙钟预算，避免长超时被无限放大"
```

---

### Task 4: 会话列表「重试中」与「后台运行中」徽章

**Files:**
- Modify: `src/widgets/session/SessionItem.tsx`（派生逻辑 ~94 行；徽章区 ~274-292 行；lucide 导入 ~1-17 行）
- Modify: `src/shared/lib/i18n/locales/zh/workspaceAndTools.ts`（`session.status_*` 区块）
- Modify: `src/shared/lib/i18n/locales/en/workspaceAndTools.ts`
- Create: `src/widgets/session/__tests__/SessionItem.status-badges.test.tsx`

**Interfaces:**
- Consumes: `slots.streaming.retryInfo`（`RetryInfo`：`attempt/max_attempts/error_type/error_message/delay`）
- Produces: `data-testid="session-retrying"` / `data-testid="session-running-background"` 徽章；i18n key `session.status_retrying` / `session.status_running_background`

- [ ] **Step 1: 写失败测试**

创建 `src/widgets/session/__tests__/SessionItem.status-badges.test.tsx`：

```tsx
/** 会话状态徽章：重试中 / 后台运行中（2026-10-30）。 */
import { act, cleanup, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { useChatStreamStore } from '../../../features/send-message/chatStreamStore';
import { I18nProvider } from '../../../shared/lib/i18n';
import type { Session } from '../../../shared/lib/store';
import { SessionItem } from '../SessionItem';

const baseSession = (overrides: Partial<Session> = {}): Session => ({
  id: 's-1',
  title: '普通会话',
  created_at: 1_750_000_000_000,
  updated_at: 1_750_000_000_000,
  last_message_at: null,
  message_count: 0,
  is_pinned: false,
  ...overrides,
});

const renderWithI18n = (ui: React.ReactElement) =>
  render(<I18nProvider defaultLocale="zh">{ui}</I18nProvider>);

describe('SessionItem — 状态徽章', () => {
  beforeEach(() => {
    useChatStreamStore.setState({ sessions: {} } as never);
  });

  afterEach(() => {
    cleanup();
    useChatStreamStore.setState({ sessions: {} } as never);
  });

  it('shows the retrying badge when the live slot carries retryInfo', () => {
    act(() => {
      const store = useChatStreamStore.getState();
      store.startStream('s-1', 'm-1');
      store.setRetryInfo('s-1', 'm-1', {
        attempt: 2,
        max_attempts: 3,
        error_type: 'timeout',
        error_message: 'LLM 代理超时',
        delay: 4,
      });
    });

    renderWithI18n(
      <SessionItem session={baseSession()} isActive={false} onSelect={vi.fn()} onDelete={vi.fn()} />,
    );

    const badge = screen.getByTestId('session-retrying');
    expect(badge).toBeInTheDocument();
    expect(badge.getAttribute('title')).toContain('重试中（2/3）');
    expect(badge.getAttribute('title')).toContain('LLM 代理超时');
    // 重试中不再显示普通运行中图标
    expect(screen.queryByTestId('session-running')).toBeNull();
  });

  it('shows the normal running badge when there is no retryInfo', () => {
    act(() => {
      useChatStreamStore.getState().startStream('s-1', 'm-1');
    });

    renderWithI18n(
      <SessionItem session={baseSession()} isActive={false} onSelect={vi.fn()} onDelete={vi.fn()} />,
    );

    expect(screen.getByTestId('session-running')).toBeInTheDocument();
    expect(screen.queryByTestId('session-retrying')).toBeNull();
  });

  it('shows the background-running badge when db says running but no live slot', () => {
    renderWithI18n(
      <SessionItem
        session={baseSession({ run_status: 'running' })}
        isActive={false}
        onSelect={vi.fn()}
        onDelete={vi.fn()}
      />,
    );

    expect(screen.getByTestId('session-running-background')).toBeInTheDocument();
    expect(screen.queryByTestId('session-running')).toBeNull();
  });
});
```

- [ ] **Step 2: 跑测试确认失败**

```bash
cd /home/fz/project/sage/.worktrees/feat-retry-visibility-session-status
npx vitest run src/widgets/session/__tests__/SessionItem.status-badges.test.tsx
```
Expected: FAIL（`session-retrying` / `session-running-background` 不存在）。

- [ ] **Step 3: 实现 i18n**

`zh/workspaceAndTools.ts` 的 `session.status_*` 区块加：

```ts
  'session.status_retrying': '重试中（{attempt}/{max}）',
  'session.status_running_background': '运行中（后台）',
```

`en/workspaceAndTools.ts` 对应加：

```ts
  'session.status_retrying': 'Retrying ({attempt}/{max})',
  'session.status_running_background': 'Running in background',
```

- [ ] **Step 4: 实现 SessionItem 徽章**

导入 `RefreshCw`（lucide-react 列表按字母序插入）。

派生逻辑（`isLive` 附近）：

```tsx
  const retryInfo = slots.streaming?.retryInfo ?? null;
  const isRetrying = isLive && retryInfo !== null;
  const backendRunning = !isLive && dbStatus === 'running';
  const retryTitle = retryInfo
    ? `${t('session.status_retrying')
        .replace('{attempt}', String(retryInfo.attempt))
        .replace('{max}', String(retryInfo.max_attempts))}: ${retryInfo.error_message}`
    : '';
```

徽章区把原 `{isLive && (...running...)}` 改为：

```tsx
          {isRetrying && (
            <span
              data-testid="session-retrying"
              aria-label={retryTitle}
              title={retryTitle}
              className="inline-flex flex-shrink-0 text-warning"
            >
              <RefreshCw className="w-3 h-3 animate-spin" />
            </span>
          )}
          {isLive && !isRetrying && (
            <span
              data-testid="session-running"
              aria-label={t('session.status_running')}
              title={t('session.status_running')}
              className="inline-flex flex-shrink-0 text-primary"
            >
              <Loader2 className="w-3 h-3 animate-spin" />
            </span>
          )}
          {backendRunning && (
            <span
              data-testid="session-running-background"
              aria-label={t('session.status_running_background')}
              title={t('session.status_running_background')}
              className="inline-flex flex-shrink-0 text-muted"
            >
              <Loader2 className="w-3 h-3 animate-spin" />
            </span>
          )}
```

- [ ] **Step 5: 跑测试确认通过**

```bash
npx vitest run src/widgets/session/__tests__/SessionItem.status-badges.test.tsx \
  src/widgets/session/__tests__/SessionItem.archive.test.tsx \
  src/widgets/session/__tests__/SessionItem.failed-tooltip.test.tsx
```
Expected: PASS。

- [ ] **Step 6: 提交**

```bash
git add src/widgets/session/SessionItem.tsx src/shared/lib/i18n/locales/zh/workspaceAndTools.ts \
  src/shared/lib/i18n/locales/en/workspaceAndTools.ts \
  src/widgets/session/__tests__/SessionItem.status-badges.test.tsx
git commit -m "feat(session): 会话列表增加重试中与后台运行中徽章"
```

---

### Task 5: 文档并入 + 架构基线 bump

**Files:**
- Modify: `docs/technical/101-llm-error-classification-retry.md`
- Create: `docs/technical/109-session-status-badges.md`
- Modify: `docs/technical/README.md`（目录表加 109 行）
- Modify: `architecture-baseline.json`（`agent.py` / `llm_client.py` 行数）
- Delete at the end: `docs/plans/2026-10-30_retry-visibility-session-status.md`

- [ ] **Step 1: 更新 101 文档**

在 `docs/technical/101-llm-error-classification-retry.md` 末尾追加三节（沿用现有文风）：

```markdown
## upstream_timeout 504 的可操作分类（2026-10-30）

Sage 自己的 LLM 代理在等待上游超时时返回 504，响应体为
`{"detail":{"type":"upstream_timeout",...}}`。`_raise_classified_error()`
现在会读取错误响应体，命中 `upstream_timeout` 时归类为 `TIMEOUT` 并给出
可操作文案（提示调大「设置 → 基础 → LLM 代理超时」，即
`llmProxyTimeoutS`）。流式路径在 `raise_for_status()` 前先 `aread()`
错误体，否则 `.text` 不可读、分类拿不到该标记。

普通 504（无 `upstream_timeout` 标记）仍归 `SERVER_ERROR`。

## 自动重试总时长预算（2026-10-30）

`chat()` 与 `chat_stream_events()` 的重试循环新增墙钟预算：
从首次尝试起算，退避前的累计耗时超过预算即停止，并用最后一次错误类型
抛出（消息追加「自动重试累计超过 Ns 总时长预算，已停止」）。

| 项 | 值 |
| --- | --- |
| 默认预算 | 180 秒 |
| 环境变量 | `SAGE_LLM_RETRY_TOTAL_BUDGET_S`（0 = 不限，非法值回退默认） |
| 作用范围 | 非流式 + 流式两条重试循环 |

原因：代理超时类 504 每次尝试本身就要等满代理超时（默认 60s），
旧行为下 10 次重试可累计卡住约 10 分钟。

## 非流式重试事件的可见性（2026-10-30）

非流式 `chat()` 的 `retry_callback` 在 `agent.run_loop` 中只能暂存，
旧实现仅在 `chat()` 正常返回后补发——重试耗尽抛异常时补发代码不执行，
前端完全看不到「重试中」。现在失败路径会先补发所有暂存重试事件再抛出。
流式路径仍是实时的。
```

- [ ] **Step 2: 新建会话状态文档**

创建 `docs/technical/109-session-status-badges.md`，内容包含：
- 徽章优先级表（注意力 > 重试中 > 运行中 > 后台运行中 > 失败 > 挂起 > 刚完成 60s > 定时）；
- 数据来源（本地流槽位 vs DB `sessions.run_status`）；
- `run_status` 五个值（idle/running/suspended/completed/failed）与写入点（`legacy_routes.py` 运行开始/终态、`recover_stale_run_states`）；
- 「重试中」消费 `slots.streaming.retryInfo`（无后端改动）；「后台运行中」覆盖刷新/多窗口/调度器场景；
- 已知限制：无 run_status 轮询，列表靠流结束或手动刷新整表重载。

在 `docs/technical/README.md` 目录表末尾按现有格式加一行：

```markdown
| 109  | [会话状态徽章](./109-session-status-badges.md) | 侧栏徽章优先级 / 重试中与后台运行中 / run_status 写入链路 |
```

- [ ] **Step 3: 基线 bump**

```bash
node scripts/architecture-check.mjs
```
按输出的新行数更新 `architecture-baseline.json` 中
`backend/core/legacy/agent.py` 与 `backend/core/legacy/llm_client.py` 的值
（ratchet：只升不降），再跑一次确认无 violation。

- [ ] **Step 4: 全量验证**

```bash
# 后端
/home/fz/anaconda3/envs/sage-backend/bin/python -m ruff check backend/core/legacy/llm_client.py backend/core/legacy/agent.py backend/tests/unit/test_agent_retry_visibility.py backend/tests/unit/test_llm_client_errors.py backend/tests/unit/test_llm_client_stream_errors.py backend/tests/unit/test_llm_retry.py backend/tests/unit/test_agent_retry_heartbeat.py
/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/test_llm_client_errors.py backend/tests/unit/test_llm_client_stream_errors.py backend/tests/unit/test_llm_retry.py backend/tests/unit/test_agent_retry_visibility.py backend/tests/unit/test_agent_run_loop.py backend/tests/unit/test_chat_steer.py -q
/home/fz/anaconda3/envs/sage-backend/bin/python scripts/check_py38_compat.py backend/core/legacy/llm_client.py backend/core/legacy/agent.py

# 前端
npx tsc --noEmit
npx vitest run src/widgets/session src/shared/lib/i18n
```

- [ ] **Step 5: 删除计划文件并提交**

按仓库规则，行为已并入技术文档后删除本计划：

```bash
git rm docs/plans/2026-10-30_retry-visibility-session-status.md
git add docs/technical/101-llm-error-classification-retry.md docs/technical/109-session-status-badges.md docs/technical/README.md architecture-baseline.json
git commit -m "docs(technical): 重试可见性、重试预算与会话状态徽章文档"
```

## 风险评估与依赖

| 风险 | 影响 | 缓解 |
| --- | --- | --- |
| 预算默认 180s 改变既有行为（曾可重试约 10 分钟） | 少数依赖长重试的用户更早看到失败 | 文案明确说明预算；env 可调；文档记录 |
| 流式路径预读错误体 | 错误响应体过大时多读一次 | 代理错误体为小型 JSON（脱敏 detail）；仅在 status>=400 时读 |
| `MagicMock` 测试替身未设 status_code | 新分支比较抛 TypeError | Task 2 Step 6 统一补 `status_code = 200`，相关测试全量跑 |
| 前端徽章优先级变化 | 重试中期间不再显示普通运行图标 | 用琥珀色 + tooltip 表达"仍在运行但正在重试" |
| 双分支同步 | win7 (py3.8) cherry-pick | 后端改动保持 py3.8 兼容；前端无差异 |

依赖：无新增第三方依赖；无设置协议变更；无数据库迁移。

## 完成后

- 创建 PR（base: `main`），标题：`feat: 重试可见性增强 + 会话状态徽章（重试中/后台运行中）`。
- CI 绿后按双分支规则评估 cherry-pick 到 `release/win7`（另开 PR，保留 py3.8 适配）。
