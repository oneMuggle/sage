"""
Sage - 记忆型 AI 桌面助手
FastAPI 后端入口
"""
import asyncio
import logging
import os
import uuid
from contextlib import asynccontextmanager, suppress
from typing import List

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from backend.adapters.out.event.file_adapter import FileEventAdapter
from backend.adapters.out.llm.httpx_adapter import HttpxLLMAdapter
from backend.adapters.out.memory.adapter import MemoryAdapter
from backend.adapters.out.metric.prometheus_adapter import PrometheusMetricAdapter
from backend.adapters.out.storage.sqlite_adapter import SqliteStorageAdapter
from backend.adapters.out.tool.inproc_adapter import InprocToolAdapter
from backend.api.chat_stream_registry import StreamRegistry
from backend.api.hex_routes import router as hex_router
from backend.api.legacy_routes import router as legacy_router
from backend.api.llm_proxy_routes import router as llm_proxy_router
from backend.api.mcp_routes import router as mcp_router
from backend.api.office_routes import (
    register_office_exception_handlers,
    router as office_router,
)
from backend.api.orchestration_router import build_router as build_orchestration_router
from backend.api.scheduled_router import build_router as build_scheduled_router
from backend.api.theme_router import router as theme_router
from backend.api.wiki_routes import router as wiki_router
from backend.api.workspace_routes import router as workspace_router
from backend.application.services.chat_service import ChatService
from backend.data.database import Database
from backend.data.session_repo import MessageRepository, SessionRepository
from backend.memory import get_memory_manager
from backend.services.scheduler import (
    get_scheduler_service,
    init_scheduler_service,
)

logger = logging.getLogger(__name__)


def _build_compute_adapter():
    """按 ``backend/config/ghm.yaml`` 装配 ComputePort。

    返回 ``None`` 时表示:

    - yaml 文件不存在(向后兼容,旧部署无 ghm 集成)
    - ``ghm.enabled = false`` (显式关闭)

    yaml 加载/解析异常会被记录并降级为 ``None``,不阻塞主流程。
    """
    from pathlib import Path

    import yaml

    cfg_path = Path("backend/config/ghm.yaml")
    if not cfg_path.is_file():
        return None

    try:
        raw = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}
        ghm_cfg = raw.get("ghm") or {}
    except (OSError, yaml.YAMLError) as exc:
        logger.warning("ghm.yaml 加载失败，跳过 ComputePort 装配: %s", exc)
        return None

    if not ghm_cfg.get("enabled", False):
        return None

    adapter_type = ghm_cfg.get("adapter", "subprocess")
    if adapter_type == "subprocess":
        from backend.adapters.out.compute.subprocess_adapter import (
            SubprocessComputeAdapter,
        )

        return SubprocessComputeAdapter(ghm_cfg)
    raise ValueError(f"未知的 ghm.adapter 类型: {adapter_type!r},有效值: 'subprocess'")


def _build_chat_service(lifecycle=None) -> ChatService:
    """工厂：装配 7 个 ports（6 个生产 adapter + 1 个暂未实现 placeholder）。

    - llm:     HttpxLLMAdapter（包装既有 LLMClient）
    - tools:   InprocToolAdapter（如启用 ghm，则用 ComputeToolAdapter 包装合并）
    - skills:  None（SkillPort 协议未实现；P3 接入）
    - storage: SqliteStorageAdapter（包装既有 SessionRepository / MessageRepository）
    - metrics: PrometheusMetricAdapter
    - events:  FileEventAdapter（写 audit jsonl）
    - memory:  MemoryAdapter（包装 MemoryManager，提供三层记忆系统）
    - lifecycle: 可选的 MemoryLifecycleManager（Task 4 / Gap A）— 让 run_turn
      驱动 set_current_turn，从而在生产路径上填充 source_turn_id。

    装配在每次依赖注入时被调用——单例化由调用方（如 ``app.state``）自行管理。
    """
    inner_tools = InprocToolAdapter()
    compute = _build_compute_adapter()
    if compute is not None:
        from backend.adapters.out.tool.compute_tool_adapter import ComputeToolAdapter

        tools = ComputeToolAdapter(compute=compute, inner=inner_tools)
        logger.info(
            "ComputeToolAdapter 已装配,注册 %d 个计算工具",
            len(compute.list_operations()),
        )
    else:
        tools = inner_tools

    # 装配 MemoryPort (Memory Integration)
    # 使用全局单例 MemoryManager，确保 WorkingMemory 跨请求持久存在
    memory_manager = get_memory_manager()
    memory_adapter = MemoryAdapter(memory_manager)
    logger.info("MemoryAdapter 已装配（三层记忆系统：Working/Episodic/Semantic，全局单例）")

    return ChatService(
        llm=HttpxLLMAdapter(),
        tools=tools,
        skills=None,  # SkillPort 协议未实现；P3 接入
        storage=SqliteStorageAdapter(),
        metrics=PrometheusMetricAdapter(),
        events=FileEventAdapter(),
        memory=memory_adapter,  # MemoryPort for memory integration
        lifecycle=lifecycle,  # Task 4 / Gap A — optional MemoryLifecycleManager
    )


def _build_lifecycle_extractor():
    """生产用的记忆事实提取器 — LLM 驱动（与 legacy ``_extract_and_store_memory``
    同级），而非 keyword-only 降级。

    ``MemoryExtractor`` 需要 ``llm_client``（支持 ``chat()``）;
    ``HttpxLLMAdapter`` 是 ``_build_chat_service`` 里用的同一个生产 adapter，
    构造无副作用（不发起网络请求）。Important-3 (final review)：之前
    ``MemoryLifecycleManager`` 没传 ``extractor=``，导致生命周期路径静默退化
    成 ``MemoryExtractor(llm_client=None)`` 的关键词启发式。"""
    from backend.adapters.out.llm.httpx_adapter import HttpxLLMAdapter
    from backend.memory.extractor import MemoryExtractor

    return MemoryExtractor(llm_client=HttpxLLMAdapter())


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理。"""
    # 启动时初始化
    db = Database()
    db.init_db()
    app.state.db = db

    # ---------------------------------------------------------------
    # Task 4 / Gap A — wire memory lifecycle hooks + evolution scheduler.
    # ---------------------------------------------------------------
    from backend.data.settings_repo import SettingsRepository
    from backend.memory.hooks import HookRegistry
    from backend.memory.lifecycle import MemoryLifecycleManager
    from backend.scheduler.cron import EvolutionScheduler
    from backend.scheduler.evolution import create_evolution_tasks

    class _AsyncSettingsAdapter:
        """Thin async wrapper so MemoryLifecycleManager can ``await``
        ``prefs.get(...)`` — the underlying SettingsRepository is sync."""

        def __init__(self, inner: SettingsRepository) -> None:
            self._inner = inner

        async def get(self, key: str):
            return self._inner.get(key)

    hooks = HookRegistry()
    preferences_repo = _AsyncSettingsAdapter(SettingsRepository(db=db))
    lifecycle = MemoryLifecycleManager(
        memory_manager=get_memory_manager(),
        hooks=hooks,
        preferences_repo=preferences_repo,
        extractor=_build_lifecycle_extractor(),  # Important-3 — LLM-backed facts
    )
    app.state.hooks = hooks
    app.state.lifecycle = lifecycle
    # Gap E (Task 5) — cache the MemoryPort adapter so the by-turn / profile /
    # summary endpoints don't rebuild (and re-init the VectorStore) per request.
    app.state.memory_port = MemoryAdapter(get_memory_manager())
    logger.info("MemoryLifecycleManager 已绑定 HookRegistry")

    # Evolution scheduler — single thread, registers all enabled tasks.
    evolution_scheduler = EvolutionScheduler()
    evolution_tasks = create_evolution_tasks(hooks=hooks)

    def _make_runner(task):
        async def _run_once() -> int:
            try:
                result = await task.run_async()
                if result is None:
                    return 0
                if isinstance(result, dict):
                    # Defensive: some task implementations return a dict
                    # (e.g. {"total": n}) — normalize to int so the scheduler
                    # never logs a spurious TypeError on a successful run.
                    return int(result.get("total", 0) or 0)
                return int(result)
            except Exception as exc:  # noqa: BLE001 — never crash scheduler
                logger.warning(
                    "evolution task %s failed: %s", type(task).__name__, exc
                )
                return 0

        return _run_once

    for task_name, task in evolution_tasks.items():
        evolution_scheduler.add_task(
            name=task_name,
            task=_make_runner(task),
            schedule="daily",
            hour=3,
            minute=0,
        )
    evolution_scheduler.start()
    app.state.evolution_scheduler = evolution_scheduler
    logger.info(
        "EvolutionScheduler 已启动 (注册 %d 个任务)", len(evolution_tasks)
    )

    # Session-end watchdog — every 60s, find sessions whose updated_at
    # is older than 30 min and fire on_session_end.
    async def _fetch_stale_session_ids(cutoff_ts: int) -> List[str]:
        """Return session ids whose ``updated_at`` is older than ``cutoff_ts``.

        Runs the synchronous SQLite SELECT through ``asyncio.to_thread`` so
        the event loop is not stalled by disk I/O. The DB connection is
        acquired lazily *inside* the worker thread (via
        ``db.get_connection``) — this keeps the single-connection / WAL /
        ``check_same_thread=False`` contract intact: only one thread at a
        time holds the connection, and ``sqlite3`` itself serialises its
        internal mutex.
        """
        def _query() -> List[str]:
            conn = db.get_connection()
            cursor = conn.cursor()
            cursor.execute(
                "SELECT id FROM sessions WHERE updated_at < ? LIMIT 50",
                (cutoff_ts,),
            )
            return [row["id"] for row in cursor.fetchall()]

        return await asyncio.get_event_loop().run_in_executor(None, _query)

    async def _session_watchdog() -> None:
        from datetime import datetime, timedelta, timezone

        while True:
            try:
                await asyncio.sleep(60)
                cutoff_ts = int(
                    (datetime.now(timezone.utc) - timedelta(minutes=30)).timestamp()  # noqa: UP017 — py38: datetime.UTC is 3.11+
                )
                try:
                    stale_ids = await _fetch_stale_session_ids(cutoff_ts)
                except Exception as exc:  # noqa: BLE001
                    logger.warning(
                        "session_watchdog: stale-id query failed: %s", exc
                    )
                    continue
                for sid in stale_ids:
                    try:
                        await lifecycle.on_session_end(sid)
                    except Exception as exc:  # noqa: BLE001
                        logger.warning(
                            "session_watchdog: on_session_end(%s) failed: %s",
                            sid,
                            exc,
                        )
            except asyncio.CancelledError:
                break
            except Exception as exc:  # noqa: BLE001
                logger.exception("session_watchdog unexpected error: %s", exc)

    watchdog_task = asyncio.create_task(
        _session_watchdog(), name="session-watchdog"
    )
    app.state.session_watchdog = watchdog_task
    # Test hook: expose the query helper so async-blocking tests can hit it
    # directly without waiting 60 s for the next watchdog tick. Production
    # callers should not depend on this attribute; it is prefixed with ``_``
    # to mark it as internal.
    app.state._watchdog_query_fn = _fetch_stale_session_ids
    logger.info("Session-end watchdog 已启动 (60s 周期)")

    # PR-3: agents 表种子化 (空表时插 4 个默认 agent, 幂等)
    from backend.data.agent_repo import AgentRepository

    seeded = AgentRepository().seed_defaults_if_empty()
    if seeded:
        logger.info("已种子化 %d 个默认 agent (primary/researcher/coder/memory_manager)", seeded)

    # I2: chat 流注册表 — 拆分 /chat/stream 为 create + attach,避免 LLM 被调两次
    app.state.streams = StreamRegistry()
    sweeper_task = asyncio.create_task(
        _periodic_stream_sweeper(app.state.streams), name="chat-stream-sweeper"
    )
    logger.info("ChatStreamRegistry 已初始化(后台 sweeper 每 60s 清理孤儿流)")

    # Phase 8: scheduled tasks service — load JSON, start APScheduler
    from pathlib import Path

    # Persist scheduled tasks JSON under SAGE_USER_DATA_DIR (per-user writable)
    # rather than the bundled resources/backend/data/, which is system-protected
    # under C:\Program Files\Sage and raised PermissionError on first write.
    # Falls back to <cwd>/backend/data/scheduled_tasks.json for `npm run
    # electron:dev` where SAGE_USER_DATA_DIR isn't injected.
    user_data_dir = os.environ.get("SAGE_USER_DATA_DIR")
    if user_data_dir:
        store_path = Path(user_data_dir) / "scheduled_tasks.json"
    else:
        store_path = Path("backend/data/scheduled_tasks.json")
    scheduler_service = init_scheduler_service(
        store_path=store_path,
        message_repo=MessageRepository(),
        session_repo=SessionRepository(),
    )
    scheduler_service.start()
    app.state.scheduler = scheduler_service
    logger.info("SchedulerService 已初始化并启动（%d 个任务）", len(scheduler_service.list_tasks()))

    # Wiki MCP Server — 在后台启动 Wiki MCP Server
    # 注意：MCP Server 通过 stdio 通信，这里只是验证模块可以导入
    # 实际使用时，用户需要单独启动 MCP Server 进程
    try:
        from backend.wiki.mcp_server import server as wiki_mcp_server

        app.state.wiki_mcp_server = wiki_mcp_server
        logger.info("Wiki MCP Server 模块已加载（7 个工具可用）")
    except Exception as e:
        logger.warning(f"Wiki MCP Server 加载失败（非关键）: {e}")
        app.state.wiki_mcp_server = None

    # Phase 2 (multi-agent core): 初始化注册中心 + Planner + Router + HeartbeatMonitor
    from backend.orchestration.heartbeat import HeartbeatMonitor
    from backend.orchestration.lane_registry import LaneRegistry
    from backend.orchestration.models import Agent
    from backend.orchestration.planner import Planner
    from backend.orchestration.router import DispatchStrategy, Router
    from backend.orchestration.task_registry import TaskRegistry
    from backend.orchestration.team_registry import TeamRegistry

    class _AgentRegistryAdapter:
        """薄适配器：将 AgentRepository (返回 dict) 适配为 Router 期望的 list_agents() 接口。"""

        def __init__(self) -> None:
            self._repo = AgentRepository()

        def list_agents(self) -> List[Agent]:
            profiles = self._repo.list_all()
            agents: List[Agent] = []
            for p in profiles:
                if not p.get("enabled", True):
                    continue
                # 解析 tools 字段为 capabilities（与现有 AgentProfile 字段对齐）
                tools = p.get("tools", [])
                if isinstance(tools, str):
                    try:
                        import json as _json

                        tools = _json.loads(tools)
                    except Exception:
                        tools = []
                agents.append(
                    Agent(
                        agent_id=p["id"],
                        name=p.get("name", p["id"]),
                        status="active",
                        capabilities=list(tools) if tools else [p.get("role", "general")],
                        max_concurrent_tasks=2,
                        default_permission="implement",
                    )
                )
            return agents

    app.state.task_registry = TaskRegistry()
    app.state.lane_registry = LaneRegistry()
    app.state.team_registry = TeamRegistry()
    app.state.planner = Planner(
        task_registry=app.state.task_registry,
        team_registry=app.state.team_registry,
    )
    app.state.router = Router(
        lane_registry=app.state.lane_registry,
        agent_registry=_AgentRegistryAdapter(),
        strategy=DispatchStrategy.CAPABILITY_BASED,
    )
    app.state.heartbeat_monitor = HeartbeatMonitor(
        lane_registry=app.state.lane_registry,
        check_interval=30.0,
        stalled_after=300.0,
        dead_after=600.0,
    )
    await app.state.heartbeat_monitor.start()
    logger.info("Multi-agent core 已装配（Planner + Router + HeartbeatMonitor 已启动）")

    # Hex 模式：装配 ChatService 并注入到 hex_routes 的 DI 工厂
    # Important-1 (final review): 默认值与路由装配对齐 — 实际 serving 的是
    # legacy 路由（PG-A1 临时默认），lifespan 不该默认构建一个无人使用的
    # hex ChatService（误导"已装配"）。API_MODE=hex 时行为不变。
    api_mode = os.environ.get("API_MODE", "legacy").lower()
    if api_mode == "hex":
        from backend.api.hex_routes import get_chat_service

        # Wire the MemoryLifecycleManager into ChatService so run_turn drives
        # set_current_turn (F4 — production caller for source_turn_id).
        app.dependency_overrides[get_chat_service] = lambda: _build_chat_service(
            lifecycle=lifecycle
        )
        app.state.chat_service = _build_chat_service(lifecycle=lifecycle)
        logger.info("Hex 模式：ChatService 已装配（/chat 走 hex_routes，其余走 legacy_routes）")
    else:
        logger.info("Legacy 模式：全部端点走 legacy_routes")

    yield

    # 关闭时清理
    sweeper_task.cancel()
    with suppress(asyncio.CancelledError, Exception):  # noqa: BLE001
        await sweeper_task
    # 取消所有残留的 producer task
    if hasattr(app.state, "streams") and app.state.streams is not None:
        for entry in list(app.state.streams._entries.values()):
            if entry.task is not None and not entry.task.done():
                entry.task.cancel()

    # Phase 8: stop APScheduler cleanly so jobs do not fire after shutdown
    if hasattr(app.state, "scheduler") and app.state.scheduler is not None:
        app.state.scheduler.shutdown()

    # Phase 2: stop HeartbeatMonitor background task
    if hasattr(app.state, "heartbeat_monitor") and app.state.heartbeat_monitor is not None:
        await app.state.heartbeat_monitor.stop()
        logger.info("HeartbeatMonitor 已停止")

    # M3: stop MCP server subprocesses held by the global pool
    try:
        from backend.mcp import shutdown_mcp_clients

        shutdown_mcp_clients()
    except Exception as exc:  # noqa: BLE001 — shutdown must not raise
        logger.warning("MCP client shutdown failed: %s", exc)

    # Task 4 / Gap A — stop the session-end watchdog so its 60 s
    # asyncio.sleep loop doesn't outlive the process.
    if hasattr(app.state, "session_watchdog") and app.state.session_watchdog is not None:
        app.state.session_watchdog.cancel()
        with suppress(asyncio.CancelledError, Exception):  # noqa: BLE001
            await app.state.session_watchdog
        logger.info("Session-end watchdog 已停止")

    # Task 4 / Gap A — stop the evolution scheduler thread.
    if (
        hasattr(app.state, "evolution_scheduler")
        and app.state.evolution_scheduler is not None
    ):
        try:
            app.state.evolution_scheduler.stop()
            logger.info("EvolutionScheduler 已停止")
        except Exception as exc:  # noqa: BLE001
            logger.warning("EvolutionScheduler stop failed: %s", exc)


async def _periodic_stream_sweeper(registry: StreamRegistry, interval_s: float = 60.0) -> None:
    """每 60s 清理一次孤儿流(创建后 5 分钟仍未 done/failed 的)。"""
    try:
        while True:
            await asyncio.sleep(interval_s)
            removed = await registry.sweep_expired(max_age_seconds=300.0)
            if removed:
                logger.info("chat-stream sweeper removed %d stale streams", removed)
    except asyncio.CancelledError:
        return


# 创建 FastAPI 应用
app = FastAPI(
    title="Sage API",
    description="记忆型 AI 桌面助手后端 API",
    version="0.1.1",
    lifespan=lifespan,
)

# 配置 CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 生产环境应限制
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def add_request_id_header(request: Request, call_next):
    """为每个响应添加 x-request-id header（与 handler 共享同一 ID）。"""
    request_id = request.headers.get("x-request-id") or str(uuid.uuid4())
    request.state.request_id = request_id
    response = await call_next(request)
    response.headers["x-request-id"] = request_id
    return response


# 路由装配（P2 双轨）：
# - API_MODE=hex：先注册 hex（/chat 走 ChatService），
#   再注册 legacy（/sessions、/memory、/evolution、/interrupt）。
#   FastAPI 按注册顺序匹配——hex 的 /chat 优先命中，其余走 legacy。
# - API_MODE=legacy（默认）：仅注册 legacy。
# 通用 LLM 代理（/api/v1/llm/*）在两种模式下都注册 — 浏览器到 LLM 的
# 测试连接 / 拉取模型调用都走它，与 API_MODE 无关（见 llm_proxy_routes.py）。
#
# === PG-A1 GREEN-2 临时变更（2026-06-13） ===
# 默认 API_MODE 从 "hex" 改为 "legacy"。原因:hex_routes 新增了 6 个
# sessions 端点（PG-A1 端点迁移），但本 PR 不装配 SessionService DI。
# 若保持默认 hex，新 6 端点会拦截 /sessions 流量并因 DI 缺失而 500，
# 破坏现有 legacy 集成测试。临时切到 legacy 保证 production 走老路径。
# 后续 PR 真正装配 SessionService 后，会把默认值改回 "hex"。
# 跟踪 issue/PR 见 docs/plans/2026-06-13_full-quality-optimization-v2.md。
app.include_router(llm_proxy_router, prefix="/api/v1")
app.include_router(theme_router, prefix="/api/v1/theme")
app.include_router(office_router, prefix="/api/v1")
register_office_exception_handlers(app)
app.include_router(workspace_router, prefix="/api/v1")
app.include_router(build_orchestration_router(), prefix="/api/v1")
app.include_router(wiki_router, prefix="/api/v1")

_API_MODE = os.environ.get("API_MODE", "legacy").lower()  # PG-A1: was "hex"
if _API_MODE == "hex":
    app.include_router(hex_router, prefix="/api/v1")
    app.include_router(legacy_router, prefix="/api/v1")
elif _API_MODE == "legacy":
    app.include_router(legacy_router, prefix="/api/v1")
else:
    raise ValueError(f"API_MODE must be 'hex' or 'legacy', got: {_API_MODE!r}")

# Phase 8: scheduled tasks — mounted for both API modes (independent feature)
app.include_router(build_scheduled_router(get_scheduler_service), prefix="/api/v1")

# M3: MCP multi-server management (status / servers CRUD)
app.include_router(mcp_router, prefix="/api/v1")


@app.get("/health")
async def health_check():
    """健康检查"""
    return {"status": "ok", "version": "0.1.1"}


if __name__ == "__main__":
    import uvicorn

    port = int(os.environ.get("PYTHON_BACKEND_PORT", "8765"))
    # v2: 把本机后端地址注入环境变量,让 backend.core.legacy.llm_client.LLMConfig
    # 知道走哪个 proxy URL(默认 http://127.0.0.1:8765,所以在大多数情况下是
    # no-op,但允许 dev/CI 通过环境变量覆盖)。
    os.environ.setdefault("BACKEND_URL", f"http://127.0.0.1:{port}")
    uvicorn.run(app, host="127.0.0.1", port=port)
