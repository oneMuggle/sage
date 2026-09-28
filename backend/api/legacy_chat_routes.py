# ruff: noqa: UP006, UP007, UP035, UP045 — release/win7 Python 3.8 兼容，保留 typing 注解
"""非流式聊天 / attach / 中断 / steering / 进化 / learn 路由组
（C2g，DSH 对标 R32，自 legacy_routes.py 迁出）。

7 个端点的唯一归属（/chat、/chat/stream/active、/chat/stream/{id} attach、
/interrupt、/chat/steer、/evolution/logs、/learn）。/chat/stream producer
仍留 legacy_routes（与流注册表/支撑模块的耦合在装配侧保持原状）。

路径与前缀保持不变——纯物理拆分，零行为变更。模型经 legacy_models.py、
状态经 chat_stream_state、支撑经 chat_stream_support 导入。
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from typing import List, Optional

from fastapi import APIRouter, Body, HTTPException, Request
from fastapi.responses import StreamingResponse

from backend.api.chat_session_lifecycle import _safe_log_field
from backend.api.chat_stream_registry import SENTINEL, StreamRegistry
from backend.api.chat_stream_state import _ACTIVE_STREAMS, interrupt_stream
from backend.api.chat_stream_support import _ndjson
from backend.api.legacy_models import (
    ChatRequest,
    ChatResponse,
    EvolutionLogResponse,
    InterruptRequest,
    LearnRequest,
    SteerRequest,
)
from backend.core.errors import LLMError
from backend.core.legacy.agent import SageAgent
from backend.data.database import get_database, make_with_db_lock
from backend.data.session_repo import SessionRepository
from backend.orchestration.llm_factory import load_llm_config_for_chat
from backend.scheduler import get_evolution_logs
from backend.services.scheduler import get_scheduler_service
from backend.skills.review_queue import get_review_queue

logger = logging.getLogger(__name__)


def with_db_lock(func):
    """装饰器：包在全局 `_SQLITE_LOCK` 内（D3 make_with_db_lock 模式）。"""
    return make_with_db_lock(globals())(func)


router = APIRouter()


# ==================== 聊天 API ====================


@router.post("/chat", response_model=ChatResponse)
async def chat(
    data: ChatRequest,
    request: Request,
):
    """发送聊天消息（单 agent；流式编排见 /chat/stream）。

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
                # temperature=0 是合法值 (确定性输出), 不能用 or 兜底
                "temperature": 0.7 if data.temperature is None else data.temperature,
            }
            logger.info(
                f"[REQ {request_id}] using custom LLM config: model={_safe_log_field(llm_config['model'])}"
            )

        # 2026-07-30: chat 默认加载 primary profile,让 profile.tools 白名单生效
        # (memory_manager 之类窄权限 agent 才不会拿到 list_dir/read_file 全部工具)
        agent = SageAgent(
            agent_id=data.agent_id or "primary",
            scheduler_service_getter=get_scheduler_service,
        )
        # G5 (2026-09-06): 请求未显式带端点配置时，用「全局端点 + 会话覆盖/
        # profile 模型」解析 —— 会话里切换模型不影响其他会话与全局设置。
        if llm_config is None:
            profile_model = (
                (agent.profile or {}).get("model_config") or {}
            ).get("model")
            llm_config = load_llm_config_for_chat(
                session_id=data.session_id, profile_model=profile_model
            )
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

@router.get("/chat/stream/active")
def get_active_chat_stream(session_id: str, request: Request):
    """R25-D4: 查询会话当前活跃的 chat 流（renderer 重载后 reattach 用）。

    Returns:
        ``{"streamId": "<uuid>" | None}`` —— None 表示该会话没有活跃流。
    """
    registry: StreamRegistry = request.app.state.streams
    return {"streamId": registry.find_active_by_session(session_id)}


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
        subscriber_queue = await registry.subscribe(stream_id)
        if subscriber_queue is None:
            return
        try:
            while True:
                try:
                    # 短 timeout 让多消费者场景下能感知 producer done 状态。
                    event = await asyncio.wait_for(subscriber_queue.get(), timeout=1.0)
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
            # 客户端断开 — 后台 producer 继续跑，其他 subscriber 不受影响。
            logger.info(f"chat-stream attach cancelled: streamId={stream_id}")
            return
        finally:
            await registry.unsubscribe(stream_id, subscriber_queue)

    return StreamingResponse(event_generator(), media_type="application/x-ndjson")





@router.post("/interrupt")
@with_db_lock
def interrupt(data: Optional[InterruptRequest] = Body(default=None)):
    """中断 Agent（P0-2: 经 stream_id 定位真实运行的 agent）"""
    stream_id = data.stream_id if data is not None else None
    target = interrupt_stream(stream_id)
    return {"status": "ok", "target": target}


#: steering 消息长度上限（与编排链 O1 steering 端点同额度）
_STEER_MAX_CHARS = 8192


@router.post("/chat/steer")
def steer_agent(data: SteerRequest):
    """RT5 (round7): 单 agent steering —— 运行中转达用户补充指示。

    消息在目标 run 的**下一迭代边界**注入 LLM 上下文（agent.run_loop
    消费，与编排链 O1 边界投递同语义）。纯内存注册表 + deque 操作，
    不走 DB 锁；失败面：
    - 404 stream_not_found：stream 不存在/已结束
    - 409 not_running：stream 存在但 agent 不在 run 活跃窗口
      （前端收到 409 回退排队语义——run 结束后作为新消息发送）
    - 400 msg_too_long：超过 8KB 额度
    """
    text = (data.content or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail={"code": "empty_content"})
    if len(text) > _STEER_MAX_CHARS:
        raise HTTPException(status_code=400, detail={"code": "msg_too_long"})
    entry = _ACTIVE_STREAMS.get(data.stream_id)
    if entry is None:
        raise HTTPException(status_code=404, detail={"code": "stream_not_found"})
    agent_obj: SageAgent = entry["agent"]
    if not agent_obj.inject_user_message(text):
        raise HTTPException(status_code=409, detail={"code": "not_running"})
    return {"ok": True}

# ==================== 进化系统 API ====================


@router.get("/evolution/logs", response_model=List[EvolutionLogResponse])
@with_db_lock
def list_evolution_logs(limit: int = 50, offset: int = 0):
    """获取进化日志列表"""
    try:
        db = get_database()
        return get_evolution_logs(db, limit=limit, offset=offset)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ==================== Background Review (Background Review) ====================
#
# /learn: 用户显式触发当前会话的 review,产生技能草案候选。
# 与 Task 8 的自动 signal detection (complex_turn / low_success_rate)
# 互补 — 本端点是 manual trigger,trigger_type="explicit_learn"。


@router.post("/learn")
@with_db_lock
def learn_from_session(request: LearnRequest):
    """User explicitly triggers review of current conversation.

    Enqueues a review event with trigger_type="explicit_learn".
    The background worker will pull it, load conversation history,
    and generate a skill draft via ReviewService.

    - 200 + ``{"status": "queued", "message": "..."}``
    - 404 — session_id does not exist
    - 422 (FastAPI 自动) — session_id 缺失

    .. note:: fix/security-perf-quickwins §1.3a d (2026-08-09)
        The route enqueues ``messages: []`` as a placeholder and the
        background worker loads the full conversation history from
        ``session_id`` via ``MessageRepository.get_by_session`` before
        invoking ``ReviewService``. This keeps the HTTP request body
        small while still giving the LLM a complete context to summarize.
    """
    # I-2 fix: validate session existence before enqueueing — avoids
    # wasting LLM tokens on reviews for non-existent sessions.
    session_repo = SessionRepository()
    if session_repo.get(request.session_id) is None:
        raise HTTPException(
            status_code=404,
            detail=f"Session not found: {request.session_id}",
        )

    review_queue = get_review_queue()
    review_queue.enqueue(
        trigger_type="explicit_learn",
        session_id=request.session_id,
        context={
            # fix/security-perf-quickwins (2026-08-09, §1.3a d): the worker
            # now loads conversation history from MessageRepository before
            # invoking ReviewService (see backend/skills/review_queue.py
            # _process_event). The empty placeholder below is intentional —
            # it signals to the worker that loading is required, and also
            # keeps the request body small (no point shipping N messages
            # over HTTP when the worker can read them from the DB).
            "messages": [],
            "user_prompt": request.prompt,
        },
    )
    logger.info(
        "/learn: enqueued explicit_learn for session=%s",
        _safe_log_field(request.session_id),
    )
    return {"status": "queued", "message": "Review started"}
