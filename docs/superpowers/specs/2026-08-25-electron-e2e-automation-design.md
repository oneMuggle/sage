# Electron 端到端自动化测试基础设施 Design

> 状态: 设计中
> 日期: 2026-08-25
> 范围: Sage 项目（main 分支），不动 release/win7

## 1. 背景与目标

Sage 项目当前已有三层自动化测试，但**没有覆盖 5 个核心功能（对话 / agent 编排 / LLM wiki / 记忆系统 / 进化）的端到端 Electron 桌面验证**：

- 前端 vitest：17 个组件测试，全部 mock 后端，无法验证 Electron 主进程与真实渲染层之间的 IPC 契约。
- 后端 pytest：70+ 个集成测试，使用真实 conda 后端 + 真实 LLM，覆盖了 5 个功能但**仅在 backend 进程边界内**——没有覆盖 React UI → preload bridge → Electron main → backend 的整条链路。
- Playwright Electron E2E（`tests/electron/`）：3 个 spec（office/permission/question-answer）共用 948 行 `stub_backend.py`，仅实现 chat + workspace + office_refs 鉴权；4 个功能（编排 / wiki / 记忆 / 进化）的 stub 端点完全不存在。

用户期望：在本地或 CI 启动真实 Electron 应用后，能自动验证对话、agent 编排、LLM wiki、记忆系统、进化等核心功能。当前结构无法做到这一点：

1. stub_backend 覆盖面不足，无法用 hermetic 模式验证后 4 个功能；
2. 真实后端 E2E 跑全量会触发真实 LLM 调用，本地 dev loop 不友好、CI flaky、token 成本高；
3. 没有按"开发阶段"分级的能力（dev 内循环 vs PR gate vs nightly vs release）——现有 `SAGE_SKIP_BACKEND=1` / `SAGE_SKIP_E2E=1` 是粗粒度开关，不是分级开关。

本设计的目标是建立一套**覆盖 5 个核心功能、可按 4 个开发阶段激活、用 stub 和真实后端双层后端**的 Electron E2E 自动化测试基础设施，让以下四种工作流都能找到合适的验证手段：

- 写代码 → 30-60s 内得到 stub smoke 反馈（本地内循环）；
- 开 PR → 5-10 min 内得到 stub 全量 + 真实后端 boot smoke 反馈（PR 门禁）；
- 每夜 → 30-60 min 内得到 stub 全量 + 真实 LLM 调用的 deep E2E 反馈（nightly）；
- 发版前 → 60-120 min 内加上 NSIS 打包产物冒烟（手动/Release）。

**非目标**：

- 不重写现有 3 个 spec（office/permission/question-answer）；按"git mv 平迁"方式归入新 tier 结构。
- 不修改真实后端的任何代码；stub 与真实后端的契约差异通过文档约定，stub 不替代真实后端测试。
- 不在本设计中改造 release/win7 分支；win7 的 E2E 策略另起 spec。
- 不引入新测试框架；继续用 `@playwright/test`（Node）+ pytest（Python stub unit）。

## 2. 已确认的现状

### 2.1 现有测试结构

| 路径 | 工具 | 内容 |
|---|---|---|
| `src/__tests__/` + `src/pages/__tests__/` | vitest | 17 个 `*.test.tsx`，mock 后端 |
| `backend/tests/unit/` `integration/` `e2e/` `contract/` `parity/` | pytest | 70+ Python 测试 |
| `tests/electron/` | `@playwright/test` + Python stub | 3 个 spec + 948 行 `stub_backend.py` + 29 个 stub unit test |
| `tests/e2e/` + `tests/packaging/` | `@playwright/test` | 浏览器侧 3 个 spec |
| `e2e/` (根) | 空 | 仅有 `__pycache__/` |
| `playwright.config.ts` | — | 已配置 3 个 project: `electron` / `e2e` / `e2e-root` |

### 2.2 stub_backend.py 已实现的端点（948 行）

- `GET /health`
- `POST/GET /api/v1/sessions` + `GET /api/v1/sessions/:id`
- `PUT/GET/DELETE /api/v1/sessions/:id/workspace`
- `GET /api/v1/sessions/:id/workspace/files`
- `POST /api/v1/chat/stream` + `GET /api/v1/chat/stream/:stream_id` (NDJSON)
- office_refs 鉴权逻辑（workspace_not_bound / workspace_path_mismatch）

### 2.3 五功能的现有 E2E 覆盖矩阵

| 功能 | 后端单测/集成 | Playwright Electron E2E |
|---|---|---|
| Chat（对话） | `test_chat_*.py` (15+) + `tests/electron/question-answer.spec.ts` | ✅ |
| Agent 编排 | `test_chat_orchestration_*.py` + `test_orchestration_router_exec_integration.py` + `src/pages/__tests__/Orchestration.test.tsx` | ❌ |
| LLM wiki | `backend/wiki/` 有 13 个模块，但 `backend/tests/integration/` 与 `unit/` 中 wiki 专项测试稀缺 | ❌ |
| 记忆系统 | `test_routes_memory*.py` (3 个) + `test_memory_tool_injection.py` + `src/pages/__tests__/Memory.export.test.tsx` | ❌ |
| 进化 | `test_evolution_scheduler_runs.py` + `test_routes_evolution.py` | ❌ |

### 2.4 项目已有的环境变量开关

- `SAGE_SKIP_BACKEND=1`：renderer 跳过真实后端 IPC（用于纯前端冒烟）
- `SAGE_SKIP_E2E=1`：跳过 Electron E2E（CI runner 没构建产物时）
- `PYTHON_BACKEND_PORT`：Electron main 读取，控制后端端口（默认 8765）
- `SAGE_BACKEND_URL`：renderer 读取的完整 base URL
- `CI`：CI 模式下 reporter 切换为 line + html

### 2.5 关键风险（设计必须正面回应）

- **stub 漂移**：stub 是简化实现，契约变化时容易忘记同步。缓解：每个 stub 端点必须配 unit test（test_stub_backend.py）。
- **真实 LLM 成本**：nightly 跑全量 LLM 会消耗 token。缓解：限定 nightly 跑的 live-deep spec 子集（chat + memory only），release 阶段才跑全部。
- **Electron 冷启动慢**：CI runner 上 20-30s 一次冷启动。缓解：保留现有 `retries: 2 on CI` 模式，spec 用 `beforeAll` 复用 Electron 实例。
- **stub 与真实后端 schema 不一致**：缓解：spec 文件中明确"以 `backend/<module>/models.py` 的 Pydantic 为准"，stub 端点必须 1:1 对齐。

## 3. 范围与非目标

### 3.1 本次范围

1. **目录重构**：在 `tests/electron/` 下新建 `tiers/{stub,live}/{smoke,deep}/` 子目录；现有 3 个 spec 用 `git mv` 平迁进去。
2. **stub_backend.py 扩展**：在 948 行基础上新增约 21 个端点，覆盖 5 个核心功能（chat 已有，新增编排 5 + wiki 5 + 记忆 6 + 进化 5 = 21 个端点）。
3. **conftest.py 扩展**：增加 `real_backend()` fixture，支持真实 conda sage-backend 启动。
4. **playwright.config.ts 新增 4 个 project**：electron-stub-smoke / electron-stub-deep / electron-live-boot / electron-live-deep。
5. **package.json 新增 5 个 npm script**：test:smoke / test:pr / test:nightly / test:release / test:dev。
6. **GitHub Actions 新增 2 个 workflow**：`.github/workflows/e2e-pr-gate.yml` + `.github/workflows/e2e-nightly.yml`。
7. **test_stub_backend.py 扩展**：从 29 个 case 扩展到 ~50 minimum / ~80 stretch，覆盖 5 个核心模块 (chat / orchestration / wiki / memory / evolution) 的 happy-path 契约。
8. **fixtures/ 目录**：共享 test seed data（sample_session.json / sample_memory.json / sample_orchestration.json）。
9. **README.md 重写**：完整 tier + stage 文档。

### 3.2 本次非目标

- 不在 release/win7 上实施此设计；win7 的 E2E 策略另起 spec。
- 不修改 backend/ 下任何真实业务代码；stub 是独立模块。
- 不引入新的测试框架或工具链；继续用 `@playwright/test` + pytest。
- 不实现"自动重试 LLM 调用直到通过"等 flaky 缓解逻辑——用确定性 stub + 真实 LLM temperature=0 解决。
- 不在本设计中集成性能/负载测试；性能验证另起。

## 4. 架构与目录结构

### 4.1 总体架构

```
                     ┌────────────────────────────────────────┐
                     │  Playwright test runner (Node.js)      │
                     │  --project={electron-*}                │
                     └─────────────────┬──────────────────────┘
                                       │
              ┌────────────────────────┼────────────────────────┐
              │                        │                        │
              ▼                        ▼                        ▼
   ┌──────────────────────┐  ┌──────────────────────┐  ┌──────────────────┐
   │ tiers/stub/smoke +   │  │ tiers/stub/deep      │  │ tiers/live/boot  │
   │ tiers/live/boot      │  │ tiers/live/deep      │  │ tiers/live/deep  │
   │       (--project=    │  │       (--project=    │  │       (--project=│
   │        electron-     │  │        electron-     │  │        electron- │
   │        stub-smoke)   │  │        stub-deep)    │  │        live-*)   │
   └──────────┬───────────┘  └──────────┬───────────┘  └────────┬─────────┘
              │                         │                        │
              ▼                         ▼                        ▼
   ┌──────────────────────┐  ┌──────────────────────┐  ┌──────────────────────┐
   │ stub_backend.py      │  │ stub_backend.py      │  │ conda sage-backend   │
   │ (in-memory SQLite)   │  │ (in-memory SQLite)   │  │ (sqlite + LLM API)   │
   │ + Electron (built)   │  │ + Electron (built)   │  │ + Electron (built)   │
   │ 无 conda、无 LLM     │  │ 无 conda、无 LLM     │  │ 需 conda + LLM key   │
   └──────────────────────┘  └──────────────────────┘  └──────────────────────┘
```

### 4.2 目录结构（最终态）

```
tests/electron/
├── README.md                          # 重写
├── conftest.py                        # 扩展：stub_backend() + real_backend()
├── stub_backend.py                    # 扩展：+~600 行（5 功能端点）
├── test_stub_backend.py               # 扩展：29 → ~50 minimum / ~80 stretch unit case
├── fixtures/                          # 新建
│   ├── __init__.py
│   ├── sample_session.json
│   ├── sample_memory.json
│   ├── sample_orchestration.json
│   └── sample_wiki_doc.json
└── tiers/                             # 新建主目录
    ├── stub/                          # 用 stub_backend.py
    │   ├── smoke/                     # 5 spec × ~50 行
    │   │   ├── chat.spec.ts
    │   │   ├── orchestration.spec.ts
    │   │   ├── wiki.spec.ts
    │   │   ├── memory.spec.ts
    │   │   └── evolution.spec.ts
    │   └── deep/                      # 5 spec × ~300 行
    │       ├── chat.spec.ts
    │       ├── orchestration.spec.ts
    │       ├── wiki.spec.ts
    │       ├── memory.spec.ts
    │       └── evolution.spec.ts
    └── live/                          # 用 conda sage-backend
        ├── boot-smoke/                # 不调 LLM
        │   ├── health.spec.ts
        │   ├── routes.spec.ts
        │   └── sse-handshake.spec.ts
        └── deep/                      # 真实 LLM 调用
            ├── chat.spec.ts
            ├── orchestration.spec.ts
            ├── wiki.spec.ts
            ├── memory.spec.ts
            └── evolution.spec.ts
```

### 4.3 平迁策略（git mv）

| 现有路径 | 新路径 |
|---|---|
| `tests/electron/office-e2e.spec.ts` | `tests/electron/tiers/stub/smoke/office.spec.ts` |
| `tests/electron/permission-approval.spec.ts` | `tests/electron/tiers/stub/smoke/permission.spec.ts` |
| `tests/electron/question-answer.spec.ts` | `tests/electron/tiers/stub/smoke/qa.spec.ts` |
| `tests/electron/skillmd-compliance.spec.ts` | `tests/electron/tiers/live/deep/skillmd.spec.ts` |

`smoke.spec.ts`（若根目录存在）平迁到 `tests/electron/tiers/stub/smoke/smoke.spec.ts`。

平迁用 `git mv` 保持 blame 连续；老路径文件删除；文档（README.md + playwright.config.ts）引用同步更新。

### 4.4 stub_backend.py 新增端点

| 功能 | 新增端点 |
|---|---|
| **Orchestration** | `POST /api/v1/orchestration/runs`、`GET /api/v1/orchestration/runs/:id`、`POST /api/v1/orchestration/runs/:id/approve`、`POST /api/v1/orchestration/runs/:id/cancel`、`GET /api/v1/orchestration/runs/:id/events` (SSE) |
| **Wiki** | `POST /api/v1/wiki/ingest`、`POST /api/v1/wiki/extract`、`POST /api/v1/wiki/search`、`GET /api/v1/wiki/insights/:id`、`POST /api/v1/wiki/deep-research` |
| **Memory** | `POST /api/v1/memory/episodic`、`POST /api/v1/memory/semantic`、`POST /api/v1/memory/working`、`GET /api/v1/memory/search`、`GET /api/v1/memory/profile/:user_id`、`POST /api/v1/memory/consolidate` |
| **Evolution** | `GET /api/v1/evolution/signals`、`POST /api/v1/evolution/draft`、`GET /api/v1/evolution/queue`、`POST /api/v1/evolution/approve/:id`、`GET /api/v1/evolution/scheduler/status` |

每条端点的返回 schema 必须 1:1 对齐 `backend/wiki/models.py`、`backend/memory/manager.py`、`backend/orchestration/events.py`、`backend/evolution/` 下的 Pydantic models。

### 4.5 fixture 与状态重置

- stub_backend：每 spec 启动一个 fresh 实例（已有 `stub_backend()` fixture 行为），DB in-memory。
- real_backend：每 spec 启动一个 fresh conda 进程；teardown 时 kill + 清本地 sqlite（用 tmp 目录）。
- Electron：每个 spec `beforeAll` 起一次 Electron（保留现有 office-e2e.spec.ts 模式），节省冷启动开销。

## 5. 阶段映射与脚本

### 5.1 阶段 → npm script → Playwright project

| 阶段 | npm script | 触发的 Playwright project | Backend | LLM |
|---|---|---|---|---|
| **本地 dev loop** | `npm run test:smoke` | electron-stub-smoke | stub | n/a |
| **PR 门禁** | `npm run test:pr` | electron-stub-smoke + electron-stub-deep + electron-live-boot | stub + real(no LLM) | no |
| **Nightly** | `npm run test:nightly` | 上面全部 + electron-live-deep(chat + memory only) | real | yes |
| **手动/Release** | `npm run test:release` | 上面全部 + electron-live-deep(全部 5) + NSIS 包冒烟 | packaged | yes |

### 5.2 package.json 新增脚本

```json
{
  "scripts": {
    "test:smoke":   "playwright test --project=electron-stub-smoke",
    "test:pr":      "playwright test --project=electron-stub-smoke --project=electron-stub-deep --project=electron-live-boot",
    "test:nightly": "playwright test --project=electron-stub-smoke --project=electron-stub-deep --project=electron-live-boot --project=electron-live-deep --grep=@nightly",
    "test:release": "playwright test --project=electron-stub-smoke --project=electron-stub-deep --project=electron-live-boot --project=electron-live-deep",
    "test:dev":     "playwright test --project=electron-stub-smoke --ui"
  }
}
```

`@nightly` 是 tag 过滤：live-deep 中只跑标注了 `@nightly` 的子集（chat + memory），避免每夜 token 消耗爆炸。

### 5.3 时长估算

| 阶段 | 时长 | 资源 |
|---|---|---|
| dev loop | 30-60s | 无依赖 |
| PR gate | 5-10 min | conda（live-boot） |
| Nightly | 30-60 min | conda + LLM key |
| Manual/Release | 60-120 min | conda + LLM key + NSIS 包 |

### 5.4 GitHub Actions 新增 workflow

```yaml
# .github/workflows/e2e-pr-gate.yml
name: E2E PR Gate
on: [pull_request]
jobs:
  stub-smoke:
    runs-on: ubuntu-latest
    steps: [checkout, setup-node, npm ci, npm run build:electron, npm run test:smoke]
  stub-deep:
    runs-on: ubuntu-latest
    needs: stub-smoke
    steps: [/* 同上 */, npm run test:pr --grep='@stub-deep']
  live-boot:
    runs-on: ubuntu-latest
    needs: stub-deep
    steps: [/* conda setup */, npm run test:pr --grep='@live-boot']
```

```yaml
# .github/workflows/e2e-nightly.yml
name: E2E Nightly
on: { schedule: [{ cron: '0 3 * *' }] }
jobs:
  live-deep:
    runs-on: ubuntu-latest
    steps: [/* conda + secret: OPENAI_API_KEY */, npm run test:nightly]
```

## 6. 五功能覆盖矩阵

### 6.1 smoke（stub 主力）

每个 smoke spec 控制在 50-80 行，验证"页面能加载 + 一个最小动作 + 后端路由 200 + DB 状态可查"。

| 功能 | smoke 验证 |
|---|---|
| Chat | 路由到 `/chat` → 输入"hello" → SSE 返回 fixture `hi there` → DB 中存 message |
| Orchestration | 路由到 `/orchestration` → 创建 run（plan + executor + reviewer 3 agents）→ 列表渲染 3 lane |
| Wiki | 路由到 `/wiki` → 上传 fixture 文本 → 看到 extract 标题/正文 → search 命中 |
| Memory | 路由到 `/memory` → 触发会话 → episodic 列表新增一条 → 搜索返回 1 条 |
| Evolution | 路由到 `/evolution` → 看到 scheduler 状态为 `idle` → 触发 draft → 队列新增 1 条 |

### 6.2 deep（nightly / release）

| 功能 | deep 验证 |
|---|---|
| Chat | SSE 流式 + 工具调用（mock tool response）+ 中断续聊 + 会话切换 + 上下文压缩触发 |
| Orchestration | planner 阶段产物 → executor 调工具 → reviewer 拒绝触发重试 → 用户审批 token → 多 agent lane 切换 → run 完成 |
| Wiki | 本地目录 ingest → extract → chunk → embed（deterministic）→ search 排序 → graph 邻居 → insights |
| Memory | episodic 写入 → working 更新 → 语义检索 → 触发 consolidation → profile 更新 → 跨会话引用 |
| Evolution | signal 检测 → LLM draft（live-deep only）→ 队列持久化 → approve → skill 写入 → 下次会话调用新 skill |

### 6.3 stub vs live 行为差异

| 维度 | stub | live |
|---|---|---|
| LLM 输出 | deterministic fixture（fixture 目录下 .json） | 真实 LLM（temperature=0） |
| 时间 | 毫秒级 | 真实耗时（chat 流式 2-10s） |
| 状态机 | in-memory SQLite | 项目本地 sqlite（teardown 清） |
| 错误注入 | stub config 开关（`STUB_FAIL_NEXT=1`） | 不注入（依赖真实错误） |
| 时间戳 | 注入固定时间 | 真实 UTC |

## 7. 数据流与错误处理

### 7.1 spec 与 stub 的数据流

```
1. spec beforeAll:
   - stub_backend 启动到 :0 端口
   - 设置 SAGE_BACKEND_URL + PYTHON_BACKEND_PORT env
   - electron.launch({ env })
2. spec body:
   - page.goto(...)
   - UI 操作 → renderer fetch('/api/v1/*') → stub_backend
   - 断言：DOM 状态 + stub SQLite 状态
3. spec afterAll:
   - electron.close()
   - stub_backend.stop()
```

### 7.2 spec 与 real backend 的数据流

```
1. spec beforeAll:
   - conda run -n sage-backend python backend/main.py 启动到 :8765
   - wait_for /health 返回 200（最多 30s）
   - 设置 PYTHON_BACKEND_PORT=8765
   - electron.launch({ env })
2. spec body:
   - 真实 UI 操作 → 真实 backend（含 LLM 调用）
   - 断言：DOM + 真实 sqlite（用 tmp 路径）
3. spec afterAll:
   - electron.close()
   - kill backend process
   - 清理 tmp 目录
```

### 7.3 错误处理统一约定

- spec 中所有断言失败：截图（on）+ trace（retain-on-failure）+ 错误日志重定向。
- stub 启动失败：spec `test.skip()` + warning log，避免 CI 红屏。
- 真实 backend 启动失败：spec `test.skip()` + warning log，附 `/health` 失败原因。
- 真实 LLM 调用 5xx/429：retry 2 次，仍失败则 `test.fail()` + 错误日志。
- 真实 LLM 输出与契约不符：用 `playwright-snapshot` 或 jest-snapshot 机制记录 live-deep 首次跑产出的 baseline JSON，后续跑做 diff；baseline 更新需人工 review 后提交。

## 8. 文件与模块边界

### 8.1 新建

- `tests/electron/tiers/stub/smoke/*.spec.ts` (5)
- `tests/electron/tiers/stub/deep/*.spec.ts` (5)
- `tests/electron/tiers/live/boot-smoke/*.spec.ts` (3)
- `tests/electron/tiers/live/deep/*.spec.ts` (5)
- `tests/electron/fixtures/*.json` (4)
- `.github/workflows/e2e-pr-gate.yml`
- `.github/workflows/e2e-nightly.yml`

### 8.2 修改

- `tests/electron/stub_backend.py`：新增 ~600 行（5 功能端点）
- `tests/electron/conftest.py`：新增 `real_backend()` fixture（~80 行）
- `tests/electron/test_stub_backend.py`：扩展到 ~50 minimum / ~80 stretch unit case
- `tests/electron/README.md`：完整重写（~200 行）
- `playwright.config.ts`：新增 4 个 project 配置
- `package.json`：新增 5 个 npm script

### 8.3 平迁（git mv）

- `tests/electron/office-e2e.spec.ts` → `tests/electron/tiers/stub/smoke/office.spec.ts`
- `tests/electron/permission-approval.spec.ts` → `tests/electron/tiers/stub/smoke/permission.spec.ts`
- `tests/electron/question-answer.spec.ts` → `tests/electron/tiers/stub/smoke/qa.spec.ts`
- `tests/electron/skillmd-compliance.spec.ts` → `tests/electron/tiers/live/deep/skillmd.spec.ts`

### 8.4 不修改

- `backend/**`：业务代码不动
- `src/**`：前端代码不动
- `electron/**`：Electron main/preload 不动

## 9. 迁移与风险

### 9.1 迁移步骤

1. 在 `tests/electron/tiers/stub/smoke/` 下创建空 spec 文件（仅含 placeholder describe）。
2. `git mv` 平迁现有 4 个 spec。
3. 扩展 `stub_backend.py` + `conftest.py` + `test_stub_backend.py`。
4. 在 4 个新 tier 子目录下补全 18 个新 spec。
5. 更新 `playwright.config.ts` + `package.json`。
6. 新增 2 个 GitHub Actions workflow。
7. 重写 `README.md`。

### 9.2 风险

| 风险 | 概率 | 影响 | 缓解 |
|---|---|---|---|
| stub 与真实后端契约漂移 | 中 | 中 | 每个 stub 端点配 unit test；contract test 标注以哪个 Pydantic 为准 |
| 真实 LLM nightly 成本超预期 | 中 | 中 | nightly 默认只跑 chat + memory（@nightly tag），release 阶段才全量 |
| Electron 冷启动在 CI flaky | 高 | 低 | 保留现有 `retries: 2 on CI` 模式；live spec 用 beforeAll 复用 Electron |
| stub_backend.py 增长到 1500 行难维护 | 中 | 中 | 模块拆：stub_chat.py / stub_orchestration.py / stub_wiki.py / stub_memory.py / stub_evolution.py，最后 stub_backend.py 仅做 routing + lifespan |
| GitHub Actions conda runner 慢/不稳 | 中 | 中 | live-boot spec 加 `test.skip()` fallback；文档化 runner 要求 |
| 现有 3 个 spec 平迁破坏 git history | 低 | 低 | 用 `git mv` 而非新增+删除，保持 blame |

### 9.3 回滚

整个设计是新增 + 平迁，不删除老路径（平迁后老路径为空 spec 占位），回滚成本低：删除 `tiers/` + `fixtures/` + workflow 文件 + 恢复 4 个老 spec 即可。

## 10. 测试与验证

设计本身的验证：

- `tests/electron/test_stub_backend.py` 80+ 个 case 全绿。
- `npm run test:smoke` 在未配置 conda 的机器上 60s 内跑通 5 个 smoke spec。
- `npm run test:pr` 在有 conda sage-backend 的机器上 10 min 内跑通 stub-smoke + stub-deep + live-boot。
- `npm run test:nightly` 在有 LLM key 的 runner 上 60 min 内跑通 chat + memory 的 live-deep。
- 现有 3 个老 spec 平迁后行为不变（CI 跑一遍对比）。

## 11. 与现有规则的关系

- 与 `feature-development.md`：本设计为新功能模块，按规则输出 spec + plan + 实施。本 spec 是 spec 阶段产物。
- 与 `git-workflow.md`：所有代码改动走 feature 分支 + squash merge + PR。
- 与 `cicd-workflow.md`：本设计新增 e2e-pr-gate.yml + e2e-nightly.yml，遵循现有 PR CI + nightly cron 模式。
- 与 `python-environment.md`：live-boot / live-deep 使用 conda sage-backend（已声明），不污染 base。
- 与 `testing.md`：本设计是 E2E 层（已有 unit + integration），不替代单测；覆盖率门禁（80%）仍由 pytest 守。
- 与 `branch-and-release-strategy.md`：仅在 main 上实施；release/win7 后续单独 cherry-pick。
- 与项目 `CLAUDE.md`：使用 sage-backend conda 环境，不污染 base；端口沿用 8765。

## 12. 待人工确认项（实施前）

- [ ] stub_backend.py 是否需要模块拆（§9.2）——本 spec 倾向拆，按模块文件组织。
- [ ] live-deep 中是否需要"截图对比"（visual diff）——本 spec 不包含，留作后续 spec。
- [ ] NSIS 包冒烟是否纳入 `test:release`——本 spec 倾向纳入，但需要打包后才能跑，留 §5.1 标记。
- [ ] 是否在 main + release/win7 同时实施——本 spec 仅 main；win7 单独 spec。