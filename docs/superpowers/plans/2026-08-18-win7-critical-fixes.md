# v0.4.7-alpha.1-win7 用户报告修复 — 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修复 v0.4.7-alpha.1-win7 用户实测中报告的 4 类 main/win7 双端缺陷（PR-D/C/A/B），并在 main 验证后批量 cherry-pick 到 release/win7，出 v0.4.8-alpha.1-win7 NSIS。

**Architecture:** 4 个独立 PR，按风险由小到大顺序：D（Python 纯逻辑）→ C（Python 注入）→ A（Electron 复用 resolver）→ B（Electron spawn 重试 + UI banner）。每个 PR 含真实单测 + 端到端冒烟。

**Tech Stack:** Python 3.11 (FastAPI/uvicorn, conda `sage-backend`)、TypeScript (Electron 主进程 + preload + renderer, vitest)、React (zustand store)。

**Spec:** `docs/superpowers/specs/2026-08-18-win7-critical-fixes-design.md` (commit `c0a6b41f`)

## Global Constraints

- 分支策略：每个 PR 走独立 feature 分支（`fix/title-generator-dict`、`fix/memory-manager-injection`、`fix/doctor-bundled-python`、`feat/backend-auto-restart-banner`）；main 全绿后批量 cherry-pick 到 `release/win7`（squash merge 到 win7，单 PR）。
- 环境：
  - 后端 Python 命令一律 `/home/fz/anaconda3/envs/sage-backend/bin/python ...`（CLAUDE.md 强制）
  - 前端/Electron 测试 `cd /home/fz/project/sage && npx vitest run <path>`
  - 后端 pytest `/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest <path> -v`
- 不新增任何 Python / npm 依赖。
- commit message 走 conventional commits 格式（feat/fix/refactor/...），便于 win7 cherry-pick 时筛选。
- PR-B 含 renderer / IPC 协议变更，新增事件名 `backend:disconnected` / `backend:reconnected` 必须在 `electron/commands.ts` 和 preload bridge 都注册。
- cherry-pick 到 win7 时，Py 3.8 兼容检查：避免 PEP 604 union（如 `X | None`）、`from __future__ import annotations` 已存在的模块安全。
- 不在范围内（spec §6 明确推迟）：子 agent 进度冒泡、IPC `get_evolution_status/_logs` 注册、asyncio ProactorBasePipeTransport stderr 抑制、electron main 进程重启。

---

## 里程碑总览

| PR | 标题 | 工作量 | 依赖 |
|---|---|---|---|
| **PR-D** | `fix(chat): TitleGenerator 走 dict 输入 + KeyError 兜底` | 3 步（1 测试 + 1 改 + 1 commit） | 无 |
| **PR-C** | `fix(memory): MemorySearchTool/SaveTool 注入 memory_manager` | 4 步（2 测试 + 1 改 + 1 commit） | 无 |
| **PR-A** | `fix(electron): doctor 使用 bundled python + PYTHONPATH` | 5 步（2 测试 + 2 改 + 1 commit） | 无 |
| **PR-B** | `feat(electron): backend 指数退避自动重启 + ECONNREFUSED 友好翻译 + UI banner` | 8 步（5 测试 + 3 改 + 1 commit + 1 e2e） | 无 |

实施顺序 **D → C → A → B**，全部完成后 main 跑 ≥3 天，再批量 cherry-pick 到 win7。

---

### Task 1: PR-D 准备分支 + 写失败测试

**Files:**
- Create: `backend/chat/test_title_generator.py`

**Interfaces:**
- Consumes: `TitleGenerator` from `backend/chat/title_generator.py`
- Produces: 测试模块 `test_title_generator.py`，暴露 `test_dict_input_returns_title` 与 `test_keyerror_fallback_returns_none`

- [ ] **Step 1: 建分支**

Run:
```bash
cd /home/fz/project/sage
git switch -c fix/title-generator-dict
```
Expected: `Switched to a new branch 'fix/title-generator-dict'`.

- [ ] **Step 2: 写失败测试**

新建 `backend/chat/test_title_generator.py`：

```python
"""PR-D: TitleGenerator 走 dict 输入 + KeyError 兜底。

验证 LLMClient.chat 接口契约修复后,KeyError 不再泄漏到外层。
"""
from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.chat.title_generator import TitleGenerator


@pytest.fixture
def mock_llm_client() -> MagicMock:
    client = MagicMock()
    client.chat = AsyncMock()
    return client


@pytest.mark.asyncio
async def test_dict_input_returns_title(mock_llm_client: MagicMock) -> None:
    """主路径:dict 输入 → LLM 返回 content → 取出标题。"""
    mock_llm_client.chat.return_value = MagicMock(content="Sage 项目诊断")
    gen = TitleGenerator(llm_client=mock_llm_client)
    result = await gen._generate_with_llm("测试 prompt")
    assert result == "Sage 项目诊断"
    call_args = mock_llm_client.chat.call_args[0][0]
    assert call_args == [{"role": "user", "content": "测试 prompt"}]


@pytest.mark.asyncio
async def test_keyerror_fallback_returns_none(mock_llm_client: MagicMock) -> None:
    """异常路径:LLMClient.chat 抛 KeyError → generate 返回 None,外层 caller 拿到 None 而非崩。"""
    mock_llm_client.chat.side_effect = KeyError("role")
    gen = TitleGenerator(llm_client=mock_llm_client)
    result = await gen._generate_with_llm("测试 prompt")
    assert result is None
```

- [ ] **Step 3: 运行测试,确认 RED**

Run:
```bash
cd /home/fz/project/sage && /home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/chat/test_title_generator.py -v
```
Expected: `test_dict_input_returns_title` 与 `test_keyerror_fallback_returns_none` 都失败（要么 `_generate_with_llm` 不存在,要么 dict 输入未生效,要么 KeyError 未被 except）。

- [ ] **Step 4: commit 测试**

```bash
git add backend/chat/test_title_generator.py
git commit -m "test(chat): TitleGenerator dict 输入 + KeyError 兜底 (RED)"
```

---

### Task 2: PR-D 改实现 + commit

**Files:**
- Modify: `backend/chat/title_generator.py:79-86`

**Interfaces:**
- Consumes: `LLMClient.chat(messages: List[Dict])`（`backend/core/legacy/llm_client.py:259`，接受 dict 列表）
- Produces: `TitleGenerator._generate_with_llm` 返回 `Optional[str]`，正常路径返回标题字符串，异常路径返回 None。

- [ ] **Step 1: 修改 `backend/chat/title_generator.py:79-86`**

当前（推测位置）：
```python
prompt_msg = Message(role="user", content=prompt)
resp = await self.llm_client.chat([prompt_msg])
if resp and getattr(resp, "content", None):
    return resp.content.strip()
```

改为：
```python
try:
    resp = await self.llm_client.chat([{"role": "user", "content": prompt}])
    if resp and getattr(resp, "content", None):
        return resp.content.strip()
except (ImportError, TypeError, AttributeError, KeyError):
    pass
return None
```

> **注意**：如果当前文件已经使用其他结构（比如 `try/except` 包装），按最小改动原则只加 `KeyError` 到 except 元组 + 把 `Message` 替换为 dict。如果 `_generate_with_llm` 函数不存在，按该签名新建。

- [ ] **Step 2: 运行测试,确认 GREEN**

Run:
```bash
cd /home/fz/project/sage && /home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/chat/test_title_generator.py -v
```
Expected: 2 个测试都通过。

- [ ] **Step 3: 跑全套后端测试,确认无回归**

Run:
```bash
cd /home/fz/project/sage && /home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/chat -v
```
Expected: 全过，无新失败。

- [ ] **Step 4: commit 修复**

```bash
git add backend/chat/title_generator.py
git commit -m "fix(chat): TitleGenerator 走 dict 输入 + KeyError 兜底

LLMClient._convert_messages 用 msg['role'] 访问,Message dataclass 不支持
[] 抛 KeyError。现有 except 不含 KeyError → fallback 不触发 → 标题保持
'新对话'。改为直接喂 dict + 把 KeyError 加入 except 列表。

Closes: PR-D 单元测试覆盖
Refs: docs/superpowers/specs/2026-08-18-win7-critical-fixes-design.md §3 PR-D"
```

- [ ] **Step 5: 合并到 main**

```bash
cd /home/fz/project/sage
git switch main
git merge --squash fix/title-generator-dict
git commit -m "fix(chat): TitleGenerator 走 dict 输入 + KeyError 兜底 (PR-D)"
git push origin main
git branch -d fix/title-generator-dict
```

Expected: main HEAD 推进 1 个 commit。后续 Task 等用户在本机跑过「首次对话自动生成标题」验收再开始。

---

### Task 3: PR-C 准备分支 + 写失败测试

**Files:**
- Create: `backend/tools/test_memory_tool_injection.py`

**Interfaces:**
- Consumes: `ToolRegistry` from `backend/tools/__init__.py:48-49`, `MemorySearchTool`/`MemorySaveTool` from `backend/tools/memory_tool.py`
- Produces: 测试模块验证 agent 启动后 `MemorySearchTool.memory is not None`。

- [ ] **Step 1: 建分支**

```bash
cd /home/fz/project/sage
git switch -c fix/memory-manager-injection
```

- [ ] **Step 2: 写失败测试**

新建 `backend/tools/test_memory_tool_injection.py`：

```python
"""PR-C: 验证 MemorySearchTool/SaveTool 在 agent 启动后注入了 memory_manager。

生产代码 0 处调用 set_memory_manager(),工具构造时 memory_manager=None,
立即抛 '记忆管理器未初始化'。本测试验证修复后注入生效。
"""
from unittest.mock import MagicMock

import pytest

from backend.memory.registry import get_memory_manager
from backend.tools import ToolRegistry, register_all_tools
from backend.tools.memory_tool import MemorySearchTool, MemorySaveTool


@pytest.fixture
def registry() -> ToolRegistry:
    return ToolRegistry()


def test_memory_tools_register_with_manager(registry: ToolRegistry) -> None:
    """register_all_tools 调用 + 注入逻辑后,MemorySearchTool.memory 不为 None。"""
    register_all_tools(registry, ctx=MagicMock())

    manager = get_memory_manager()
    for tool in registry.list_tools():
        if isinstance(tool, (MemorySearchTool, MemorySaveTool)):
            tool.set_memory_manager(manager)

    search_tool = next(
        t for t in registry.list_tools() if isinstance(t, MemorySearchTool)
    )
    save_tool = next(
        t for t in registry.list_tools() if isinstance(t, MemorySaveTool)
    )

    assert search_tool.memory is not None, (
        "MemorySearchTool.memory 应在注入后非 None,否则用户调用时报 '未初始化'"
    )
    assert save_tool.memory is not None


def test_memory_search_returns_results_not_error(registry: ToolRegistry) -> None:
    """端到端:注入后调用 search 应返回结果而非抛 '未初始化' 错误。"""
    register_all_tools(registry, ctx=MagicMock())
    manager = get_memory_manager()
    for tool in registry.list_tools():
        if isinstance(tool, (MemorySearchTool, MemorySaveTool)):
            tool.set_memory_manager(manager)

    search_tool = next(
        t for t in registry.list_tools() if isinstance(t, MemorySearchTool)
    )
    try:
        out = search_tool.run(query="test")
        assert out is not None
    except Exception as e:
        pytest.fail(f"MemorySearchTool.run 抛了意外异常: {e}")
```

- [ ] **Step 3: 运行测试,确认 RED**

Run:
```bash
cd /home/fz/project/sage && /home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tools/test_memory_tool_injection.py -v
```
Expected: 2 个测试都失败（`search_tool.memory is None` / `set_memory_manager` 不存在）。

- [ ] **Step 4: commit 测试**

```bash
git add backend/tools/test_memory_tool_injection.py
git commit -m "test(memory): MemorySearchTool/SaveTool 注入 memory_manager (RED)"
```

---

### Task 4: PR-C 改实现 + commit

**Files:**
- Modify: `backend/core/legacy/agent.py:270`（在 `register_all_tools` 后加注入逻辑）

**Interfaces:**
- Consumes: `get_memory_manager()` from `backend/memory/registry.py`（全局单例）
- Produces: 所有 `MemorySearchTool` / `MemorySaveTool` 在 agent 启动时被注入。

- [ ] **Step 1: 定位 `backend/core/legacy/agent.py` 第 270 行附近的 `register_all_tools` 调用**

Read 命令：`sed -n '260,280p' backend/core/legacy/agent.py`

预期：
```python
register_all_tools(self.tool_registry, ctx)
```

（行号会随代码演进漂移，按实际查到的位置改。）

- [ ] **Step 2: 加注入逻辑**

在 `register_all_tools(self.tool_registry, ctx)` 调用后,添加：

```python
# PR-C: 注入全局 memory_manager 单例到 MemorySearchTool / MemorySaveTool。
# 此前两工具构造时 memory_manager=None,生产代码 0 处调用 set_memory_manager(),
# 用户调用时立即抛 "记忆管理器未初始化"。
from backend.memory.registry import get_memory_manager
from backend.tools.memory_tool import MemorySearchTool, MemorySaveTool

for tool in self.tool_registry.list_tools():
    if isinstance(tool, (MemorySearchTool, MemorySaveTool)):
        tool.set_memory_manager(get_memory_manager())
```

- [ ] **Step 3: 运行测试,确认 GREEN**

```bash
cd /home/fz/project/sage && /home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tools/test_memory_tool_injection.py -v
```
Expected: 2 个测试都通过。

- [ ] **Step 4: 跑全套后端测试,确认无回归**

```bash
cd /home/fz/project/sage && /home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tools backend/core -v
```
Expected: 全过。

- [ ] **Step 5: 同步检查 hex 路径**

如果 `backend/app/services/chat_service.py`（hex）或 `backend/chat/service.py` 也调用 `register_all_tools`,需要同样注入。Read 该文件查 `register_all_tools` 出现位置,如有则复制粘贴同一段注入逻辑（hex 路径下 `self.tool_registry` 可能命名不同,按实际命名替换）。

- [ ] **Step 6: commit 修复**

```bash
git add backend/core/legacy/agent.py
git commit -m "fix(memory): MemorySearchTool/SaveTool 注入 memory_manager

register_all_tools 后遍历 registry,把全局 get_memory_manager() 单例注入
到所有 MemorySearchTool/SaveTool 实例。hex ChatService 同步处理。

Refs: docs/superpowers/specs/2026-08-18-win7-critical-fixes-design.md §3 PR-C"
```

- [ ] **Step 7: 合并到 main**

```bash
cd /home/fz/project/sage
git switch main
git merge --squash fix/memory-manager-injection
git commit -m "fix(memory): MemorySearchTool/SaveTool 注入 memory_manager (PR-C)"
git push origin main
git branch -d fix/memory-manager-injection
```

---

### Task 5: PR-A 准备分支 + 改 `runDoctorCheck` 签名 + 写失败测试

**Files:**
- Modify: `electron/doctor.ts:78`（`runDoctorCheck` 增加 `extraEnv` 参数）
- Create: `electron/test_doctor_extra_env.ts`

**Interfaces:**
- Consumes: 无（API 扩展）
- Produces: `runDoctorCheck(pythonBin, projectRoot, timeoutMs?, extraEnv?)`，spawn 时合并 `extraEnv` 到 env。

- [ ] **Step 1: 建分支**

```bash
cd /home/fz/project/sage
git switch -c fix/doctor-bundled-python
```

- [ ] **Step 2: 修改 `electron/doctor.ts:78` 签名 + 注入 extraEnv**

当前：
```typescript
export async function runDoctorCheck(
  pythonBin: string,
  projectRoot: string,
  timeoutMs: number = DEFAULT_TIMEOUT_MS,
): Promise<DoctorSummary> {
  // ...
  const proc = spawn(pythonBin, ['-m', 'backend.cli.doctor', '--json'], {
    cwd: projectRoot,
    stdio: ['ignore', 'pipe', 'pipe'],
    windowsHide: true,
  });
```

改为：
```typescript
export async function runDoctorCheck(
  pythonBin: string,
  projectRoot: string,
  timeoutMs: number = DEFAULT_TIMEOUT_MS,
  extraEnv?: Record<string, string>,
): Promise<DoctorSummary> {
  // ...
  const proc = spawn(pythonBin, ['-m', 'backend.cli.doctor', '--json'], {
    cwd: projectRoot,
    stdio: ['ignore', 'pipe', 'pipe'],
    windowsHide: true,
    env: extraEnv ? { ...process.env, ...extraEnv } : process.env,
  });
```

- [ ] **Step 3: 写失败测试（确保 extraEnv 实际生效）**

新建 `electron/test_doctor_extra_env.ts`：

```typescript
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { runDoctorCheck } from './doctor';
import { spawn } from 'child_process';

vi.mock('child_process', async () => {
  const actual = await vi.importActual<typeof import('child_process')>('child_process');
  return { ...actual, spawn: vi.fn() };
});

describe('runDoctorCheck extraEnv propagation (PR-A)', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('spawns with merged extraEnv containing PYTHONPATH', async () => {
    const fakeProc = {
      stdout: { on: vi.fn() },
      stderr: { on: vi.fn() },
      on: vi.fn(),
      kill: vi.fn(),
    };
    (spawn as any).mockReturnValue(fakeProc);

    const promise = runDoctorCheck(
      'C:\\fake\\python.exe',
      'C:\\fake\\root',
      5000,
      { PYTHONPATH: 'C:\\fake\\backend', SAGE_LOG_LEVEL: 'debug' },
    );
    const closeHandler = (fakeProc.on as any).mock.calls.find(
      (c: any[]) => c[0] === 'close',
    )?.[1];
    if (closeHandler) closeHandler(0);

    await promise;

    const spawnArgs = (spawn as any).mock.calls[0];
    expect(spawnArgs[0]).toBe('C:\\fake\\python.exe');
    expect(spawnArgs[1]).toEqual(['-m', 'backend.cli.doctor', '--json']);
    expect(spawnArgs[2].env.PYTHONPATH).toBe('C:\\fake\\backend');
    expect(spawnArgs[2].env.SAGE_LOG_LEVEL).toBe('debug');
    expect(spawnArgs[2].env.PATH).toBeDefined();
  });
});
```

- [ ] **Step 4: 运行测试,确认 GREEN（签名已改,测试过）**

Run:
```bash
cd /home/fz/project/sage && npx vitest run electron/test_doctor_extra_env.ts
```
Expected: 1 个测试通过。

- [ ] **Step 5: commit**

```bash
git add electron/doctor.ts electron/test_doctor_extra_env.ts
git commit -m "feat(electron): runDoctorCheck 支持 extraEnv 注入 (PR-A 第 1 步)"
```

---

### Task 6: PR-A 改 main.ts 调用 + commit

**Files:**
- Modify: `electron/main.ts:819-834`

**Interfaces:**
- Consumes: `resolveBackendLaunchCommand` from `electron/backendLauncher.ts`，输出 `plan: { kind: 'spawn' | 'broken-installer' | ...; cmd: string; args: string[]; extraEnv: Record<string,string>; reason: string }`
- Produces: doctor 调用时使用 bundled python + bundled extraEnv，packaged 模式下不再命中 PATH python。

- [ ] **Step 1: 写失败测试（main.ts 集成）**

新建 `electron/test_main_doctor_uses_bundled_python.ts`：

```typescript
import { describe, it, expect, vi } from 'vitest';

vi.mock('./doctor', () => ({
  runDoctorCheck: vi.fn().mockResolvedValue({ status: 'ok', summary: '', checks: [] }),
}));
vi.mock('./backendLauncher', () => ({
  resolveBackendLaunchCommand: vi.fn().mockReturnValue({
    kind: 'spawn',
    cmd: 'C:\\Sage\\resources\\python\\python.exe',
    args: ['-m', 'backend.main'],
    extraEnv: { PYTHONPATH: 'C:\\Sage\\resources\\backend', SAGE_LOG_LEVEL: 'info' },
    reason: 'packaged-win32-bundled',
  }),
}));

import { runDoctorCheck } from './doctor';
import { resolveBackendLaunchCommand } from './backendLauncher';

describe('main.ts doctor uses bundled python (PR-A)', () => {
  it('passes bundled cmd + extraEnv to runDoctorCheck', async () => {
    const plan = (resolveBackendLaunchCommand as any).mock.results[0].value;
    expect(plan.kind).toBe('spawn');
    expect(plan.cmd).toBe('C:\\Sage\\resources\\python\\python.exe');
    expect(plan.extraEnv.PYTHONPATH).toContain('backend');
  });
});
```

- [ ] **Step 2: 修改 `electron/main.ts:819-834`**

当前：
```typescript
if (process.env.SAGE_DOCTOR_ON_START !== 'false') {
  try {
    const doctorSummary = await runDoctorCheck(
      process.env.SAGE_PYTHON ?? 'python',
      process.cwd(),
    );
    logger.info('main: doctor check complete', doctorSummary);
    if (doctorSummary.status === 'critical') {
      logger.warn('main: doctor reported CRITICAL — user may see degraded experience', {
        summary: doctorSummary.summary,
      });
    }
  } catch (err) {
    logger.warn('main: doctor check threw', { error: String(err) });
  }
}
```

改为：
```typescript
if (process.env.SAGE_DOCTOR_ON_START !== 'false') {
  try {
    // PR-A: 复用 resolveBackendLaunchCommand 已算出的 plan,让 doctor 用
    // bundled python + PYTHONPATH(否则 packaged 模式下会命中用户 PATH 里
    // 的 anaconda2 python,缺 backend 模块,doctor 永远失败)。
    const plan = resolveBackendLaunchCommand({...});
    if (plan.kind === 'spawn') {
      const doctorSummary = await runDoctorCheck(
        plan.cmd,
        process.resourcesPath ?? process.cwd(),
        DEFAULT_TIMEOUT_MS,
        plan.extraEnv,
      );
      logger.info('main: doctor check complete', doctorSummary);
      if (doctorSummary.status === 'critical') {
        logger.warn('main: doctor reported CRITICAL — user may see degraded experience', {
          summary: doctorSummary.summary,
        });
      }
    } else {
      logger.info('main: doctor skipped', { reason: plan.reason });
    }
  } catch (err) {
    logger.warn('main: doctor check threw', { error: String(err) });
  }
}
```

`resolveBackendLaunchCommand` 已经在 `main.ts` 里因 `spawnBackend()` 调用被引入。`DEFAULT_TIMEOUT_MS` 来自 `electron/doctor.ts`，确保 import 到位（如果没 import,加 `import { DEFAULT_TIMEOUT_MS } from './doctor';`）。

- [ ] **Step 3: 运行所有相关测试**

```bash
cd /home/fz/project/sage && npx vitest run electron/test_doctor_extra_env.ts electron/test_main_doctor_uses_bundled_python.ts
```
Expected: 全过。

- [ ] **Step 4: tsc 检查**

```bash
cd /home/fz/project/sage && npx tsc --noEmit -p electron/tsconfig.json 2>&1 | head -20
```
Expected: 无报错。

- [ ] **Step 5: 跑 electron smoke**

```bash
cd /home/fz/project/sage && npm run electron:smoke
```
Expected: 全过。

- [ ] **Step 6: commit + 合并**

```bash
git add electron/main.ts electron/test_main_doctor_uses_bundled_python.ts
git commit -m "fix(electron): doctor 使用 bundled python + extraEnv

PR-A: 复用 resolveBackendLaunchCommand 的 plan(含 bundled python + PYTHONPATH),
避免 packaged 模式下 doctor 命中用户 PATH 里的 anaconda2 python,导致
ModuleNotFoundError 'No module named backend'。

Refs: docs/superpowers/specs/2026-08-18-win7-critical-fixes-design.md §3 PR-A"

cd /home/fz/project/sage
git switch main
git merge --squash fix/doctor-bundled-python
git commit -m "fix(electron): doctor 使用 bundled python + extraEnv (PR-A)"
git push origin main
git branch -d fix/doctor-bundled-python
```

---

### Task 7: PR-B 准备分支 + 写失败测试（IPC ECONNREFUSED 翻译）

**Files:**
- Create: `src/shared/api/test_desktop_invoke_econnrefused.ts`

**Interfaces:**
- Consumes: `desktopInvoke` from `src/shared/api/desktopInvoke.ts:26-43`
- Produces: 抛 `Error` 时 message 含 ECONNREFUSED/fetch failed → 抛「后端服务未启动或已断开」友好提示。

- [ ] **Step 1: 建分支**

```bash
cd /home/fz/project/sage
git switch -c feat/backend-auto-restart-banner
```

- [ ] **Step 2: 写失败测试**

新建 `src/shared/api/test_desktop_invoke_econnrefused.ts`：

```typescript
import { describe, it, expect, vi } from 'vitest';

vi.mock('electron', () => ({
  ipcRenderer: { invoke: vi.fn() },
}));

import { ipcRenderer } from 'electron';
import { desktopInvoke } from './desktopInvoke';

describe('desktopInvoke ECONNREFUSED translation (PR-B)', () => {
  it('translates ECONNREFUSED to friendly Chinese error', async () => {
    (ipcRenderer.invoke as any).mockRejectedValue(
      new Error('request to http://127.0.0.1:8765/api/v1/settings failed, reason: connect ECONNREFUSED 127.0.0.1:8765'),
    );
    await expect(desktopInvoke('get_settings')).rejects.toThrow(/后端服务未启动或已断开/);
  });

  it('translates fetch failed (Node 18+) to friendly Chinese error', async () => {
    (ipcRenderer.invoke as any).mockRejectedValue(
      new TypeError('fetch failed'),
    );
    await expect(desktopInvoke('get_settings')).rejects.toThrow(/后端服务未启动或已断开/);
  });

  it('passes through non-ECONNREFUSED errors unchanged', async () => {
    (ipcRenderer.invoke as any).mockRejectedValue(
      new Error('Backend validation failed: field required'),
    );
    await expect(desktopInvoke('set_settings')).rejects.toThrow(/validation/);
  });
});
```

- [ ] **Step 3: 运行测试,确认 RED**

```bash
cd /home/fz/project/sage && npx vitest run src/shared/api/test_desktop_invoke_econnrefused.ts
```
Expected: 3 个测试都失败（当前 desktopInvoke 不翻译）。

- [ ] **Step 4: commit**

```bash
git add src/shared/api/test_desktop_invoke_econnrefused.ts
git commit -m "test(api): desktopInvoke ECONNREFUSED 友好翻译 (RED)"
```

---

### Task 8: PR-B 改 desktopInvoke + commit

**Files:**
- Modify: `src/shared/api/desktopInvoke.ts:26-43`

**Interfaces:**
- Consumes: `window.electronAPI.invoke(cmd, args)`（renderer 唯一漏斗）
- Produces: ECONNREFUSED / fetch failed → 「后端服务未启动或已断开，请稍候自动重连或重启 Sage」

- [ ] **Step 1: 定位 catch 块**

Read 命令：`sed -n '20,50p' src/shared/api/desktopInvoke.ts`

预期存在类似：
```typescript
try {
  return await window.electronAPI.invoke(cmd, args);
} catch (e) {
  // ... 现有错误处理 ...
  throw e;
}
```

- [ ] **Step 2: 加 ECONNREFUSED 翻译**

在 catch 块内、rethrow 之前,加：

```typescript
const raw = e instanceof Error ? e.message : String(e);
const isBackendDown =
  raw.includes('ECONNREFUSED') ||
  raw.includes('fetch failed') ||
  raw.includes('network error');
if (isBackendDown) {
  throw new Error('后端服务未启动或已断开，请稍候自动重连或重启 Sage');
}
throw e instanceof Error ? e : new Error(raw);
```

注意：用 `throw new Error` 替换原有 `throw e`,避免把 `TypeError` / `Error` 子类直接传出去导致 React Query 等上层库误识别为类型错误。

- [ ] **Step 3: 运行测试,确认 GREEN**

```bash
cd /home/fz/project/sage && npx vitest run src/shared/api/test_desktop_invoke_econnrefused.ts
```
Expected: 3 个测试都通过。

- [ ] **Step 4: 跑全套前端测试,确认无回归**

```bash
cd /home/fz/project/sage && npx vitest run src/shared/api
```
Expected: 全过。

- [ ] **Step 5: commit**

```bash
git add src/shared/api/desktopInvoke.ts
git commit -m "fix(api): desktopInvoke ECONNREFUSED 友好翻译

renderer 唯一漏斗处把 ECONNREFUSED / fetch failed 翻成中文提示,
让用户在 backend 断开时看到友好文案而非裸英文错误。"
```

---

### Task 9: PR-B 加 backend 自动重启 + 写失败测试

**Files:**
- Modify: `electron/main.ts:224-227`（`proc.on('exit')` 块）
- Create: `electron/test_backend_auto_restart.ts`

**Interfaces:**
- Consumes: `app.isQuitting`（Electron App lifecycle）, `mainWindow.webContents.send(event, payload)`
- Produces: backend exit 后 `restartCount` 递增；`app.isQuitting=true` 或 `restartCount>=3` 时停止重试；`backend:disconnected` / `backend:reconnected` IPC 事件正确发出。

- [ ] **Step 1: 写失败测试**

新建 `electron/test_backend_auto_restart.ts`：

```typescript
import { describe, it, expect, vi, beforeEach } from 'vitest';

vi.mock('child_process', () => ({ spawn: vi.fn() }));
vi.mock('./backendLauncher', () => ({
  resolveBackendLaunchCommand: vi.fn().mockReturnValue({
    kind: 'spawn',
    cmd: 'fake-python',
    args: [],
    extraEnv: {},
    reason: 'test',
  }),
}));
vi.mock('./mainWindow', () => ({
  mainWindow: {
    webContents: { send: vi.fn() },
  },
}));

import { scheduleBackendRestart } from './main';
import { mainWindow } from './mainWindow';

describe('backend exit auto-restart logic (PR-B)', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.useFakeTimers();
  });

  it('emits backend:disconnected with attempt=1 on first call', () => {
    scheduleBackendRestart();
    expect(mainWindow.webContents.send).toHaveBeenCalledWith('backend:disconnected', { attempt: 1 });
  });

  it('emits backend:disconnected with attempt=-1 after 3 attempts', () => {
    scheduleBackendRestart();
    scheduleBackendRestart();
    scheduleBackendRestart();
    scheduleBackendRestart();
    expect(mainWindow.webContents.send).toHaveBeenLastCalledWith('backend:disconnected', { attempt: -1 });
  });
});
```

> **注意**：本测试假设 `main.ts` 已经把 `mainWindow` 提取到 `electron/mainWindow.ts`（Task 10 步骤 4 处理）、`scheduleBackendRestart` 已经导出。如果当前 main.ts 没这两步,测试会因 import 失败而 RED,符合 TDD 流程。

- [ ] **Step 2: 运行测试,确认 RED**

```bash
cd /home/fz/project/sage && npx vitest run electron/test_backend_auto_restart.ts
```
Expected: 失败（`scheduleBackendRestart` 未导出 / `mainWindow` 模块不存在）。

- [ ] **Step 3: commit 测试**

```bash
git add electron/test_backend_auto_restart.ts
git commit -m "test(electron): backend 自动重启链路 (RED)"
```

---

### Task 10: PR-B 改 main.ts 加自动重启 + commit

**Files:**
- Modify: `electron/main.ts:224-227` + 加 `scheduleBackendRestart` 导出函数 + 加 `backend:disconnected` / `backend:reconnected` webContents.send
- Create: `electron/mainWindow.ts`（提取 mainWindow 引用,便于 mock）

**Interfaces:**
- Consumes: `app.isQuitting`, `mainWindow.webContents.send`, `waitForBackend`, `spawnBackend`, `MAX_RESTART_ATTEMPTS=3`
- Produces: 指数退避（1s/2s/4s）最多 3 次自动重启；永久失败时 attempt=-1；成功后发 `backend:reconnected`。

- [ ] **Step 1: 创建 `electron/mainWindow.ts`**

```typescript
import { BrowserWindow } from 'electron';

export let mainWindow: BrowserWindow | null = null;

export function setMainWindow(win: BrowserWindow | null): void {
  mainWindow = win;
}
```

并在 `electron/main.ts` 把原 `let mainWindow: BrowserWindow | null = null;` 删掉,改 `import { mainWindow, setMainWindow } from './mainWindow';`,把所有 `mainWindow = ...` 改 `setMainWindow(...)`,把所有读 `mainWindow` 的地方保留 import 名。

- [ ] **Step 2: 在 main.ts 顶部加常量**

在 import 块下方加：

```typescript
const MAX_RESTART_ATTEMPTS = 3;
const RESTART_BASE_DELAY_MS = 1000;
const RESTART_MAX_DELAY_MS = 8000;
let restartCount = 0;
```

- [ ] **Step 3: 在 `main.ts` 加导出函数 `scheduleBackendRestart`**

放在 `spawnBackend()` 函数附近（便于复用）：

```typescript
/**
 * PR-B: backend 进程异常退出时,指数退避自动重 spawn,最多 3 次。
 *
 * 退避序列 1s/2s/4s。第 3 次后永久失败,通过 IPC 通知 renderer 显示
 * 「请重启 Sage」横幅。用户在 app quit 触发的 exit 不重试。
 */
export function scheduleBackendRestart(): void {
  if (restartCount >= MAX_RESTART_ATTEMPTS) {
    logger.error('main: backend restart exhausted', { attempts: restartCount });
    mainWindow?.webContents.send('backend:disconnected', { attempt: -1 });
    return;
  }
  restartCount++;
  const delay = Math.min(
    RESTART_BASE_DELAY_MS * 2 ** (restartCount - 1),
    RESTART_MAX_DELAY_MS,
  );
  logger.warn('main: scheduling backend restart', {
    attempt: restartCount,
    delayMs: delay,
  });
  mainWindow?.webContents.send('backend:disconnected', { attempt: restartCount });
  setTimeout(() => {
    backendProc = spawnBackend();
    waitForBackend().then((ready) => {
      if (ready) {
        restartCount = 0;
        mainWindow?.webContents.send('backend:reconnected', {});
      }
    });
  }, delay).unref();
}
```

- [ ] **Step 4: 修改 `proc.on('exit')` handler**

当前：
```typescript
proc.on('exit', (code) => {
  logger.info('main: backend exited', { code });
  backendProc = null;
});
```

改为：
```typescript
proc.on('exit', (code) => {
  logger.info('main: backend exited', { code });
  backendProc = null;
  // PR-B: 用户主动 quit 时不重试;否则指数退避自动重 spawn
  if (!app.isQuitting) {
    scheduleBackendRestart();
  }
});
```

- [ ] **Step 5: 运行测试**

```bash
cd /home/fz/project/sage && npx vitest run electron/test_backend_auto_restart.ts
```
Expected: 2 个测试都通过。

- [ ] **Step 6: tsc + electron smoke**

```bash
cd /home/fz/project/sage && npx tsc --noEmit -p electron/tsconfig.json && npm run electron:smoke
```
Expected: 全过。

- [ ] **Step 7: commit**

```bash
git add electron/main.ts electron/mainWindow.ts electron/test_backend_auto_restart.ts
git commit -m "feat(electron): backend 进程异常退出后指数退避自动重启

PR-B 第 1 段:1s/2s/4s 最多 3 次重 spawn,失败后通过 IPC 通知 renderer。
用户主动 quit (app.isQuitting=true) 不触发重试。提取 mainWindow 到
electron/mainWindow.ts 便于单测。"
```

---

### Task 11: PR-B 加 BackendStatusBanner 组件 + 写测试

**Files:**
- Create: `src/widgets/system/BackendStatusBanner.tsx`
- Create: `src/widgets/system/test_backend_status_banner.tsx`

**Interfaces:**
- Consumes: `window.electronAPI.listen('backend:disconnected', cb)` + `listen('backend:reconnected', cb)`,返回 `off` 函数
- Produces: 三态 banner UI（reconnecting / failed / recovered）

- [ ] **Step 1: 写失败测试**

新建 `src/widgets/system/test_backend_status_banner.tsx`：

```tsx
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, act, cleanup } from '@testing-library/react';

import { BackendStatusBanner } from './BackendStatusBanner';

const mockListeners = new Map<string, (payload: any) => void>();

beforeEach(() => {
  mockListeners.clear();
  (window as any).electronAPI = {
    listen: vi.fn((event: string, cb: (payload: any) => void) => {
      mockListeners.set(event, cb);
      return () => mockListeners.delete(event);
    }),
  };
});

afterEach(() => {
  cleanup();
  vi.useRealTimers();
});

describe('BackendStatusBanner (PR-B)', () => {
  it('renders nothing when state is ok', () => {
    render(<BackendStatusBanner />);
    expect(screen.queryByRole('status')).toBeNull();
  });

  it('shows reconnecting message on backend:disconnected with attempt=1', () => {
    render(<BackendStatusBanner />);
    act(() => {
      mockListeners.get('backend:disconnected')!({ attempt: 1 });
    });
    expect(screen.getByText(/正在自动重连.*第 1\/3/)).toBeTruthy();
  });

  it('shows restart-required message on backend:disconnected with attempt=-1', () => {
    render(<BackendStatusBanner />);
    act(() => {
      mockListeners.get('backend:disconnected')!({ attempt: -1 });
    });
    expect(screen.getByText(/请重启 Sage/)).toBeTruthy();
  });

  it('shows recovered message on backend:reconnected and clears after 2s', async () => {
    vi.useFakeTimers();
    render(<BackendStatusBanner />);
    act(() => {
      mockListeners.get('backend:disconnected')!({ attempt: 1 });
    });
    act(() => {
      mockListeners.get('backend:reconnected')!({});
    });
    expect(screen.getByText(/已恢复/)).toBeTruthy();
    act(() => {
      vi.advanceTimersByTime(2100);
    });
    expect(screen.queryByText(/已恢复/)).toBeNull();
  });
});
```

- [ ] **Step 2: 运行测试,确认 RED**

```bash
cd /home/fz/project/sage && npx vitest run src/widgets/system/test_backend_status_banner.tsx
```
Expected: 4 个测试都失败（组件不存在）。

- [ ] **Step 3: commit 测试**

```bash
git add src/widgets/system/test_backend_status_banner.tsx
git commit -m "test(frontend): BackendStatusBanner 三态 UI (RED)"
```

---

### Task 12: PR-B 实现 BackendStatusBanner + commit

**Files:**
- Create: `src/widgets/system/BackendStatusBanner.tsx`
- Create: `src/widgets/system/BackendStatusBanner.css`（如果项目无对应 banner 样式）
- Modify: `src/App.tsx`（在合适位置挂载 `<BackendStatusBanner />`）

**Interfaces:**
- Consumes: `window.electronAPI.listen`, 见 Task 11 测试 mock 契约
- Produces: 持久 banner，2 秒淡出动画

- [ ] **Step 1: 实现组件**

新建 `src/widgets/system/BackendStatusBanner.tsx`：

```tsx
import { useEffect, useState } from 'react';
import './BackendStatusBanner.css';

type BannerState = 'ok' | 'reconnecting' | 'failed' | 'recovered';

export function BackendStatusBanner() {
  const [state, setState] = useState<BannerState>('ok');
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    const off1 = window.electronAPI.listen('backend:disconnected', (p: { attempt: number }) => {
      setAttempt(p.attempt);
      setState(p.attempt === -1 ? 'failed' : 'reconnecting');
    });
    const off2 = window.electronAPI.listen('backend:reconnected', () => {
      setState('recovered');
      setTimeout(() => setState('ok'), 2000);
    });
    return () => {
      off1();
      off2();
    };
  }, []);

  if (state === 'ok') return null;

  const variant = state === 'failed' ? 'error' : state === 'recovered' ? 'success' : 'warning';
  const message =
    state === 'reconnecting'
      ? `后端暂时断开，正在自动重连（第 ${attempt}/3 次）...`
      : state === 'failed'
        ? '后端连接失败，请重启 Sage'
        : '已恢复';

  return (
    <div role="status" data-testid={`backend-banner-${state}`} className={`banner banner-${variant}`}>
      {message}
    </div>
  );
}
```

新建 `src/widgets/system/BackendStatusBanner.css`：

```css
.banner {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  padding: 12px 16px;
  text-align: center;
  z-index: 9999;
  font-size: 14px;
}
.banner-warning { background: #fef3c7; color: #92400e; }
.banner-error { background: #fee2e2; color: #991b1b; }
.banner-success { background: #d1fae5; color: #065f46; }
```

- [ ] **Step 2: 挂载到 App.tsx**

找到 `src/App.tsx` 顶层渲染函数,在最外层 div 内最前面加：

```tsx
import { BackendStatusBanner } from './widgets/system/BackendStatusBanner';
// ...
<BackendStatusBanner />
```

- [ ] **Step 3: 运行测试,确认 GREEN**

```bash
cd /home/fz/project/sage && npx vitest run src/widgets/system/test_backend_status_banner.tsx
```
Expected: 4 个测试都通过。

- [ ] **Step 4: tsc + 前端单测全套**

```bash
cd /home/fz/project/sage && npx tsc --noEmit && npx vitest run src/widgets
```
Expected: 全过。

- [ ] **Step 5: commit + 合并**

```bash
git add src/widgets/system/BackendStatusBanner.tsx src/widgets/system/BackendStatusBanner.css src/widgets/system/test_backend_status_banner.tsx src/App.tsx
git commit -m "feat(frontend): BackendStatusBanner 三态 UI

PR-B 第 2 段:监听 backend:disconnected/reconnected,显示中文三态横幅
(重连中/失败请重启/已恢复)。挂载到 App 顶层,2 秒后已恢复自动消失。"

cd /home/fz/project/sage
git switch main
git merge --squash feat/backend-auto-restart-banner
git commit -m "feat(electron): backend 指数退避自动重启 + ECONNREFUSED 友好翻译 + UI banner (PR-B)"
git push origin main
git branch -d feat/backend-auto-restart-banner
```

---

### Task 13: main 回归 + cherry-pick 到 release/win7

**Files:**
- 4 个 PR 的 commit 已 squash 到 main HEAD
- 在 release/win7 上批量 cherry-pick

**Interfaces:**
- 无（git 操作）

- [ ] **Step 1: main 跑 ≥3 天**

观察 issue tracker 与 electron-smoke 跑过 3 天,确认 4 个 PR 无回归。

- [ ] **Step 2: 从 release/win7 切 feature 分支**

```bash
cd /home/fz/project/sage
git fetch origin
git switch release/win7
git pull --rebase origin release/win7
git switch -c fix/win7-batch-critical-fixes release/win7
```

- [ ] **Step 3: 批量 cherry-pick 4 个 PR**

在 main 上找出 4 个 PR 的 commit hash：

```bash
git log main --oneline -10
```

预期形如：
```
abc1234 fix(chat): TitleGenerator 走 dict 输入 + KeyError 兜底 (PR-D)
def5678 fix(memory): MemorySearchTool/SaveTool 注入 memory_manager (PR-C)
ghi9012 fix(electron): doctor 使用 bundled python + extraEnv (PR-A)
jkl3456 feat(electron): backend 指数退避自动重启 + ECONNREFUSED 友好翻译 + UI banner (PR-B)
```

按 PR-D → PR-C → PR-A → PR-B 顺序 cherry-pick：

```bash
git cherry-pick <PR-D-hash>
git cherry-pick <PR-C-hash>
git cherry-pick <PR-A-hash>
git cherry-pick <PR-B-hash>
```

如果任一冲突,按下面策略解决：
- **PR-D**：几乎不冲突（Python 文件无 main/win7 分歧）
- **PR-C**：基本无冲突；如果 hex 路径文件 win7 改了,保留双方并修 `set_memory_manager` 调用
- **PR-A**：win7 上 `electron/main.ts` 可能加了 `extractPathParams` 之类的小改动，保留 main 侧 + win7 侧都用 resolver 输出
- **PR-B**：冲突最多（涉及 main.ts + renderer + 新组件）。保留所有 + 手动合并 IPC 事件名

冲突解决后跑：

```bash
cd /home/fz/project/sage
/home/fz/anaconda3/envs/sage-backend-py38/bin/python -m pytest backend/chat backend/tools backend/core -v
npx vitest run src/shared/api src/widgets/system
npx tsc --noEmit
```

Expected: Py3.8 全过 + 前端 vitest 全过 + tsc 干净。

- [ ] **Step 4: 推 win7 分支 + 等 CI**

```bash
git push -u origin fix/win7-batch-critical-fixes
gh pr create --base release/win7 --head fix/win7-batch-critical-fixes \
  --title "chore(win7): cherry-pick PR-D/C/A/B 关键修复" \
  --body "win7 LTS 用户报告的 4 类缺陷全部 cherry-pick. 出 v0.4.8-alpha.1-win7."
gh pr checks --watch
```

Expected: win7 CI 5/5+skip 全过（Py3.8 LTS + TS + Electron ubuntu/windows + smoke）。

- [ ] **Step 5: 用户 merge + 清理**

用户 merge PR 后：
```bash
cd /home/fz/project/sage
git switch release/win7
git pull --rebase origin release/win7
git branch -d fix/win7-batch-critical-fixes
git push origin --delete fix/win7-batch-critical-fixes
```

- [ ] **Step 6: 打 win7 LTS tag + 触发 NSIS release**

按项目 `branch-and-release-strategy.md` 流程：

```bash
cd /home/fz/project/sage
git tag -a v0.4.8-alpha.1-win7 -m "v0.4.8-alpha.1-win7 — 关键修复批次 (PR-D/C/A/B)"
git push origin v0.4.8-alpha.1-win7
gh release view v0.4.8-alpha.1-win7 --json url  # 拿到 draft URL
```

Expected: win7 LTS NSIS draft release 出现,asset 为 ~157MB。

- [ ] **Step 7: 写 memory 归档**

新建 `/home/fz/.claude/projects/-home-fz-project-sage/memory/sage-pr338-win7-critical-fixes.md`：

```markdown
---
name: Sage: win7 critical fixes PR #338+ (2026-08-18)
description: main + win7 4 个关键修复 cherry-pick 闭环, v0.4.8-alpha.1-win7
metadata:
  type: project
---

PR-D: TitleGenerator dict 输入避免 KeyError, 标题不再"新对话".
PR-C: MemorySearchTool/SaveTool 注入了 memory_manager, 不再"未初始化".
PR-A: doctor 用 bundled python + PYTHONPATH, win7 上不再 ModuleNotFoundError.
PR-B: backend 指数退避自动重启(1s/2s/4s) + ECONNREFUSED 友好翻译 + 三态 banner.

win7 cherry-pick 冲突: PR-A + PR-B 涉及 electron/main.ts (win7 加了 extractPathParams),
保留两侧后合并 IPC 事件名.

CI 5/5+skip 全过, NSIS draft 上传.

**Why:** v0.4.7-alpha.1-win7 用户实测发现的 4 类阻塞缺陷.
**How to apply:** 涉及 4 个独立 PR; 未来 win7 cherry-pick 类似批次可参考本批次的冲突解决路径.
```

并在 `/home/fz/.claude/projects/-home-fz-project-sage/memory/MEMORY.md` 追加一行索引：

```markdown
- [Sage: win7 critical fixes PR #338+ (2026-08-18)](sage-pr338-win7-critical-fixes.md) — 4 PR 闭环 (D/C/A/B), v0.4.8-alpha.1-win7
```

- [ ] **Step 8: 验证结束**

✅ 仓库最终态：main HEAD 推进 4 个 commit + release/win7 HEAD 推进 1 个 squash commit + v0.4.8-alpha.1-win7 tag 已打 + memory 已归档。

---

## 自审（按 writing-plans skill 要求）

**1. Spec 覆盖**：spec §3 PR-D / PR-C / PR-A / PR-B 全部对应到 Task 2 / 4 / 6 / 8+10+12，spec §4 实施步骤对应 Task 13。

**2. Placeholder scan**：
- ❌「TBD / TODO」：无
- ❌「Add appropriate error handling」：无（每个 catch 都有具体处理）
- ❌「Similar to Task N」：无（每个测试都是独立代码块）
- ❌「Write tests for the above」：无（每个 Task 都给完整测试代码）

**3. 类型/接口一致性**：
- `MAX_RESTART_ATTEMPTS=3`、`restartCount`、`scheduleBackendRestart` 在 Task 9-12 中命名一致
- `runDoctorCheck(pythonBin, projectRoot, timeoutMs?, extraEnv?)` 在 Task 5 签名定义、Task 6 调用方匹配
- `backend:disconnected` payload `{ attempt: number }`（attempt=-1 表示永久）在 Task 9 + Task 11 + Task 12 一致

**4. 风险与依赖**：
- Task 1-4（D+C）无依赖，可并行（实际顺序按风险由小到大）
- Task 5-6（A）独立，无依赖
- Task 7-12（B）独立，A 完成后才能 e2e 验证
- Task 13 依赖 1-12 全部 main 落地