"""
API 路由定义
"""
import uuid
import logging
from fastapi import APIRouter, HTTPException, Depends, Request
from typing import List, Optional
from pydantic import BaseModel

from backend.data.session_repo import SessionRepository, Session, MessageRepository
from backend.core.agent import SageAgent
from backend.core.errors import LLMError
from backend.scheduler import get_evolution_logs, get_scheduler, create_evolution_tasks
from backend.data.database import get_database
from backend.memory import WorkingMemory, EpisodicMemory, SemanticMemory, MemoryManager


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
    parent_id: Optional[str] = None


class SessionUpdate(BaseModel):
    title: Optional[str] = None
    is_pinned: Optional[bool] = None


class ChatRequest(BaseModel):
    session_id: str
    message: str
    api_key: Optional[str] = None
    api_url: Optional[str] = None
    model: Optional[str] = None
    max_context: Optional[int] = None
    temperature: Optional[float] = None


class MessageResponse(BaseModel):
    id: str
    session_id: str
    role: str
    content: str
    created_at: int
    model: Optional[str] = None
    tool_calls: Optional[str] = None


class ChatErrorInfo(BaseModel):
    """结构化的 /chat 错误信息。

    字段与 LLMError.to_dict() 对齐，便于前端统一处理。
    """
    type: str
    message: str
    status_code: Optional[int] = None
    retry_after: Optional[int] = None


class ChatResponse(BaseModel):
    """聊天响应：成功时含 message+session，失败时含 error+null message。"""
    message: Optional[MessageResponse] = None
    session: Optional[dict] = None
    error: Optional[ChatErrorInfo] = None


class TriggerEvolutionRequest(BaseModel):
    """手动触发进化任务请求"""
    task_name: str


class EvolutionLogResponse(BaseModel):
    """进化日志响应"""
    id: str
    evolution_type: str
    description: str
    before_state: Optional[str] = None
    after_state: Optional[str] = None
    trigger_type: str
    trigger_condition: Optional[str] = None
    status: str
    error_message: Optional[str] = None
    tokens_used: Optional[int] = None
    created_at: int
    completed_at: Optional[int] = None


class EvolutionStatusResponse(BaseModel):
    """进化状态响应"""
    name: str
    schedule: str
    last_run: Optional[str] = None
    next_run: Optional[str] = None
    running: bool


class TriggerResponse(BaseModel):
    """触发响应"""
    success: bool
    message: str


# ==================== 依赖注入 ====================

def get_session_repo() -> SessionRepository:
    return SessionRepository()


def get_agent() -> SageAgent:
    return SageAgent()


# ==================== 会话 API ====================

@router.post("/sessions", response_model=dict)
async def create_session(
    data: SessionCreate,
    repo: SessionRepository = Depends(get_session_repo)
):
    """创建新会话"""
    session = repo.create(title=data.title, parent_id=data.parent_id)
    return session.to_dict()


@router.get("/sessions", response_model=List[dict])
async def list_sessions(
    limit: int = 100,
    offset: int = 0,
    repo: SessionRepository = Depends(get_session_repo)
):
    """获取会话列表"""
    sessions = repo.list(limit=limit, offset=offset)
    return [s.to_dict() for s in sessions]


@router.get("/sessions/{session_id}", response_model=dict)
async def get_session(
    session_id: str,
    repo: SessionRepository = Depends(get_session_repo)
):
    """获取单个会话"""
    session = repo.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="会话不存在")
    return session.to_dict()


@router.patch("/sessions/{session_id}", response_model=dict)
async def update_session(
    session_id: str,
    data: SessionUpdate,
    repo: SessionRepository = Depends(get_session_repo)
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
async def delete_session(
    session_id: str,
    repo: SessionRepository = Depends(get_session_repo)
):
    """删除会话"""
    if not repo.delete(session_id):
        raise HTTPException(status_code=404, detail="会话不存在")
    return {"status": "ok"}


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
    logger.info(f"[REQ {request_id}] /chat received: session_id={_safe_log_field(data.session_id)}, "
                f"api_key={'***' if data.api_key else 'MISSING'}, "
                f"model={_safe_log_field(data.model or 'default')}")

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
            logger.info(f"[REQ {request_id}] using custom LLM config: model={_safe_log_field(llm_config['model'])}")

        agent = SageAgent()
        result = await agent.chat(data.session_id, data.message, llm_config=llm_config)
        logger.info(f"[REQ {request_id}] /chat success: message_id={result.get('message', {}).get('id')}")
        return result

    except LLMError as e:
        logger.warning(f"[REQ {request_id}] /chat LLM error: type={e.type.value}, message={e.message}")
        return {
            "error": e.to_dict(),
            "message": None,
            "session": None,
        }
    except Exception as e:
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


@router.post("/interrupt")
async def interrupt(agent: SageAgent = Depends(get_agent)):
    """中断 Agent"""
    agent.interrupt()
    return {"status": "ok"}


# ==================== 消息 API ====================

@router.get("/sessions/{session_id}/messages", response_model=List[dict])
async def get_messages(
    session_id: str,
    limit: int = 100,
    offset: int = 0
):
    """获取会话消息"""
    repo = MessageRepository()
    messages = repo.get_by_session(session_id, limit=limit, offset=offset)
    return [m.to_dict() for m in messages]


# ==================== 进化系统 API ====================

@router.get("/evolution/logs", response_model=List[EvolutionLogResponse])
async def list_evolution_logs(
    limit: int = 50,
    offset: int = 0
):
    """获取进化日志列表"""
    try:
        db = get_database()
        logs = get_evolution_logs(db, limit=limit, offset=offset)
        return logs
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/evolution/trigger", response_model=TriggerResponse)
async def trigger_evolution(
    data: TriggerEvolutionRequest
):
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


@router.get("/evolution/status", response_model=List[EvolutionStatusResponse])
async def get_evolution_status():
    """获取进化任务状态"""
    try:
        scheduler = get_scheduler()
        status = scheduler.get_task_status()
        return status
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
    memory_type: Optional[str] = None
    limit: int = 20


class MemorySaveRequest(BaseModel):
    content: str
    memory_type: str = "episodic"
    importance: int = 5
    tags: List[str] = []


class MemoryDeleteRequest(BaseModel):
    id: str


@router.get("/memory/search")
async def search_memory(
    query: str,
    limit: int = 20,
    type: Optional[str] = None
):
    """搜索记忆"""
    try:
        mm = get_memory_manager()
        results = mm.search_memories(query=query, memory_type=type, limit=limit)
        return results
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
            tags=data.tags
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
async def list_memories(
    page: int = 1,
    page_size: int = 20,
    type: Optional[str] = None
):
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
