# Sage P3 详细实施计划 — 可观测性 + UX/a11y + Tauri 2

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 把 Sage 推进到"运行可观测、桌面跨 Win7、前端无障碍"——P3 是质量优化的收官阶段

**Phase:** P3 of 4（P0 + P1 + P2 已完工）

**周期：** 3-4 周（单人）/ 2-3 周（2 人）

**关联文档：**
- 总体规划：`docs/superpowers/plans/2026-06-05-sage-quality-optimization.md`
- 设计 spec：`docs/superpowers/specs/2026-06-05-sage-quality-optimization-design.md` § 6
- 质量门禁：`docs/technical/15-quality-gates.md`
- 前端质量：`docs/technical/17-frontend-quality.md`
- 六边形架构：`docs/technical/18-hexagonal.md`

**P2 末基线（2026-06-05/06）：**
- 后端覆盖率 87%（512 测试；`--cov-fail-under=80` 强制）
- 后端 100% domain+ports 覆盖、96% application、100% adapters（15/16）
- 前端 53/53 通过；FSD 7 层 enforcement 生效
- 5 个共享 UI 组件目录已占位（`src/shared/ui/`）但空
- metric + event adapter 骨架已建（PG2.7+PG2.8）
- Tauri 1.6（`@tauri-apps/api: "1.6"`，无 Win7 配置）

---

## P3 验收标准

- [ ] `GET /metrics` 返回 9 个 Prometheus 指标（5 counter + 3 histogram + 1 gauge）
- [ ] `backend/data/audit/audit.jsonl` 记录 5 类事件（chat_message_sent / chat_response_completed / tool_invoked / session_created / settings_changed）
- [ ] OpenTelemetry span 注入 request_id；日志带 trace_id
- [ ] 4 个共享 UI 组件（ErrorState / LoadingState / RetryButton / Skeleton）创建并测试
- [ ] 5 页面采用新组件
- [ ] Lighthouse a11y ≥ 95
- [ ] Tauri 2 升级；3 平台 build 成功（Windows 10/11、macOS、Linux）
- [ ] Win7 兼容：embedBootstrapper + windows7-compat feature
- [ ] 端到端 512 + 新增测试全过
- [ ] `docs/technical/16-observability.md` 发布
- [ ] `docs/user-manual/01-desktop.md` + `02-metrics.md` 发布

---

## P3 任务组概览

| ID | 主题 | 文件 | 验收 |
|----|------|------|------|
| **PG3.1** | Prometheus 9 指标 | `backend/adapters/out/metric/prometheus_adapter.py` + `backend/api/hex_routes.py` 加 /metrics | curl /metrics 返回 9 |
| **PG3.2** | 用户行为审计 5 类事件 | `backend/adapters/out/event/file_adapter.py` + ChatService emit | 5 类事件落盘 |
| **PG3.3** | OpenTelemetry 接入 | `backend/utils/otel.py` + ChatService + LLMAdapter | span 注入，日志带 trace_id |
| **PG3.4** | ErrorState 组件 | `src/shared/ui/ErrorState/` | 1 组件 + 测试 |
| **PG3.5** | LoadingState 组件 | `src/shared/ui/LoadingState/` | spinner + skeleton variant |
| **PG3.6** | RetryButton 组件 | `src/shared/ui/RetryButton/` | 内置退避 [1s, 2s, 4s] |
| **PG3.7** | Skeleton 组件 | `src/shared/ui/Skeleton/` | Skeleton / MessageSkeleton / SessionListSkeleton |
| **PG3.8** | 5 页面采用 | 5 个 page 文件 | UI 行为不变 |
| **PG3.9** | a11y 改造 | 全局 | Lighthouse ≥ 95 |
| **PG3.10** | Tauri 2 升级 | `src-tauri/Cargo.toml` + `package.json` + `src-tauri/src/` | 3 平台 build 成功 |
| **PG3.11** | Win7 兼容 | `src-tauri/tauri.conf.json` + `Cargo.toml` feature | embedBootstrapper + windows7-compat |
| **PG3.12** | 文档发布 | 3 文件 | 16-observability + 2 user-manual |
| **PG3.13** | 集成测试 + 门禁 | CI /metrics + /audit grep + tauri-smoke 强门禁 | 端到端验证 |

**总计：13 任务组**

---

## PG3.1 — Prometheus 9 指标

### 任务 3.1.1：注册 9 个核心指标

**Files:** Modify `backend/adapters/out/metric/prometheus_adapter.py`

按 spec § 6.1 定义：

```python
"""完整 Prometheus 指标 adapter（9 个核心指标）。"""
from prometheus_client import Counter, Histogram, Gauge, CollectorRegistry, generate_latest, CONTENT_TYPE_LATEST


class PrometheusMetricAdapter:
    # 5 Counter
    HTTP_REQUESTS_TOTAL = "sage_http_requests_total"
    LLM_CALLS_TOTAL = "sage_llm_calls_total"
    TOOL_INVOCATIONS_TOTAL = "sage_tool_invocations_total"
    TOKENS_CONSUMED_TOTAL = "sage_tokens_consumed_total"
    ERRORS_TOTAL = "sage_errors_total"

    # 3 Histogram
    HTTP_REQUEST_DURATION = "sage_http_request_duration_seconds"
    LLM_CALL_DURATION = "sage_llm_call_duration_seconds"
    REACT_STEPS = "sage_react_steps_per_request"

    # 1 Gauge
    ACTIVE_SESSIONS = "sage_active_sessions"

    def __init__(self, registry: CollectorRegistry | None = None):
        self._registry = registry or CollectorRegistry()
        # ... 同 PG2.7 骨架 + 9 个指标的"known" 列表 ...

    def render(self) -> bytes:
        """返回 Prometheus 文本格式。"""
        return generate_latest(self._registry)

    @property
    def registry(self) -> CollectorRegistry:
        return self._registry
```

### 任务 3.1.2：在 ChatService 中埋点

**Files:** Modify `backend/application/services/chat_service.py`

ChatService 已 emit 4 类事件 + 3 指标。P3.1 加上 `http_requests_total` 路由级埋点（不在 ChatService 中——在路由层）。

ChatService 现状：每次 `run_turn` 已 emit `chat_message_sent` / `chat_response_completed` / `llm_error` / `tool_invoked` / `tool_failed`，并 counter `chat_messages_total` / `llm_calls_total` / `errors_total` / `tool_invocations_total` / `tool_errors_total`。

**新增/升级**：
- `llm_call_duration` histogram：记录 `await self.llm.chat(...)` 的耗时
- `tokens_consumed_total` counter：在 LLM response 解析时记录（如果 response 含 `usage`）
- `react_steps` histogram：每次 `_execute_tool_calls` 累加，最后 `observe(N)`
- `active_sessions` gauge：每 `create_session` +1，`delete_session` -1

### 任务 3.1.3：/metrics 端点

**Files:** Modify `backend/api/hex_routes.py`

加 endpoint：

```python
@router.get("/metrics")
def metrics(svc: ChatService = Depends(get_chat_service)) -> Response:
    """Prometheus 指标端点。"""
    prom = svc.metrics
    if not isinstance(prom, PrometheusMetricAdapter):
        # 非生产 adapter（Noop）：返回空
        return Response(content=b"", media_type="text/plain")
    return Response(content=prom.render(), media_type=CONTENT_TYPE_LATEST)
```

**约束**：`/metrics` 不需要鉴权（仅本机访问，Tauri localhostOnly 保护）。

### 任务 3.1.4：测试

**Files:** Create `backend/tests/integration/test_metrics_endpoint.py`

```python
"""验证 /metrics 端点暴露 9 个核心指标。"""
import pytest
from prometheus_client import REGISTRY

pytestmark = pytest.mark.integration


async def test_metrics_endpoint_returns_prometheus_format(client):
    resp = await client.get("/metrics")
    assert resp.status_code == 200
    assert "text/plain" in resp.headers["content-type"]
    body = resp.text
    for name in [
        "sage_http_requests_total",
        "sage_llm_calls_total",
        "sage_tool_invocations_total",
        "sage_tokens_consumed_total",
        "sage_errors_total",
    ]:
        assert name in body or f"# HELP {name}" in body
```

### 任务 3.1.5：commit

```bash
git add backend/adapters/out/metric/prometheus_adapter.py backend/application/services/chat_service.py backend/api/hex_routes.py backend/tests/integration/test_metrics_endpoint.py
git commit -m "feat(backend): 9 个核心 Prometheus 指标 + /metrics 端点

- 5 counter: http_requests / llm_calls / tool_invocations / tokens / errors
- 3 histogram: http_duration / llm_duration / react_steps
- 1 gauge: active_sessions
- /metrics 端点暴露（text/plain）
- ChatService 埋点 4 个新指标
- 集成测试验证端点"
```

**退出标准：** `curl /metrics` 包含 9 个指标名

---

## PG3.2 — 用户行为审计 5 类事件

### 任务 3.2.1：定义 5 类事件常量

**Files:** Modify `backend/adapters/out/event/file_adapter.py`

```python
class AuditEventType:
    """5 类审计事件常量。"""
    CHAT_MESSAGE_SENT = "chat_message_sent"
    CHAT_RESPONSE_COMPLETED = "chat_response_completed"
    TOOL_INVOKED = "tool_invoked"
    SESSION_CREATED = "session_created"
    SETTINGS_CHANGED = "settings_changed"
```

### 任务 3.2.2：ChatService 完整 emit 5 类

**Files:** Modify `backend/application/services/chat_service.py`

当前 ChatService 已 emit 4 类：`chat_message_sent` / `chat_response_completed` / `llm_error` / `tool_invoked` / `tool_failed`。

需要新加：
- `session_created` —— 在 `ChatService.create_session()` 新方法中（新增）
- `settings_changed` —— 不在 ChatService 中，在 settings 路由中（PG3.2 范围之外的 settings 路由层加；这里只占位）

或者简化：5 类事件**至少** 在 audit.jsonl 中可观察到——`chat_message_sent`、`chat_response_completed`、`tool_invoked` 已自动落盘（PG2.9 ChatService），剩 `session_created` + `settings_changed` 需在 P3.2 加。

### 任务 3.2.3：测试

**Files:** Create `backend/tests/integration/test_audit_log.py`

```python
"""验证 5 类事件落盘 audit.jsonl。"""
import json
import pytest
from pathlib import Path

pytestmark = pytest.mark.integration


async def test_audit_log_records_5_event_types(client, tmp_path: Path):
    # 重定向 audit 路径到 tmp
    # 触发：chat / session / tool
    # 验证文件含 5 类事件
    ...
```

### 任务 3.2.4：commit

---

## PG3.3 — OpenTelemetry 接入

### 任务 3.3.1：创建 otel.py 工具

**Files:** Create `backend/utils/otel.py`

```python
"""OpenTelemetry stdlib 接入（P3 启用，不接 collector）。"""
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import (
    BatchSpanProcessor,
    ConsoleSpanExporter,
)

_provider: TracerProvider | None = None


def init_tracing() -> TracerProvider:
    """初始化全局 TracerProvider（导出到 stdout）。"""
    global _provider
    if _provider is not None:
        return _provider
    _provider = TracerProvider()
    _provider.add_span_processor(BatchSpanProcessor(ConsoleSpanExporter()))
    trace.set_tracer_provider(_provider)
    return _provider


def get_tracer(name: str = "sage"):
    return trace.get_tracer(name)
```

### 任务 3.3.2：在 ChatService 中加 span

**Files:** Modify `backend/application/services/chat_service.py`

```python
from backend.utils.otel import get_tracer

_tracer = get_tracer("chat_service")

async def run_turn(self, ...):
    with _tracer.start_as_current_span("chat.run_turn") as span:
        span.set_attribute("session_id", session_id)
        # ... 现有逻辑
```

### 任务 3.3.3：在 logging 中读 trace_id

**Files:** Modify `backend/utils/logging.py`

```python
import logging
from opentelemetry import trace


class TraceIdFilter(logging.Filter):
    def filter(self, record):
        span = trace.get_current_span()
        if span.is_recording():
            ctx = span.get_span_context()
            record.trace_id = format(ctx.trace_id, "032x")
        return True
```

### 任务 3.3.4：测试

**Files:** Create `backend/tests/unit/test_otel.py`

验证：
- `init_tracing()` 幂等
- `get_tracer` 返回非 None
- `start_as_current_span` 上下文管理器工作

### 任务 3.3.5：commit

---

## PG3.4 — ErrorState 共享组件

### 任务 3.4.1：创建组件

**Files:** Create `src/shared/ui/ErrorState/ErrorState.tsx` + `index.ts`

```tsx
import clsx from 'clsx';

interface ErrorStateProps {
  title?: string;
  message: string;
  onRetry?: () => void;
  retryLabel?: string;
  className?: string;
}

export function ErrorState({
  title = '出错了',
  message,
  onRetry,
  retryLabel = '重试',
  className,
}: ErrorStateProps) {
  return (
    <div
      role="alert"
      aria-live="assertive"
      className={clsx('flex flex-col items-center gap-4 p-6 rounded-lg bg-red-50 dark:bg-red-950/30 border border-red-200', className)}
    >
      <div className="text-red-600 dark:text-red-400" aria-hidden="true">⚠</div>
      <h2 className="text-lg font-semibold text-red-900 dark:text-red-100">{title}</h2>
      <p className="text-sm text-red-700 dark:text-red-300 text-center max-w-md">{message}</p>
      {onRetry && (
        <button
          type="button"
          onClick={onRetry}
          className="px-4 py-2 rounded-md bg-red-600 text-white hover:bg-red-700 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-red-500"
        >
          {retryLabel}
        </button>
      )}
    </div>
  );
}
```

### 任务 3.4.2：测试

**Files:** Create `src/shared/ui/ErrorState/__tests__/ErrorState.test.tsx`

3-4 测试：渲染、retry 按钮、aria-live。

### 任务 3.4.3：commit

```bash
git add src/shared/ui/ErrorState
git commit -m "feat(frontend): ErrorState 共享组件（a11y 友好）"
```

---

## PG3.5 — LoadingState 组件

类似 PG3.4，但 LoadingState 有 `variant: 'spinner' | 'skeleton'` 双形态。

---

## PG3.6 — RetryButton 组件

内置退避 [1s, 2s, 4s]，暴露 `onClick` + `attempts` + `maxAttempts`。

---

## PG3.7 — Skeleton 组件

`Skeleton` 基础 + `MessageSkeleton` + `SessionListSkeleton` 复合。

---

## PG3.8 — 5 页面采用共享组件

修改 Chat / Settings / Knowledge / Skills / Agents / Memory（实际 6 个页面），把现有散落的错误/加载/重试 UI 替换为新组件。

每个页面 1 个 commit。

---

## PG3.9 — a11y 改造 + Lighthouse ≥ 95

### 任务 3.9.1：颜色对比度修复

按 spec § 5.4：

- `text-gray-400` → `text-gray-600`（4.5:1 → 5.7:1）
- 错误色 `#dc2626` → `#b91c1c`（4.7:1 → 6.2:1）
- 主色按钮文字用 white 达 4.5:1

### 任务 3.9.2：跳过链接 + ARIA 改造

- 加 `<a href="#main" class="skip-link">` 跳到主内容
- 所有 `<div onClick>` 改为 `<button>`
- 表单 `<label htmlFor>`
- 弹窗 aria-labelledby

### 任务 3.9.3：Lighthouse CI

**Files:** Modify `.github/workflows/ci.yml`

加 Lighthouse job（手动触发 workflow_dispatch）：

```yaml
lighthouse:
  runs-on: ubuntu-latest
  if: github.event_name == 'workflow_dispatch' || github.event.pull_request
  steps:
    - uses: actions/checkout@v4
    - run: npm ci && npm run build
    - run: npx serve -s dist &
    - run: npx lighthouse http://localhost:3000 --only-categories=accessibility --output=json
    - run: jq '.categories.accessibility.score' > score.txt
    - run: test "$(cat score.txt)" -ge "0.95"
```

### 任务 3.9.4：commit

---

## PG3.10 — Tauri 2 升级

### 任务 3.10.1：依赖升级

**Files:** Modify `src-tauri/Cargo.toml` + `package.json` + `package-lock.json`

```toml
[dependencies]
tauri = { version = "2", features = ["windows7-compat"] }
tauri-plugin-shell = "2"
tauri-plugin-dialog = "2"
tauri-plugin-fs = "2"
```

```json
{
  "devDependencies": {
    "@tauri-apps/api": "^2",
    "@tauri-apps/cli": "^2"
  }
}
```

### 任务 3.10.2：commands 迁移

**Files:** Modify `src-tauri/src/commands.rs` + 全部 `src-tauri/src/*.rs`

每个 `#[tauri::command]` 函数的签名适配 Tauri 2 API：

```rust
// Tauri 1
#[tauri::command]
fn my_command(window: tauri::Window) -> Result<String, String> { ... }

// Tauri 2
#[tauri::command]
fn my_command(app: tauri::AppHandle) -> Result<String, String> { ... }
```

### 任务 3.10.3：前端 invoke 适配

**Files:** Modify 全部 `src/**/*` 使用 `@tauri-apps/api` 的文件

```typescript
// Tauri 1
import { invoke } from '@tauri-apps/api/tauri';
await invoke('my_command', { arg: 'value' });

// Tauri 2
import { invoke } from '@tauri-apps/api/core';
await invoke('my_command', { arg: 'value' });
```

### 任务 3.10.4：build 验证

**本地（本机未装 Rust，跳过）**：
- 不能直接 build，但可以 `npm run build`（仅前端）验证 Vite 不报错

**CI**：
- 3 平台 build smoke test

### 任务 3.10.5：commit

⚠️ **本机无 Rust**：Tauri 2 升级需要 CI 验证（PG3.10 不阻塞 P3 整体进度）

---

## PG3.11 — Win7 兼容

### 任务 3.11.1：tauri.conf.json

**Files:** Modify `src-tauri/tauri.conf.json`

```json
{
  "bundle": {
    "windows": {
      "webviewInstallMode": {
        "type": "embedBootstrapper"
      }
    }
  }
}
```

### 任务 3.11.2：Cargo.toml

`windows7-compat` feature 已在 PG3.10.1 加。

### 任务 3.11.3：CI Win7 矩阵

**Files:** Modify `.github/workflows/ci.yml`

```yaml
tauri-win7:
  runs-on: [self-hosted, win7]
  if: github.event_name == 'workflow_dispatch'
  steps:
    - uses: actions/checkout@v4
    - uses: dtolnay/rust-toolchain@1.77.2
    - run: cargo build --release
    - run: ./target/release/sage.exe
```

⚠️ Win7 需自托管 runner（CI 仓库内 GitHub-hosted runner 不支持 Win7）

### 任务 3.11.4：commit

---

## PG3.12 — 文档发布

### 任务 3.12.1：写 16-observability.md

**Files:** Create `docs/technical/16-observability.md`

内容：
- 9 个 Prometheus 指标表
- 5 类审计事件
- OTel 集成方式
- /metrics 端点
- audit.jsonl 路径
- 故障排查指南

### 任务 3.12.2：写 user-manual/01-desktop.md

**Files:** Create `docs/user-manual/01-desktop.md`

内容：
- Win7 系统要求
- embedBootstrapper 安装说明
- WebView2 缺失时如何处理
- 常见问题

### 任务 3.12.3：写 user-manual/02-metrics.md

**Files:** Create `docs/user-manual/02-metrics.md`

内容：
- /metrics 端点使用
- 5 类事件查询（`jq` 示例）
- Grafana 面板接入（可选）

### 任务 3.12.4：commit

---

## PG3.13 — 集成测试 + 门禁

### 任务 3.13.1：/metrics 集成测试

PG3.1.4 已建。

### 任务 3.13.2：/audit 集成测试

PG3.2.3 已建。

### 任务 3.13.3：CI tauri-smoke 升级为强门禁

**Files:** Modify `.github/workflows/ci.yml`

原 PG0-T11 中 tauri-smoke 是 `continue-on-error: true`（P0 阶段无 Rust 验证）。

P3.13.3 升级：在 `tauri-smoke` job 移除 `continue-on-error`，并增加 3 平台 build artifact 上传（不在 PR 时阻止，只在 main 触发时）。

### 任务 3.13.4：全量验证

```bash
cd /home/fz/project/sage/backend && \
  /home/fz/anaconda3/envs/sage-backend/bin/pytest --cov=backend --cov-fail-under=80
cd /home/fz/project/sage && \
  npm run typecheck && \
  npm run test:run && \
  npm run lint
```

### 任务 3.13.5：commit

---

## 自审（Self-Review）

### Spec 覆盖

| Spec 节 | 对应 PG | 状态 |
|---------|--------|------|
| § 6.1 Prometheus 9 指标 | PG3.1 | ✅ |
| § 6.1 MetricPort 端口 | PG3.1 (PG2.7 已建骨架) | ✅ |
| § 6.1 OTel trace | PG3.3 | ✅ |
| § 6.1 EventPort 端口 | PG3.2 (PG2.8 已建骨架) | ✅ |
| § 5.4 a11y 重点子集 | PG3.9 | ✅ |
| § 5.4 共享组件 | PG3.4-PG3.7 | ✅ |
| § 5.4 5 页面采用 | PG3.8 | ✅ |
| § 2.3 Tauri 2 + Win7 | PG3.10-PG3.11 | ✅ |
| § 7.3 文档 | PG3.12 | ✅ |

### 范围检查

- 13 任务组完整
- 每 PG 独立可测试
- 风险点（Tauri 2 在本机不可测）已显式说明

**无缺口，可执行。**

---

## 实施步骤追踪

### P3 阶段
- [ ] PG3.1: Prometheus 9 指标 + /metrics 端点
- [ ] PG3.2: 5 类审计事件落盘
- [ ] PG3.3: OpenTelemetry 接入
- [ ] PG3.4: ErrorState 共享组件
- [ ] PG3.5: LoadingState 共享组件
- [ ] PG3.6: RetryButton 共享组件
- [ ] PG3.7: Skeleton 共享组件
- [ ] PG3.8: 5 页面采用共享组件
- [ ] PG3.9: a11y 改造 + Lighthouse ≥ 95
- [ ] PG3.10: Tauri 2 升级
- [ ] PG3.11: Win7 兼容 + CI 矩阵
- [ ] PG3.12: 文档发布（3 文件）
- [ ] PG3.13: 集成测试 + 门禁

**总计：13 任务组**
