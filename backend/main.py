"""
Sage - 记忆型 AI 桌面助手
FastAPI 后端入口
"""
import asyncio
import logging
import os
import uuid
from contextlib import asynccontextmanager, suppress
from pathlib import Path
from typing import Callable, Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sage_core import Message, Role


def configure_ssl_ca_bundle(where: Callable[[], str]) -> Optional[str]:
    """为 ``httpx`` / ``requests`` / ``curl`` 兜底注入 certifi 的 CA bundle。

    返回最终选中的 CA 路径；任何异常（certifi 缺失、文件不存在、文件为空）
    都吞掉并返回 ``None``，避免阻塞后端启动。只有当对应环境变量尚未
    设置时（``setdefault``），才写入路径——用户自定义值永远不被覆盖。
    """
    try:
        ca_path = where()
        ca_file = Path(ca_path)
        if not ca_file.is_file() or ca_file.stat().st_size <= 0:
            return None
        for variable in ("SSL_CERT_FILE", "REQUESTS_CA_BUNDLE", "CURL_CA_BUNDLE"):
            os.environ.setdefault(variable, ca_path)
    except Exception:  # noqa: BLE001 — bootstrap failure must not crash import
        return None
    return ca_path


try:
    import certifi
except ImportError:
    certifi = None  # type: ignore[assignment]

if certifi is not None:
    configure_ssl_ca_bundle(certifi.where)

from backend.adapters.out.event.file_adapter import FileEventAdapter
from backend.adapters.out.llm.httpx_adapter import HttpxLLMAdapter
from backend.adapters.out.memory.adapter import MemoryAdapter
from backend.adapters.out.metric.prometheus_adapter import PrometheusMetricAdapter
from backend.adapters.out.storage.sqlite_adapter import SqliteStorageAdapter
from backend.adapters.out.tool.inproc_adapter import InprocToolAdapter
from backend.api.artifact_routes import router as artifact_router
from backend.api.chat_stream_registry import StreamRegistry
from backend.api.export_routes import router as export_router
from backend.api.hex_routes import router as hex_router
from backend.api.legacy_routes import router as legacy_router
from backend.api.llm_proxy_routes import router as llm_proxy_router
from backend.api.local_auth import (
    LocalAuthMiddleware,
    initialize_local_auth_token,
    is_ownership_health_valid,
    ownership_health_proof,
)
from backend.api.mcp_routes import router as mcp_router
from backend.api.office_routes import (
    register_office_exception_handlers,
    router as office_router,
)
from backend.api.orchestration_router import build_router as build_orchestration_router
from backend.api.permission_routes import router as permission_router
from backend.api.question_routes import router as question_router
from backend.api.runtime_routes import router as runtime_router
from backend.api.scheduled_router import build_router as build_scheduled_router
from backend.api.theme_router import router as theme_router
from backend.api.usage_routes import router as usage_router
from backend.api.wiki_routes import router as wiki_router
from backend.api.workspace_routes import router as workspace_router
from backend.application.services.chat_service import ChatService
from backend.application.services.wake_store import get_wake_store
from backend.data.database import Database
from backend.data.session_repo import MessageRepository, SessionRepository
from backend.domain.wake import Wake
from backend.memory import get_memory_manager
from backend.orchestration.wake_scheduler import WakeScheduler
from backend.services.scheduler import (
    get_scheduler_service,
    init_scheduler_service,
)

logger = logging.getLogger(__name__)


# Browser clients only need the local Vite dev origin. Electron's packaged
# ``file://`` renderer does not send CORS preflight requests, and requests
# without an Origin header remain unaffected.
_ALLOWED_CORS_ORIGINS = (
    "http://localhost:1420",
    "http://127.0.0.1:1420",
)


def _build_health_metadata() -> dict:
    """Return only the non-sensitive fields needed by the supervisor."""
    return {
        "buildId": os.environ.get("SAGE_BUILD_ID", "dev-build"),
        "pid": os.getpid(),
        "generation": int(os.environ.get("SAGE_BACKEND_GENERATION", "0")),
    }


def _shutdown_bash_sessions() -> None:
    """在后端退出时尽力终止并清理后台 shell 会话。"""
    try:
        from backend.tools.bash_session import get_registry

        get_registry().clear()
    except Exception as exc:  # noqa: BLE001 — shutdown must not raise
        logger.warning("后台 shell shutdown failed（异常类型=%s）", type(exc).__name__)


def _shutdown_repl_cleanups() -> None:
    """在后端退出时尽力清理 REPL 残留资源。"""
    try:
        from backend.tools.repl_tool import shutdown_pending_cleanups

        shutdown_pending_cleanups()
    except Exception as exc:  # noqa: BLE001 — shutdown must not raise
        logger.warning("REPL shutdown failed（异常类型=%s）", type(exc).__name__)


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


def _build_chat_service() -> ChatService:
    """工厂：装配 7 个 ports（7 个生产 adapter）。

    - llm:     HttpxLLMAdapter（包装既有 LLMClient）
    - tools:   InprocToolAdapter（如启用 ghm，则用 ComputeToolAdapter 包装合并）
    - skills:  InprocSkillAdapter（M2 part B 接线；包装既有 SkillRegistry，
               与 /api/v1/skills* REST 端点同源）
    - storage: SqliteStorageAdapter（包装既有 SessionRepository / MessageRepository）
    - metrics: PrometheusMetricAdapter
    - events:  FileEventAdapter（写 audit jsonl）
    - memory:  MemoryAdapter（包装 MemoryManager，提供三层记忆系统）

    装配在每次依赖注入时被调用——单例化由调用方（如 ``app.state``）自行管理。
    """
    # M2 part B: SkillPort 接线 —— 关闭 skills=None TODO。InprocSkillAdapter
    # 结构上满足 sage_core.repositories.SkillPort（list_skills / execute），
    # 构造对 SKILL.md 装载失败容错（guarded），不破坏 hex 模式装配。
    from backend.adapters.out.skill import InprocSkillAdapter

    skills_adapter = InprocSkillAdapter()

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
        skills=skills_adapter,  # M2 part B: SkillPort 接线完成
        storage=SqliteStorageAdapter(),
        metrics=PrometheusMetricAdapter(),
        events=FileEventAdapter(),
        memory=memory_adapter,  # MemoryPort for memory integration
        wake_store=get_wake_store(),  # A4: 会话挂起 / 唤醒注册
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理。"""
    # Local desktop capability: resolve the token before serving any sensitive route.
    # The value is intentionally never logged or returned by the health endpoint.
    initialize_local_auth_token()

    # 启动时初始化
    db = Database()
    db.init_db()
    app.state.db = db

    # PR-3: agents 表种子化 — 用 ensure_default_agents 替代 seed_defaults_if_empty:
    # 首次启动插全量默认集, 已存在的 DB 增量补 writer 等新增默认角色。
    from backend.agents.profiles import ensure_default_agents
    from backend.data.agent_repo import AgentRepository

    ensure_default_agents()

    # I2: chat 流注册表 — 拆分 /chat/stream 为 create + attach,避免 LLM 被调两次
    app.state.streams = StreamRegistry()
    sweeper_task = asyncio.create_task(
        _periodic_stream_sweeper(app.state.streams), name="chat-stream-sweeper"
    )
    logger.info("ChatStreamRegistry 已初始化(后台 sweeper 每 60s 清理孤儿流)")

    # 记忆提取异步化：后台单 worker 消费提取队列，不阻塞聊天响应
    from backend.memory.async_extractor import get_memory_extraction_queue

    get_memory_extraction_queue().start()
    logger.info("MemoryExtractionQueue 已启动（记忆提取后台 worker）")

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

    # PR-C §5.1: 把 5 个 evolution 任务挂到 lifespan,按 cron 自动跑
    # (memory_pruning / memory_consolidation / daily_summary /
    #  preference_learning / importance_reevaluation)。读 config.yaml
    # evolution.tasks.<name>.time/day 作可选 override,默认 cron 兜底。
    from backend.services._evolution_register import _register_evolution_tasks

    _evo_registered = _register_evolution_tasks(
        scheduler_service,
        config_path=Path(__file__).parent / "config.yaml",
    )
    logger.info(
        "Evolution tasks scheduled: %d — %s",
        len(_evo_registered),
        list(_evo_registered.keys()),
    )

    # PR-C §5.2: 把 ReviewService + SkillDraftStore 注入到全局 ReviewQueue,
    # 然后启动后台 worker。否则 hex/legacy 路径 enqueue 的 review_events
    # 永远在 SQLite 里堆积、不出草稿。和 init_scheduler_service 同 pattern。
    from backend.skills.review_bootstrap import bootstrap_review_collaborators
    from backend.skills.review_queue import get_review_queue

    bootstrap_review_collaborators()
    get_review_queue().start()
    logger.info("ReviewQueue 协作对象已注入且 worker 已启动")

    # A4 Suspend-Resume: wake 仓储 + 唤醒调度器 — tick 扫描到期 wake,
    # 在对应 session 注入新一轮对话恢复挂起的 agent。resumer 走
    # ChatService.run_turn（hex 模式装配后可用）；legacy 模式下记录并跳过。
    app.state.wake_store = get_wake_store()

    async def _resume_session_from_wake(wake: Wake) -> None:
        chat_service = getattr(app.state, "chat_service", None)
        if chat_service is None:
            logger.warning(
                "wake %s (session=%s) 到期, 但 ChatService 未装配, 跳过恢复",
                wake.id,
                wake.session_id,
            )
            return
        content = f"[系统唤醒: {wake.kind.value}] {wake.note or '继续之前挂起的任务。'}"
        await chat_service.run_turn(
            wake.session_id, Message(role=Role.USER, content=content)
        )

    app.state.wake_scheduler = WakeScheduler(
        store=app.state.wake_store,
        resumer=_resume_session_from_wake,
        tick_seconds=15.0,
    )
    app.state.wake_scheduler.start()
    logger.info("WakeScheduler 已初始化并启动（A4 Suspend-Resume，tick=15s）")

    # M1 工具安全加固: 全局审批闸口 — agent 循环 await 审批, 路由解析应答
    from backend.services.permission_gate import init_permission_gate

    app.state.permission_gate = init_permission_gate()
    logger.info("PermissionGate 已初始化（工具审批闸口）")

    # M2 part B: 全局提问闸口 — agent 循环 await 用户应答, 路由解析应答
    from backend.services.question_gate import init_question_gate

    app.state.question_gate = init_question_gate()
    logger.info("QuestionGate 已初始化（AskUserQuestion 提问闸口）")

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
    from backend.orchestration.agent_adapter import SeededAgentRegistry
    from backend.orchestration.heartbeat import HeartbeatMonitor
    from backend.orchestration.lane_registry import LaneRegistry
    from backend.orchestration.planner import Planner
    from backend.orchestration.router import DispatchStrategy, Router
    from backend.orchestration.task_registry import TaskRegistry
    from backend.orchestration.team_registry import TeamRegistry

    app.state.task_registry = TaskRegistry()
    app.state.lane_registry = LaneRegistry()
    app.state.team_registry = TeamRegistry()
    app.state.planner = Planner(
        task_registry=app.state.task_registry,
        team_registry=app.state.team_registry,
    )
    app.state.router = Router(
        lane_registry=app.state.lane_registry,
        agent_registry=SeededAgentRegistry(AgentRepository()),
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
    api_mode = os.environ.get("API_MODE", "hex").lower()
    if api_mode == "hex":
        from backend.api.hex_routes import get_chat_service

        app.dependency_overrides[get_chat_service] = _build_chat_service
        app.state.chat_service = _build_chat_service()
        logger.info("Hex 模式：ChatService 已装配（/chat 走 hex_routes，其余走 legacy_routes）")
    else:
        logger.info("Legacy 模式：全部端点走 legacy_routes")

    yield

    # 关闭时清理
    _shutdown_bash_sessions()
    _shutdown_repl_cleanups()
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

    # A4: stop WakeScheduler before tearing down chat services
    if hasattr(app.state, "wake_scheduler") and app.state.wake_scheduler is not None:
        await app.state.wake_scheduler.stop()

    # 记忆提取：优雅排空在途提取（best-effort，超时 5s 丢弃）
    try:
        from backend.memory.async_extractor import get_memory_extraction_queue

        await get_memory_extraction_queue().drain(timeout=5.0)
        get_memory_extraction_queue().stop()
    except Exception as exc:  # noqa: BLE001 — shutdown must not raise
        logger.warning("MemoryExtractionQueue shutdown failed: %s", exc)

    # ReviewQueue worker uses a daemon thread; stop it explicitly so shutdown
    # does not leave an active worker behind during orderly application exit.
    try:
        from backend.skills.review_queue import get_review_queue

        get_review_queue().stop()
    except Exception as exc:  # noqa: BLE001 — shutdown must not raise
        logger.warning("ReviewQueue shutdown failed: %s", exc)

    # Phase 2: stop HeartbeatMonitor background task
    if hasattr(app.state, "heartbeat_monitor") and app.state.heartbeat_monitor is not None:
        await app.state.heartbeat_monitor.stop()
        logger.info("HeartbeatMonitor 已停止")

    # Stop the bounded DNS resolver without waiting for uninterruptible
    # getaddrinfo worker threads; cancellation cannot stop those OS calls.
    try:
        from backend.api.llm_proxy_routes import shutdown_dns_executor

        shutdown_dns_executor()
    except Exception as exc:  # noqa: BLE001 — shutdown must not raise
        logger.warning("LLM proxy DNS executor shutdown failed: %s", exc)

    # M3: stop MCP server subprocesses held by the global pool
    try:
        from backend.mcp import shutdown_mcp_clients

        shutdown_mcp_clients()
    except Exception as exc:  # noqa: BLE001 — shutdown must not raise
        logger.warning("MCP client shutdown failed: %s", exc)


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


@app.exception_handler(RequestValidationError)
async def settings_validation_exception_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    """Prevent Pydantic input values from leaking on the settings PUT boundary.

    FastAPI's default validation response includes ``exc.errors()``.  That
    structure can contain the rejected input value, so this narrowly scoped
    handler replaces it only for the settings route; every other route keeps
    FastAPI's default validation behavior.
    """
    if request.method == "PUT" and request.url.path.rstrip("/") == "/api/v1/settings":
        return JSONResponse(
            status_code=422,
            content={
                "detail": {
                    "type": "invalid_settings_payload",
                    "message": "设置内容无效，请检查字段格式",
                }
            },
        )
    from fastapi.exception_handlers import request_validation_exception_handler

    return await request_validation_exception_handler(request, exc)


# 配置 CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=list(_ALLOWED_CORS_ORIGINS),
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-Sage-Local-Authorization", "X-Request-ID"],
)


# Local capability enforcement runs as a pure ASGI middleware (not
# BaseHTTPMiddleware) so it does not add per-request task-group/stream overhead
# to the event loop; see LocalAuthMiddleware's docstring for the measurement.
app.add_middleware(LocalAuthMiddleware)


@app.middleware("http")
async def add_request_id_header(request: Request, call_next):
    """为每个响应添加 x-request-id header（与 handler 共享同一 ID）。"""
    request_id = request.headers.get("x-request-id") or str(uuid.uuid4())
    request.state.request_id = request_id
    response = await call_next(request)
    response.headers["x-request-id"] = request_id
    return response


# 路由装配（P2 双轨）：
# - API_MODE=hex（默认）：先注册 hex（/chat 走 ChatService），
#   再注册 legacy（/sessions、/memory、/evolution、/interrupt）。
#   FastAPI 按注册顺序匹配——hex 的 /chat 优先命中，其余走 legacy。
# - API_MODE=legacy：仅注册 legacy。
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
# M1 工具安全加固: /api/v1/permissions/{pending, <id>/answer}
app.include_router(permission_router, prefix="/api/v1")
# M2 part B: /api/v1/questions/{pending, <id>/answer}（AskUserQuestion）
app.include_router(question_router, prefix="/api/v1")
app.include_router(build_orchestration_router(), prefix="/api/v1")
app.include_router(wiki_router, prefix="/api/v1")
# M6 生态扩展: 用量/成本面板 (内存态 tracker, 与 API_MODE 无关)
app.include_router(usage_router, prefix="/api/v1")
# U18: HTML 会话导出 (POST /sessions/{id}/export, 与 API_MODE 无关)
app.include_router(export_router, prefix="/api/v1")
# Artifacts 面板: /sessions/{id}/artifacts (list / content / reveal)
app.include_router(artifact_router, prefix="/api/v1")

# 本地开发环境助手: /api/v1/runtime/{probe, diagnose, exec}
# 复用 ChatService.tools 路径, runtime_exec 自动走 PermissionEnforcer 审批
# (与 BashTool 同等门禁), 见 docs/plans/2026-09-04_local-development-assistant.md
app.include_router(runtime_router, prefix="/api/v1")

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


@app.get("/health/proof")
async def health_proof(request: Request):
    """Return a token-bound proof; the ownership token itself never leaves backend."""
    if not is_ownership_health_valid(request):
        raise HTTPException(status_code=404, detail="Not Found")
    metadata = _build_health_metadata()
    token = os.environ.get("SAGE_BACKEND_OWNERSHIP_TOKEN", "")
    return {
        "status": "ok",
        **metadata,
        "proof": ownership_health_proof(
            token, metadata["buildId"], metadata["generation"], metadata["pid"]
        ),
    }


@app.get("/health")
async def health_check():
    """Return a machine-readable build and process ownership envelope."""
    return {"status": "ok", **_build_health_metadata()}


if __name__ == "__main__":
    import uvicorn

    from backend.utils.logging import setup_logging

    port = int(os.environ.get("PYTHON_BACKEND_PORT", "8765"))
    # v2: 把本机后端地址注入环境变量,让 backend.core.legacy.llm_client.LLMConfig
    # 知道走哪个 proxy URL(默认 http://127.0.0.1:8765,所以在大多数情况下是
    # no-op,但允许 dev/CI 通过环境变量覆盖)。
    os.environ.setdefault("BACKEND_URL", f"http://127.0.0.1:{port}")

    # 日志基线修复 #1: 启用 setup_logging()。此前从未被调用,根 logger 保持
    # 默认 WARNING 且无文件 handler → 后端模块 logger.* 的 INFO/DEBUG 全丢。
    # SAGE_LOG_LEVEL 由 Electron 注入(取值 debug/info/warn/error,小写),
    # 需显式映射到大写 LOG_LEVELS key(尤其 warn → WARNING,upper() 会得到 WARN)。
    _LEVEL_MAP = {"debug": "DEBUG", "info": "INFO", "warn": "WARNING", "error": "ERROR"}
    _level = _LEVEL_MAP.get(os.environ.get("SAGE_LOG_LEVEL", "info").lower(), "INFO")
    setup_logging(log_level=_level)

    # uvicorn 自带 logger 默认 WARNING 且无 handler;显式放行到 INFO 并传播到
    # 根 logger,否则 log_config=None 后 access log 会被 uvicorn 自身级别过滤。
    for _name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        logging.getLogger(_name).setLevel(logging.INFO)

    uvicorn.run(app, host="127.0.0.1", port=port, log_config=None)
