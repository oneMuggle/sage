# 日志系统基线修复 — 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 `sage` 已有的日志基建真正生效 —— 后端 `setup_logging()` 被调用、Electron 日志级别可运行时切换、doctor 日志路径正确、前端 store 失败进 NDJSON、office 模块不再黑盒。

**Architecture:** 6 处相互独立的"接通已有机制"改动，每处 ≤6 行。后端在 `backend/main.py` 的 `__main__` 块调用 `setup_logging()` 并把 Electron 注入的 `SAGE_LOG_LEVEL` 映射为 Python 级别；Electron 把 `CURRENT_LEVEL` 从模块常量改为可 `setLogLevel()` 运行时切换；doctor 与前端 store 各改一处路径/logger 调用；office 12 个文件各补一行 `getLogger(__name__)`。

**Tech Stack:** Python 3.11 (FastAPI/uvicorn, conda `sage-backend`)、TypeScript (Electron 主进程 vitest)、React (zustand store vitest)。

**Spec:** `docs/superpowers/specs/2026-08-12-logging-foundation-fix-design.md` (commit `2e12f075`)

## Global Constraints

- 分支：`feature/fix-logging-foundation`，每 Task 一个 commit，最终 squash 合并为 1 个 PR。
- 不修改 `backend/utils/logging.py` 本身（`setup_logging` 已写得够好，只是没人调）。
- 不新增任何 Python / npm 依赖。
- **`SAGE_LOG_LEVEL` 值域是 Electron 的小写 `debug|info|warn|error`，而 `backend/utils/logging.py:22-28` 的 `LOG_LEVELS` key 是大写 `DEBUG|INFO|WARNING|ERROR|CRITICAL`。** 直接 `.upper()` 会把 `warn` 变成 `WARN`（不是 `WARNING`）→ 静默回落 INFO。**必须用显式映射。**
- 后端日志文件是 `backend/logs/sage_YYYYMMDD.log`（下划线 + `.log`，由 `logging.py:177` 生成，记录所有级别）。NDJSON `sage-YYYY-MM-DD.ndjson` 是 Electron 的格式，两者不同名。
- 后端命令一律用 `/home/fz/anaconda3/envs/sage-backend/bin/python`（项目 CLAUDE.md 强制，禁用系统 python3）。
- 前端/Electron 测试跑 `npx vitest run <path>`。
- 后端 Python 测试跑 `/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest <path> -v`。
- **对 spec 的有益偏离（已透明标注）**：spec 原说"不写新测试"；本计划对 Fix 2/4/5/6 增加真实单测，因为对应测试文件已存在且改动便宜，符合全局 testing 规则（TDD / 80% 覆盖）。Fix 1 与 Fix 3 属集成/配置插线，无法低成本单测，保留人工验证。

---

### Task 1: backend/main.py 接通 `setup_logging()`

**Files:**
- Modify: `backend/main.py:425-433`（`__main__` 块）

**Interfaces:**
- Consumes: `backend.utils.logging.setup_logging(log_dir=None, log_level="INFO", project_root=None)` — 注意参数名是 `log_level`，无 `level=`/`json_format=`。
- Produces: 后端根 logger 配置完成（文件 handler `sage_YYYYMMDD.log` 记录全部级别 + console handler 按级别门控）；`uvicorn`/`uvicorn.error`/`uvicorn.access` 三个 logger 显式放行到 INFO 并传播到根 logger。
- 供 Task 3 消费：`os.environ["SAGE_LOG_LEVEL"]`（Electron 注入，小写）→ 映射为 Python 级别。

- [ ] **Step 1: 修改 `backend/main.py` 的 `__main__` 块**

当前（`backend/main.py:425-433`）：
```python
if __name__ == "__main__":
    import uvicorn

    port = int(os.environ.get("PYTHON_BACKEND_PORT", "8765"))
    # v2: 把本机后端地址注入环境变量,让 backend.core.legacy.llm_client.LLMConfig
    # 知道走哪个 proxy URL(默认 http://127.0.0.1:8765,所以在大多数情况下是
    # no-op,但允许 dev/CI 通过环境变量覆盖)。
    os.environ.setdefault("BACKEND_URL", f"http://127.0.0.1:{port}")
    uvicorn.run(app, host="127.0.0.1", port=port)
```

改为：
```python
if __name__ == "__main__":
    import uvicorn

    from backend.utils.logging import setup_logging

    port = int(os.environ.get("PYTHON_BACKEND_PORT", "8765"))
    # v2: 把本机后端地址注入环境变量,让 backend.core.legacy.llm_client.LLMConfig
    # 知道走哪个 proxy URL(默认 http://127.0.0.1:8765,所以在大多数情况下是
    # no-op,但允许 dev/CI 通过环境变量覆盖)。
    os.environ.setdefault("BACKEND_URL", f"http://127.0.0.1:{port}")

    # 日志基线修复 #1: 启用 setup_logging()。此前从未被调用,根 logger 保持
    # 默认 WARNING 且无文件 handler → 后端模块 logger.* 的 INFO/DEBUG 全丢。
    # SAGE_LOG_LEVEL 由 Electron 注入(取值 debug/info/warn/error,小写),
    # 需显式映射到大写 LOG_LEVELS key(尤其 warn → WARNING,upper() 会得到 WARN)。
    _LEVEL_MAP = {"debug": "DEBUG", "info": "INFO", "warn": "WARNING", "error": "ERROR"}
    _level = _LEVEL_MAP.get(os.environ.get("SAGE_LOG_LEVEL", "info").lower(), "INFO")
    setup_logging(log_level=_level)

    # uvicorn 自带 logger 默认 WARNING 且无 handler;显式放行到 INFO 并传播到
    # 根 logger,否则 log_config=None 后 access log 会被 uvicorn 自身级别过滤。
    for _name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        logging.getLogger(_name).setLevel(logging.INFO)

    uvicorn.run(app, host="127.0.0.1", port=port, log_config=None)
```

> 说明：`import logging` 已在 `backend/main.py` 顶部（第 8 行），无需重复。`setup_logging()` 仅在 `__main__` 块执行，测试 import `backend.main` 不会触发，不干扰现有测试套件。

- [ ] **Step 2: 语法检查**

Run: `/home/fz/anaconda3/envs/sage-backend/bin/python -m py_compile backend/main.py`
Expected: 无输出，退出码 0。

- [ ] **Step 3: 本地验证（人工）**

Run（后台启动，`SAGE_LOG_LEVEL=debug` 走通映射）：
```bash
cd /home/fz/project/sage
SAGE_LOG_LEVEL=debug /home/fz/anaconda3/envs/sage-backend/bin/python backend/main.py &
sleep 3
curl -s http://127.0.0.1:8765/health
kill %1
```
Expected:
- `/health` 返回 `{"status":"ok","version":"0.1.1"}`
- `backend/logs/sage_$(date +%Y%m%d).log` 存在且非空，含 `[INFO] [trace=-]` 行（如 uvicorn access log `"GET /health HTTP/1.1" 200`）
- 控制台输出中出现同一行（证明 console handler 级别生效）

- [ ] **Step 4: 确认无回归 —— 后端测试套件子集**

Run: `/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/test_utils_logging.py -q`
Expected: 全部 PASS（`setup_logging` 行为未被改动）。

- [ ] **Step 5: Commit**

```bash
git add backend/main.py
git commit -m "fix(backend): 接通 setup_logging() 让后端日志真正落盘 (#1)"
```

---

### Task 2: Electron `setLogLevel()` 运行时切换日志级别

**Files:**
- Modify: `electron/logger.ts:48`（`const CURRENT_LEVEL` → `let` + 新增导出 setter）
- Modify: `electron/ipc/logIpc.ts:96-103`（set-level handler 调 setter）
- Test: `electron/__tests__/logger.test.ts`

**Interfaces:**
- Consumes: `LogLevel` type + `LOG_LEVELS`（`src/shared/log/levels.ts`）；`resolveLevel()`（`electron/logger.ts:41-45`）。
- Produces: `export function setLogLevel(level: LogLevel): void` —— 更新 `CURRENT_LEVEL` 并同步 `log.transports.file.level`。供 logIpc 的 `sage:log:set-level` handler 调用。
- 前置：Task 1 已确认后端读 `SAGE_LOG_LEVEL` env；本 Task 让 Electron 侧真正改级别。

- [ ] **Step 1: 写失败测试**

在 `electron/__tests__/logger.test.ts` 末尾（`describe('logger')` 块内）追加：

```typescript
it('setLogLevel switches level at runtime', async () => {
  // beforeEach 已设 SAGE_LOG_LEVEL=debug 并 resetModules,导入时级别为 debug
  const mod = await import('../logger');
  mod.setLogLevel('error');

  mod.logger.info('hidden-info');
  mod.logger.error('shown-error');

  const today = new Date().toISOString().slice(0, 10);
  const file = join(tmpDir, 'logs', `sage-${today}.ndjson`);
  if (!existsSync(file)) throw new Error('no NDJSON written');

  const lines = readFileSync(file, 'utf-8').trim().split('\n').filter(Boolean);
  const levels = lines.map((l) => JSON.parse(l).level);
  expect(levels).not.toContain('info');
  expect(levels).toContain('error');
});
```

> `import('../logger')` 的类型：该测试文件已有 `importLogger()` helper 只返回 `mod.logger`；本用例需要 `mod.setLogLevel`，因此直接 `const mod = await import('../logger')`（TS 允许，`mod.setLogLevel` 在实现后存在）。

- [ ] **Step 2: 运行测试确认失败**

Run: `npx vitest run electron/__tests__/logger.test.ts -t "setLogLevel switches"`
Expected: FAIL —— `mod.setLogLevel is not a function`（尚未导出）。

- [ ] **Step 3: 实现 `setLogLevel`**

`electron/logger.ts:48`，`const CURRENT_LEVEL = resolveLevel();` → `let CURRENT_LEVEL = resolveLevel();`

在 `logger` 导出对象（`electron/logger.ts:112-129`）之前新增：

```typescript
/** 运行时切换日志级别(日志基线修复 #2)。同步 electron-log 文件 transport。 */
export function setLogLevel(level: LogLevel): void {
  CURRENT_LEVEL = level;
  try {
    log.transports.file.level = level;
  } catch {
    /* electron-log transport 在测试/无 electron 环境可能未配置,忽略 */
  }
}
```

- [ ] **Step 4: 更新 logIpc 的 set-level handler**

`electron/ipc/logIpc.ts:7` 的 import 改为：

```typescript
import { logger, setLogLevel } from '../logger';
```

`electron/ipc/logIpc.ts:96-103` 的 handler 改为：

```typescript
  ipcMain.handle(
    'sage:log:set-level',
    async (_evt, payload: { level: LogLevel }) => {
      process.env.SAGE_LOG_LEVEL = payload.level;
      setLogLevel(payload.level);
      logger.info('main: log level changed', { level: payload.level });
      return { ok: true };
    },
  );
```

- [ ] **Step 5: 运行 logger 测试确认通过**

Run: `npx vitest run electron/__tests__/logger.test.ts`
Expected: 全部 PASS（新增 + 既有 `respects SAGE_LOG_LEVEL filtering` 等）。

- [ ] **Step 6: 确认 logIpc 无回归**

Run: `npx vitest run electron/__tests__/logIpc.test.ts`
Expected: 全部 PASS（set-level 用例返回 `{ok:true}`，断言不受影响）。

- [ ] **Step 7: Commit**

```bash
git add electron/logger.ts electron/ipc/logIpc.ts electron/__tests__/logger.test.ts
git commit -m "fix(electron): 日志级别可运行时切换 — setLogLevel() (#2)"
```

---

### Task 3: backendLauncher 注入 `SAGE_LOG_LEVEL`

**Files:**
- Modify: `electron/backendLauncher.ts:239-250`（`packagedEnv`）

**Interfaces:**
- Consumes: 无新依赖；`process.env.SAGE_LOG_LEVEL`（由 Task 2 的 logIpc 写入）。
- Produces: packaged 模式下 backend 子进程 env 含 `SAGE_LOG_LEVEL`，供 Task 1 的 `_LEVEL_MAP` 读取。
- 说明：dev 模式走 `process.env` 透传（已含 SAGE_LOG_LEVEL），无需改；本改动只补 packaged 模式的显式注入。

- [ ] **Step 1: 修改 `packagedEnv`**

`electron/backendLauncher.ts:239-250`：

```typescript
function packagedEnv(
  resourcesPath: string,
  sageDbPath: string,
  sageUserDataDir: string,
  sep: string,
): Record<string, string> {
  return {
    SAGE_DB_PATH: sageDbPath,
    SAGE_USER_DATA_DIR: sageUserDataDir,
    SAGE_LOG_LEVEL: process.env.SAGE_LOG_LEVEL ?? 'info',
    PYTHONPATH: [join(resourcesPath, 'backend'), join(resourcesPath, 'sage-core')].join(sep),
  };
}
```

- [ ] **Step 2: 类型检查**

Run: `npx tsc --noEmit -p electron/tsconfig.json`
Expected: 退出码 0，无 SAGE_LOG_LEVEL 相关错误。

- [ ] **Step 3: 人工验证（限制说明）**

`packagedEnv` 仅在打包模式调用，dev 无法单测此函数。验证方式：
- 确认 Step 2 tsc 通过；
- 可选：`git diff` 确认只加了 1 行、无逻辑改动。
- 打包模式端到端验证留到 PR 的 Electron build 检查（CI 会跑 `npm run electron:build`）。

- [ ] **Step 4: Commit**

```bash
git add electron/backendLauncher.ts
git commit -m "fix(electron): packaged backend 注入 SAGE_LOG_LEVEL (#3)"
```

---

### Task 4: doctor `log_dir_size` 兼容 `SAGE_USER_DATA_DIR`

**Files:**
- Modify: `backend/cli/checks/log_dir_size.py:22-30`（`_resolve_log_dir`）
- Test: `backend/tests/unit/cli/checks/test_log_dir_size.py`

**Interfaces:**
- Consumes: `_resolve_log_dir()` 当前签名（`() -> Path`）；`_LOG_DIR_ENV = "SAGE_LOG_DIR"`（`log_dir_size.py:19`）。
- Produces: `_resolve_log_dir()` 返回路径优先级改为 `SAGE_LOG_DIR` → `SAGE_USER_DATA_DIR/logs` → `backend/logs` 兜底。与 `backend/utils/logging.py:121-125`（backend 实际写日志的路径解析）保持一致。
- 供 spec 验收标准"packaged Electron 模式下 doctor 不再永远 INFO"。

- [ ] **Step 1: 写失败测试**

在 `backend/tests/unit/cli/checks/test_log_dir_size.py` 的 `class TestResolveLogDir` 内追加两个方法（沿用既有 `mock.patch.dict(os.environ, ...)` + `tmp_path` 风格，`mock`/`os`/`_resolve_log_dir` 均已 import）：

```python
    def test_uses_sage_user_data_dir_when_log_dir_unset(self, tmp_path):
        """SAGE_LOG_DIR 未设时,回退到 $SAGE_USER_DATA_DIR/logs(与 setup_logging 一致)。"""
        with mock.patch.dict(os.environ, {"SAGE_USER_DATA_DIR": str(tmp_path)}, clear=True):
            assert _resolve_log_dir() == tmp_path / "logs"

    def test_sage_log_dir_wins_over_user_data(self, tmp_path):
        """SAGE_LOG_DIR 优先级仍最高,即使同时设了 SAGE_USER_DATA_DIR。"""
        with mock.patch.dict(
            os.environ,
            {"SAGE_LOG_DIR": str(tmp_path / "custom"), "SAGE_USER_DATA_DIR": str(tmp_path)},
            clear=True,
        ):
            assert _resolve_log_dir() == tmp_path / "custom"
```

> 既有 `TestResolveLogDir` 已覆盖 `SAGE_LOG_DIR` 优先级（`test_env_takes_precedence`）与默认兜底（`test_default_backend_logs`）；本步只补 `SAGE_USER_DATA_DIR` 两个分支。用 `clear=True` 保证确定性（不依赖测试环境残留 env）。

- [ ] **Step 2: 运行测试确认失败**

Run: `/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/cli/checks/test_log_dir_size.py -q`
Expected: 2 个新用例 FAIL（`_resolve_log_dir` 未认 `SAGE_USER_DATA_DIR`），既有用例 PASS。

- [ ] **Step 3: 实现**

`backend/cli/checks/log_dir_size.py:22-30` 改为：

```python
def _resolve_log_dir() -> Path:
    """解析日志目录。

    优先级(与 backend/utils/logging.py 的 setup_logging 一致):
    1. $SAGE_LOG_DIR(测试/重载用 env override)
    2. $SAGE_USER_DATA_DIR/logs(packaged Electron 注入,实际写日志位置)
    3. backend/logs/(相对此文件位置,dev/裸后端兜底)
    """
    env = os.environ.get(_LOG_DIR_ENV)
    if env:
        return Path(env)
    user_data = os.environ.get("SAGE_USER_DATA_DIR")
    if user_data:
        return Path(user_data) / "logs"
    # backend/cli/checks/<this>.py → backend/logs/
    return Path(__file__).resolve().parents[2] / "logs"
```

> `import os` 已在文件顶部（第 8 行），`_resolve_log_dir` 内的 `import os`（原第 24 行）可删可不删；删掉更干净，但保留也无害。建议删除以消除重复 import。

- [ ] **Step 4: 运行测试确认通过**

Run: `/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/cli/checks/test_log_dir_size.py -q`
Expected: 全部 PASS（新 2 个 + 既有 `test_log_dir_size.py` 全量）。

- [ ] **Step 5: Commit**

```bash
git add backend/cli/checks/log_dir_size.py backend/tests/unit/cli/checks/test_log_dir_size.py
git commit -m "fix(doctor): log_dir_size 兼容 SAGE_USER_DATA_DIR,packaged 下不再误报 (#4)"
```

---

### Task 5: store.ts 4 处 console.error → clientLogger.error

**Files:**
- Modify: `src/shared/lib/store.ts:93,113,128,139`（4 处 `console.error`）+ 顶部 import
- Test: `src/shared/lib/__tests__/store.test.ts`

**Interfaces:**
- Consumes: `clientLogger.error(msg: string, meta?: Record<string, unknown>)`（`src/shared/log/client.ts`，签名已确认）；`invoke`（`src/shared/lib/store.ts:4` 从 `../api/desktopInvoke` import）。
- Produces: 4 个 store action 失败时写 NDJSON（经 IPC → Electron 主进程）。
- 注意：`createSession` 失败会 `throw error`（store.ts:114），其余 3 个不 rethrow。测试需对 createSession 的 await 加 `.catch()`。

- [ ] **Step 1: 写失败测试**

在 `src/shared/lib/__tests__/store.test.ts` 顶部（`vi.hoisted` 块附近）追加 mock `invoke`：

```typescript
const { mockInvoke } = vi.hoisted(() => ({ mockInvoke: vi.fn() }));
vi.mock('../../api/desktopInvoke', () => ({
  invoke: (...args: unknown[]) => mockInvoke(...args),
}));

import { clientLogger } from '../../log/client';
```

> 注意：`vi.mock` 调用会提升到文件顶部（不受 `import` 顺序影响）；`clientLogger` 的 import 放在既有 `import { useStore } from '../store'` 附近即可。

在文件末尾追加：

```typescript
describe('store failure logging', () => {
  beforeEach(() => {
    mockInvoke.mockReset();
    useStore.setState({ sessions: [], messages: [], currentSessionId: null });
  });

  it.each([
    ['loadSessions', 'store.loadSessions failed'],
    ['createSession', 'store.createSession failed'],
    ['deleteSession', 'store.deleteSession failed'],
    ['loadMessages', 'store.loadMessages failed'],
  ])('%s failure logs via clientLogger.error', async (action, msg) => {
    mockInvoke.mockRejectedValue(new Error('boom'));
    const spy = vi.spyOn(clientLogger, 'error').mockImplementation(() => {});
    const st = useStore.getState() as unknown as Record<string, (arg?: string) => Promise<unknown>>;
    await (st[action] as (arg?: string) => Promise<unknown>)('sess-1').catch(() => {});
    expect(spy).toHaveBeenCalledWith(msg, { error: 'Error: boom' });
    spy.mockRestore();
  });
});
```

- [ ] **Step 2: 运行测试确认失败**

Run: `npx vitest run src/shared/lib/__tests__/store.test.ts`
Expected: 4 个 `it.each` 用例 FAIL（store 仍走 `console.error`，`clientLogger.error` 未被调用）。

- [ ] **Step 3: 实现**

`src/shared/lib/store.ts` 顶部（第 4 行 `invoke` import 之后）新增：

```typescript
import { clientLogger } from '../log/client';
```

4 处替换：

- `store.ts:93`：
```typescript
    } catch (error) {
      clientLogger.error('store.loadSessions failed', { error: String(error) });
    }
```
- `store.ts:113`：
```typescript
    } catch (error) {
      clientLogger.error('store.createSession failed', { error: String(error) });
      throw error;
    }
```
- `store.ts:128`：
```typescript
    } catch (error) {
      clientLogger.error('store.deleteSession failed', { error: String(error) });
    }
```
- `store.ts:139`：
```typescript
    } catch (error) {
      clientLogger.error('store.loadMessages failed', { error: String(error) });
      set({ isLoading: false });
    }
```

> `String(error)`：`Error('boom')` → `"Error: boom"`，与测试断言一致。`clientLogger` 在非 Electron 环境（`window.electronAPI` 缺失）时 DEV 下回退 console、prod 静默，不会新增崩溃路径。

- [ ] **Step 4: 运行测试确认通过**

Run: `npx vitest run src/shared/lib/__tests__/store.test.ts`
Expected: 全部 PASS（新增 4 个 + 既有 `setCurrentSessionId` 用例）。

- [ ] **Step 5: Commit**

```bash
git add src/shared/lib/store.ts src/shared/lib/__tests__/store.test.ts
git commit -m "fix(frontend): store 4 个核心 action 失败改走 clientLogger 进 NDJSON (#5)"
```

---

### Task 6: office 模块补 logger

**Files:**
- Modify: `backend/office/` 下 12 个非 `__init__` 的 .py 文件
- Test: 新建 `backend/tests/unit/office/test_office_loggers.py`（若 `backend/tests/unit/office/` 不存在则创建目录）

**Interfaces:**
- Consumes: 无。
- Produces: 12 个模块各暴露模块级 `logger = logging.getLogger(__name__)`，后续模块内 `logger.*` 调用自动生效（本 Task 不新增业务调用点）。
- 12 个文件清单：`chat_refs.py`、`errors.py`、`excel.py`、`models.py`、`path_safety.py`、`ppt.py`、`session_workspace.py`、`storage.py`、`tool_service.py`、`word.py`、`workspace_errors.py`、`workspace_search.py`。**不改 `__init__.py`。**

- [ ] **Step 1: 写失败测试**

新建 `backend/tests/unit/office/test_office_loggers.py`：

```python
"""Smoke: backend/office 各模块暴露模块级 logger(日志基线修复 #6)。"""
from __future__ import annotations

import importlib
import logging

import pytest

# 除 __init__.py 外 backend/office/ 下全部模块
_OFFICE_MODULES = [
    "chat_refs",
    "errors",
    "excel",
    "models",
    "path_safety",
    "ppt",
    "session_workspace",
    "storage",
    "tool_service",
    "word",
    "workspace_errors",
    "workspace_search",
]


@pytest.mark.parametrize("name", _OFFICE_MODULES)
def test_office_module_exposes_logger(name: str) -> None:
    mod = importlib.import_module(f"backend.office.{name}")
    assert hasattr(mod, "logger")
    assert isinstance(mod.logger, logging.Logger)
```

- [ ] **Step 2: 运行测试确认失败**

Run: `/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/office/test_office_loggers.py -q`
Expected: 12 个用例 FAIL（`hasattr(mod, "logger")` 为 False）。

- [ ] **Step 3: 实现**

对 12 个文件（`backend/office/{chat_refs,errors,excel,models,path_safety,ppt,session_workspace,storage,tool_service,word,workspace_errors,workspace_search}.py`）各自在**现有 import 区之后**添加：

```python
import logging

logger = logging.getLogger(__name__)
```

> 若某文件已 `import logging`（本次改动前 0 处 logger 调用，预计都没有），则只加 `logger = logging.getLogger(__name__)` 一行。放置位置统一为文件顶部 import 块之后、第一个函数/类定义之前。

- [ ] **Step 4: 运行测试确认通过**

Run: `/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/office/test_office_loggers.py -q`
Expected: 12 个用例 PASS。

- [ ] **Step 5: 确认无 import 回归**

Run: `/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/office/ -q`
Expected: 全部 PASS（既有 office 单测不受影响；`importlib.import_module` 会触发各模块顶层 import，若有依赖缺失会在此暴露）。

- [ ] **Step 6: Commit**

```bash
git add backend/office/ backend/tests/unit/office/test_office_loggers.py
git commit -m "feat(office): 12 个模块补模块级 logger,office 不再黑盒 (#6)"
```

---

## 集成验证（全部 Task 完成后、PR 前）

在 `feature/fix-logging-foundation` 分支末尾执行一次全量验证：

1. **后端**：`/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/cli/checks/test_log_dir_size.py backend/tests/unit/office/test_office_loggers.py backend/tests/unit/test_utils_logging.py -q`
2. **前端 + Electron**：`npx vitest run electron/__tests__/logger.test.ts electron/__tests__/logIpc.test.ts src/shared/lib/__tests__/store.test.ts`
3. **类型**：`npx tsc --noEmit`（或仓库实际使用的 typecheck 命令，见 package.json）
4. **人工冒烟**：Task 1 Step 3 的后端启动命令，确认 `backend/logs/sage_YYYYMMDD.log` 有 INFO 行。
5. 确认无新 `console.error` 散落到生产代码：`grep -rn "console.error" src/shared/lib/store.ts` 应无命中。

## 验收标准对照（spec §验收标准）

| spec 标准 | 覆盖 Task |
|---|---|
| 后端启动后日志文件存在且含 INFO 行 | Task 1（文件实为 `sage_YYYYMMDD.log`，非 spec 笔误的 NDJSON 名） |
| Electron UI 改级别后新 NDJSON 行用新级别 | Task 2 |
| backend 日志级别随 SAGE_LOG_LEVEL（打包模式） | Task 1 + Task 3 |
| doctor log_dir_size 打包模式下读真实目录 | Task 4 |
| store 4 个失败路径进 NDJSON | Task 5 |
| office 调用有日志 | Task 6（logger 已暴露，调用点后续接入） |
| 既有 pytest + vitest 全绿 | 各 Task Step + 集成验证 |
| 无新 console.error | Task 5 + 集成验证第 5 条 |

## 文档归档（PR 合并后）

- `docs/technical/29-electron-logging.md`：末尾加 §修复记录，记 Task 2（setLogLevel）+ Task 3（SAGE_LOG_LEVEL 注入）
- `docs/technical/41-sage-doctor.md`：§日志路径优先级，记 Task 4
- 本计划与 spec 不归档（`docs/superpowers/` 下 plans/specs 属进行中产物；功能落地后并入技术手册相应章节）
