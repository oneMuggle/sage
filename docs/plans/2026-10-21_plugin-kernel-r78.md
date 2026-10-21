# R78 — 插件内核骨架（contract + kernel）

> 日期：2026-10-21
> 轮次：plugin-evo R78（见 `docs/plans/plugin-evo-index.md`）
> 上游决策：`docs/mcp-dsh-plugin-adoption-decision-20261021.md`（学机制，不接生态）
> 基线：`origin/main` @ `9145005ae`（2026-10-20）
> 分支 / worktree：`feat/plugin-kernel-r78` → `.worktrees/feat-plugin-kernel-r78`

---

## 1. 目标

把「可逆副作用 + 依赖驱动生命周期 + 事件中间件 + 命名服务」四件事做成 sage 自己的内核，
**纯新增、不接线、零行为变更**，为 R79（hook 收编）/ R80（tool 收编）/ R81（三层配置）提供地基。

一句话验收：**新增四个内核模块与两份契约文件，存量代码零改动，全部测试通过，架构检查绿。**

## 2. 非目标（本轮明确不做）

- 不接入任何现有 hooks / tools / skills（R79–R80 再做）
- 不改 `backend/plugins/{manifest,registry,lifecycle}.py`（R80 收编时统一处理）
- 不做进程外宿主、不做 cordis-shim、不引入任何第三方插件框架
- 不做配置解析（`harness.yaml` 属 R81）
- 不改前端

## 3. 分层落位

| 层 | 新增文件 | 行数预算 | 说明 |
| --- | --- | --- | --- |
| domain | `backend/domain/plugin.py` | ≤300（契约上限） | 纯契约：`ProviderKind` / `TrustLevel` / `FiberState` / `CapabilityDecl` |
| ports | `backend/ports/plugin.py` | ≤300（契约上限） | `EffectScopePort` / `ServiceRegistryPort` / `EventBusPort` / `PluginHostPort` |
| application | `backend/application/kernel/__init__.py` | ≤80 | 导出面 |
| application | `backend/application/kernel/effects.py` | ≤200 | `EffectScope` |
| application | `backend/application/kernel/events.py` | ≤260 | `EventBus`（四模式） |
| application | `backend/application/kernel/services.py` | ≤200 | `ServiceRegistry` |
| application | `backend/application/kernel/fiber.py` | ≤300 | `Fiber` / `FiberContext` / `PluginHost` |
| application | `backend/application/kernel/cordis_names.py` | ≤120 | 与 Cordis 的名称映射表（只读常量） |

`backend/application` 模块已在 `architecture-policy.json` 登记（requires: domain, ports），
**本轮不需要改 policy/baseline**——新增文件天然落在既有模块边界内。

## 4. 设计要点

### 4.1 EffectScope：注册即可逆

```python
with - 语义（Python 无 RAII，改用显式 API）：
scope.effect(lambda: make_resource_and_return_disposer())
```

- **逆序释放**：子 scope 先于父 scope，同一 scope 内后注册先释放（LIFO）。
- **异步并发**：同步 disposer 立即按逆序执行；异步 disposer 收集后 `asyncio.gather` 并发执行
  （与 Cordis 文档一致：多个 async disposer 并发、不保证逐个完成）。
- **已销毁的 scope 上再注册 → 立即抛 `ScopeDisposedError`**（对应 Cordis 的 `assertActive`），
  这条是杜绝「插件在异步回调里注册东西、而它已经被卸载」这类泄漏的关键。
- 幂等：重复 dispose 不重复执行。
- 异常：单个 disposer 抛错不阻断其余，最终抛 `EffectDisposalError(errors=[...])` 汇总。

### 4.2 EventBus：四模式

| 模式 | 语义 | 典型用途 |
| --- | --- | --- |
| `emit` | 同步广播，忽略返回值 | 观测、日志、审计 |
| `bail` | 顺序执行，首个非 `None/False` 返回值即结果 | 守卫 / 拦截（是否允许） |
| `serial` | 顺序 await，首个有效返回值终止链 | 多级审批 |
| `waterfall` | 每个监听器包装下游结果，必须 `next()` | 中间件 / 参数改写 |

约定：
- 名称 `namespace/action`（如 `tool/pre`、`agent/request`）；`validate_event_name()` 供内核断言，
  **不强制**存量事件名（`PreToolUse` 等旧名照常可用，R79 再做别名映射）。
- 排序：`priority` 降序，同优先级按注册顺序；返回 `Disposer` 可撤销。
- **超时**：`bail/serial/waterfall` 支持 `timeout`；超时抛 `EventTimeoutError`。
  水fall 链中任何一个监听器卡死不得拖垮工具链——这是硬要求。
- `emit` 的异常默认**聚合后统一抛出**（`EventDispatchError`），保证一个坏监听器不会饿死其余监听器。

与 Cordis 的**已知差异**（写在文档里，不假装等价）：
- Python 无 `undefined`，`None` 同时承担 `null` 与 `undefined` 的角色；
- `bail/serial` 在 Python 侧统一为 async（JS 侧 bail 可同步）；
- `emit` 的错误聚合策略是 sage 的选择（Cordis 未规定）。

### 4.3 ServiceRegistry：命名服务 + 变更通知

- `provide(name, instance, owner)` → 返回 disposer；**同名冲突显式抛 `ServiceConflictError`**。
- `get(name)` 返回 `Optional`；`require(name)` 缺失即抛 `ServiceNotFoundError`。
- `on_change(callback)`：服务增删时通知（Fiber 依赖驱动的基础）。
- 不做类型反射，纯名字 + duck typing（对应 `ctx.tools` / `ctx.llm`）。
- **不在构造期创建 `asyncio.Lock()`**（py3.8 兼容雷区），需要锁时惰性创建。

### 4.4 Fiber：状态机 + 依赖驱动

```
PENDING --(依赖就绪且 start)--> LOADING --> ACTIVE
                                   \--> FAILED
ACTIVE --(必需服务消失)--> UNLOADING --> DISPOSED
DISPOSED/FAILED --(服务恢复 + 重新 start)--> LOADING ...
```

- `inject`: 必需服务名列表；缺任一项 → 停在 `PENDING`，不执行 `apply`。
- 服务消失 → 自动 `dispose`（走 `UNLOADING → DISPOSED`）；服务恢复 → 自动重新 `start`。
- `apply(ctx)` 抛错 → `FAILED`，错误记录在 `fiber.error`，不影响其他 fiber。
- 子 fiber（`ctx.plugin(...)`）随父级联 dispose。
- 状态变更通过 `on_state_change` 回调暴露（供 UI/日志，R82 用）。

### 4.5 Cordis 名称映射（只读常量，供未来桥接）

`cordis_names.py` 维护三张表：`SERVICE_ALIASES`（`ctx.tools` ↔ sage 端口）、
`EVENT_ALIASES`（`tools/result` ↔ sage 事件）、`KIND_ALIASES`。
本轮**只用于测试断言与文档**，不参与运行时——保证即使将来不做兼容，也不留死代码债。

## 5. 测试矩阵

| 文件 | 覆盖面 | 目标用例数 |
| --- | --- | --- |
| `test_kernel_effects.py` | LIFO 顺序、子 scope 先释放、异步并发、重复 dispose 幂等、已销毁注册抛错、异常聚合 | ≥9 |
| `test_kernel_events.py` | 四模式语义、priority、disposer、异常聚合、超时、waterfall 短路/透传、名称校验 | ≥12 |
| `test_kernel_services.py` | provide/get/require、冲突、on_change 通知、dispose 撤销 | ≥7 |
| `test_kernel_fiber.py` | PENDING→ACTIVE、FAILED、依赖消失自动 dispose、恢复自动重载、子 fiber 级联、ctx.effect 回收 | ≥8 |
| `test_domain_plugin.py` | 枚举值、CapabilityDecl 校验、非法 id/名称 | ≥6 |

合计 ≥42 例。全部为纯内存测试，无 I/O、无网络、无数据库。

## 6. 验收门禁

```bash
cd backend
python -m pytest tests/unit/test_kernel_*.py tests/unit/test_domain_plugin.py -q
cd .. && node scripts/architecture-check.mjs
npx ruff check backend/domain/plugin.py backend/ports/plugin.py backend/application/kernel
```

- 目标测试全绿，且**存量测试不回归**（抽 3 个相邻模块复跑）
- 架构检查绿（文件行数、分层依赖、无环）
- ruff 无告警（含 UP006/007/035 豁免下的 py3.8 兼容写法）
- `git status` 只包含本轮新增文件

## 7. 风险

| 风险 | 处置 |
| --- | --- |
| 异步 disposer 并发导致测试不稳定 | 测试用可控 coroutine + `asyncio.wait` 断言；不依赖调度顺序 |
| 事件超时用真实时钟导致 flaky | 用短超时（0.05s）+ 明确的挂起协程 |
| 内核膨胀 | 文件行数硬上限 + 本轮零业务逻辑（内核不含任何策略判断） |
| py3.8 兼容 | `from __future__ import annotations` + `typing.List/Dict/Optional`，禁用 PEP604/585 |

## 8. 交付清单

```
backend/domain/plugin.py
backend/ports/plugin.py
backend/application/kernel/__init__.py
backend/application/kernel/effects.py
backend/application/kernel/events.py
backend/application/kernel/services.py
backend/application/kernel/fiber.py
backend/application/kernel/cordis_names.py
backend/tests/unit/test_domain_plugin.py
backend/tests/unit/test_kernel_effects.py
backend/tests/unit/test_kernel_events.py
backend/tests/unit/test_kernel_services.py
backend/tests/unit/test_kernel_fiber.py
docs/plans/2026-10-21_plugin-kernel-r78.md   ← 本文
docs/plans/plugin-evo-index.md               ← 新建账本
```

## 9. 下游依赖（R79 起才会触碰）

- R79：`backend/hooks/*` 的注册改走 `PluginHost.effect()`，旧 `.sage/hooks.json` 路径保留
- R80：`backend/tools/__init__.py` 的硬编码装配改为 bundle 注册
- R81：`harness.yaml` 三层叠加 + 按路径寻址的 patch
