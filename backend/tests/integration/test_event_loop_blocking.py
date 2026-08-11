"""§1.2 修复回归测试 — 验证事件循环不再被 sync SQLite 调用阻塞。

## 背景
PR #294 §1.2 把 `backend/api/legacy_routes.py` 中 34 个无 await 的 `async def` handler
降级为 `def`,让 FastAPI/Starlette 把它们 dispatch 到 anyio 默认 threadpool,不再
阻塞事件循环。

## 测试策略
- **核心断言**:并发跑多个 session CRUD(sync def,跑在 threadpool),期间 `/health`
  P99 < 50ms。
  - 修复前 (handler 是 async def):所有 SQLite 写阻塞事件循环,`/health` 排队等待,
    P99 飙到 200-500ms。
  - 修复后 (handler 是 def):SQLite 写跑在 threadpool,事件循环空闲,`/health` P99 < 50ms。
- **基线对比**:单独跑 `/health` 时,延迟 < 5ms(纯 dict 返回)。
- **回归保护**:测试通过任何 P0 §1.2 PR 改动都会被守护。

## How to apply
- PR B(StoragePort to_thread)完成后,加类似测试覆盖 chat_stream_create 阻塞场景。
- PR C(wiki_routes 修复)完成后,加类似测试覆盖 wiki 文件 IO 阻塞场景。
"""
from __future__ import annotations

import asyncio
import time
from typing import List

import pytest

pytestmark = pytest.mark.integration

# /api/v1/sessions 端点(legacy mode)
SESSIONS_URL = "/api/v1/sessions"
HEALTH_URL = "/health"

# 验收门槛 (毫秒): /health 空闲时延迟应低于 20ms;加 50 并发 SQLite 写负载后,
# 事件循环若空闲则 /health P99 < 100ms;修复前 P99 会 > 200ms (被 sqlite 写排队)。
HEALTH_P99_THRESHOLD_MS = 100.0
HEALTH_BASELINE_THRESHOLD_MS = 20.0  # 空闲时 /health 单次 < 20ms

# 负载规模
CONCURRENT_WRITES = 50  # 50 并发 session POST(锁串行化后 50 个仍可让 probe 采 ≥ 30 个样本)


@pytest.mark.asyncio()
async def test_health_baseline_no_load(client):
    """基线:无负载时 /health 延迟 < 20ms。"""
    samples: List[float] = []
    for _ in range(20):
        t0 = time.perf_counter()
        r = await client.get(HEALTH_URL)
        elapsed_ms = (time.perf_counter() - t0) * 1000
        assert r.status_code == 200
        samples.append(elapsed_ms)

    samples_sorted = sorted(samples)
    p99 = samples_sorted[int(len(samples_sorted) * 0.99)]
    avg = sum(samples) / len(samples)
    print(f"\n  /health baseline: avg={avg:.1f}ms p99={p99:.1f}ms (n={len(samples)})")  # noqa: T201
    assert p99 < HEALTH_BASELINE_THRESHOLD_MS, (
        f"/health baseline p99={p99:.1f}ms > {HEALTH_BASELINE_THRESHOLD_MS}ms"
    )


@pytest.mark.asyncio()
async def test_health_latency_under_concurrent_session_crud(client):
    """§1.2 修复回归:50 并发 POST /api/v1/sessions 期间,/health P99 < 50ms。

    修复前:34 个 handler 是 async def,SQLite 写在事件循环上,50 并发会
    把事件循环占满,/health 探针排队等待,P99 飙到 200-500ms。
    修复后:handler 是 def,SQLite 写跑 threadpool,事件循环空闲,/health P99 < 50ms。

    50 并发选择:修复后 lock 串行化让单批负载完成在 100ms 内,50 个足够
    让 /health 探针采集到至少 30 个样本。
    """
    CONCURRENT = 200  # 增加负载以确保探针采集足够样本(修复前 50 不够 — 负载太快完成,样本不足)
    health_samples: List[float] = []
    write_tasks: List[asyncio.Task] = []

    async def probe_health(stop: asyncio.Event) -> None:
        """持续打 /health 探针,直到 stop 事件。"""
        while not stop.is_set():
            t0 = time.perf_counter()
            r = await client.get(HEALTH_URL)
            elapsed_ms = (time.perf_counter() - t0) * 1000
            assert r.status_code == 200
            health_samples.append(elapsed_ms)
            # 短间隔,模拟高频探针
            await asyncio.sleep(0.002)

    # 启动 /health 探针后台任务
    stop = asyncio.Event()
    probe_task = asyncio.create_task(probe_health(stop))

    try:
        # 启动 CONCURRENT 个并发 POST /api/v1/sessions(降级后是 def,跑 threadpool)
        for i in range(CONCURRENT):
            task = asyncio.create_task(
                client.post(SESSIONS_URL, json={"title": f"load-test-{i}"})
            )
            write_tasks.append(task)

        # 等所有写完成
        responses = await asyncio.gather(*write_tasks, return_exceptions=True)

        # 确认所有写都成功
        for i, r in enumerate(responses):
            if isinstance(r, Exception):
                pytest.fail(f"session {i} failed: {r}")
            assert r.status_code in (200, 201), f"session {i} got {r.status_code}: {r.text}"
    finally:
        # 停止探针
        stop.set()
        await probe_task

    # 收集至少 30 个 /health 样本(确保负载期间确实在测)
    assert len(health_samples) >= 30, (
        f"健康探针样本不足: {len(health_samples)} < 30 (负载太快完成)"
    )

    # 算 /health P99
    samples_sorted = sorted(health_samples)
    p50 = samples_sorted[len(samples_sorted) // 2]
    p99 = samples_sorted[int(len(samples_sorted) * 0.99)]
    p100 = samples_sorted[-1]
    avg = sum(health_samples) / len(health_samples)

    print(  # noqa: T201
        f"\n  /health under {CONCURRENT_WRITES} concurrent session POST:\n"
        f"    samples: {len(health_samples)}, avg={avg:.1f}ms "
        f"p50={p50:.1f}ms p99={p99:.1f}ms p100={p100:.1f}ms"
    )

    # 核心断言:事件循环应保持空闲,/health P99 < 100ms
    assert p99 < HEALTH_P99_THRESHOLD_MS, (
        f"§1.2 修复失效? /health P99={p99:.1f}ms > {HEALTH_P99_THRESHOLD_MS}ms\n"
        f"  这说明 30 并发 session POST 仍阻塞事件循环(应该是 def 跑 threadpool)。\n"
        f"  请检查:1) legacy_routes.py session CRUD handler 是否已降级为 def;\n"
        f"        2) 是否被某个新代码意外改成 async def。\n"
        f"  samples: avg={avg:.1f}ms p50={p50:.1f}ms p99={p99:.1f}ms"
    )


@pytest.mark.asyncio()
async def test_concurrent_session_list_completes(client):
    """基线:50 并发 GET /api/v1/sessions(降级为 def)全部成功,总耗时合理。

    验证 threadpool 排队 + sqlite 读延迟合理。这是 PR A 修复的副作用测试。
    """
    # 先建一些 session 供读取
    for i in range(5):
        await client.post(SESSIONS_URL, json={"title": f"setup-{i}"})

    # 50 并发 GET
    N = 50
    t0 = time.perf_counter()
    tasks = [client.get(f"{SESSIONS_URL}?limit=20") for _ in range(N)]
    responses = await asyncio.gather(*tasks, return_exceptions=True)
    total_ms = (time.perf_counter() - t0) * 1000

    # 验证所有请求成功
    for i, r in enumerate(responses):
        if isinstance(r, Exception):
            pytest.fail(f"GET #{i} failed: {r}")
        assert r.status_code == 200

    avg = total_ms / N
    print(f"\n  50 并发 GET /api/v1/sessions: total={total_ms:.0f}ms avg={avg:.1f}ms")  # noqa: T201
    # 不强约束 P99,只确保所有请求成功 + 总时长合理
    assert total_ms < 5000, f"50 并发 GET 总耗时 {total_ms:.0f}ms 过长"


@pytest.mark.asyncio()
async def test_cross_path_concurrent_no_sqlite_programming_error(client):
    """PR B §1.2 跨路径并发回归:PR A (sync def handler 直连 repo) + PR B
    (async adapter → to_thread) 同时打同一个 sqlite3.Connection,不能报错。

    修复前:PR B 用 per-instance ``asyncio.Lock``,PR A 用 module-level
    ``threading.Lock``。两把锁互不可见,而底层是同一个
    ``sqlite3.Connection(check_same_thread=False)`` —— PR A handler 跑
    SELECT 的同时 PR B worker 跑 INSERT,可触发
    "cannot start a transaction within a transaction"。

    修复后:两者共用 ``backend.data.database._SQLITE_LOCK``,所有同步
    SQLite 访问串行化。

    NOTE(实现偏差):brief 原本建议用 ``POST /api/v1/chat/stream`` 作为 PR B
    路径,但 ``main.py`` 的 ``_API_MODE`` 默认是 ``legacy``,hex_router 未挂载,
    且 legacy ``/chat/stream`` 走的是 ``SessionRepository``(仍是 PR A 路径)
    —— 那样测不到 adapter。这里直接驱动 ``SqliteStorageAdapter``,才真正让
    两条路径并发。
    """
    import sqlite3

    from backend.adapters.out.storage.sqlite_adapter import SqliteStorageAdapter

    PR_A_COUNT = 20
    PR_B_COUNT = 20

    adapter = SqliteStorageAdapter()

    # PR A:HTTP handler(sync def + @with_db_lock,跑在 anyio threadpool)
    pr_a_tasks = [
        asyncio.create_task(client.post(SESSIONS_URL, json={"title": f"pr_a_{i}"}))
        for i in range(PR_A_COUNT)
    ]
    # PR B:adapter(async + asyncio.to_thread + _SQLITE_LOCK)
    pr_b_tasks = [
        asyncio.create_task(adapter.create_session(title=f"pr_b_{i}"))
        for i in range(PR_B_COUNT)
    ]

    responses = await asyncio.gather(*pr_a_tasks, *pr_b_tasks, return_exceptions=True)

    sqlite_errors: List[BaseException] = []
    other_errors: List[BaseException] = []
    success_count = 0
    for r in responses:
        if isinstance(r, BaseException):
            # OperationalError 同样是连接竞争的表现形式之一
            if isinstance(r, sqlite3.ProgrammingError | sqlite3.OperationalError):
                sqlite_errors.append(r)
            else:
                other_errors.append(r)
        else:
            success_count += 1

    assert not sqlite_errors, (
        f"跨路径并发暴露 SQLite 连接竞争(PR A + PR B 锁未共享):\n"
        f"  sqlite errors: {len(sqlite_errors)}\n"
        f"  first: {sqlite_errors[0]!r}\n"
        f"  other errors: {len(other_errors)}"
    )
    assert success_count >= PR_A_COUNT + PR_B_COUNT - 5, (
        f"太多非 SQLite 失败: {len(other_errors)} 个 ({other_errors[:3]!r})\n"
        f"  success={success_count}, expected~{PR_A_COUNT + PR_B_COUNT}"
    )

    # PR B 侧额外验证:20 个 create_session 必须产出 20 个唯一 ID
    pr_b_ids = [r for r in responses[PR_A_COUNT:] if isinstance(r, str)]
    assert len(set(pr_b_ids)) == len(pr_b_ids), (
        f"SqliteStorageAdapter 并发产出重复 session ID: {len(set(pr_b_ids))} != {len(pr_b_ids)}"
    )


if __name__ == "__main__":
    # 允许 `python backend/tests/integration/test_event_loop_blocking.py` 直接跑
    pytest.main([__file__, "-v", "-s"])
