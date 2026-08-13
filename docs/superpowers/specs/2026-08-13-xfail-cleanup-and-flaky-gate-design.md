# xfail 清理 + 事件循环门禁升级 设计

> **状态**: Design — 待用户 review
> **作者**: Claude
> **日期**: 2026-08-13
> **范围**: 1 spec 涵盖 2 PR 改动,实施时拆分为独立 PR(PR1 = xfail 清理,PR2 = 门禁升级)
> **关联 issue**: 无;源于 PR #308 (`fix(llm-proxy)`) 观察到的两条独立问题
> **回滚成本**: 每 PR 单独 revert 即可,互不依赖

## 背景

PR #308 (`fix(llm-proxy): dedupe /v1 when baseURL already ends with /v1`) 监控 CI 时观察到两条**互相独立但都阻碍后端 CI 健康的**问题:

1. **过时 xfail 堆积** — 6 个测试文件模块级挂了 `pytest.mark.xfail(reason="respx mock 与 httpx 客户端不兼容,预存在问题")`,是 2026-06-26/27 临时绕过 pre-push hook 加的。49 天后这些测试全部 XPASS(104/104),意味着 respx 与 httpx 兼容问题**已不存在**,但 marker 仍在掩盖测试。
2. **`test_health_latency_under_concurrent_session_crud` CI flake** — §1.2 修复(PR #294)回归门禁阈值,2026-08-13 在 PR #308 的 CI runner 上被踩破(P99=376ms)。阈值历史:50ms → PR #294 改 100ms → PR #298/99 改 200ms → 本 spec 改 150ms 中位数。继续放宽阈值是治标不治本。

两条问题都"小事",但合在一起让 Backend Python CI 红灯频繁,开发者每次都要先排查是否真 bug。

## 目标

- **PR1**: 把 6 个文件共 104 个测试从「标记失败」恢复为「实际验证」,零功能改动。
- **PR2**: 把单点 P99 门禁改为「5 轮重复 + P99 中位数」,抗 CI runner 单次抖动,同时对真实 §1.2 复班保持敏感。

## 非目标

- 不动 conftest.py / 任何业务代码(后端 API、路由、SQLite schema)。
- 不重写 event_loop_blocking 测试的 `collect_health_samples_during_load` 内部逻辑。
- 不引入新依赖(不引入 `pytest-repeat` / `pytest-rerunfailures`)。
- 不修改 `HEALTH_BASELINE_THRESHOLD_MS`(空闲基线门禁,与本问题无关,稳定通过)。
- 不动 `HEALTH_P99_THRESHOLD_MS` 之外的常量(除 `GATE_REPETITIONS` 新增外)。

## 设计

### 架构总览

```
┌──────────────────────────────────────────────────────────────────┐
│          PR1: xfail 清理(test infrastructure)                   │
│                                                                  │
│   6 个测试文件删除模块级 pytest.mark.xfail:                      │
│   - backend/tests/integration/test_llm_proxy_routes.py          │
│   - backend/tests/unit/test_llm_client_remaining.py             │
│   - backend/tests/unit/test_llm_client_reasoning_params.py      │
│   - backend/tests/unit/test_httpx_llm_adapter.py                │
│   - backend/tests/unit/test_web_tool.py                         │
│   - backend/tests/unit/test_conftest_fixtures.py                │
│                                                                  │
│   效果:104 个测试从「预期失败」变为「实际验证」                    │
│   风险:0(本地已跑通 1811 passed,respx 工作正常)                  │
│                                                                  │
├──────────────────────────────────────────────────────────────────┤
│          PR2: 事件循环门禁换策略(test sensitivity)               │
│                                                                  │
│   backend/tests/integration/test_event_loop_blocking.py         │
│   - 函数 test_health_latency_under_concurrent_session_crud      │
│     内部增加「5 轮重复 + 取 P99 中位数」逻辑                     │
│   - 阈值改 200ms → 150ms(中位数比单次容错更强,可更严)           │
│   - 保留单次 P99 作为诊断信息打印(供本机排查用)                  │
│                                                                  │
│   效果:CI 抖动不再单点定罪;真出 §1.2 复班时仍能触发 fail         │
│   风险:中(需在 CI runner 上验证 5 轮中位数能区分正常 vs 真的阻塞)│
│                                                                  │
├──────────────────────────────────────────────────────────────────┤
│          共用前置:win7 LTS 同步(都需 cherry-pick)                │
│                                                                  │
│   PR1 → cherry-pick 到 release/win7(纯 Python 测试改动,py38 兼容)│
│   PR2 → 在 sage-backend-py38 环境跑一次手动验证 → 再 cherry-pick │
└──────────────────────────────────────────────────────────────────┘
```

### 组件细节

#### 组件 1 — PR1 `xfail 清理器`(纯删除,无新逻辑)

**Before**(示例 `test_llm_proxy_routes.py:17-20`):
```python
pytestmark = [
    pytest.mark.integration,
    pytest.mark.xfail(reason="respx mock 与代理新 httpx 客户端不兼容,预存在问题"),
]
```

**After**:
```python
pytestmark = [pytest.mark.integration]
```

6 个文件统一动作,删除 `pytest.mark.xfail(...)` 这一行,保留 `pytest.mark.unit` / `pytest.mark.integration`。

**为什么不引入新抽象(conftest helper / 自动 marker 注入)?**
- KISS:测试本来就过,不需要 helper。
- 每个文件 2 行改动,reviewer 一眼看完。
- git blame 立即能定位到原作者(无需迁移历史)。

#### 组件 2 — PR2 `门禁重试器`(新逻辑,小函数)

**Before**(节选 `test_event_loop_blocking.py:71-100`):
```python
async def test_health_latency_under_concurrent_session_crud(client):
    """§1.2 修复回归:.../health P99 < HEALTH_P99_THRESHOLD_MS。"""
    # 启动负载线程...
    samples = await collect_health_samples_during_load(client, CONCURRENT_WRITES)
    p99 = percentile(samples, 99)
    assert p99 < HEALTH_P99_THRESHOLD_MS, ...
```

**After**:
```python
# 顶部常量(替换)
HEALTH_P99_THRESHOLD_MS = 150.0  # 中位数阈值,比单次 200ms 更严,因抗抖动
GATE_REPETITIONS = 5             # 跑 5 轮,中位数代表

async def test_health_latency_under_concurrent_session_crud(client):
    """§1.2 修复回归(抗 CI runner 抖动版):5 轮 P99 中位数 < 150ms。"""
    p99s = []
    for round_idx in range(GATE_REPETITIONS):
        try:
            samples = await collect_health_samples_during_load(
                client, CONCURRENT_WRITES
            )
        except (httpx.ReadTimeout, httpx.ConnectError) as exc:
            # 单次网络异常记惩罚值,避免毁掉整次 CI
            print(f"  [round {round_idx+1}] 探针网络异常 {exc!r},记为惩罚值 9999ms")
            p99s.append(9999.0)
            continue

        p99 = percentile(samples, 99)
        p99s.append(p99)
        print(f"  [round {round_idx+1}/{GATE_REPETITIONS}] /health p99={p99:.1f}ms")

    p99s_sorted = sorted(p99s)
    median_p99 = p99s_sorted[len(p99s_sorted) // 2]
    worst_p99 = p99s_sorted[-1]
    print(f"  → median_p99={median_p99:.1f}ms, worst_p99={worst_p99:.1f}ms")
    assert median_p99 < HEALTH_P99_THRESHOLD_MS, (
        f"§1.2 修复失效? 5 轮 /health P99 中位数={median_p99:.1f}ms > "
        f"{HEALTH_P99_THRESHOLD_MS}ms (worst={worst_p99:.1f}ms, all={p99s})"
    )
```

**关键点:**
- **不改 `collect_health_samples_during_load` 内部逻辑** — 它是 5 轮共用,只外层循环。
- **5 轮 ≈ 5 × 2.5s ≈ 12.5s,加进 CI 总时长 +12s,可接受**。
- **最坏情况判定**:单轮 P99 > 阈值但中位数 < 阈值 → 仍绿(抗抖动);5 轮 P99 都超 → 红(真复班)。
- **保留 `print` 作为诊断信息**:CI log 可看到每轮数据,便于事后追溯。

#### 组件 3 — 共用:`win7 LTS 同步器`

两 PR merge 后:
1. 开 cherry-pick PR 到 `release/win7`。
2. PR2 在 win7 cherry-pick 后,**必须**手动跑一次:
   ```bash
   conda run -n sage-backend-py38 python -m pytest \
     backend/tests/integration/test_event_loop_blocking.py -v
   ```
   确认 5 轮完成且中位数 < 150ms(Py3.8 性能略差但 150ms 阈值仍有富余)。

### 数据流(PR2 主要新增逻辑)

```
test_health_latency_under_concurrent_session_crud(client)
  └─ for round in range(GATE_REPETITIONS=5):
       └─ collect_health_samples_during_load(client, CONCURRENT_WRITES=200)
          ├─ 后台启动 200 个并发 POST /api/v1/sessions
          ├─ 主协程收集期间 200 次 GET /health 的延迟样本
          └─ 返回 samples: list[float]
       └─ percentile(samples, 99) → 单轮 P99
       └─ append 到 p99s: list[float]
  └─ p99s_sorted = sorted(p99s)
  └─ median_p99 = p99s_sorted[2]    (中位数)
  └─ worst_p99  = p99s_sorted[-1]   (最大值,仅诊断)
  └─ assert median_p99 < HEALTH_P99_THRESHOLD_MS=150.0
```

#### 关键边界与异常

| 场景 | 行为 |
|------|------|
| CI runner 抽风,5 轮里只有 1 轮 376ms | 中位数可能 < 150ms → 绿灯(抗抖动) |
| 真的 §1.2 复班,5 轮全部超 200ms | 中位数 > 150ms → 红灯(敏感度比单次 200ms 更强) |
| 5 轮里 3 轮 > 200ms,2 轮 < 100ms | 中位数约 180ms → 红灯;log 提示 "worst=300ms, all=[200,210,80,90,300]" |
| 单次网络瞬断(ReadTimeout/ConnectError) | 该轮记惩罚值 9999ms,后续中位数门禁负责评判 |
| 后台 200 个 session POST 集体失败 | `collect_health_samples_during_load` 内部 raise,直接抛 |
| 客户端 fixture setup 失败 | pytest 自身机制捕获,与本逻辑无关 |

### 错误处理

#### PR1 残留风险

| 风险 | 概率 | 处理 |
|------|------|------|
| 删除后某些测试真的不通过(原 XPASS 是 flaky) | 极低 | PR1 验证阶段就跑一次 `pytest backend/tests/ -m "unit or integration"`,看是否全绿;若发现 flaky,退回加回 xfail 并写 follow-up |
| 6 个文件之一在 main 上被其他 PR 修改,merge 时冲突 | 低 | merge 时 `gh pr merge` 会显示冲突,届时 rebase 解 |

#### PR2 错误处理决策

| 错误类型 | 来自 | 处理策略 | 理由 |
|---------|------|---------|------|
| 单次 `/health` 探针 ReadTimeout/ConnectError | httpx 网络栈 | 该轮记为惩罚值(9999ms),不抛 | 避免一次瞬断毁掉整次 CI;惩罚值会让该轮拖累中位数(若多轮网络异常,中位数会升高,符合预期) |
| 后台 200 个 session POST 集体失败 | SQLite/DB 问题 | **继续抛**(`collect_health_samples_during_load` 内部已 raise) | 这是真错误,需要 PR 修复 |
| 客户端 fixture setup 失败 | conftest.py | **继续抛**(pytest 自动捕获) | 与本逻辑无关,按原机制处理 |
| `percentile` 计算返回 nan | 样本为空(理论不可能) | 显式抛 `AssertionError("samples empty")` | 防御性编程 |
| 测试本身被 `pytest.skip` 跳过 | 上游 marker | **不抛**;跳过意味着没门禁,与本逻辑无关 | 维持 pytest 原行为 |

#### 为什么不直接 retry 整个测试函数?

考虑过 `pytest-repeat` / `pytest-rerunfailures` 自动 rerun 失败测试。**不采用**,因为:
1. 这些是 plugin,要更新依赖并扩 pytest 配置,改动面比内联循环更大。
2. 自动 rerun 会掩盖偶发真实失败(不是所有 fail 都该自动重试)。
3. 内联 5 轮循环让 log 透明(每轮数据都打印),比黑盒 retry 更有诊断价值。

### 测试方案

#### PR1 验证

| 验证 | 方法 | 通过标准 |
|------|------|---------|
| 本地单跑 6 个被改文件 | `pytest <6 files> -v` | 0 failed, 0 error, 合计 104 passed(无 XPASS) |
| 回归后端全量 | `pytest backend/tests/ -m "unit or integration" -q` | 失败数 = 0;若出现新 failed,立即回滚 PR1 |
| CI 绿 | push → `gh pr checks` 监控 | Backend Python job 全绿 |

#### PR2 验证

| 验证 | 方法 | 通过标准 |
|------|------|---------|
| 本地单跑新门禁 | `pytest backend/tests/integration/test_event_loop_blocking.py::test_health_latency_under_concurrent_session_crud -v -s` | 5 轮全部完成,中位数 < 150ms,log 可见 5 个 round 行 |
| 本机 CPU 抖动模拟 | 用 `stress --cpu 4 --timeout 30 &` 人工施压 | 验证抗抖动:即使 1 轮超阈值,中位数仍 < 150ms → 绿 |
| 回归单测 | `pytest backend/tests/unit/test_event_loop_blocking.py` | 全绿 |
| CI 绿 | push → `gh pr checks` | Backend Python job 全绿;若 flaky 仍出现,先 read 数据,可能需 GATE_REPETITIONS=7 |
| win7 验证(合并后由 cherry-pick PR 触发) | `conda run -n sage-backend-py38 python -m pytest backend/tests/integration/test_event_loop_blocking.py -v` | 5 轮完成,中位数 < 150ms |

#### PR2 回归测试设计原则

门禁本身**没有新功能**,所以不写新单测。验证手段是**跑一遍门禁本身**(5 轮循环 + 中位数计算),看是否:

1. 正常情况:5 轮全 < 100ms → 中位数 ~50ms → 绿(原门禁也会绿)
2. CI 抖动:1 轮 376ms + 4 轮 < 100ms → 中位数 ~80ms → 绿(原门禁会红 ❌ → 新门禁绿 ✅,这就是新门禁的价值)
3. 真复班:5 轮全 > 200ms → 中位数 > 200ms → 红(原门禁也会红)

如果想给 5 轮循环逻辑本身加单测,需要 mock `collect_health_samples_during_load` 返回固定 samples,**YAGNI** — 这部分代码 8 行,直接跑门禁比单测更可信。

### 文档同步

- `docs/technical/` 下找现有 §1.2 相关章节(若有)追加"门禁升级"段;若无可新建 `XX-event-loop-gate.md`,实施时按当时编号。
- 内容:阈值历史(50 → 100 → 200 → 150 中位数),`GATE_REPETITIONS=5` 的设计权衡。

## 风险评估

| 风险 | 概率 | 影响 | 缓解 |
|------|------|------|------|
| PR1 移除 xfail 后某个测试在 CI 上 fail | 极低(本地 1811 passed) | PR1 阻塞 merge | PR 验证阶段全量 pytest;若发现,加回 xfail 并记 follow-up |
| PR2 5 轮跑超时 CI runner 容忍度 | 低(每轮 2.5s,总 +12s) | CI 时长 +12s | 可接受;若不接受,降 GATE_REPETITIONS=3(中位数仍稳健) |
| PR2 中位数 150ms 太严,旧 runner 经常挂 | 中 | 门禁反复红 | 先在 1-2 个 PR 上观察;若仍频繁,改 175ms |
| 5 轮循环 bug 写错 | 低 | 门禁误判 | commit 前本地跑一次门禁,对比 log |
| win7 Py3.8 性能比 Py3.11 慢,5 轮中位数超 150ms | 中 | win7 LTS CI 频繁红 | 必在 py38 环境验证;若超,降阈值到 200ms |

## 依赖

- 不引入新 Python 依赖。
- 不修改 conftest.py。
- 不动业务代码(后端 API、路由、SQLite schema)。
- 复用现有 `collect_health_samples_during_load` helper。
- 新增 import: `httpx`(已在 conftest.py 中导入,test 文件需 `import httpx`)。

## 实施步骤

> 实施时拆分为两个独立 PR,各自独立 review + merge + cherry-pick 到 win7。

### PR1 — xfail 清理

1. 新建 `fix/cleanup-xfail-markers` 分支(基于 main)。
2. 删除 6 个文件的 `pytest.mark.xfail(...)` 行。
3. 本地跑 `pytest <6 files> -v` 验证 104 passed。
4. 本地跑 `pytest backend/tests/ -m "unit or integration" -q` 验证无回归。
5. commit: `test: remove stale respx xfail markers — 104 tests back to real verification`
6. push + `gh pr create`。
7. 监控 CI,merge。
8. cherry-pick 到 `release/win7`。

### PR2 — 门禁升级

1. 等 PR1 merge 后,新建 `test/event-loop-gate-median-p99` 分支。
2. 修改 `backend/tests/integration/test_event_loop_blocking.py`:
   - 新增 `GATE_REPETITIONS = 5` 常量。
   - 改 `HEALTH_P99_THRESHOLD_MS = 200.0` → `150.0`。
   - 改 `test_health_latency_under_concurrent_session_crud` 函数体为 5 轮循环。
   - 更新 module docstring 注释段(200ms 历史 → 150ms 中位数历史)。
3. 本地跑门禁 + 全量 pytest 验证。
4. commit: `test(event-loop): 5-round median P99 gate, 200ms → 150ms median`
5. push + `gh pr create`。
6. 监控 CI;若 CI runner 上仍有 flake,read log,考虑 GATE_REPETITIONS=7。
7. merge。
8. cherry-pick 到 `release/win7`,**在 py38 环境验证**。

## 成功标准

- PR1:Backend CI 全绿;104 个测试从 XPASS 变为 pass。
- PR2:Backend CI 全绿;`test_health_latency_under_concurrent_session_crud` 在 5 轮下中位数 < 150ms;真 §1.2 复班时仍能 fail。
- Win7:两 PR cherry-pick 后 py38 环境跑通。
- CI Backend Py job 在接下来 4 周内,无 flake 红灯出现(若仍出现,降 GATE_REPETITIONS 到 3 或阈值 175ms)。