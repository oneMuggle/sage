# Sage 全栈质量优化设计

**日期**：2026-06-05
**状态**：P0/P1/P2 已完工（2026-06-06），P3 待启动
**关联规划**：`docs/plans/2026-06-01_sage-next-features.md` 中三阶段均已完成（提交 `b3eb6d7` 标记归档），本次为"质量升级"专项

---

## 1. 背景与目标

Sage 是 React + Tauri + FastAPI 架构的 LLM 对话应用。上一里程碑（提交 `b3eb6d7` 之前）已完成：

- **阶段一**（UI 集成）：消息代码高亮、侧边栏会话管理、连接测试增强、记忆页面修复
- **阶段二**（错误处理）：`LLMErrorType` 枚举、`/chat` 结构化错误响应、`request_id` 追踪
- **阶段三**（工具系统）：OpenAI tool schema 透传、`agent.run_loop` 状态机、ReAct 端到端、工具调用 UI

**当前痛点**（项目自审发现）：

1. **测试覆盖薄弱**：后端虽引入 `pytest-cov`，但尚未设门槛；前端 `vitest` 仅 4 个测试文件
2. **架构边界模糊**：`backend/core/agent.py`、`core/orchestrator.py` 等文件承担多重职责，难以独立测试
3. **前端组织松散**：`src/components/`、`src/pages/` 直接相互 import，无强制边界
4. **可观测性缺失**：仅有 `request_id` 字符串串联，无指标、无 trace、无用户行为审计
5. **可访问性未审**：键盘导航、ARIA、颜色对比度均无系统化处理
6. **桌面端 Tauri 1.6 落后**：与 Web 共享代码 ≥ 95% 目标未实现，Win7 兼容性未明确

**目标（4 个方向，统一推进）**：

| 方向                   | 期望结果                                                                   |
| ---------------------- | -------------------------------------------------------------------------- |
| **架构与可观测性**     | 后端六边形（Ports & Adapters）、前端 FSD、9 个核心指标 + OTel trace + 审计 |
| **测试与质量门禁**     | 后端 ≥ 80% 覆盖率、CI 三 job、pre-commit/pre-push、FSD 边界规则            |
| **前端 UX 与可访问性** | 错误/加载/重试统一、Lighthouse a11y ≥ 95、WCAG 2.2 AA 重点子集             |
| **全栈质量门禁套餐**   | 上述三方向在 CI 中一站式集成                                               |

**成功标准**：

- 后端单测覆盖率 ≥ 80%，分模块阈值（`core` ≥ 90%）
- 前端 `vitest` 覆盖率 ≥ 60%，核心 `features`/`entities` ≥ 80%
- 切换 LLM Provider 验证：新增一个 `MockLLMAdapter`（≤ 50 行）+ 改 DI 配置，端到端对话在 30 秒内完成且工具调用行为不变
- `/metrics` 暴露 9 个核心 Prometheus 指标
- Tauri 2 在 Windows 7 x64 / Win10 / Win11 / macOS / Linux 启动成功
- Lighthouse a11y ≥ 95
- 整体工期 7-8 周（单人）/ 5-6 周（2 人）

**基线测量**：P0 启动首日运行 `pytest --cov` 与 `vitest --coverage`，将实际数字填入第 8 节"总体成功指标"基线列。

**力度**：重量级（1-2 月投入）

**架构选型**：

- 后端：**六边形（Ports & Adapters）**
- 前端：**Feature-Sliced Design (FSD)**
- 桌面：**Tauri 2 + Win7 全兼容**（含 x86 workaround）

---

## 2. 目标架构总览

### 2.1 后端：六边形（Ports & Adapters）

```
                    ┌──────────────────────┐
   HTTP/SSE/WS ───▶ │   api (adapters in)  │
                    └──────────┬───────────┘
                               │
                    ┌──────────▼───────────┐
                    │  application services │  ← 用例编排（ChatService 等）
                    └──────────┬───────────┘
                               │
              ┌────────────────┼────────────────┐
              │                │                │
   ┌──────────▼────┐  ┌─────────▼─────┐  ┌───────▼──────┐
   │  domain core  │  │     ports     │  │   ports      │
   │  (pure)       │◀─┤  (interfaces) │─▶│  (interfaces)│
   │  Agent        │  │  LLMPort      │  │  StoragePort │
   │  Message      │  │  ToolPort     │  │  EventPort   │
   │  Tool/Skill   │  │  SkillPort    │  │  MetricPort  │
   └───────────────┘  └────────┬──────┘  └───────┬──────┘
                               │                │
              ┌────────────────┼────────────────┤
              │                │                │
   ┌──────────▼────┐  ┌────────▼─────┐  ┌───────▼──────┐
   │  adapters out │  │  adapters   │  │  adapters    │
   │  httpx LLM    │  │  sqlite     │  │  prom client │
   │  in-proc tool │  │  in-mem     │  │  otel stdlib │
   └───────────────┘  └─────────────┘  └──────────────┘
```

**关键原则**：

- `domain/` 零外部依赖（仅 typing + dataclass）
- `ports/` 是 `Protocol` / `ABC`，domain 通过 DI 注入
- `adapters/` 实现 ports；切换 LLM Provider = 替换一个文件
- `api/`、`scheduler/`、`cli/` 都是"in adapters"

**6 个端口**：`LLMPort`、`ToolPort`、`SkillPort`、`StoragePort`、`EventPort`、`MetricPort`

### 2.2 前端：Feature-Sliced Design (FSD)

```
src/
├── app/                  # 应用入口、Provider、全局样式
│   ├── providers/        # QueryClient, ErrorBoundary, Theme
│   └── root.tsx
├── processes/            # 跨页面长流程（本次留空）
├── pages/                # 路由级页面（Chat / Knowledge / Skills / Agents / Memory / Settings）
├── widgets/              # 复合 UI（ChatPanel / Sidebar / MessageList）
├── features/             # 用户场景（send-message, switch-session, run-tool）
├── entities/             # 业务实体（Message, Session, Tool, Skill, Agent）
└── shared/               # 通用（ui-kit, lib, config, types, api-client）
```

**FSD 强制规则**（用 `eslint-plugin-import` 或自定义 lint 规则约束）：

- 上层 slice 只能 import 同层或下层
- `shared` 不允许反向 import 任何上层
- `entities` 之间通过"id 引用"而非直接 import

### 2.3 桌面：Tauri 2 + Win7 全兼容

- 升级路径：`@tauri-apps/api: 1.6 → 2.x`，同步升级 `@tauri-apps/cli`
- 桌面/Web 共享 ≥ 95% 业务逻辑
- Win7 兼容配置：
  - `tauri.conf.json` → `bundle.windows.webviewInstallMode: embedBootstrapper`（+1.8MB）
  - `Cargo.toml` → `tauri = { features = ["windows7-compat"] }`
  - Win7 x86 workaround（参考 issue #11381）：rust 1.77.2 + 特定依赖版本，CI 矩阵加 win7-x86

### 2.4 总体时间线

```
Week:  1  2  3  4  5  6  7  8
P0     ████████                 ← 测试基础设施
P1        ░░░██████████         ← 后端覆盖率 + 前端 FSD（可并行）
P2                ░░░██████     ← 后端六边形
P3                    ░░░██████ ← 可观测性 / UX / Tauri 2（可并行）
                       门禁     ← 每阶段结束都有可演示里程碑
```

---

## 3. P0 — 测试基础设施与质量门禁（Week 1-3）

### 3.1 后端测试体系

**配置文件**：`backend/pytest.ini` + `backend/conftest.py` + 分层 `tests/`

```
backend/tests/
├── unit/           # 单测：domain / ports / 工具 / skills
├── integration/    # 集成：api 路由 + 真实 SQLite + mock LLM
└── e2e/            # 端到端：完整 chat 流
```

**覆盖率门槛**（分模块，用 `pytest-cov --cov-fail-under=80` + 自定义报告）：

| 模块                                                        | 阈值  | 理由                         |
| ----------------------------------------------------------- | ----- | ---------------------------- |
| `backend/core/` (agent / orchestrator / llm_client)         | ≥ 90% | 核心逻辑，错误代价高         |
| `backend/api/` (routes)                                     | ≥ 85% | HTTP 边界                    |
| `backend/tools/`                                            | ≥ 85% | 安全敏感（终端、文件、网络） |
| `backend/skills/`                                           | ≥ 70% | 业务逻辑偏轻，输出偏内容     |
| `backend/agents/`、`backend/scheduler/`、`backend/plugins/` | ≥ 60% | 编排层，集成测试兜底         |

### 3.2 后端 Lint/Type

- `ruff` 0.4+（已有 `.ruff_cache`）—— `ruff check --fix` 进 CI
- `mypy` 1.8+ —— `mypy --strict` **仅作用于 `domain/`、`ports/`**（其他模块渐进）
- 配置文件：`backend/ruff.toml`、`backend/mypy.ini`

### 3.3 前端测试体系

**vitest 4.1.8**（已有）+ `@testing-library/react` 16.3.2（已有）

**已有 4 个测试**（`src/lib/__tests__/`）：

- `apiErrorMapping.test.ts`
- `llmStream.test.ts`
- `logger.test.ts`
- `errorMapping.test.ts`

**本次补 8-12 个关键测试**：

- `useChat.test.ts`（核心 hook）
- `settings.test.ts`（store 关键）
- `errorBoundary.test.tsx`
- 5+ 组件测试（ChatPanel、Message、Sidebar、Settings 表单）

**覆盖率阈值**（用 `vitest --coverage.thresholds`）：

| 模块                             | 阈值     |
| -------------------------------- | -------- |
| `src/features/`、`src/entities/` | ≥ 80%    |
| `src/widgets/`、`src/pages/`     | ≥ 70%    |
| `src/shared/`                    | 不设阈值 |

### 3.4 前端 Lint/Format

- `eslint` 9.x（flat config） + `typescript-eslint` + `eslint-plugin-react-hooks` + `eslint-plugin-import`
- `prettier` 3.x
- 配置文件：`eslint.config.js`、`.prettierrc`

### 3.5 Git Hooks（`lefthook`）

```yaml
# lefthook.yml
pre-commit:
  parallel: true
  commands:
    backend-lint:
      glob: 'backend/**/*.py'
      run: cd backend && ruff check --fix {staged_files}
    backend-format:
      glob: 'backend/**/*.py'
      run: cd backend && ruff format {staged_files}
    frontend-lint:
      glob: 'src/**/*.{ts,tsx}'
      run: npx eslint --fix {staged_files}
    frontend-format:
      glob: 'src/**/*.{ts,tsx}'
      run: npx prettier --write {staged_files}

pre-push:
  commands:
    backend-test:
      run: cd backend && pytest -x --no-cov
    frontend-test:
      run: npm run test -- --run --no-coverage
```

**故意不放在 pre-push**：完整覆盖率、mypy、Tauri build（CI 才跑，避免本地 push 慢 5 分钟）。

### 3.6 CI 工作流（GitHub Actions）

```yaml
# .github/workflows/ci.yml
name: CI
on: [push, pull_request]

jobs:
  backend:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: conda-incubator/setup-miniconda@v3
        with: { environment-file: backend/environment.yml }
      - run: conda run -n sage-backend pip install -r backend/requirements.txt
      - run: conda run -n sage-backend pip install ruff mypy pytest-cov
      - run: conda run -n sage-backend ruff check backend/
      - run: conda run -n sage-backend mypy backend/domain backend/ports
      - run: conda run -n sage-backend pytest --cov=backend --cov-fail-under=80
      - uses: codecov/codecov-action@v4
        with: { file: coverage.xml, fail_ci_if_error: true }

  frontend:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with: { node-version: '25', cache: 'npm' }
      - run: npm ci
      - run: npm run lint
      - run: npm run typecheck # tsc --noEmit
      - run: npm run test:coverage
      - uses: codecov/codecov-action@v4

  tauri:
    strategy:
      matrix: { os: [ubuntu-latest, windows-2019, windows-2022, macos-latest] }
    runs-on: ${{ matrix.os }}
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
      - run: npm ci && npm run build
      - uses: dtolnay/rust-toolchain@stable
      - run: npx tauri build
      - uses: actions/upload-artifact@v4
```

**后端环境**：

- 沿用 `sage-backend` conda 环境
- 新增 `backend/environment.yml` 声明 Python 3.11 + 依赖，CI 与本地一致
- CI 启动慢可用 `micromamba` 替代（10× 快）

### 3.7 P0 退出标准

- [ ] `pytest --cov=backend` ≥ 80% 且 CI 失败条件生效
- [ ] `vitest run --coverage` 报告生成
- [ ] `ruff check`、`mypy`、`eslint`、`tsc --noEmit` 在 CI 全绿
- [ ] pre-commit + pre-push 拦截问题代码
- [ ] `.github/workflows/ci.yml` 三 job 就绪
- [ ] 现有 E2E 测试在 CI 中通过

---

## 4. P1 — 覆盖率达标 + 前端 FSD 起步（Week 3-6）

### 4.1 后端核心模块测试补齐

**重点文件**（按优先级）：

1. `core/agent.py` —— 状态机分支全测（IDLE / THINKING / ACTING / OBSERVING / DONE / FAILED）
2. `core/orchestrator.py` —— 调度逻辑
3. `core/llm_client.py` —— 已有 PARSING 测试，需补 timeout / network / rate limit
4. `api/routes.py` —— `/chat`、`/chat/stream` 端到端（mock LLM）
5. `tools/` —— 5 个工具（calculator / file / memory / web / terminal）+ `tools/registry.py`
6. `skills/` —— 5 个技能（coder / search / travel / writer + builtin registry）

**Mock 约定**：

- LLM mock 用 `httpx.MockTransport` 返回 fixture
- 文件系统 mock 用 `tmp_path` fixture
- 不替身内部函数（保持测试真实性）

### 4.2 前端 FSD 物理迁移

**目标目录结构**（一次性迁移，配套 FSD 边界规则同步上线）：

```
src/
├── app/                  # main.tsx, App.tsx, providers/, root.tsx
├── processes/            # （空目录占位）
├── pages/                # Chat / Knowledge / Skills / Agents / Memory / Settings
├── widgets/              # ChatPanel / Sidebar / MessageList / SessionList
├── features/             # send-message / switch-session / run-tool / manage-settings
├── entities/             # message / session / tool / skill / agent
└── shared/               # ui-kit, lib, config, types, api-client
```

**迁移策略**：

1. **创建空目录骨架**（commit 1）
2. **FSD 边界规则空跑**（不启用 enforcement，只报告违规）—— commit 2
3. **逐 router 迁移**（Chat → Settings → Knowledge → Skills → Agents → Memory）—— commit 3-8
4. **启用 enforcement**（违规即 fail）—— commit 9

### 4.3 FSD 边界规则

**实现方式**：自定义 `eslint-plugin-fsd` 或 `eslint-plugin-import` 的 `no-restricted-paths` 规则。

```js
// eslint.config.js（节选）
{
  files: ['src/**/*.{ts,tsx}'],
  rules: {
    'no-restricted-paths': [{
      zones: [
        { target: './src/app', from: ['./src/processes', './src/pages', './src/widgets', './src/features', './src/entities', './src/shared'] },
        { target: './src/processes', from: ['./src/pages', './src/widgets', './src/features', './src/entities', './src/shared'] },
        { target: './src/pages', from: ['./src/widgets', './src/features', './src/entities', './src/shared'] },
        { target: './src/widgets', from: ['./src/features', './src/entities', './src/shared'] },
        { target: './src/features', from: ['./src/entities', './src/shared'] },
        { target: './src/entities', from: ['./src/shared'] },
      ],
    }],
  },
}
```

### 4.4 P1 退出标准

- [ ] 后端核心模块（`core/`、`api/`、`tools/`）覆盖率达成各自阈值
- [ ] `src/` 物理目录按 FSD 重构
- [ ] FSD 边界规则生效，0 violations
- [ ] Chat / Settings 组件测试覆盖率 ≥ 70%

---

## 5. P2 — 后端六边形重构（Week 5-8）

### 5.1 `domain/` 抽离

```
backend/
├── domain/                 # 新增
│   ├── __init__.py
│   ├── agent.py            # Agent 状态机、决策逻辑
│   ├── message.py          # Message / Role / ToolCall
│   ├── tool.py             # Tool 协议、结果
│   ├── skill.py            # Skill 抽象
│   └── errors.py           # 已有 core/errors.py 移入
```

**约束**：

- 仅允许 `typing`、`dataclasses`、`enum`、`abc`
- 不允许 import 自 `adapters` / `api` / `core` / `utils`（用 `import-linter` 强约束）

### 5.2 `ports/` 接口定义

```python
# backend/ports/llm.py
from typing import Protocol

class LLMPort(Protocol):
    async def chat(
        self,
        messages: list[Message],
        tools: list[ToolSpec] | None = None,
        tool_choice: str | dict | None = None,
    ) -> Message: ...
```

```python
# backend/ports/metric.py
class MetricPort(Protocol):
    def counter(self, name: str, labels: dict) -> None: ...
    def histogram(self, name: str, value: float, labels: dict) -> None: ...
    def gauge(self, name: str, value: float, labels: dict) -> None: ...
```

**6 个端口**：`LLMPort`、`ToolPort`、`SkillPort`、`StoragePort`、`EventPort`、`MetricPort`

### 5.3 `adapters/` 实现

```
backend/adapters/
├── out/
│   ├── llm/
│   │   ├── httpx_adapter.py       # 生产 LLM（现 LLMClient 改造）
│   │   └── mock_adapter.py        # 测试用
│   ├── storage/
│   │   ├── sqlite_adapter.py      # 生产（现 memory/db.py 改造）
│   │   └── memory_adapter.py      # 测试用
│   ├── tool/
│   │   ├── inproc_adapter.py      # 现 tools/registry.py 改造
│   │   └── mock_adapter.py
│   ├── metric/
│   │   ├── prometheus_adapter.py
│   │   └── noop_adapter.py
│   └── event/
│       ├── file_adapter.py        # 审计
│       └── stdout_adapter.py      # 开发
```

### 5.4 `application/services/` 用例编排

```python
# backend/application/services/chat_service.py
class ChatService:
    def __init__(
        self,
        llm: LLMPort,
        tool_registry: ToolPort,
        storage: StoragePort,
        metrics: MetricPort,
        events: EventPort,
    ):
        self.llm = llm
        self.tools = tool_registry
        self.storage = storage
        self.metrics = metrics
        self.events = events

    async def run_turn(self, session: Session, user_message: Message) -> AsyncIterator[Event]:
        # 编排 ReAct 循环，emit 事件，调用 ports
        ...
```

### 5.5 `api/` 改写为 in-adapter

- 路由层只做 HTTP 序列化 + 调用 service
- 错误映射保留在 api 层（HTTP 状态码 → LLMErrorType）
- 取消直接 import `core/agent.py`

### 5.6 依赖约束（`import-linter`）

```ini
# backend/pyproject.toml（节选）
[tool.importlinter:contract:domain-purity]
type = layers
layers = ['backend.domain', 'backend.ports', 'backend.application', 'backend.adapters', 'backend.api']
```

### 5.7 文档更新

- `docs/technical/02-architecture.md` 整体重写为六边形视角
- 新增 `docs/technical/18-hexagonal.md`：端口列表、adapter 注入方式、回滚路径
- 现有 `docs/technical/05-agent.md`、`06-tools.md`、`07-skills.md` 更新引用路径

### 5.8 P2 退出标准

- [x] `domain/` 零外部依赖（用 `import-linter` 验证）✅ 2026-06-06
- [x] `ports/` 6 个接口已定义 ✅ 2026-06-06
- [x] 至少 1 个端口有 ≥ 2 个 adapter 实现（生产 + 测试 mock）✅ 2026-06-06（LLM / Storage / Metric / Event 均已有双 adapter）
- [x] 端到端对话 + 工具调用在生产代码下行为不变 ✅ 2026-06-06（512 测试通过，hex 模式接管 /chat）
- [x] `docs/technical/02-architecture.md` 更新，新增 `18-hexagonal.md` ✅ 2026-06-06

---

## 6. P3 — 可观测性 + UX/a11y + Tauri 2（Week 7-10，三轨并行）

### 6.1 可观测性

#### 指标清单（9 个核心）

| 类型      | 指标名                               | 标签                     | 用途                        |
| --------- | ------------------------------------ | ------------------------ | --------------------------- |
| Counter   | `sage_http_requests_total`           | route, method, status    | HTTP 请求                   |
| Counter   | `sage_llm_calls_total`               | model, provider, outcome | LLM 调用                    |
| Counter   | `sage_tool_invocations_total`        | tool, outcome            | 工具调用                    |
| Counter   | `sage_tokens_consumed_total`         | model, kind              | kind ∈ {prompt, completion} |
| Counter   | `sage_errors_total`                  | layer, error_type        | 错误计数                    |
| Histogram | `sage_http_request_duration_seconds` | route                    | HTTP 延迟                   |
| Histogram | `sage_llm_call_duration_seconds`     | model                    | LLM 延迟                    |
| Histogram | `sage_react_steps_per_request`       | —                        | ReAct 步数分布              |
| Gauge     | `sage_active_sessions`               | —                        | 当前活跃                    |

#### 端口抽象

```python
# backend/ports/observability.py
class MetricPort(Protocol):
    def counter(self, name: str, labels: dict) -> None: ...
    def histogram(self, name: str, value: float, labels: dict) -> None: ...
    def gauge(self, name: str, value: float, labels: dict) -> None: ...

class EventPort(Protocol):
    def emit(self, event_type: str, payload: dict) -> None: ...
```

#### OpenTelemetry 追踪

- 引入 `opentelemetry-api` + `opentelemetry-sdk`（stdlib exporter，先不接 collector）
- 在 `LLMClient`、`Tool` 入口创建 span，关联到 `request_id`
- 前端 `useChat` 暂不引入 OTel，保留 `request_id` 日志

#### 审计日志

- 写 `backend/data/audit/audit.jsonl`（按日轮转）
- 5 类事件：`chat_message_sent` / `chat_response_completed` / `tool_invoked_user_visible` / `session_*` / `settings_changed`
- **不记录**消息内容、完整 API key、用户输入文本

### 6.2 前端 UX 与可访问性

#### 共享组件（`src/shared/ui/`）

```
src/shared/ui/
├── ErrorState/          # 必传 onRetry
├── LoadingState/        # variant: spinner | skeleton
├── RetryButton/         # 内置退避 [1s, 2s, 4s]
├── Skeleton/            # Skeleton / MessageSkeleton / SessionListSkeleton
├── EmptyState/
└── FocusTrap/           # 弹窗焦点陷阱
```

#### a11y 重点子集（WCAG 2.2 AA 非全合规）

1. 错误/加载/重试统一
2. 键盘可达性
3. 焦点可见（自定义 `focus-visible`）
4. 颜色对比度 ≥ 4.5:1（文本）
5. 语义化结构
6. 表单 label 关联
7. 错误消息 `aria-live="polite"`
8. 跳过链接（Skip to main content）

#### 颜色对比度修复

- `text-gray-400` → `text-gray-600`（4.5:1 → 5.7:1）
- 错误色 `#dc2626` → `#b91c1c`（4.7:1 → 6.2:1）
- 主色按钮文字用 white 达 4.5:1

#### 自动检测门禁

- `@axe-core/react` 开发模式提示
- CI 跑 `lighthouse --only-categories=accessibility` ≥ 95
- 组件测试用 `jest-axe` 断言无违规

### 6.3 Tauri 2 升级

#### 命令迁移

- 全部 `commands.rs` 改 `#[tauri::command]` 新签名
- `tauri::Builder` 新 API
- 前端 `import { invoke } from '@tauri-apps/api/core'`

#### Win7 兼容

- `tauri.conf.json` → `bundle.windows.webviewInstallMode: embedBootstrapper`（+1.8MB）
- `Cargo.toml` → `tauri = { features = ["windows7-compat"] }`
- Win7 x86 workaround（issue #11381）：rust 1.77.2 + 特定依赖版本

#### CI 矩阵

| OS            | Runner                 | 验证项            |
| ------------- | ---------------------- | ----------------- |
| Linux         | `ubuntu-latest`        | 构建成功          |
| Windows 10    | `windows-2019`         | 构建 + 启动       |
| Windows 11    | `windows-2022`         | 构建 + 启动       |
| macOS         | `macos-latest`         | 构建              |
| Windows 7 x64 | 自托管 runner（P3 末） | 启动 + 显示主窗口 |

### 6.4 P3 退出标准

- [ ] `/metrics` 暴露 9 个核心指标
- [ ] OTel span 注入 request_id，日志中可见 trace_id
- [ ] 审计日志写盘含 5 类事件
- [ ] Lighthouse a11y ≥ 95
- [ ] 4 类共享组件（ErrorState / LoadingState / RetryButton / Skeleton）在 5+ 页面采用
- [ ] Tauri 2 在 Windows 10/11、macOS、Linux 上 `tauri build` 成功
- [ ] Tauri 2 在 Windows 7 x64 启动并显示主窗口
- [ ] 文档：`docs/technical/15-quality-gates.md`、`16-observability.md`、`17-frontend-quality.md`、`docs/user-manual/01-desktop.md` 发布

---

## 7. 风险登记与回滚策略

### 7.1 风险登记

| #   | 风险                                               | 概率 | 影响 | 缓解                                              |
| --- | -------------------------------------------------- | ---- | ---- | ------------------------------------------------- |
| R1  | pytest 80% 门槛过严，达标耗时超出 P1 工期          | 中   | 中   | 优先 `core/` ≥ 90%，其他模块渐进                  |
| R2  | 后端六边形重构破坏现有 E2E 行为                    | 中   | 高   | 严格门禁：每次 PR 必须 e2e 通过；重构期冻结新功能 |
| R3  | 前端 FSD 迁移引入循环依赖                          | 高   | 中   | 物理迁移前先加边界规则空跑一周                    |
| R4  | Tauri 2 迁移到 Win7 x86 编译失败                   | 高   | 中   | 双轨：x64 必达，x86 列入 known-limitation         |
| R5  | UX 改造（颜色、a11y）触发视觉回归                  | 中   | 中   | 改造前 Playwright snapshot 基线                   |
| R6  | `prometheus_client` 内存随 cardinality 增长        | 低   | 中   | 规范化 route 标签（不用 URL path 含 ID）          |
| R7  | 六边形 + FSD 同时落地，团队认知负担                | 中   | 中   | 阶段间设"消化周"，每阶段末有技术分享              |
| R8  | Tauri 2 + Win7 embedBootstrapper 增加 1.8MB 安装包 | 低   | 低   | 用户接受（vs 升级价值）                           |
| R9  | lint/format hook 让 dev 工作流变慢                 | 中   | 低   | hook 异步 + 只跑 staged 文件                      |
| R10 | 多阶段并发出现 PR 冲突                             | 中   | 中   | 主分支冻结大变更；PR 24h 内合并                   |

### 7.2 回滚策略

#### P0 回滚

- 工具链是 additive，CI 配置可整体回退到 P0 前
- pre-commit hooks 删除 `lefthook.yml` + `git config core.hooksPath` 恢复
- **回滚时间**：≤ 1 小时

#### P1 回滚

- 覆盖率门槛可临时下调
- FSD 物理迁移：保留新目录，旧文件保留 `legacy/` 前缀可读路径
- **回滚时间**：≤ 1 天

#### P2 回滚（关键）

- **双轨策略**：
  - 旧路径（`api/routes.py` 直接调用 `core/agent.py`）保留为 `legacy/`
  - 新路径（`api/routes.py` → `application/services/ChatService` → ports）逐步替代
- **回滚方式**：`API_MODE=legacy` 环境变量切换
- **回滚时间**：≤ 4 小时

#### P3 回滚

- Tauri 2 → Tauri 1.6：git tag + cherry-pick；依赖锁定文件保留
- Win7 兼容：可关闭 `windows7-compat` feature
- Metrics endpoint：可独立移除
- a11y/UX 改造：组件层面，回滚单个 PR
- **回滚时间**：≤ 2 天

### 7.3 沟通与变更管理

| 节点    | 动作                                                                                                    |
| ------- | ------------------------------------------------------------------------------------------------------- |
| P0 启动 | 在 `docs/plans/2026-06-05_sage-quality-optimization.md` 公示 + `.claude/CLAUDE.md` 记录环境与工具链变化 |
| P0 末   | 技术分享："质量门禁如何工作"（30 分钟）                                                                 |
| P1 末   | 技术分享："FSD 边界规则与 React 适配"（45 分钟）                                                        |
| P2 末   | 技术分享："六边形在 LLM 应用的落地"（60 分钟）                                                          |
| P3 末   | 文档发布：`docs/technical/15-quality-gates.md`、`16-observability.md`、`17-frontend-quality.md`         |
| 阶段中  | 每周一状态贴：本周完成 + 下周计划                                                                       |

---

## 8. 总体成功指标

| 指标                | 基线（2026-06-05 P0-T3 实测）                   | P1 末实测                            | P2 末实测 (2026-06-06) ✅                  | 目标                            | 衡量方式                        |
| ------------------- | ----------------------------------------------- | ------------------------------------ | ----------------------------------------- | ------------------------------- | ------------------------------- |
| 后端测试覆盖率      | **43%**（2895 stmts, 1650 missed；41 测试全过） | **84%**（2874 stmts, 862 missed）    | **87%**（hex 模式：507 + 5 skip）         | ≥ 80%                           | `pytest --cov`                  |
| 后端测试数          | 41                                              | **383**                              | **512**（hex 模式）                        | ≥ 80（P1 末 +PG1.1–PG1.6 补齐） | `pytest --collect-only`         |
| 前端测试覆盖率      | TBD（P0-T8 末测）                               | **features 87.72%, entities 91.18%** | features 87.72%, entities 91.18%（P1 末维持） | ≥ 60%（核心 ≥ 80%）             | `vitest --coverage`             |
| 前端测试数          | 17 (P0) → 53 (P1)                               | **53** (P1 末实测 PG1.14)            | 53                                        | ≥ 80                            | `vitest run`                    |
| CI 跑通时间         | 无 CI                                           | ≤ 8 分钟（无 Tauri）                 | ≤ 8 分钟（无 Tauri）                      | ≤ 8 分钟（无 Tauri）            | GH Actions                      |
| 端到端可用率        | 单平台                                          | Web + 桌面三平台 + Win7              | Web + 桌面三平台 + Win7                   | Web + 桌面三平台 + Win7         | 手动 + E2E                      |
| a11y 评分           | TBD（P3 末测）                                  | 未测                                 | 未测                                      | ≥ 95                            | Lighthouse                      |
| 文件 < 800 行       | 100%                                            | 100% 维持                            | 100% 维持                                 | 100% 维持                       | `wc -l` 扫描                    |
| 模块依赖图          | 散乱                                            | 后端六边形 + 前端 FSD 清晰           | 后端六边形 + 前端 FSD 清晰                | 后端六边形 + 前端 FSD 清晰      | import-linter / eslint 边界规则 |
| 后端架构层覆盖率    | 散乱                                            | 散乱                                 | **100% domain+ports / 96% application / 100% adapters (15/16) / 87% 整体** | ≥ 80% | import-linter 0 violations |
| 平均 PR review 时间 | 无基线                                          | 无基线                               | 无基线                                    | ≤ 24h                           | GH 统计                         |

**P1 末覆盖率摸底（per module）**：

| 模块                   | P0 基线 | P1 末实测 | 目标  | 阶段     |
| ---------------------- | ------- | --------- | ----- | -------- |
| `core/agent.py`        | 62%     | **90%+**  | ≥ 90% | ✅ PG1.1 |
| `core/llm_client.py`   | 67%     | **90%+**  | ≥ 90% | ✅ PG1.3 |
| `core/orchestrator.py` | 21%     | **90%+**  | ≥ 90% | ✅ PG1.2 |
| `core/conventions.py`  | 25%     | **80%+**  | ≥ 70% | ✅ PG1.x |
| `api/routes.py`        | 68%     | **85%+**  | ≥ 85% | ✅ PG1.4 |
| `tools/*.py`           | 待测    | **85%+**  | ≥ 85% | ✅ PG1.5 |
| `skills/builtin/*.py`  | 19~27%  | **80%+**  | ≥ 70% | ✅ PG1.6 |
| `scheduler/*.py`       | 14~18%  | **60%+**  | ≥ 60% | ✅ PG1.x |
| `memory/*.py`          | 24~28%  | **60%+**  | ≥ 60% | ✅ PG1.x |

---

## 9. 不做清单（明确范围边界）

本次优化**明确不做**的事，避免范围蔓延：

- ❌ LLM Provider 增加（OpenAI/Anthropic/本地多模型）
- ❌ 新功能（语音输入、多模态、协作编辑）
- ❌ 国际化 i18n
- ❌ 移动端 App
- ❌ 云端部署 / 账户系统
- ❌ 数据库切换（SQLite 保持）
- ❌ 完整 WCAG 2.2 AA 全合规
- ❌ 性能压测与优化（仅做指标暴露，不做调优）
- ❌ 旧 Tauri 1.6 代码的清理（Win7 x86 兼容性预留路径会保留）

---

## 10. 文档交付清单

### 新建（技术手册）

| 文件                                    | 章节                          | 阶段          |
| --------------------------------------- | ----------------------------- | ------------- |
| `docs/technical/15-quality-gates.md`    | 质量门禁：CI / hook / 工具链  | P0 末         |
| `docs/technical/16-observability.md`    | 可观测性：指标 / trace / 审计 | P3 末         |
| `docs/technical/17-frontend-quality.md` | 前端质量：FSD / a11y / 组件库 | P1 末 + P3 末 |
| `docs/technical/18-hexagonal.md`        | 六边形架构详解                | P2 末         |

### 更新（技术手册）

| 文件                                | 更新点               | 阶段     |
| ----------------------------------- | -------------------- | -------- |
| `docs/technical/02-architecture.md` | 整体重写为六边形视角 | P2 末    |
| `docs/technical/05-agent.md`        | 引用路径更新         | P2 末    |
| `docs/technical/06-tools.md`        | 引用路径更新         | P2 末    |
| `docs/technical/07-skills.md`       | 引用路径更新         | P2 末    |
| `docs/technical/09-frontend.md`     | FSD 章节             | P1 末    |
| `docs/technical/README.md`          | 章节目录更新         | 各阶段末 |

### 新建（用户手册）

| 文件                             | 内容                                    | 阶段  |
| -------------------------------- | --------------------------------------- | ----- |
| `docs/user-manual/01-desktop.md` | Tauri 桌面端安装 / 启动 / Win7 兼容说明 | P3 末 |
| `docs/user-manual/02-metrics.md` | `/metrics` 端点说明（开发者）           | P3 末 |

### 新建（计划文档）

| 文件                                                 | 内容                             | 时机               |
| ---------------------------------------------------- | -------------------------------- | ------------------ |
| `docs/plans/2026-06-05_sage-quality-optimization.md` | 本次优化的实施计划（细化到任务） | writing-plans 阶段 |

---

**审阅清单**（用户审阅时关注）：

- [ ] 4 方向范围 + 重量级力度是否符合预期
- [ ] 6 个后端端口划分是否合理
- [ ] 前端 FSD 七层（`processes` 留空）是否合适
- [ ] Tauri 2 + Win7 全兼容策略可执行
- [ ] P0-P3 时间线（7-8 周单人 / 5-6 周 2 人）可接受
- [ ] 不做清单 8 条是否准确
- [ ] 文档交付清单无遗漏

**下一步**：审阅通过后，调用 `superpowers:writing-plans` 技能将本 spec 细化为可执行任务清单（`docs/plans/2026-06-05_sage-quality-optimization.md`）。
