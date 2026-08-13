# 43. §1.2 事件循环门禁升级 — 5 轮 P99 中位数

> **最后更新**: 2026-08-13
> **适用版本**: Sage main @ 8175d48f（PR #312 已 merged）
> **背景计划**: [`../superpowers/specs/2026-08-13-xfail-cleanup-and-flaky-gate-design.md`](../superpowers/specs/2026-08-13-xfail-cleanup-and-flaky-gate-design.md)
> **关联章节**: [15 质量门禁](./15-quality-gates.md)、[42 Chat-Native Multi-Agent Orchestration](./42-chat-multi-agent-orchestration.md)

---

## 43.1 背景：为什么需要这道门禁

PR #294（§1.2 事件循环阻塞修复，**main-only**）把 `backend/api/legacy_routes.py` 中 34 个无 `await` 的 `async def` handler 降级为 `def`，让 FastAPI/Starlette 把它们 dispatch 到 anyio 默认 threadpool，不再阻塞事件循环；同时引入共享 `threading.Lock`（与 PR B 的 adapter `asyncio.to_thread` 共用 `_SQLITE_LOCK`）与 jieba 预热。

修复前：34 个 handler 是 `async def`，SQLite 写在事件循环上，200 并发会把事件循环占满，`/health` 探针排队等待，P99 飙到 200-500ms。

修复后：handler 是 `def`，SQLite 写跑在 threadpool，事件循环空闲，`/health` P99 本机实测 < 50ms（5 轮中位数 22.8ms）。

**门禁定位**：`backend/tests/integration/test_event_loop_blocking.py` 的 `test_health_latency_under_concurrent_session_crud` 是守护这次修复不被回归的 **regression gate**——"§1.2 修复真的失效时才应失败"，而非"runner 资源抖动一次就红"。

> **Win7 LTS 侧说明**：PR #294 从未 cherry-pick 到 `release/win7`，所以这道门禁是 **main-only**；win7 侧同步已在 2026-08-13 用户决策中跳过（无对应基础设施可守护）。

---

## 43.2 门禁升级：单点 P99 → 5 轮 P99 中位数

### 阈值演进历史

| 阶段 | 阈值 | 触发原因 |
|------|------|---------|
| 初始 | `50ms` | §1.2 修复后本机基线 |
| PR #294 | `100ms` | 修复后放宽 |
| PR #298 | `200ms` | CI runner 与 Electron build 共享 CPU，实测 p99=376.4ms，rerun 100% 复现 |
| 原计划假设 | `150ms`（中位数） | 基于本机性能（中位数 ~11ms）推算的"留足 buffer"设计值 |
| **最终定稿（PR #312）** | **`400ms`（中位数）** | CI 现实校准 |

### 为什么最终是 400ms 而不是 150ms

单点 P99 阈值被 CI runner CPU 争用反复踩破。**这不是单点抖动，而是 runner 本身慢**：CI runner 持续基线 ~350ms，实测单轮 P99=376ms 可 100% 复现，而本地（`sage-backend` conda 环境）5 轮中位数 22.8ms——本机 vs CI 存在 ~15x 差距。

原始 spec 假设 CI runner 性能 ≈ 本机，150ms 是"留足 buffer"的设计值；但 PR #312 第一次 CI 跑显示 5 轮全在 ~350ms，与 PR #298 文档化的 p99=376.4ms 完全一致。**150ms 阈值是规划阶段的假设错误，不是 5 轮中位数设计本身的错误**——设计保留，只放宽阈值。

400ms 正好坐在 **CI baseline（~350ms）之上、§1.2 真回归范围（500ms+）之下**的安全中位。

### 最终设计

- 门禁文件：`backend/tests/integration/test_event_loop_blocking.py`
- 常量：`HEALTH_P99_THRESHOLD_MS = 400.0`、`GATE_REPETITIONS = 5`、`HEALTH_BASELINE_THRESHOLD_MS = 20.0`（空闲基线，不变）
- 跑 `GATE_REPETITIONS = 5` 轮 `test_health_latency_under_concurrent_session_crud`
- 取 5 轮 P99 的**中位数**：`sorted(p99s)[len(p99s)//2]`
- 中位数 < `HEALTH_P99_THRESHOLD_MS`（400ms）算通过

`GATE_REPETITIONS = 5` 保留不变。若想进一步降 CI 时长，可降为 3（中位数仍稳健，但容错差一些）。

### 抗抖动 vs 真回归权衡

| 场景 | 单点 P99 | 5 轮中位数（400ms） |
|------|---------|-------------------|
| 1 轮 376ms + 4 轮 < 100ms | ❌ 红 | ✅ 绿（中位数 ~80ms，抗单轮抖动） |
| 5 轮全 ~350ms（CI baseline） | ❌ 红 | ✅ 绿（阈值是 400ms，不误报） |
| 5 轮全 > 500ms（§1.2 真回归） | ❌ 红 | ❌ 红（中位数 > 400ms，仍能抓住真回归） |

### 单轮网络瞬断处理

`httpx.ReadTimeout` / `httpx.ConnectError` → 该轮记**惩罚值 9999ms**，继续后续轮次，不毁掉整次 CI。惩罚值会拖累中位数：若多轮都网络异常，中位数会升高 → 反映真问题。

### 已知权衡

400ms 能抓住 §1.2 **总回归**（5 轮全 > 500ms），但会**漏掉 200→400ms 的渐进漂移**（已记录在 PR #312 body）。这是接受 CI runner 基线 ~350ms 的现实代价——阈值低于 350ms 必然每轮误报红。

### CI 时长影响

5 轮 × ~2.5s/轮 ≈ **+12s** 总 CI 时长。可接受；若不接受，降 `GATE_REPETITIONS = 3`。

---

## 43.3 如何应用

- PR B（StoragePort to_thread）完成后，加类似测试覆盖 `chat_stream_create` 阻塞场景。
- PR C（wiki_routes 修复）完成后，加类似测试覆盖 wiki 文件 IO 阻塞场景。
