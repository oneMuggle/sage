"""
Sage - 记忆型 AI 桌面助手
FastAPI 后端入口
"""
import asyncio
import logging
import os
import sys
import time
import uuid
from contextlib import asynccontextmanager, suppress
from pathlib import Path
from typing import Callable

# ── Startup diagnostic timer (module-level) ───────────────────────────────
# 2026-09-10 (slow-startup incident): record monotonic start BEFORE any
# heavy import so we can diagnose which phase is slow on machines where the
# backend hangs between "python -m backend.main" and "uvicorn.run()".
# Guarded by __name__ == "__main__" so pytest imports don't emit noise.
# Carried over from release/win7 PR #585; equally applicable to main.
_startup_t0: float = time.monotonic() if __name__ == "__main__" else 0.0
if __name__ == "__main__":
    print(  # noqa: T201
        f"[sage-startup] t=0.0s module load begin (pid={os.getpid()})",
        file=sys.stderr,
        flush=True,
    )

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sage_core import Message, Role


def configure_ssl_ca_bundle(where: Callable[[], str]) -> str | None:
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

# S7-3 (P7): 会话 CRUD 端点注册到 legacy_router 上, 必须在 include 前导入
import backend.api.legacy_session_routes  # noqa: F401,E402
from backend.adapters.out.event.file_adapter import FileEventAdapter
from backend.adapters.out.llm.httpx_adapter import HttpxLLMAdapter
from backend.adapters.out.memory.adapter import MemoryAdapter
from backend.adapters.out.metric.prometheus_adapter import PrometheusMetricAdapter
from backend.adapters.out.storage.sqlite_adapter import SqliteStorageAdapter
from backend.adapters.out.tool.inproc_adapter import InprocToolAdapter
from backend.api.artifact_routes import router as artifact_router
from backend.api.chat_attachment_routes import router as chat_attachment_router
from backend.api.chat_stream_registry import StreamRegistry

# B1 (P11): 记忆嵌入器状态/切换 API
from backend.api.diagnostic_routes import router as diagnostic_router
from backend.api.embedder_routes import router as embedder_router
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
from backend.api.media_routes import router as media_router
from backend.api.office_routes import (
    register_office_exception_handlers,
    router as office_router,
)
from backend.api.orchestration_router import build_router as build_orchestration_router
from backend.api.permission_routes import router as permission_router
from backend.api.question_routes import router as question_router
from backend.api.runtime_routes import router as runtime_router
from backend.api.scheduled_router import build_router as build_scheduled_router
from backend.api.system_routes import router as system_router
from backend.api.theme_router import router as theme_router
from backend.api.usage_routes import router as usage_router
from backend.api.v1 import updates as updates_router_module
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


def _shutdown_browser_sessions() -> None:
    """在后端退出时终止全部受控浏览器实例并清理临时目录（G7）。"""
    try:
        from backend.tools.browser_cdp import get_browser_manager

        closed = get_browser_manager().close_all()
        if closed:
            logger.info("已关闭 %d 个受控浏览器实例", closed)
    except Exception as exc:  # noqa: BLE001 — shutdown must not raise
        logger.warning("浏览器 shutdown failed（异常类型=%s）", type(exc).__name__)


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

    # R21-A: 应用待恢复备份（必须在 init_db 之前 —— 原子替换主库文件后
    # 再建连接，避免旧 WAL 污染恢复出的库）。fail-safe，不阻塞启动。
    try:
        from backend.services.backup_service import apply_pending_restore

        if apply_pending_restore():
            logger.info("pending backup restore applied at startup")
    except Exception:
        logger.exception("apply_pending_restore failed (ignored)")

    # 启动时初始化
    db = Database()
    db.init_db()
    app.state.db = db
    if __name__ == "__main__":
        _elapsed_db = time.monotonic() - _startup_t0
        print(  # noqa: T201
            f"[sage-startup] t={_elapsed_db:.1f}s db.init_db() complete",
            file=sys.stderr,
            flush=True,
        )

    # L15 SecretBox: 历史明文 apiKey 一次性加密回写(Windows DPAPI / macOS keychain /
    # Linux secret-tool)。fail-open — 任何失败保留明文, 不阻塞启动, doctor
    # secret_storage 检查会持续告警。
    from backend.services.secret_box import migrate_plaintext_settings

    try:
        _secret_report = migrate_plaintext_settings()
        if _secret_report.get("encrypted_now"):
            logger.info("SecretBox 迁移完成: %s", _secret_report)
    except Exception:
        logger.exception("SecretBox 迁移失败(保留明文, 不影响启动)")

    # S1 (2026-09-06): 会话运行态启动恢复 —— 上次进程被杀时 producer 的
    # finally 写库点没有机会执行，遗留 running 统一收口为 failed（与编排
    # finalize 的 default-failed 语义一致）；suspended 不动（A4 wake 仍在）。
    _stale_runs = SessionRepository().recover_stale_run_states()
    if _stale_runs:
        logger.info("启动恢复: %d 个遗留 running 会话已标记为 failed", _stale_runs)

    # O6 (2026-09-08): 编排 run 级启动恢复 —— orch_runs 滞留 running 同样
    # 收口为 failed（此前只有会话级有恢复，run 级永远滞留）。
    from backend.data.orch_run_repo import OrchRunRepository

    _stale_orch_runs = OrchRunRepository().fail_stale_running_runs()
    if _stale_orch_runs:
        logger.info(
            "启动恢复: %d 个遗留 running 编排 run 已标记为 failed", _stale_orch_runs
        )

    # C2 (2026-09-09): 审批决策 run/task 归属解析器注册（依赖反转）——
    # services 层不得 import orchestration（六边形 import 契约），故由
    # 顶层装配注入回查回调；子代理审批决策落库时经它归因 run/task。
    from backend.orchestration.chat_dispatcher import find_dispatcher_for_approval
    from backend.services import permission_gate as _approval_gate

    def _resolve_approval_context(request_id: str):
        dispatcher = find_dispatcher_for_approval(request_id)
        if dispatcher is None:
            return (None, None)
        return (dispatcher.run_id, dispatcher._pending_approvals.get(request_id))

    _approval_gate.set_approval_context_resolver(_resolve_approval_context)

    # PR-3: agents 表种子化 — 用 ensure_default_agents 替代 seed_defaults_if_empty:
    # 首次启动插全量默认集, 已存在的 DB 增量补 writer 等新增默认角色。
    from backend.agents.profiles import ensure_default_agents, validate_profile_tools
    from backend.data.agent_repo import AgentRepository

    ensure_default_agents()
    # T3 (2026-09-04): 启动期白名单校验 —— profile 引用未注册工具名
    # （改名/拼写漂移）时告警。仅告警不剔除：未注册名对 LLM 本就不可见，
    # 剔除会误伤引用 MCP 等动态工具的自定义 profile。
    validate_profile_tools()
    # CA1 (round9): .sage/agents/*.md 档案文件导入 —— 文件即真相（有差异才
    # upsert；enabled 开关保留 DB 现值）。失败仅告警，绝不阻塞启动。
    try:
        from backend.agents.agents_files import import_agents_from_files

        _agents_import = import_agents_from_files()
        if _agents_import["imported"]:
            logger.info(
                "agents-files: 启动导入 %d 个档案（%s）",
                len(_agents_import["imported"]),
                ", ".join(_agents_import["imported"]),
            )
        if _agents_import["errors"]:
            logger.warning(
                "agents-files: %d 个档案文件解析失败: %s",
                len(_agents_import["errors"]),
                "; ".join(_agents_import["errors"]),
            )
    except Exception as agents_files_exc:  # noqa: BLE001 — 增强面降级
        logger.warning("agents-files: 启动导入失败（忽略）: %s", agents_files_exc)

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

    # R19-B: SQLite 自动备份 —— 启动时后台线程备份一次（fail-safe, 不阻塞
    # 启动）+ 每日 03:10 定时备份（独立于 evolution 任务, 只做整库在线复制）。
    def _startup_backup() -> None:
        from backend.services.backup_service import create_backup

        try:
            create_backup("startup")
        except Exception:
            logger.exception("startup backup failed (ignored)")

    def _create_backup_daily() -> None:
        from backend.services.backup_service import create_backup

        try:
            create_backup("daily")
        except Exception:
            logger.exception("daily backup failed (ignored)")

    import threading as _threading

    _threading.Thread(target=_startup_backup, name="startup-backup", daemon=True).start()
    try:

        scheduler_service.register_system_task(
            "daily-backup", _create_backup_daily, "10 3 * * *"
        )
    except Exception:
        logger.exception("daily backup job registration failed (ignored)")

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

    # Round 6 (Telegram 网关 MVP): 配置了 TELEGRAM_BOT_TOKEN 才启动长轮询
    # 后台线程；未配置零开销。白名单见 gateway/telegram.py 模块文档。
    try:
        from backend.gateway.telegram import get_telegram_gateway

        _tg_gateway = get_telegram_gateway()
        if _tg_gateway is not None:
            _tg_gateway.start_polling()
            app.state.telegram_gateway = _tg_gateway
            logger.info("Telegram 网关已启动（长轮询，白名单 %d 个 chat）",
                        len(_tg_gateway.config.allowed_chat_ids))
    except Exception as exc:  # noqa: BLE001 — 网关失败不阻塞后端启动
        logger.warning("Telegram 网关启动失败（忽略）: %s", exc)

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

    # Phase 1 observability: SnapshotStore + EventHub + REST endpoints
    from backend.api import orch_run_control
    from backend.data.orch_context_repo import OrchestrationContextRepository
    from backend.data.orch_events_repo import OrchEventRepository
    from backend.data.orch_task_repo import OrchTaskRepository
    from backend.orchestration.event_hub import EventHub
    from backend.orchestration.snapshot_store import SnapshotStore

    app.state.snapshot_store = SnapshotStore()
    app.state.orch_event_repository = OrchEventRepository()
    app.state.orch_task_repository = OrchTaskRepository()
    app.state.orch_context_repository = OrchestrationContextRepository()
    app.state.event_hub = EventHub(
        event_repository=app.state.orch_event_repository,
        event_applier=app.state.snapshot_store.apply_event,
    )
    restored_events = await app.state.event_hub.restore_runs()
    orch_run_control.configure(
        app.state.snapshot_store,
        app.state.event_hub,
        context_repo=app.state.orch_context_repository,
        task_repo=app.state.orch_task_repository,
    )
    logger.info(
        "Phase 1 observability: SnapshotStore + EventHub + /orch/runs 已就绪，恢复 %s 个事件",
        restored_events,
    )

    # S7-1 (P7): ChatService 无条件装配 —— runtime 路由复用其 tools 路径,
    # 与 API_MODE 无关 (此前 lifespan 默认 "hex" 恰好让 runtime 可用, 属于
    # 矛盾默认值的巧合而非设计); hex /chat 是否挂载由模块级 API_MODE 决定。
    from backend.api.hex_routes import get_chat_service

    app.dependency_overrides[get_chat_service] = _build_chat_service
    app.state.chat_service = _build_chat_service()
    # B1 (P11): MemoryAdapter 全局暴露 —— embedder select API 热重载用。
    # MemoryAdapter 在 _build_chat_service 内构造, 经 ChatService.memory 可达。
    app.state.memory_adapter = getattr(app.state.chat_service, "memory", None)
    logger.info(
        "ChatService 已装配 (runtime 与 hex /chat 共享); API_MODE=%s (路由挂载见模块级常量)",
        API_MODE,
    )

    if __name__ == "__main__":
        _elapsed_lifespan = time.monotonic() - _startup_t0
        print(  # noqa: T201
            f"[sage-startup] t={_elapsed_lifespan:.1f}s lifespan startup complete (before yield)",
            file=sys.stderr,
            flush=True,
        )

    yield

    # 关闭时清理
    # Round 6: 停 Telegram 轮询线程（daemon 兜底，显式停更干净）
    _tg = getattr(app.state, "telegram_gateway", None)
    if _tg is not None:
        with suppress(Exception):
            _tg.stop_polling()
    _shutdown_bash_sessions()
    _shutdown_browser_sessions()
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


# S7-1 (P7): API_MODE 单一读取点。此前 lifespan (默认 "hex") 与路由挂载
# (默认 "legacy") 各读各的环境变量, 默认部署会装配 ChatService 却从不挂载
# hex 路由。现在: ChatService 无条件装配 (runtime 依赖), 本常量只决定
# hex /chat 是否挂载; 缺省 "legacy" 保持现行 wire 行为不变。
API_MODE = os.environ.get("API_MODE", "legacy").lower()

# 路由装配（P2 双轨）：
# - API_MODE=hex（默认）：先注册 hex（/chat 走 ChatService），
#   再注册 legacy（/sessions、/memory、/evolution、/interrupt）。
#   FastAPI 按注册顺序匹配——hex 的 /chat 优先命中，其余走 legacy。
# - API_MODE=legacy：仅注册 legacy。
# 通用 LLM 代理（/api/v1/llm/*）在两种模式下都注册 — 浏览器到 LLM 的
# 测试连接 / 拉取模型调用都走它，与 API_MODE 无关（见 llm_proxy_routes.py）。
# PG-A1 GREEN-2 的"临时切 legacy"已于 S7-1 (P7) 收口为单一读取点;
# 缺省仍为 "legacy", hex 的 /sessions 端点已随 ChatService DI 装配可安全启用
# (显式 API_MODE=hex 时)。
app.include_router(llm_proxy_router, prefix="/api/v1")
app.include_router(theme_router, prefix="/api/v1/theme")
app.include_router(office_router, prefix="/api/v1")
from backend.api.gateway_routes import router as gateway_router

app.include_router(gateway_router, prefix="/api/v1")
register_office_exception_handlers(app)
app.include_router(workspace_router, prefix="/api/v1")
# M1 工具安全加固: /api/v1/permissions/{pending, <id>/answer}
app.include_router(permission_router, prefix="/api/v1")
# M2 part B: /api/v1/questions/{pending, <id>/answer}（AskUserQuestion）
app.include_router(question_router, prefix="/api/v1")
app.include_router(build_orchestration_router(), prefix="/api/v1")
# Phase 1 observability: run snapshot + NDJSON event stream
from backend.api.orch_run_control import router as orch_run_router

app.include_router(orch_run_router, prefix="/api/v1")
app.include_router(wiki_router, prefix="/api/v1")
# M6 生态扩展: 用量/成本面板 (内存态 tracker, 与 API_MODE 无关)
app.include_router(usage_router, prefix="/api/v1")
# U18: HTML 会话导出 (POST /sessions/{id}/export, 与 API_MODE 无关)
app.include_router(export_router, prefix="/api/v1")
# R19-C/D: 系统维护 (备份清单/手动备份/记忆导出, 与 API_MODE 无关)
app.include_router(system_router, prefix="/api/v1")
# Artifacts 面板: /sessions/{id}/artifacts (list / content / reveal)
app.include_router(artifact_router, prefix="/api/v1")

# Update system: /api/v1/updates/{latest, history, channels}
app.include_router(updates_router_module.router, prefix="/api/v1")

# 本地开发环境助手: /api/v1/runtime/{probe, diagnose, exec}
# 复用 ChatService.tools 路径, runtime_exec 自动走 PermissionEnforcer 审批
# (与 BashTool 同等门禁), 见 docs/plans/2026-09-04_local-development-assistant.md
app.include_router(runtime_router, prefix="/api/v1")

# L8 PR-A (2026-09-09): Prometheus /metrics 端点从 hex_routes 抽出,
# 无条件挂载, 与 API_MODE 解耦 (历史仅 API_MODE=hex 时挂载, 默认 legacy 模式下
# /api/v1/metrics 不存在, Grafana 无法直接接入)。
from backend.api.metrics_routes import router as metrics_router

app.include_router(metrics_router, prefix="/api/v1")

if API_MODE == "hex":
    app.include_router(hex_router, prefix="/api/v1")
    app.include_router(legacy_router, prefix="/api/v1")
elif API_MODE == "legacy":
    app.include_router(legacy_router, prefix="/api/v1")
else:
    raise ValueError(f"API_MODE must be 'hex' or 'legacy', got: {API_MODE!r}")

# B1 (P11): 记忆嵌入器状态/切换 API (与 API_MODE 解耦, 挂在 legacy 命名空间)
app.include_router(embedder_router, prefix="/api/v1")

# Phase 8: scheduled tasks — mounted for both API modes (independent feature)
app.include_router(build_scheduled_router(get_scheduler_service), prefix="/api/v1")

# M3: MCP multi-server management (status / servers CRUD)
app.include_router(mcp_router, prefix="/api/v1")

# LLM trace diagnostic preview (settings page card)
app.include_router(diagnostic_router, prefix="/api/v1")

# Multimodal: media file serving + chat attachment upload
app.include_router(media_router, prefix="/api/v1")
app.include_router(chat_attachment_router, prefix="/api/v1")


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


# ── Diagnostic: all module-level imports complete ─────────────────────────
# 2026-09-10: if this line never appears in stderr, the hang is inside the
# import chain. If it appears but uvicorn never starts, the hang is inside
# __main__ or lifespan(). Elapsed time isolates slow imports from slow init.
if __name__ == "__main__":
    _elapsed_imports = time.monotonic() - _startup_t0
    print(  # noqa: T201
        f"[sage-startup] t={_elapsed_imports:.1f}s all module imports complete",
        file=sys.stderr,
        flush=True,
    )


if __name__ == "__main__":
    import uvicorn

    from backend.utils.logging import setup_logging

    _elapsed_entry = time.monotonic() - _startup_t0
    print(  # noqa: T201
        f"[sage-startup] t={_elapsed_entry:.1f}s entering __main__",
        file=sys.stderr,
        flush=True,
    )

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

    _elapsed_serve = time.monotonic() - _startup_t0
    print(  # noqa: T201
        f"[sage-startup] t={_elapsed_serve:.1f}s calling uvicorn.run() on :{port}",
        file=sys.stderr,
        flush=True,
    )
    uvicorn.run(app, host="127.0.0.1", port=port, log_config=None)
