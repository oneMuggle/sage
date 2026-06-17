"""
API 路由定义
"""

import asyncio

# I5: 流式视觉延迟 — DONE 事件的 content 拆成 chunk 逐个入队,
# 让前端能逐字渲染 (避免 LLM 一次返回完整字符串时 "砰一下" 全显示)。
# 真 LLM streaming 需要 OpenAI stream=true + adapter 支持 tool_calls (大改),
# 先用这个 producer 端的 fake stream 解决 90% 的视觉体验。
_STREAMING_CHUNK_SIZE = 6
_STREAMING_CHUNK_DELAY_S = 0.04
import json
import logging
import time
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, StrictBool

from backend.api.chat_stream_registry import SENTINEL, StreamEntry, StreamRegistry
from backend.core.errors import LLMError
from backend.core.legacy.agent import SageAgent
from backend.data.database import get_database
from backend.data.session_repo import Message as DbMessage, MessageRepository, SessionRepository
from backend.memory import EpisodicMemory, MemoryManager, SemanticMemory, WorkingMemory
from backend.scheduler import get_evolution_logs, get_scheduler

logger = logging.getLogger(__name__)

router = APIRouter()


def _safe_log_field(value: object, max_length: int = 64) -> str:
    """Sanitize a user-controlled field for safe logging.

    - Strip newlines and control chars to prevent log injection
    - Truncate to max_length to prevent log spam
    """
    s = str(value)
    s = "".join(c for c in s if c.isprintable() or c == " ")
    return s[:max_length]


# ==================== Pydantic 模型 ====================


class SessionCreate(BaseModel):
    title: str = "新对话"
    parent_id: str | None = None


class SessionUpdate(BaseModel):
    title: str | None = None
    is_pinned: bool | None = None


class ChatRequest(BaseModel):
    session_id: str
    message: str
    api_key: str | None = None
    api_url: str | None = None
    model: str | None = None
    max_context: int | None = None
    temperature: float | None = None
    # 透传字段:provider 让后端不再硬写,reasoning_effort/thinking_budget
    # 让上游 LLM 启用 thinking 输出(provider 决定哪种 key 会被接受)
    # - provider: openai / claude / gemini / deepseek / ollama / custom
    # - reasoning_effort: OpenAI o1/o3/5 + DeepSeek OpenAI 兼容代理
    # - thinking_budget: Gemini 2.5 OpenAI 兼容模式
    provider: str | None = None
    reasoning_effort: str | None = None
    thinking_budget: int | None = None


class MessageResponse(BaseModel):
    id: str
    session_id: str
    role: str
    content: str
    created_at: int
    model: str | None = None
    tool_calls: str | None = None


class ChatErrorInfo(BaseModel):
    """结构化的 /chat 错误信息。

    字段与 LLMError.to_dict() 对齐，便于前端统一处理。
    """

    type: str
    message: str
    status_code: int | None = None
    retry_after: int | None = None


class ChatResponse(BaseModel):
    """聊天响应：成功时含 message+session，失败时含 error+null message。"""

    message: MessageResponse | None = None
    session: dict | None = None
    error: ChatErrorInfo | None = None


class TriggerEvolutionRequest(BaseModel):
    """手动触发进化任务请求"""

    task_name: str


class EvolutionLogResponse(BaseModel):
    """进化日志响应"""

    id: str
    evolution_type: str
    description: str
    before_state: str | None = None
    after_state: str | None = None
    trigger_type: str
    trigger_condition: str | None = None
    status: str
    error_message: str | None = None
    tokens_used: int | None = None
    created_at: int
    completed_at: int | None = None


class EvolutionStatusResponse(BaseModel):
    """进化状态响应"""

    name: str
    schedule: str
    last_run: str | None = None
    next_run: str | None = None
    running: bool


class TriggerResponse(BaseModel):
    """触发响应"""

    success: bool
    message: str


class AgentToggle(BaseModel):
    """PATCH /agents/{id}/toggle 请求体 (PR-5)。

    单字段 ``enabled`` 必填 — 缺失走 Pydantic 自动 422。专门用来对
    enable/disable 这一高频操作做语义化端点 (审计 + 未来权限),不
    与 PATCH /agents/{id} 重叠。

    注: 用 ``StrictBool`` 而非 ``bool`` — Pydantic v2 默认 lax 模式会把
    "yes"/"1"/1 等强转 True, 在 API 边界宁可 422 也不要静默转换。前端
    TypeScript 永远传真 bool, 严格模式不会误伤。
    """

    enabled: StrictBool


class AgentUpdate(BaseModel):
    """PATCH /agents/{id} 请求体 (PR-4)。

    所有字段可选 — 不传视为"该字段不更新"。role / max_iterations
    走 Pydantic 校验, 非法值 422 (由 FastAPI 自动处理)。
    """

    # 注: Pydantic v2 默认对 "model_" 前缀的字段名有保留命名空间保护.
    # 我们在类内用 model_config 字段, 通过 ConfigDict 关掉该保护.
    model_config = {"protected_namespaces": ()}

    name: str | None = None
    role: str | None = None  # 校验放在路由层 (依赖 Pydantic Literal 不直观)
    system_prompt: str | None = None
    tools: list[str] | None = None
    memory_access: list[str] | None = None
    model_config_data: dict | None = None  # 字段名避开 Pydantic 保留名, 路由层映射到 model_config
    max_iterations: int | None = None  # 路由层校验 1..50
    enabled: bool | None = None
    description: str | None = None


# ==================== 依赖注入 ====================


def get_session_repo() -> SessionRepository:
    return SessionRepository()


def get_agent() -> SageAgent:
    return SageAgent()


# ==================== 会话 API ====================


@router.post("/sessions", response_model=dict)
async def create_session(data: SessionCreate, repo: SessionRepository = Depends(get_session_repo)):
    """创建新会话"""
    session = repo.create(title=data.title, parent_id=data.parent_id)
    return session.to_dict()


@router.get("/sessions", response_model=list[dict])
async def list_sessions(
    limit: int = 100, offset: int = 0, repo: SessionRepository = Depends(get_session_repo)
):
    """获取会话列表"""
    sessions = repo.list(limit=limit, offset=offset)
    return [s.to_dict() for s in sessions]


@router.get("/sessions/{session_id}", response_model=dict)
async def get_session(session_id: str, repo: SessionRepository = Depends(get_session_repo)):
    """获取单个会话"""
    session = repo.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="会话不存在")
    return session.to_dict()


@router.patch("/sessions/{session_id}", response_model=dict)
async def update_session(
    session_id: str, data: SessionUpdate, repo: SessionRepository = Depends(get_session_repo)
):
    """更新会话"""
    update_data = {}
    if data.title is not None:
        update_data["title"] = data.title
    if data.is_pinned is not None:
        update_data["is_pinned"] = 1 if data.is_pinned else 0

    if update_data:
        repo.update(session_id, **update_data)

    session = repo.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="会话不存在")
    return session.to_dict()


@router.delete("/sessions/{session_id}")
async def delete_session(session_id: str, repo: SessionRepository = Depends(get_session_repo)):
    """删除会话"""
    if not repo.delete(session_id):
        raise HTTPException(status_code=404, detail="会话不存在")
    return {"status": "ok"}


# ==================== 消息 API ====================


@router.post("/messages/{message_id}/delete")
async def delete_message(message_id: str):
    """删除单条消息（物理删除，非软删）。

    对应 Tauri command ``delete_message`` (PR-2):
    - 现有消息 → 200 + ``{"deleted": true}``
    - 不存在消息 → 404 + 结构化 detail (前端可分类处理)
    - 重复删除 → 第二次 404 (幂等性)

    注: 选 POST 而非 DELETE 是为了与项目其他 `/<resource>/<id>/delete` 路由
    (sessions/{id}/delete) 保持一致; 真正的 RESTful DELETE 在 v2 改造时再做。
    """
    from backend.data.session_repo import MessageRepository

    deleted = MessageRepository().delete(message_id)
    if not deleted:
        raise HTTPException(
            status_code=404,
            detail={
                "type": "message_not_found",
                "message": f"message {message_id} not found",
            },
        )
    return {"deleted": True}


# ==================== Agent API (PR-3) ====================
#
# 4 个默认 agent (primary/researcher/coder/memory_manager) 由
# backend/main.py:lifespan 启动时通过 AgentRepository.seed_defaults_if_empty
# 种子化到 SQLite agents 表. 本节路由不写 (PR-4/5 负责 PATCH /toggle).


@router.get("/agents")
async def list_agents():
    """列出所有 agent (含 disabled), 按 id 排序。

    对应 Tauri command ``list_agents`` (PR-3)。
    """
    from backend.data.agent_repo import AgentRepository

    return AgentRepository().list_all()


@router.get("/agents/{agent_id}")
async def get_agent_by_id(agent_id: str):
    """按 id 取单个 agent。

    命名注意: 不能叫 ``get_agent`` — 与本文件 line 136 的 dependency
    provider ``def get_agent()`` 同名会覆盖, 导致 ``/interrupt`` 路由
    拿错函数. 后续 PR 可把 dependency 改名 ``make_sage_agent()``,
    本 PR 仅做局部重命名.
    """
    from backend.data.agent_repo import AgentRepository

    agent = AgentRepository().get(agent_id)
    if not agent:
        raise HTTPException(
            status_code=404,
            detail={"type": "agent_not_found", "message": f"agent {agent_id} not found"},
        )
    return agent


@router.patch("/agents/{agent_id}")
async def update_agent(agent_id: str, data: AgentUpdate):
    """部分更新 agent (PR-4)。

    - 200 + 更新后完整 profile
    - 404 + 结构化 detail (id 不存在)
    - 422 (FastAPI 自动) — 字段类型 / role 白名单 / max_iterations 范围
    - PATCH 是 partial update: 缺省字段保留原值
    - 空 body: 视为 no-op, 返回当前 profile, updated_at 不动
    """
    from backend.data.agent_repo import AgentRepository

    # 字段级校验: role 白名单
    valid_roles = {"coordinator", "researcher", "coder", "memory_manager"}
    if data.role is not None and data.role not in valid_roles:
        raise HTTPException(
            status_code=422,
            detail={
                "type": "invalid_role",
                "message": f"role must be one of {sorted(valid_roles)}, got {data.role!r}",
            },
        )

    # 字段级校验: max_iterations 范围
    if data.max_iterations is not None and not (1 <= data.max_iterations <= 50):
        raise HTTPException(
            status_code=422,
            detail={
                "type": "invalid_max_iterations",
                "message": f"max_iterations must be in 1..50, got {data.max_iterations}",
            },
        )

    repo = AgentRepository()

    # 不存在 → 404 (update 返回 0 时区分"没字段改"和"id 不存在")
    if repo.get(agent_id) is None:
        raise HTTPException(
            status_code=404,
            detail={"type": "agent_not_found", "message": f"agent {agent_id} not found"},
        )

    # 转 dict 给 repo.update; 字段名 model_config_data → model_config (避开 Pydantic 保留名)
    update_payload = data.model_dump(exclude_none=True)
    if "model_config_data" in update_payload:
        update_payload["model_config"] = update_payload.pop("model_config_data")

    repo.update(agent_id, update_payload)
    return repo.get(agent_id)


@router.patch("/agents/{agent_id}/toggle")
async def toggle_agent(agent_id: str, data: AgentToggle):
    """启用/禁用 agent (PR-5)。

    - 200 + 更新后完整 profile (含 enabled / updated_at 新值)
    - 404 + 结构化 detail (id 不存在, 与 PR-3/PR-4 复用同一 type)
    - 422 (FastAPI 自动) — enabled 缺失 / 类型错

    选 ``/toggle`` 子路径而非复用 ``PATCH /agents/{id}`` 的理由:
    - 审计语义清晰: events.jsonl 里可单独 grep 出 toggle 操作
    - 未来权限模型: toggle 与 system_prompt 编辑可独立授权

    同值 toggle 也走 SQL UPDATE — 幂等但 updated_at 仍刷新, 符合
    set_enabled() 语义。
    """
    from backend.data.agent_repo import AgentRepository

    repo = AgentRepository()

    # 与 update_agent 一致: 显式查存在性, 给出比 set_enabled() 更友好的 404 detail
    if repo.get(agent_id) is None:
        raise HTTPException(
            status_code=404,
            detail={"type": "agent_not_found", "message": f"agent {agent_id} not found"},
        )

    repo.set_enabled(agent_id, data.enabled)
    return repo.get(agent_id)


# ==================== 技能 API (PR-7) ====================

# 进程内单例: adapter 自身带 enabled / usage_count 内存状态,
# 模块级 cache 让多个请求共享同一份,避免 toggle 后状态错位。
_skill_adapter_singleton: object | None = None


def _get_skill_adapter():
    """惰性构造 + 缓存 InprocSkillAdapter 单例。"""
    global _skill_adapter_singleton
    if _skill_adapter_singleton is None:
        from backend.adapters.out.skill import InprocSkillAdapter

        _skill_adapter_singleton = InprocSkillAdapter()
    return _skill_adapter_singleton


def _skill_to_dict(spec, enabled: bool, usage_count: int) -> dict:
    """把 SkillSpec + 路由层扩展字段序列化为 dict。"""
    return {
        "name": spec.name,
        "description": spec.description,
        "triggers": list(spec.triggers),
        "parameters": dict(spec.parameters),
        "examples": list(spec.examples),
        "enabled": enabled,
        "usage_count": usage_count,
    }


@router.get("/skills")
async def list_skills():
    """列出所有已注册技能 (含 disabled 与 usage_count)。"""
    adapter = _get_skill_adapter()
    return [
        _skill_to_dict(spec, adapter.is_enabled(spec.name), adapter.usage_count(spec.name))
        for spec in adapter.list_skills()
    ]


class SkillToggle(BaseModel):
    """``POST /skills/{name}/toggle`` 请求体。"""

    enabled: StrictBool


@router.post("/skills/{name}/toggle")
async def toggle_skill(name: str, data: SkillToggle):
    """启用 / 禁用技能 (PR-7)。

    - 200 + 完整 skill dict (含新 enabled)
    - 404 + 结构化 detail (技能名不存在)
    - 422 (FastAPI 自动) — enabled 缺失 / 类型错
    """
    adapter = _get_skill_adapter()
    if not adapter.set_enabled(name, data.enabled):
        raise HTTPException(
            status_code=404,
            detail={"type": "skill_not_found", "message": f"skill '{name}' not found"},
        )
    # 返回完整 skill dict (与 list 接口一致)
    spec = next((s for s in adapter.list_skills() if s.name == name), None)
    assert spec is not None  # set_enabled 已 guard
    return _skill_to_dict(spec, adapter.is_enabled(name), adapter.usage_count(name))


class SkillExecuteRequest(BaseModel):
    """``POST /skills/{name}/execute`` 请求体。

    - action: 技能子动作(单动作 builtin 留空字符串即可)
    - args:   技能参数 (透传给 BaseSkill.execute)
    """

    action: str = ""
    args: dict = {}


@router.post("/skills/{name}/execute")
async def execute_skill(name: str, data: SkillExecuteRequest):
    """执行技能 (PR-7)。

    - 200 + SkillResult (success / content / metadata / error)
    - 404 + 结构化 detail (技能名不存在 — 资源不存在的标准 REST 语义)
    - 422 (FastAPI 自动) — args 类型错等
    - execute 内部失败(技能 disabled / builtin 工具不可用)→ 200 + success=False,
      **不抛 4xx/5xx**,由前端按 success 字段判定。
    """
    adapter = _get_skill_adapter()
    # 资源不存在 → 404 (与 disabled 走 200 + success=False 区分开)
    if not adapter.has_skill(name):
        raise HTTPException(
            status_code=404,
            detail={"type": "skill_not_found", "message": f"skill '{name}' not found"},
        )
    result = await adapter.execute(name, data.action, data.args)
    if result.success:
        adapter.bump_usage(name)
    return {
        "success": result.success,
        "content": result.content,
        "metadata": result.metadata,
        "error": result.error,
    }


# ==================== 聊天 API ====================


@router.post("/chat", response_model=ChatResponse)
async def chat(
    data: ChatRequest,
    request: Request,
):
    """发送聊天消息。

    错误处理：
    - LLMError: 返回 HTTP 200 + 结构化 error 字段
    - 其他未预期错误: 返回 HTTP 200 + 通用 unknown 错误
    - request_id 来自中间件（确保响应头与日志一致）
    """
    request_id = getattr(request.state, "request_id", str(uuid.uuid4()))
    logger.info(
        f"[REQ {request_id}] /chat received: session_id={_safe_log_field(data.session_id)}, "
        f"api_key={'***' if data.api_key else 'MISSING'}, "
        f"model={_safe_log_field(data.model or 'default')}"
    )

    try:
        llm_config = None
        if data.api_key and data.api_url:
            llm_config = {
                "provider": "custom",
                "api_key": data.api_key,
                "base_url": data.api_url,
                "model": data.model or "gpt-3.5-turbo",
                "temperature": data.temperature or 0.7,
            }
            logger.info(
                f"[REQ {request_id}] using custom LLM config: model={_safe_log_field(llm_config['model'])}"
            )

        agent = SageAgent()
        result = await agent.chat(data.session_id, data.message, llm_config=llm_config)

        # agent.chat() may return a structured error dict (Task 6 refactor) instead of raising
        if isinstance(result, dict) and result.get("error"):
            logger.warning(
                f"[REQ {request_id}] /chat returned error from agent: "
                f"type={result['error'].get('type')}, message={result['error'].get('message')}"
            )
        else:
            msg = result.get("message") if isinstance(result, dict) else None
            msg_id = msg.get("id") if isinstance(msg, dict) else None
            logger.info(f"[REQ {request_id}] /chat success: message_id={msg_id}")
        return result

    except LLMError as e:
        logger.warning(
            f"[REQ {request_id}] /chat LLM error: type={e.type.value}, message={e.message}"
        )
        return {
            "error": e.to_dict(),
            "message": None,
            "session": None,
        }
    except Exception:
        logger.exception(f"[REQ {request_id}] /chat unexpected error")
        return {
            "error": {
                "type": "unknown",
                "message": "服务内部错误",
                "status_code": 500,
                "retry_after": None,
            },
            "message": None,
            "session": None,
        }


@router.post("/chat/stream")
async def chat_stream_create(data: ChatRequest, request: Request):
    """创建 chat 流 (I2)。

    立即返回 ``{"streamId": "..."}``,后台启动 ``agent.run_loop`` 跑一次 LLM,
    事件入 ``app.state.streams[streamId].queue``。

    Electron 端拿到 streamId 后调 ``GET /chat/stream/{streamId}`` attach 取事件。
    这样 LLM 只被调一次(原方案 invoke 阶段读首行 + relay 重放 = 两次)。

    Args:
        data: 与原 /chat 相同的 ChatRequest 体
        request: FastAPI Request,用于访问 app.state

    Returns:
        ``{"streamId": "<uuid4>"}``
    """
    request_id = str(uuid.uuid4())
    stream_id = str(uuid.uuid4())
    logger.info(
        f"[REQ {request_id}] /chat/stream create: "
        f"streamId={stream_id}, "
        f"session_id={_safe_log_field(data.session_id)}, "
        f"api_key={'***' if data.api_key else 'MISSING'}, "
        f"model={_safe_log_field(data.model or 'default')}"
    )

    registry: StreamRegistry = request.app.state.streams

    async def producer(entry: StreamEntry) -> None:
        """后台跑 agent.run_loop,事件入 entry.queue。

        这里把 AgentEvent.to_dict() 在入队时序列化,避免对象跨 task 边界泄漏
        内部状态(detached Pydantic / cyclic ref 等)。
        """
        try:
            llm_config = None
            if data.api_key and data.api_url:
                llm_config = {
                    # 修: provider 不再硬写,从前端请求透传;
                    # 默认 "custom" 保留向后兼容(老客户端/无 provider 字段)
                    "provider": data.provider or "custom",
                    "api_key": data.api_key,
                    "base_url": data.api_url,
                    "model": data.model or "gpt-3.5-turbo",
                    "temperature": data.temperature or 0.7,
                }
                # 推理参数:None 时不传,避免污染老 LLM
                if data.reasoning_effort is not None:
                    llm_config["reasoning_effort"] = data.reasoning_effort
                if data.thinking_budget is not None:
                    llm_config["thinking_budget"] = data.thinking_budget
                logger.info(
                    f"[REQ {request_id}] /chat/stream producer using custom LLM: "
                    f"model={_safe_log_field(llm_config['model'])}"
                )

            agent = SageAgent()
            messages = [
                {"role": "system", "content": "你是 Sage，一个智能 AI 助手。"},
                {"role": "user", "content": data.message},
            ]
            # PR-7: 流式 chat 持久化。run_loop() 自身不写库(保持通用 ReAct
            # 迭代器纯净),由 producer 整合层负责落 user+assistant 消息 + 更新
            # session metadata。每个落盘独立 try/except,失败只 logger.warning
            # 不破坏流。
            message_repo = MessageRepository()
            session_repo = SessionRepository()
            user_now = int(time.time() * 1000)
            try:
                message_repo.save(
                    DbMessage(
                        id=str(uuid.uuid4()),
                        session_id=data.session_id,
                        role="user",
                        content=data.message,
                        created_at=user_now,
                    )
                )
            except Exception as db_err:
                logger.warning(f"[REQ {request_id}] 用户消息持久化失败: {db_err}")

            done_content: str | None = None
            async for evt in agent.run_loop(messages, llm_config=llm_config):
                # I5: DONE 事件的 content 拆成 chunk 逐个入队,前端累积实现逐字显示。
                # 真 LLM streaming 需要 OpenAI stream=true + adapter 支持 tool_calls,
                # 那是更大的重构;这个 producer 端的 fake stream 给出 90% 视觉效果。
                if evt.state.value == "done" and evt.content:
                    done_content = evt.content
                    content = evt.content
                    for i in range(0, len(content), _STREAMING_CHUNK_SIZE):
                        delta = content[i : i + _STREAMING_CHUNK_SIZE]
                        await entry.queue.put(
                            {
                                "state": "content_delta",
                                "iteration": evt.iteration,
                                "content": delta,
                            }
                        )
                        await asyncio.sleep(_STREAMING_CHUNK_DELAY_S)
                    # 最终 DONE 事件保留完整 content (前端 finishStream 需要)
                    await entry.queue.put(evt.to_dict())
                else:
                    await entry.queue.put(evt.to_dict())

            # run_loop 正常结束 (DONE) → 持久化 assistant + 更新 session。
            # LLMError 走 except 分支,此块不执行 (无 assistant 可保存)。
            if done_content:
                assistant_now = int(time.time() * 1000)
                try:
                    message_repo.save(
                        DbMessage(
                            id=str(uuid.uuid4()),
                            session_id=data.session_id,
                            role="assistant",
                            content=done_content,
                            created_at=assistant_now,
                            model=(llm_config.get("model") if llm_config else "local"),
                        )
                    )
                except Exception as db_err:
                    logger.warning(f"[REQ {request_id}] 助手消息持久化失败: {db_err}")
                try:
                    sess = session_repo.get(data.session_id)
                    if sess is not None:
                        session_repo.update(
                            data.session_id,
                            last_message_at=assistant_now,
                            message_count=sess.message_count + 2,
                        )
                except Exception as db_err:
                    logger.warning(f"[REQ {request_id}] 会话更新失败: {db_err}")
        except LLMError as e:
            logger.warning(
                f"[REQ {request_id}] /chat/stream LLM error: "
                f"type={e.type.value}, message={e.message}"
            )
            await entry.queue.put({"error": e.to_dict(), "state": "failed"})

    await registry.create(stream_id, queue_maxsize=1000, producer=producer)
    return {"streamId": stream_id}


@router.get("/chat/stream/{stream_id}")
async def chat_stream_attach(stream_id: str, request: Request):
    """attach 到已创建的 chat 流 (I2),NDJSON 推送事件。

    从 ``app.state.streams[stream_id].queue`` 拉事件,序列化 NDJSON 返回。
    多次同时 attach 到同一 streamId 会**共享**queue(广播) — 不会触发新的 LLM 调用。
    客户端断开时(CancelledError)不取消后台 producer(已消耗的 token 不浪费),
    producer 跑完后会通过 SENTINEL 关闭此流。

    Args:
        stream_id: create 端点返回的 streamId
        request: FastAPI Request

    Returns:
        StreamingResponse(media_type=application/x-ndjson)

    Raises:
        HTTPException 404: streamId 不存在或已过期
    """
    registry: StreamRegistry = request.app.state.streams
    entry = registry.get(stream_id)
    if entry is None:
        raise HTTPException(
            status_code=404,
            detail=f"chat stream not found or expired: {stream_id}",
        )
    logger.info(f"chat-stream attach: streamId={stream_id} status={entry.status}")

    async def event_generator():
        try:
            while True:
                try:
                    # 短 timeout 让多消费者场景下能感知 producer done 状态。
                    # SENTINEL 只入队一次,只有一个 attach 能拿到 — 其余
                    # attach 必须靠 status 字段判断流是否结束。
                    event = await asyncio.wait_for(entry.queue.get(), timeout=1.0)
                except asyncio.TimeoutError:  # noqa: UP041 — Py3.10 中 asyncio.TimeoutError ≠ built-in TimeoutError
                    # 1s 内没新事件 — 检查 producer 是否已结束
                    # 注: Python 3.10 中 asyncio.TimeoutError 不等同内置 TimeoutError
                    if entry.status in ("done", "failed"):
                        break
                    continue
                if event is SENTINEL:
                    break
                yield _ndjson(event)
        except asyncio.CancelledError:
            # 客户端断开 — 后台 producer 继续跑,队列中未消费的事件留给下次 attach
            logger.info(f"chat-stream attach cancelled: streamId={stream_id}")
            return

    return StreamingResponse(event_generator(), media_type="application/x-ndjson")


def _ndjson(d: dict) -> str:
    """序列化为 NDJSON 行（以 \\n 结尾）。

    Args:
        d: 可被 json.dumps 序列化的字典

    Returns:
        单行 JSON 字符串，末尾带换行符
    """
    return json.dumps(d, ensure_ascii=False) + "\n"


@router.post("/interrupt")
async def interrupt(agent: SageAgent = Depends(get_agent)):
    """中断 Agent"""
    agent.interrupt()
    return {"status": "ok"}


# ==================== 消息 API ====================


@router.get("/sessions/{session_id}/messages", response_model=list[dict])
async def get_messages(session_id: str, limit: int = 100, offset: int = 0):
    """获取会话消息"""
    repo = MessageRepository()
    messages = repo.get_by_session(session_id, limit=limit, offset=offset)
    return [m.to_dict() for m in messages]


# ==================== 进化系统 API ====================


@router.get("/evolution/logs", response_model=list[EvolutionLogResponse])
async def list_evolution_logs(limit: int = 50, offset: int = 0):
    """获取进化日志列表"""
    try:
        db = get_database()
        return get_evolution_logs(db, limit=limit, offset=offset)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/evolution/trigger", response_model=TriggerResponse)
async def trigger_evolution(data: TriggerEvolutionRequest):
    """手动触发进化任务"""
    try:
        scheduler = get_scheduler()

        # 检查任务是否存在
        task_names = [t["name"] for t in scheduler.get_task_status()]
        if data.task_name not in task_names:
            raise HTTPException(status_code=404, detail=f"任务不存在: {data.task_name}")

        # 触发任务
        success = scheduler.trigger_task(data.task_name)

        if success:
            return TriggerResponse(success=True, message=f"任务 {data.task_name} 已触发")
        else:
            return TriggerResponse(success=False, message=f"任务 {data.task_name} 触发失败")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/evolution/status", response_model=list[EvolutionStatusResponse])
async def get_evolution_status():
    """获取进化任务状态"""
    try:
        scheduler = get_scheduler()
        return scheduler.get_task_status()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ==================== 记忆 API ====================


def get_memory_manager() -> MemoryManager:
    """获取记忆管理器实例"""
    db = get_database()
    working = WorkingMemory(max_size=20, max_tokens=4000)
    episodic = EpisodicMemory(db)
    semantic = SemanticMemory(db)
    return MemoryManager(working, episodic, semantic)


class MemorySearchRequest(BaseModel):
    query: str
    memory_type: str | None = None
    limit: int = 20


class MemorySaveRequest(BaseModel):
    content: str
    memory_type: str = "episodic"
    importance: int = 5
    tags: list[str] = []


class MemoryDeleteRequest(BaseModel):
    id: str


@router.get("/memory/search")
async def search_memory(query: str, limit: int = 20, type: str | None = None):
    """搜索记忆"""
    try:
        mm = get_memory_manager()
        return mm.search_memories(query=query, memory_type=type, limit=limit)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/memory/save")
async def save_memory(data: MemorySaveRequest):
    """保存记忆"""
    try:
        mm = get_memory_manager()
        memory_id = mm.memorize(
            content=data.content,
            memory_type=data.memory_type,
            importance=data.importance,
            tags=data.tags,
        )
        return {"id": memory_id, "status": "ok"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/memory/delete")
async def delete_memory(data: MemoryDeleteRequest):
    """删除记忆"""
    try:
        mm = get_memory_manager()
        # 尝试从所有类型中删除
        for mtype in ["episodic", "semantic"]:
            if mm.delete_memory(data.id, mtype):
                return {"status": "ok"}
        raise HTTPException(status_code=404, detail="记忆不存在")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/memory/list")
async def list_memories(page: int = 1, page_size: int = 20, type: str | None = None):
    """获取记忆列表"""
    try:
        mm = get_memory_manager()
        if type == "episodic":
            results = mm.episodic.get_recent(limit=page_size)
        elif type == "semantic":
            results = mm.semantic.get_recent(limit=page_size)
        else:
            results = mm.episodic.get_recent(limit=page_size)
        return results
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
