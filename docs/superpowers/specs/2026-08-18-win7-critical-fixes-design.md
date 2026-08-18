# v0.4.7-alpha.1-win7 用户报告修复 — Design Spec

**日期**：2026-08-18
**作者**：Claude + 用户
**目的**：解决 v0.4.7-alpha.1-win7 用户实测中报告的 4 类 main/win7 双端缺陷
**范围**：4 个独立 PR（PR-D → PR-C → PR-A → PR-B），合并为单个 plan
**决策**：合并为 1 个 plan / PR-B 全做（翻译+横幅+自动重启）/ 最多 3 次指数退避 / 中文上下文自适应 banner / main 全绿后一次性 cherry-pick 到 win7

---

## 1. 背景

用户在 v0.4.7-alpha.1-win7 实测中报告了多类问题（详见 session closeout）。经 main + win7 双分支调研，4 项需要**双端修复**：

| 问题 | 修复项 | 根因 |
|---|---|---|
| doctor 在 packaged 模式下命中 `E:\ProgramData\anaconda2\python.exe` 而非 bundled python | **PR-A** | `electron/main.ts:821-824` 用 `process.env.SAGE_PYTHON ?? 'python'` |
| backend 进程退出后无自动重启 + IPC ECONNREFUSED 用户看到裸英文错误 | **PR-B** | `electron/main.ts:224-227` exit handler 只 log；`src/shared/api/desktopInvoke.ts` 无 ECONNREFUSED 翻译 |
| 记忆管理器未初始化 | **PR-C** | `backend/tools/memory_tool.py` 构造时 `memory_manager=None`，生产代码 0 处 `set_memory_manager()` |
| 会话列表总显示"新对话" | **PR-D** | `backend/chat/title_generator.py:79` 构造 `Message` 对象喂 `LLMClient.chat`，触发 `KeyError` 未被 except 捕获 |

另外 5 个用户报告问题已**不需要新代码修复**：
- 日志不完整 → PR #306 已修；用户改 `SAGE_LOG_LEVEL=debug`
- max turn limit → PR #333 (main) + #335 (win7) 已合并
- 工具调用顺序 / 长内容 → PR #267 (main) + #329 (win7) 已 pick
- 子 agent 卡死 → 用户在设置页把 `max_subagent_iterations` 调到 8-10；UI 进度冒泡是长期设计项，本 plan 不包含

## 2. 目标

4 个 PR 全部合并到 main + win7 双端，并出新 LTS tag `v0.4.8-alpha.1-win7`：
- win7 用户装机后无 anaconda2 python 干扰
- backend 偶发崩溃自动恢复 + UI 横幅提示
- 记忆搜索/保存工具在所有路径可用
- 首次对话后自动生成标题

## 3. 设计（按 PR 拆分）

### PR-D：TitleGenerator dict 输入 + KeyError 兜底

**改动文件**：`backend/chat/title_generator.py`

**当前行为**：
```python
# title_generator.py:79
prompt_msg = Message(role="user", content=prompt)
resp = await self.llm_client.chat([prompt_msg])
```

**问题**：`LLMClient._convert_messages` 用 `msg["role"]` 访问（`backend/core/legacy/llm_client.py:206`），而 `Message` 是 dataclass 不支持 `[]` → 抛 `KeyError`。现有 except 列表 `(ImportError, TypeError, AttributeError)` 不含 `KeyError` → fallback 不触发 → `generate()` 返回 `None` → 标题保持"新对话"。

**修复**：直接走 dict 输入（dict 接口是 `_convert_messages` 的设计目标），并把 `KeyError` 加进 except：

```python
# title_generator.py:79-86
try:
    resp = await self.llm_client.chat([{"role": "user", "content": prompt}])
    if resp and getattr(resp, "content", None):
        return resp.content.strip()
except (ImportError, TypeError, AttributeError, KeyError):
    pass
return None
```

**测试**（`backend/chat/test_title_generator.py`）：
- mock `LLMClient.chat` 抛 `KeyError` → 返回 None 而非崩
- mock 正常 dict 输入 → 返回 content
- 主路径：end-to-end 生成标题后 `session_repo.update(title=...)` 被调用

### PR-C：MemorySearchTool/SaveTool 注入 memory_manager

**改动文件**：`backend/core/legacy/agent.py:270`

**当前行为**：`register_all_tools(self.tool_registry, ...)` 注入工具时 `memory_manager` 参数为 `None`，而这两个工具的实现 (`backend/tools/memory_tool.py:57`/`:128`) 立即抛 `"记忆管理器未初始化"`。

**修复**：

```python
# backend/core/legacy/agent.py:270 附近
from backend.memory.registry import get_memory_manager
from backend.tools.memory_tool import MemorySearchTool, MemorySaveTool

register_all_tools(self.tool_registry, ...)

# 注入全局 memory_manager 单例到所有 memory 工具
for tool in self.tool_registry.list_tools():
    if isinstance(tool, (MemorySearchTool, MemorySaveTool)):
        tool.set_memory_manager(get_memory_manager())
```

**hex 路径同理**：如果 hex ChatService 也注册 ToolRegistry，需在相同位置注入。

**测试**：
- 集成测试：agent 启动后，`MemorySearchTool.memory is not None`
- 端到端：用户在对话中调用 `memory_search` 工具，返回真实结果而非"未初始化"错误

### PR-A：doctor 使用 bundled python + PYTHONPATH

**改动文件**：`electron/main.ts:819-834` + `electron/doctor.ts:78`（签名扩展）

**当前行为**：`runDoctorCheck(process.env.SAGE_PYTHON ?? 'python', process.cwd())` 在 packaged 模式下用用户 PATH 里第一个 python（典型：anaconda2）。该 python 没有 bundled `backend` 模块 → doctor 报 `ModuleNotFoundError`。

**修复**：复用 `resolveBackendLaunchCommand()` 已经在 `spawnBackend()` 中算出的 `plan`：

```typescript
// electron/main.ts:819-834 改造
if (process.env.SAGE_DOCTOR_ON_START !== 'false') {
  try {
    const plan = resolveBackendLaunchCommand({...});
    if (plan.kind === 'spawn') {
      const doctorSummary = await runDoctorCheck(
        plan.cmd,
        process.resourcesPath ?? process.cwd(),
        DEFAULT_TIMEOUT_MS,
        plan.extraEnv,
      );
      logger.info('main: doctor check complete', doctorSummary);
    } else {
      logger.info('main: doctor skipped', { reason: plan.reason });
    }
  } catch (err) {
    logger.warn('main: doctor check threw', { error: String(err) });
  }
}
```

**`runDoctorCheck` 签名扩展**（`electron/doctor.ts:78`）：增加可选第 4 参数 `extraEnv?: Record<string, string>`，spawn 时合并到 env。

**测试**：
- 单元：mock `resolveBackendLaunchCommand` 返回 bundled python + extraEnv → `runDoctorCheck` 收到正确 `cmd` + `env`
- 集成：在 packaged NSIS 中 doctor 不再 `ModuleNotFoundError`

### PR-B：backend 自动重启 + IPC ECONNREFUSED 友好翻译 + UI banner

**改动文件**（3 处）：

1. **`electron/main.ts:224-227`** `proc.on('exit')`：加指数退避重 spawn（最多 3 次）

```typescript
// electron/main.ts spawnBackend() 内
proc.on('exit', (code) => {
  logger.info('main: backend exited', { code });
  backendProc = null;
  if (!app.isQuitting && restartCount < MAX_RESTART_ATTEMPTS) {
    restartCount++;
    const delay = Math.min(1000 * 2 ** (restartCount - 1), 8000);
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
  } else {
    mainWindow?.webContents.send('backend:disconnected', {
      attempt: -1,
    });
  }
});
```

`MAX_RESTART_ATTEMPTS = 3`，退避序列 `1s / 2s / 4s`，第 3 次后永久失败，UI 显示「请重启 Sage」。

**新增 IPC 事件**：
- `backend:disconnected` — payload `{ attempt: number }`（attempt=-1 表示永久）
- `backend:reconnected` — payload `{}`

2. **`src/shared/api/desktopInvoke.ts:26-43`** 加 ECONNREFUSED 翻译：

```typescript
catch (e: unknown) {
  const msg = e instanceof Error ? e.message : String(e);
  if (msg.includes('ECONNREFUSED') || msg.includes('fetch failed')) {
    throw new Error('后端服务未启动或已断开，请稍候自动重连或重启 Sage');
  }
  throw e;
}
```

3. **`src/widgets/system/BackendStatusBanner.tsx`**（新增组件）+ **`src/App.tsx`** 挂载：

```tsx
function BackendStatusBanner() {
  const [state, setState] = useState<'ok' | 'reconnecting' | 'failed' | 'recovered'>('ok');
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    const off1 = window.electronAPI.listen('backend:disconnected', (p) => {
      setAttempt(p.attempt);
      setState(p.attempt === -1 ? 'failed' : 'reconnecting');
    });
    const off2 = window.electronAPI.listen('backend:reconnected', () => {
      setState('recovered');
      setTimeout(() => setState('ok'), 2000);
    });
    return () => { off1(); off2(); };
  }, []);
  if (state === 'ok') return null;
  return <Banner variant={state === 'failed' ? 'error' : 'warning'}>{message}</Banner>;
}
```

**文案规则**（context-aware）：
- `state=reconnecting, attempt>0`：「后端暂时断开，正在自动重连（第 1/3 次）...」
- `state=failed`（attempt=-1）：「后端连接失败，请重启 Sage」
- `state=recovered`：「已恢复」（2 秒后自动消失）

**测试**：
- vitest：mock `window.electronAPI.listen` → 文案切换正确
- 单元：mock `proc.on('exit')` → 重 spawn 触发条件正确（不在 `app.isQuitting`）
- e2e（electron-smoke）：强制 kill backend 进程，验证 3 次重连后显示 failed banner

## 4. 实施步骤

| 步骤 | 内容 | 验收 |
|---|---|---|
| 1 | 开 PR-D + 测试 + CI 绿 | pytest 全过，PR merge |
| 2 | 开 PR-C + 测试 + CI 绿 | pytest 全过，PR merge |
| 3 | 开 PR-A + 测试 + CI 绿 | vitest + electron-smoke 过，PR merge |
| 4 | 开 PR-B + 测试 + CI 绿 | vitest + electron-smoke 过，PR merge |
| 5 | main 跑 ≥3 天，验证 4 个 PR 无回归 | 无新 issue |
| 6 | 从 develop 切 release/v0.4.8-alpha，打 alpha tag | tag v0.4.8-alpha.1 |
| 7 | 4 个 PR 批量 cherry-pick 到 release/win7 | win7 CI 5/5+skip 全过 |
| 8 | win7 出 v0.4.8-alpha.1-win7 NSIS，用户升级 | draft release 上传 |

## 5. 风险评估

| 风险 | 概率 | 影响 | 缓解 |
|---|---|---|---|
| PR-B 自动重启干扰用户主动 quit | 中 | 中 | `app.isQuitting` 守门 |
| PR-A doctor extraEnv 漏字段导致 doctor 失败 | 低 | 低 | 复用 backendLauncher 已验证的 plan |
| PR-C hex 路径漏注入 | 中 | 中 | 实施时同步检查 hex ChatService 启动路径 |
| PR-D dict 输入让 LLMClient 误用历史消息 schema | 低 | 中 | 加单元测试覆盖 |
| 4 个 PR 同时 cherry-pick 到 win7 触发大冲突 | 低 | 高 | 已在 win7 上 pick 过类似 PR（#324/#330/#331），冲突模式熟悉 |

## 6. 不在范围内（明确推迟）

- 子 agent 内部进度回传（thinking/acting/observing 冒泡到 UI）— 涉及 Wave 4 设计，本 plan 不含
- IPC `get_evolution_status/_logs` 注册 — UI 没暴露入口，YAGNI
- asyncio ProactorBasePipeTransport.__del__ stderr 抑制 — 良性噪音
- electron main 进程崩溃自动重启 — 与 backend 重启是独立问题