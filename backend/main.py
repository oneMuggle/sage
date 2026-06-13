"""
Sage - 记忆型 AI 桌面助手
FastAPI 后端入口
"""
import logging
import os
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

import yaml
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from backend.adapters.out.compute.http_adapter import HttpComputeAdapter
from backend.adapters.out.compute.subprocess_adapter import SubprocessComputeAdapter
from backend.adapters.out.event.file_adapter import FileEventAdapter
from backend.adapters.out.llm.httpx_adapter import HttpxLLMAdapter
from backend.adapters.out.metric.prometheus_adapter import PrometheusMetricAdapter
from backend.adapters.out.storage.sqlite_adapter import SqliteStorageAdapter
from backend.adapters.out.tool.compute_tool_adapter import ComputeToolAdapter
from backend.adapters.out.tool.inproc_adapter import InprocToolAdapter
from backend.api.hex_routes import get_chat_service, router as hex_router
from backend.api.legacy_routes import router as legacy_router
from backend.api.llm_proxy_routes import router as llm_proxy_router
from backend.application.services.chat_service import ChatService
from backend.data.agent_repo import AgentRepository
from backend.data.database import Database

logger = logging.getLogger(__name__)


def _build_compute_adapter():
    """按 ``backend/config/ghm.yaml`` 装配 ComputePort。

    返回 ``None`` 时表示:

    - yaml 文件不存在(向后兼容,旧部署无 ghm 集成)
    - ``ghm.enabled = false`` (显式关闭)

    yaml 加载/解析异常会被记录并降级为 ``None``,不阻塞主流程。
    """


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
        return SubprocessComputeAdapter(ghm_cfg)
    if adapter_type == "http":
        logger.warning(
            "ghm.adapter=http: HttpComputeAdapter 仍是空壳,运行时调用会抛 NotImplementedError"
        )
        return HttpComputeAdapter(ghm_cfg)
    raise ValueError(f"未知的 ghm.adapter 类型: {adapter_type!r}")


def _build_chat_service() -> ChatService:
    """工厂：装配 6 个 ports（5 个生产 adapter + 1 个暂未实现 placeholder）。

    - llm:     HttpxLLMAdapter（包装既有 LLMClient）
    - tools:   InprocToolAdapter（如启用 ghm，则用 ComputeToolAdapter 包装合并）
    - skills:  None（SkillPort 协议未实现；P3 接入）
    - storage: SqliteStorageAdapter（包装既有 SessionRepository / MessageRepository）
    - metrics: PrometheusMetricAdapter
    - events:  FileEventAdapter（写 audit jsonl）

    装配在每次依赖注入时被调用——单例化由调用方（如 ``app.state``）自行管理。
    """
    inner_tools = InprocToolAdapter()
    compute = _build_compute_adapter()
    if compute is not None:
        tools = ComputeToolAdapter(compute=compute, inner=inner_tools)
        logger.info(
            "ComputeToolAdapter 已装配,注册 %d 个计算工具",
            len(compute.list_operations()),
        )
    else:
        tools = inner_tools

    return ChatService(
        llm=HttpxLLMAdapter(),
        tools=tools,
        skills=None,  # SkillPort 协议未实现；P3 接入
        storage=SqliteStorageAdapter(),
        metrics=PrometheusMetricAdapter(),
        events=FileEventAdapter(),
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理。"""
    # 启动时初始化
    db = Database()
    db.init_db()
    app.state.db = db

    # PR-3: agents 表种子化 (空表时插 4 个默认 agent, 幂等)

    seeded = AgentRepository().seed_defaults_if_empty()
    if seeded:
        logger.info("已种子化 %d 个默认 agent (primary/researcher/coder/memory_manager)", seeded)

    # Hex 模式：装配 ChatService 并注入到 hex_routes 的 DI 工厂
    api_mode = os.environ.get("API_MODE", "hex").lower()
    if api_mode == "hex":
        app.dependency_overrides[get_chat_service] = _build_chat_service
        app.state.chat_service = _build_chat_service()
        logger.info("Hex 模式：ChatService 已装配（/chat 走 hex_routes，其余走 legacy_routes）")
    else:
        logger.info("Legacy 模式：全部端点走 legacy_routes")

    yield

    # 关闭时清理
    pass


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
# - API_MODE=hex（默认）：先注册 hex（/chat 走 ChatService），
#   再注册 legacy（/sessions、/memory、/evolution、/interrupt）。
#   FastAPI 按注册顺序匹配——hex 的 /chat 优先命中，其余走 legacy。
# - API_MODE=legacy：仅注册 legacy。
# 通用 LLM 代理（/api/v1/llm/*）在两种模式下都注册 — 浏览器到 LLM 的
# 测试连接 / 拉取模型调用都走它，与 API_MODE 无关（见 llm_proxy_routes.py）。
app.include_router(llm_proxy_router, prefix="/api/v1")

_API_MODE = os.environ.get("API_MODE", "hex").lower()
if _API_MODE == "hex":
    app.include_router(hex_router, prefix="/api/v1")
    app.include_router(legacy_router, prefix="/api/v1")
elif _API_MODE == "legacy":
    app.include_router(legacy_router, prefix="/api/v1")
else:
    raise ValueError(f"API_MODE must be 'hex' or 'legacy', got: {_API_MODE!r}")


@app.get("/health")
async def health_check():
    """健康检查"""
    return {"status": "ok", "version": "0.1.1"}


if __name__ == "__main__":
    import uvicorn

    port = int(os.environ.get("PYTHON_BACKEND_PORT", "8765"))
    uvicorn.run(app, host="127.0.0.1", port=port)
