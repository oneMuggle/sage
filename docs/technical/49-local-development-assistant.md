# 48 · 本地开发环境助手（Runtime Assistant）

> 2026-09 · Stage 0–6 完整落地

---

## 1. 背景与目标

Sage 桌面端用户经常遇到"环境错配"类问题：
Python 解释器版本冲突、Node.js 缺失、venv 没激活、conda 环境指向错误路径……
传统 CLI 工具（`which` / `where` / `pyenv versions`）输出原始、需要人脑解释。

本地开发环境助手把"运行时发现 / 诊断 / 试跑"封装成三个结构化 REST 端点 +
一个 Settings Tab + agent 工具链路，让 LLM / 用户都能直接消费。

**目标**：
- 只读发现本机可用运行时（Python、Node.js、未来可扩展）
- 推断项目类型并诊断运行时是否齐备
- 提供"试跑"入口验证运行时真实可用（经 PermissionEnforcer 审批，与 Bash 同等闸口）
- 复用既有安全矩阵，不引入新权限模型

**非目标（第一版边界）**：
- ❌ 不自动安装缺失的运行时（只报问题，不修问题）
- ❌ 不做远程 / SSH 目标机探测（仅本机）
- ❌ 不做 Docker / WSL 内部探测（未来 adapter 可扩展）

---

## 2. 架构总览

```
┌──────────────────┐     ┌────────────────┐      ┌─────────────────────┐
│ React Settings   │────▶│ runtimeApi.ts  │─IPC─▶│ electron/commands.ts│
│ RuntimeEnvTab    │     │ (3 methods)    │      │ COMMAND_ROUTES      │
└──────────────────┘     └────────────────┘      └──────────┬──────────┘
                                                            │ HTTP fetch
                                                            ▼
┌──────────────────┐                            ┌──────────────────────┐
│ Agent stream     │─tool call event──────────▶│ backend/api/runtime_ │
│ (Chat)           │                            │ routes.py            │
└──────────────────┘                            └──────────┬───────────┘
                                                           │ dispatch
                                                           ▼
                                                ┌──────────────────────┐
                                                │ ChatService.tools    │
                                                │ (InprocToolAdapter)  │
                                                └──────────┬───────────┘
                                                           │ PermissionEnforcer
                                                           ▼
                                                ┌──────────────────────┐
                                                │ RuntimeProbeTool     │
                                                │ ProjectDiagnoseTool  │
                                                │ RuntimeExecTool      │
                                                └──────────────────────┘
```

**关键设计决策**：
- **复用 `ChatService.tools` 路径**（不新建 `ToolRegistry`）→ 自动继承
  InprocToolAdapter + MemoryManager 注入 + PermissionEnforcer 矩阵
- **runtime_exec 走 EXEC 风险等级** → 与 BashTool 同等审批闸口，不可旁路
- **REST 端点返回 `ToolCallEnvelope`**（`{success, output?, error?, metadata?}`）
  → 与 LLM agent 看到的结构一致，UI / agent 共用一份契约

---

## 3. 后端模块

### 3.1 领域模型（`backend/domain/runtime.py`）

| 类型 | 字段 | 说明 |
|---|---|---|
| `RuntimeSource` | `Literal['system', 'conda', 'venv', 'project', 'toolchain', 'unknown']` | 发现来源 |
| `RuntimeCapability` | `can_execute` / `can_install_packages` / `has_build_tools` | 能力旗标 |
| `RuntimeInfo` | `language`, `path`, `version`, `is_default`, `is_compatible`, `source`, `capabilities`, `labels`, `manifest` | 单个运行时 |
| `ProbeResult` | `runtimes`, `recommended`, `errors` | probe 输出 |
| `Diagnostic` | `level`, `severity`, `code`, `message`, `fix_hint` | 单个诊断 |
| `ProjectDiagnosis` | `project_type`, `required_languages`, `diagnostics`, `satisfied` | diagnose 输出 |
| `ExecutionResult` | `exit_code`, `stdout`, `stderr`, `duration_seconds`, `success` | exec 输出 |
| `ProbeRequest` / `DiagnoseRequest` / `ExecRequest` | … | 输入请求 |

### 3.2 适配器注册（`backend/tools/runtime_adapter.py`）

`AdapterRegistry` 单例 + `register_default_adapters()` 幂等注册。
目前实现：
- `PythonAdapter` — `sys.executable` + conda env 扫描 + venv 发现
- `NodeAdapter` — `node` binary PATH 搜索 + 工具链（npm/pnpm/yarn/bun）

`AdapterContext` 传入 workspace_root + safe_run（subprocess 封装）。

### 3.3 工具（`backend/tools/runtime_*.py`）

| 工具 | 风险等级 | 说明 |
|---|---|---|
| `runtime_probe` | READ | 只读探测 |
| `project_diagnose` | READ | 只读诊断（基于 probe 结果 + 工作区文件推断） |
| `runtime_exec` | EXEC | 代码执行，PermissionEnforcer 拦截 |

`runtime_probe.py` 在模块顶层调用 `register_default_adapters()`，确保 standalone 使用（如 doctor check）也能拿到已注册的适配器。幂等，与 `register_all_tools` 重复调用无副作用。

### 3.4 REST 端点（`backend/api/runtime_routes.py`）

```
POST /api/v1/runtime/probe     → ProbeRequestBody → ToolCallEnvelope<ProbeResult>
POST /api/v1/runtime/diagnose  → DiagnoseRequestBody → ToolCallEnvelope<ProjectDiagnosis>
POST /api/v1/runtime/exec      → ExecRequestBody → ToolCallEnvelope<ExecutionResult>
```

**错误路径**：
- `chat_service` 未注入（lifespan 未完成） → **503** `chat_service 未初始化`
- 工具未注册 → **503** `runtime 工具未注册: <name>`
- 工具执行失败 → **200** `{success: false, error: ...}`（fail-open，与 InprocToolAdapter 一致）

### 3.5 Doctor CLI 集成（`backend/cli/checks/runtime_env.py`）

复用 `RuntimeProbeTool` 直接实例化（不经过 chat_service）。
- Python ×0 → CRITICAL
- Node.js ×0 → WARN
- 其它 → INFO

fail-open：工具实例化异常时报告 degraded，不阻塞整个 doctor。

---

## 4. Electron 与前端

### 4.1 IPC 路由（`electron/commands.ts`）

```typescript
runtime_probe:    { method: 'POST', path: () => '/api/v1/runtime/probe' },
runtime_diagnose: { method: 'POST', path: () => '/api/v1/runtime/diagnose' },
runtime_exec:     { method: 'POST', path: () => '/api/v1/runtime/exec' },
```

默认 camelCase→snake_case 翻译（body 字段均为单段标识符，无 user-defined keys）。

### 4.2 TypeScript 类型（`src/shared/api/runtimeTypes.ts`）

与 Python 模型字段一一对应，snake_case 拼写保持 round-trip 一致。

### 4.3 API 客户端（`src/shared/api/runtimeApi.ts`）

```typescript
runtimeApi.probe(req?: ProbeRequest): Promise<ToolCallEnvelope<ProbeResult>>
runtimeApi.diagnose(req?: DiagnoseRequest): Promise<ToolCallEnvelope<ProjectDiagnosis>>
runtimeApi.exec(req: ExecRequest): Promise<ToolCallEnvelope<ExecutionResult>>
```

### 4.4 Settings Tab（`src/pages/settings/RuntimeEnvTab.tsx`）

三区块：
- **ProbePanel** — 本机运行时按语言分组，推荐项带"推荐"徽章
- **DiagnosePanel** — 项目类型 + 满足度 + severity 着色徽章的诊断列表
- **ExecPanel** — 运行时下拉 + 代码文本域 + 执行按钮 + 输出渲染（success/denied/error 三态）

进入 tab 自动 `useEffect` 触发 probe + diagnose；exec 需用户主动点击。

### 4.5 Chat 渲染（`src/shared/lib/humanize.ts`）

新增 3 个 case：
- `runtime_probe` → `Probe <languages>`（无参 → `Probe available runtimes`）
- `project_diagnose` → `Diagnose <project_root>`（无参 → `Diagnose workspace`）
- `runtime_exec` → `Run in <language>` `scope: local`

---

## 5. 安全与权限

| 工具 | 风险等级 | 审批 |
|---|---|---|
| `runtime_probe` | READ | 无需审批 |
| `project_diagnose` | READ | 无需审批 |
| `runtime_exec` | EXEC | 经 PermissionEnforcer，默认 deny，与 BashTool 同等闸口 |

`runtime_exec` 的 `env_overrides` 不允许覆盖 `SAGE_LOCAL_AUTH_TOKEN` 等敏感凭据
（在 ExecRequestBody 文档中显式声明；实际拦截在 InprocToolAdapter 内完成）。

`cwd` 建议位于 `workspace_root` 内（路径约束检查由 RuntimeExecTool 内部做）。

---

## 6. 测试覆盖

| 测试文件 | 数量 | 覆盖 |
|---|---|---|
| `backend/tests/unit/tools/test_runtime_probe.py` | — | 工具单元 |
| `backend/tests/api/test_runtime_routes.py` | 7 | 3 端点 200 + 2 个 503 + 字段映射 |
| `backend/tests/unit/cli/test_doctor.py` | 15 项 | runtime_env check |
| `src/shared/lib/__tests__/humanize.test.ts` | +4 | 3 工具 chat 渲染 |

---

## 7. 已知局限与演进

- **仅本机**：远程 / Docker / WSL 内部需新 adapter
- **Python / Node 优先**：其它语言（Ruby / Go / Rust）按需加 adapter
- **无自动修复**：诊断结果仅展示，下一步可考虑"一键生成修复 SKILL.md"
- **版本约束粗粒度**：当前 `target_version` 仅做 `>=` 比较，未实现 semver range

---

## 8. 相关文件

- 后端：`backend/domain/runtime.py`, `backend/tools/runtime_adapter.py`,
  `backend/tools/runtime_{probe,diagnose,exec}.py`, `backend/api/runtime_routes.py`,
  `backend/cli/checks/runtime_env.py`
- Electron：`electron/commands.ts`
- 前端：`src/shared/api/runtime{Api,Types}.ts`, `src/pages/settings/RuntimeEnvTab.tsx`,
  `src/pages/settings/Settings.tsx`, `src/shared/lib/humanize.ts`
