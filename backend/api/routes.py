"""
API 路由定义
"""
from fastapi import APIRouter, HTTPException, Depends
from typing import List, Optional
from pydantic import BaseModel

from backend.data.session_repo import SessionRepository, Session
from backend.core.agent import SageAgent


router = APIRouter()


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


class MessageResponse(BaseModel):
    id: str
    session_id: str
    role: str
    content: str
    created_at: int
    model: Optional[str] = None
    tool_calls: Optional[str] = None


class ChatResponse(BaseModel):
    message: MessageResponse
    session: Optional[dict] = None


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
    agent: SageAgent = Depends(get_agent)
):
    """发送聊天消息"""
    try:
        result = await agent.chat(data.session_id, data.message)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


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
    # TODO: 实现消息获取
    return []
