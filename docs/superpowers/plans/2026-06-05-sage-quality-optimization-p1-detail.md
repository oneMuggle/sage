# Sage P1 详细实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 把后端覆盖率从 43% 推到 ≥ 80%，完成前端 FSD 物理迁移 + 边界规则强制

**Phase:** P1 of 4（P0 已完工，详见 `docs/technical/15-quality-gates.md`）

**周期：** 3-4 周（单人）/ 2-3 周（2 人）

**关联文档：**
- 总体规划：`docs/superpowers/plans/2026-06-05-sage-quality-optimization.md`
- 设计 spec：`docs/superpowers/specs/2026-06-05-sage-quality-optimization-design.md`
- 质量门禁：`docs/technical/15-quality-gates.md`

**P0 基线（2026-06-05 末）：**
- 后端覆盖率：43%（2895 stmts / 1650 missed）
- 后端测试：48/48
- 前端覆盖率：未测
- 前端测试：17/17
- Ruff：0 违规
- ESLint：8 违规（已记录位置）
- 详见 `docs/technical/15-quality-gates.md` § 15.5

---

## P1 验收标准

- [ ] 后端覆盖率 ≥ 80%（分模块达成）
- [ ] 后端测试 ≥ 80 个
- [ ] CI 在覆盖率 < 80% 时失败（`--cov-fail-under=80`）
- [ ] 前端 `src/` 按 FSD 七层物理重组
- [ ] FSD 边界规则 enforcement 生效，0 violations
- [ ] 前端 `features` + `entities` 覆盖率 ≥ 80%
- [ ] `docs/technical/17-frontend-quality.md` 发布
- [ ] spec 总体成功指标基线列更新

---

## P1 任务组概览

| ID | 主题 | 文件 | 验收 |
|----|------|------|------|
| **PG1.1** | agent 状态机测试 | `backend/tests/unit/test_agent_state_transitions.py` 等 | `core/agent.py` ≥ 90% |
| **PG1.2** | orchestrator 测试 | `backend/tests/unit/test_orchestrator_*.py` | `core/orchestrator.py` ≥ 90% |
| **PG1.3** | llm_client 错误分支 | `backend/tests/unit/test_llm_client_*.py` | `core/llm_client.py` ≥ 90% |
| **PG1.4** | api 路由测试 | `backend/tests/integration/test_routes_*.py` | `api/routes.py` ≥ 85% |
| **PG1.5** | tools 测试 | `backend/tests/unit/test_tools_*.py` | `tools/*.py` ≥ 85% |
| **PG1.6** | skills/builtin 测试 | `backend/tests/unit/test_skills_builtin_*.py` | `skills/builtin/*.py` ≥ 70% |
| **PG1.7** | 覆盖率门槛 | `pytest.ini` | `--cov-fail-under=80` 生效 |
| **PG1.8** | FSD 目录骨架 | `src/{app,...,shared}/` | 7 个目录存在 |
| **PG1.9** | FSD 边界规则空跑 | `eslint.config.js` | 规则 warn-only |
| **PG1.10** | 迁移 Chat 页面 | `src/pages/Chat.tsx` + 依赖 | UI 行为不变 |
| **PG1.11** | 迁移 Settings 页面 | `src/pages/Settings.tsx` + 依赖 | UI 行为不变 |
| **PG1.12** | 迁移 K/S/A/M 页面 | 4 个 page 文件 | UI 行为不变 |
| **PG1.13** | 启用 FSD enforcement | `eslint.config.js` | 违规即 fail |
| **PG1.14** | 前端关键组件测试 | `src/**/__tests__/` | features+entities ≥ 80% |
| **PG1.15** | P1 完工 | `docs/technical/17-frontend-quality.md` + spec | 发布 |

---

## PG1.1 — 后端覆盖率补齐：agent 状态机

**目标文件：** `backend/core/agent.py`（591 行，**基线 62%** → **目标 ≥ 90%**）
**已有测试：** `backend/tests/unit/test_agent_state.py`（状态枚举）、`backend/tests/unit/test_agent_run_loop.py`（循环基本路径）
**缺口分析：** 591 行中 ~225 行未覆盖。集中在：工具调用分支、错误恢复路径、流式响应、message 持久化边界

### 任务 1.1.1：扩展 agent 状态转移测试

**Files:**
- Create: `backend/tests/unit/test_agent_state_transitions.py`

```python
"""测试 AgentState 状态机所有合法转移与异常路径。"""
import pytest
from backend.core.agent_state import AgentState

pytestmark = pytest.mark.unit


def test_initial_state_is_idle():
    assert AgentState.initial() == AgentState.IDLE


@pytest.mark.parametrize("from_state,to_state", [
    (AgentState.IDLE, AgentState.THINKING),
    (AgentState.THINKING, AgentState.ACTING),
    (AgentState.THINKING, AgentState.DONE),
    (AgentState.THINKING, AgentState.FAILED),
    (AgentState.ACTING, AgentState.OBSERVING),
    (AgentState.ACTING, AgentState.FAILED),
    (AgentState.OBSERVING, AgentState.THINKING),
    (AgentState.OBSERVING, AgentState.DONE),
    (AgentState.OBSERVING, AgentState.FAILED),
])
def test_legal_transitions(from_state, to_state):
    assert from_state.can_transition_to(to_state) is True


@pytest.mark.parametrize("from_state,to_state", [
    (AgentState.IDLE, AgentState.DONE),  # 跳过 THINKING
    (AgentState.IDLE, AgentState.ACTING),  # 跳过 THINKING
    (AgentState.DONE, AgentState.THINKING),  # 终态
    (AgentState.FAILED, AgentState.ACTING),  # 终态
])
def test_illegal_transitions(from_state, to_state):
    assert from_state.can_transition_to(to_state) is False


def test_terminal_states_have_no_transitions():
    for terminal in [AgentState.DONE, AgentState.FAILED]:
        for state in AgentState:
            if state != terminal:
                assert terminal.can_transition_to(state) is False
```

- [ ] 写入文件
- [ ] 运行 `pytest tests/unit/test_agent_state_transitions.py -v`（应 7+ passed）
- [ ] Commit：`test(backend): 扩展 AgentState 状态机转移测试`

### 任务 1.1.2：补 run_loop 工具调用与错误恢复测试

**Files:**
- Modify: `backend/tests/unit/test_agent_run_loop.py`

读现有 `test_agent_run_loop.py`，识别 run_loop 行为边界，添加：
- 工具调用成功 → OBSERVING → DONE 路径
- 工具调用失败 → FAILED 路径
- 工具返回错误 observation → 继续 THINKING 路径
- LLM 返回空 content → DONE（无工具）
- max_iterations 截断 → DONE + log warning
- run_loop 异常 → 状态 FAILED + 重抛

每个场景 1-2 个测试。

- [ ] 添加测试
- [ ] 运行 `pytest tests/unit/test_agent_run_loop.py -v`（新增 ≥ 6 个）
- [ ] 运行 `pytest --cov=backend/core/agent.py` 验证 ≥ 90%
- [ ] Commit：`test(backend): 补齐 agent run_loop 工具调用与错误恢复路径`

### 任务 1.1.3：流式响应边界测试

**Files:**
- Create: `backend/tests/unit/test_agent_streaming.py`

```python
"""测试 agent 流式响应（NDJSON）边界。"""
import pytest

pytestmark = pytest.mark.unit


def test_streaming_emits_thinking_event():
    """流式首事件应为 thinking"""
    pass  # 写实际断言


def test_streaming_handles_disconnect():
    """客户端断开时优雅终止"""
    pass


def test_streaming_aggregates_tool_observations():
    """多个工具 observation 聚合成一个 message"""
    pass
```

- [ ] 读 `core/agent.py` 找到流式相关函数
- [ ] 写 3-5 个测试覆盖流式边界
- [ ] 运行 + 验证覆盖率提升
- [ ] Commit

**退出标准：** `core/agent.py` 覆盖率 ≥ 90%

---

## PG1.2 — 后端覆盖率补齐：orchestrator

**目标文件：** `backend/core/orchestrator.py`（383 行，**基线 21%** → **目标 ≥ 90%**）
**缺口：** 主要逻辑未测试；推测是调度逻辑

### 任务 1.2.1：读 orchestrator.py 摸清结构

- [ ] Read `backend/core/orchestrator.py` 全文
- [ ] 在 dispatch prompt 中描述：识别 3-5 个核心函数；为每个函数规划至少 2 个测试
- [ ] Commit（如有笔记）：无需 commit，仅为规划

### 任务 1.2.2：写 orchestrator 核心测试

**Files:**
- Create: `backend/tests/unit/test_orchestrator_dispatch.py`
- Create: `backend/tests/unit/test_orchestrator_scheduling.py`

```python
# test_orchestrator_dispatch.py
"""测试 Orchestrator 任务分派逻辑。"""
import pytest
from backend.core.orchestrator import Orchestrator

pytestmark = pytest.mark.unit


def test_orchestrator_initialization():
    """Orchestrator 初始化无外部依赖"""
    orch = Orchestrator()
    assert orch is not None


def test_dispatch_routes_task_to_handler(monkeypatch):
    """dispatch 把 task 路由到对应 handler"""
    pass
```

```python
# test_orchestrator_scheduling.py
"""测试 Orchestrator 调度（cron / 队列）。"""
import pytest

pytestmark = pytest.mark.unit


def test_cron_parsing():
    """cron 表达式解析"""
    pass


def test_queue_add_and_drain():
    """任务队列 add + drain"""
    pass
```

- [ ] 写 6-8 个测试覆盖核心函数
- [ ] 运行覆盖率验证
- [ ] Commit

**退出标准：** `core/orchestrator.py` 覆盖率 ≥ 90%

---

## PG1.3 — 后端覆盖率补齐：llm_client 错误分支

**目标文件：** `backend/core/llm_client.py`（306 行，**基线 67%** → **目标 ≥ 90%**）
**已有测试：** `test_llm_client_errors.py`、`test_llm_client_tools.py`（P0 末已 11 个相关测试）

### 任务 1.3.1：使用 P0 conftest mock fixtures 补缺失场景

**Files:**
- Create: `backend/tests/unit/test_llm_client_remaining.py`

利用 P0-T7 新增的 `mock_llm_ok`、`mock_llm_rate_limit`、`mock_llm_timeout`、`mock_llm_server_error` 写测试覆盖：

```python
"""LLMClient 未覆盖路径（使用 P0 共享 fixture）。"""
import pytest
from backend.core.llm_client import LLMClient
from backend.core.errors import LLMError, LLMErrorType

pytestmark = pytest.mark.unit


def test_chat_completion_normal(mock_llm_ok):
    """正常 chat completion 路径"""
    client = LLMClient(base_url="https://api.example.com", api_key="test")
    # 调用 client.chat(...) 应当返回 Message
    # 验证 message.content == "Hello from mock!"
    pass


def test_chat_completion_rate_limit_raises(mock_llm_rate_limit):
    """429 限流 → LLMError(RATE_LIMITED)"""
    client = LLMClient(base_url="https://api.example.com", api_key="test")
    with pytest.raises(LLMError) as exc_info:
        client.chat([{"role": "user", "content": "hi"}])
    assert exc_info.value.type == LLMErrorType.RATE_LIMITED


def test_chat_completion_timeout_raises(mock_llm_timeout):
    """超时 → LLMError(TIMEOUT)"""
    client = LLMClient(base_url="https://api.example.com", api_key="test")
    with pytest.raises(LLMError) as exc_info:
        client.chat([{"role": "user", "content": "hi"}])
    assert exc_info.value.type == LLMErrorType.TIMEOUT


def test_chat_completion_500_raises(mock_llm_server_error):
    """500 → LLMError(SERVER_ERROR)"""
    client = LLMClient(base_url="https://api.example.com", api_key="test")
    with pytest.raises(LLMError) as exc_info:
        client.chat([{"role": "user", "content": "hi"}])
    assert exc_info.value.type == LLMErrorType.SERVER_ERROR
```

- [ ] 写 4-6 个测试
- [ ] 验证 `core/llm_client.py` ≥ 90%
- [ ] Commit：`test(backend): 用共享 mock fixture 补齐 LLMClient 错误分支`

**退出标准：** `core/llm_client.py` 覆盖率 ≥ 90%

---

## PG1.4 — 后端覆盖率补齐：api 路由

**目标文件：** `backend/api/routes.py`（501 行，**基线 68%** → **目标 ≥ 85%**）
**已有测试：** `test_chat_stream.py`、`test_routes_chat_errors.py`、`test_health.py`

### 任务 1.4.1：识别 routes.py 主要端点

- [ ] Read `backend/api/routes.py`，列出所有 `@app.*` 端点（预计 8-12 个）
- [ ] 列出每个端点已测试 / 未测试状态
- [ ] 规划 4-6 个新测试覆盖未测试端点（设置/会话管理/记忆 CRUD 等）

### 任务 1.4.2：补齐未覆盖端点测试

**Files:**
- Modify: `backend/tests/integration/test_routes_settings.py`（新建）
- Modify: `backend/tests/integration/test_routes_sessions_crud.py`（新建）
- Modify: `backend/tests/integration/test_routes_memory.py`（新建）

```python
# test_routes_settings.py
"""测试 /settings 系列端点。"""
import pytest

pytestmark = pytest.mark.integration


async def test_get_settings(client):
    resp = await client.get("/settings")
    assert resp.status_code == 200
    assert "api_base_url" in resp.json()


async def test_update_settings(client):
    resp = await client.put("/settings", json={"api_base_url": "https://new.example.com"})
    assert resp.status_code == 200
    assert resp.json()["api_base_url"] == "https://new.example.com"
```

- [ ] 写 4-8 个新测试
- [ ] 验证 `api/routes.py` ≥ 85%
- [ ] Commit

**退出标准：** `api/routes.py` 覆盖率 ≥ 85%

---

## PG1.5 — 后端覆盖率补齐：tools

**目标文件：** `backend/tools/*.py`（10 个文件，**基线 TBD** → **目标 ≥ 85%**）
**已有测试：** 0 个 tools 测试

### 任务 1.5.1：识别 5 个核心工具

- [ ] Read `backend/tools/__init__.py` 列出注册的工具
- [ ] 预计：calculator / file_tool / memory_tool / web_tool / terminal / skill
- [ ] 选 5 个最常用工具（基于使用频率或风险）

### 任务 1.5.2：calculator 测试

**Files:**
- Create: `backend/tests/unit/test_calculator.py`

```python
import pytest
from backend.tools.calculator import CalculatorTool

pytestmark = pytest.mark.unit


def test_calculator_basic_addition():
    tool = CalculatorTool()
    result = tool.execute(expression="2 + 2")
    assert result.success is True
    assert "4" in result.output


def test_calculator_handles_invalid_expression():
    tool = CalculatorTool()
    result = tool.execute(expression="invalid")
    assert result.success is False
```

- [ ] 写 4-6 个测试

### 任务 1.5.3：其他 4 个工具测试

按 1.5.2 模式为每个工具写 3-5 个测试。

- [ ] Commit 每个工具测试单独 commit

### 任务 1.5.4：tool registry 测试

**Files:**
- Create: `backend/tests/unit/test_tools_registry.py`

测试：register / get / list / unregister / 重复注册检测

- [ ] 写 3-4 个测试
- [ ] Commit

**退出标准：** `tools/*.py` 平均覆盖率 ≥ 85%

---

## PG1.6 — 后端覆盖率补齐：skills/builtin

**目标文件：** `backend/skills/builtin/*.py`（4 个文件：coder / search / travel / writer，**基线 19-27%** → **目标 ≥ 70%**）
**已有测试：** 0 个 skills 测试

### 任务 1.6.1-1.6.4：每个 skill 一个测试文件

**Files:**
- Create: `backend/tests/unit/test_skills_coder.py`
- Create: `backend/tests/unit/test_skills_search.py`
- Create: `backend/tests/unit/test_skills_travel.py`
- Create: `backend/tests/unit/test_skills_writer.py`

每个文件 3-5 个测试：
- 初始化（参数验证）
- 正常执行
- 错误处理（缺参数、不可用 LLM 等）
- 边界（空输入、超长输入）

- [ ] 写 12-20 个测试
- [ ] 验证 `skills/builtin/*.py` 平均 ≥ 70%
- [ ] Commit 每个 skill 单独

**退出标准：** `skills/builtin/*.py` 平均覆盖率 ≥ 70%

---

## PG1.7 — 提升覆盖率门槛到 80%

### 任务 1.7.1：先确认当前整体覆盖率

- [ ] Run: `cd backend && pytest --cov=backend --cov-report=term-missing`
- [ ] 记录实际数字到 dispatch prompt

### 任务 1.7.2：修改 pytest.ini

- [ ] Edit `backend/pytest.ini` 找到 `--cov-fail-under=0`
- [ ] 改为 `--cov-fail-under=80`
- [ ] 同时在 `[coverage:report]` 加 `fail_under = 80` 双重保险

### 任务 1.7.3：跑一次 CI 模拟

- [ ] Run: `pytest --cov-fail-under=80`（在 sage-backend 环境）
- [ ] 如果失败（覆盖率不足），**STOP and report** — 说明需先补更多测试
- [ ] 如果通过，commit

### 任务 1.7.4：CI 配置同步

- [ ] Edit `.github/workflows/ci.yml`
- [ ] `pytest` 命令的 `--cov-fail-under=0` 改为 `--cov-fail-under=80`
- [ ] Commit：`ci: 把覆盖率门槛从 0 提到 80`

**退出标准：** CI 在覆盖率 < 80% 时硬性失败

---

## PG1.8 — FSD 目录骨架

### 任务 1.8.1：创建 7 个空目录

```bash
cd /home/fz/project/sage/src
mkdir -p app/providers
mkdir -p processes
mkdir -p pages
mkdir -p widgets
mkdir -p features
mkdir -p entities
mkdir -p shared/{ui,lib,config,api-client,types,styles}
```

每个目录加 `README.md` 说明层级意图：

```bash
# app/README.md
# app 层
- 应用入口、Provider、全局样式
- 只能被本目录内文件 import
- **不可**被下层（processes / pages / widgets / features / entities / shared）import

# 同模式给其他 6 层
```

- [ ] 7 目录 + 6 README.md 创建
- [ ] Commit：`refactor(frontend): 创建 FSD 7 层目录骨架 + README`

---

## PG1.9 — FSD 边界规则空跑（warn-only）

### 任务 1.9.1：安装 eslint-plugin-fsd

```bash
cd /home/fz/project/sage && npm install --save-dev eslint-plugin-fsd
```

### 任务 1.9.2：扩展 eslint.config.js

读当前 `eslint.config.js`，增加 FSD 边界规则块（**warn only**，不阻塞）：

```js
// 在 plugins 块加：
plugins: {
  // ... existing
  'fsd': fsdPlugin,
},

// 新增 rules 块：
{
  files: ['src/**/*.{ts,tsx}'],
  rules: {
    // ... existing
    'fsd/layer-imports': ['warn', {
      alias: '@',
      layers: ['app', 'processes', 'pages', 'widgets', 'features', 'entities', 'shared'],
    }],
  },
},
```

- [ ] 写配置
- [ ] 运行 `npm run lint` 验证（应产生 warn 不 fail）
- [ ] Commit：`chore(frontend): 配置 FSD 边界规则（warn only）`

---

## PG1.10 — 迁移 Chat 页面

### 任务 1.10.1：识别 Chat.tsx 依赖

- [ ] Read `src/pages/Chat.tsx` 找出所有 import
- [ ] 列出依赖文件（store / hook / component / lib）
- [ ] 决定每个依赖迁到 FSD 哪一层

### 任务 1.10.2：迁移 Chat + 依赖

按 import 关系先迁依赖、再迁 Chat 自身：
- 如果依赖是 component：迁到 `widgets/` 或 `features/`
- 如果依赖是 hook：迁到 `features/`
- 如果依赖是 store：迁到 `entities/` 或 `features/`
- 如果依赖是 lib：迁到 `shared/lib`

- [ ] 物理移文件（`git mv`）
- [ ] 更新所有 import 路径
- [ ] 运行 `npm run typecheck && npm run test:run` 验证
- [ ] 运行 `npm run dev` 启动 UI 行为不变（人工检查）

### 任务 1.10.3：commit

- [ ] Commit：`refactor(frontend): 迁移 Chat 页面到 FSD（widgets/features/entities）`

---

## PG1.11 — 迁移 Settings 页面

按 PG1.10 模式。Settings 较大（625 行）— 可能涉及多个 feature 拆分。

### 任务 1.11.1-1.11.3：同 PG1.10

- [ ] 识别依赖
- [ ] 物理迁移 + 更新 import
- [ ] typecheck + test + dev 验证
- [ ] Commit

---

## PG1.12 — 迁移 K/S/A/M 页面

Knowledge / Skills / Agents / Memory 四个页面。

### 任务 1.12.1-1.12.5：每个页面独立迁移

- 1.12.1 Knowledge
- 1.12.2 Skills
- 1.12.3 Agents
- 1.12.4 Memory
- 1.12.5 验证（typecheck + test + dev 一次跑全 5 个页面）

每个独立 commit。

---

## PG1.13 — 启用 FSD enforcement

### 任务 1.13.1：把 FSD 规则从 warn 改为 error

- [ ] Edit `eslint.config.js`：`'warn'` → `'error'`
- [ ] Run `npm run lint`，验证应 0 errors

### 任务 1.13.2：CI 同步

- [ ] 确认 `.github/workflows/ci.yml` 中 `npm run lint` 没 `--max-warnings` flag（否则会因历史 warning 失败）
- [ ] 跑一次本地 `npm run lint`，记录 errors 数字
- [ ] Commit：`chore(frontend): 启用 FSD 边界 enforcement`

**退出标准：** 任何逆向 import 立即 fail

---

## PG1.14 — 前端关键组件测试

### 任务 1.14.1：列出要测的核心 hook / store

按 P0 spec 列出的清单：
- `useChat.test.ts`（核心 hook）
- `useSettings.test.ts`（store 关键）
- `useSessions.test.ts`
- errorBoundary.test.tsx
- 5+ 组件测试（ChatPanel / Message / Sidebar / Settings 表单）

### 任务 1.14.2：写 useChat 测试

**Files:**
- Create: `src/hooks/__tests__/useChat.test.ts`

```typescript
import { renderHook, act } from '@testing-library/react';
import { useChat } from '../useChat';

describe('useChat', () => {
  it('initializes with empty messages', () => {
    const { result } = renderHook(() => useChat());
    expect(result.current.messages).toEqual([]);
  });

  it('sends a message and updates state', async () => {
    const { result } = renderHook(() => useChat());
    await act(async () => {
      await result.current.sendMessage('Hello');
    });
    expect(result.current.messages.length).toBeGreaterThan(0);
  });

  it('handles send error gracefully', async () => {
    // mock fetch to throw
    // verify error state set, retry function available
  });
});
```

- [ ] 写 5-8 个测试覆盖 send / receive / error / retry / abort

### 任务 1.14.3：写 store + 5 组件测试

按 1.14.2 模式。

- [ ] 写 8-12 个测试
- [ ] 验证 features + entities 覆盖率 ≥ 80%

### 任务 1.14.4：commit

- [ ] Commit：`test(frontend): 关键 hook + store + 组件 8-12 测试`

---

## PG1.15 — P1 完工

### 任务 1.15.1：最终验证

- [ ] 后端：`ruff check . && pytest --cov-fail-under=80`（应通过）
- [ ] 前端：`npm run lint && npm run typecheck && npm run test:run -- --coverage`
- [ ] 验证：覆盖率 ≥ 80%（后端），features+entities ≥ 80%（前端）

### 任务 1.15.2：写 17-frontend-quality.md

**Files:**
- Create: `docs/technical/17-frontend-quality.md`

包含：
- FSD 架构总览
- 七层目录说明
- 边界规则 enforcement
- 共享组件清单
- 测试覆盖率现状
- a11y 当前状态（P3 完善）

### 任务 1.15.3：更新 spec 总体成功指标

- [ ] Edit `docs/superpowers/specs/2026-06-05-sage-quality-optimization-design.md` § 8
- [ ] 把"后端测试覆盖率"基线从 43% 改为 P1 末实测
- [ ] 把"前端测试覆盖率"基线从 TBD 改为 P1 末实测

### 任务 1.15.4：commit + push

- [ ] Commit：`docs: P1 完工 + 更新基线`
- [ ] Push
- [ ] 在 plan 文档标记 PG1.1-PG1.15 为 [x]

---

## 自审（Self-Review）

### Spec 覆盖

| Spec 节 | 对应 PG | 状态 |
|---------|--------|------|
| § 3.1 后端测试体系 | PG1.1-PG1.7 | ✅ |
| § 3.3 前端测试体系 | PG1.14 | ✅ |
| § 3.4 前端 Lint/Format | PG1.9, PG1.13 | ✅ |
| § 4 P1 全节 | 全部 | ✅ |
| § 8 总体成功指标 | PG1.7, PG1.15 | ✅ |

### 类型/接口一致性

- 所有状态机测试使用同一个 `AgentState` 枚举（已存在）
- `LLMError` / `LLMErrorType` 在多个 PG 中复用（P0 已定义）
- 覆盖率门槛 `80%` 在 spec / plan / pytest.ini 三处一致

### 范围检查

- PG1.1-PG1.7 覆盖率补齐：明确分模块，7 个 PG 全部目标
- PG1.8-PG1.13 FSD 迁移：5 个页面 + 边界规则
- PG1.14 前端测试：8-12 个
- PG1.15 完工：文档 + 基线

**无缺口，可执行。**

---

## 实施步骤追踪

### P1 阶段
- [ ] PG1.1: agent 状态机测试（3 任务）
- [ ] PG1.2: orchestrator 测试（2 任务）
- [ ] PG1.3: llm_client 错误分支（1 任务）
- [ ] PG1.4: api 路由测试（2 任务）
- [ ] PG1.5: tools 测试（4 任务）
- [ ] PG1.6: skills/builtin 测试（4 任务）
- [ ] PG1.7: 覆盖率门槛（4 任务）
- [ ] PG1.8: FSD 目录骨架（1 任务）
- [ ] PG1.9: FSD 边界规则空跑（2 任务）
- [ ] PG1.10: 迁移 Chat 页面（3 任务）
- [ ] PG1.11: 迁移 Settings 页面（3 任务）
- [ ] PG1.12: 迁移 K/S/A/M 页面（5 任务）
- [ ] PG1.13: 启用 FSD enforcement（2 任务）
- [ ] PG1.14: 前端关键组件测试（4 任务）
- [ ] PG1.15: P1 完工（4 任务）

**总计：40 个任务**
