"""用户反馈系统 HTTP 端点(Phase 1)。

- POST   /feedback/conversations                 创建会话(含首条消息)
- GET    /feedback/conversations                 列出会话
- GET    /feedback/conversations/{id}            会话详情(含消息)
- GET    /feedback/conversations/{id}/pending    尚未转发到管理员侧的消息
- POST   /feedback/conversations/{id}/messages   追加消息
- POST   /feedback/conversations/{id}/attachments 上传截图(raw bytes)
- PATCH  /feedback/conversations/{id}/status     更新会话状态
- POST   /feedback/messages/{id}/synced          标记消息已转发
- GET    /feedback/search                        按关键词搜索消息正文
- GET    /feedback/log-tail                      采集脱敏后的日志尾部

受 LocalAuthMiddleware 保护(仅监听 127.0.0.1 + SAGE_LOCAL_AUTH_TOKEN)。
<<<<<<< HEAD
设计见 docs/technical/111-feedback-relay-deployment.md §11.2。
=======
设计见 docs/technical/109-feedback-relay-deployment.md §11.2。
>>>>>>> origin/main

字段命名:snake_case, 与仓库其它 HTTP DTO (Todo / Session) 一致 —— 前端
经 invoke.ts 桥时 camelCase 请求体会被翻译成 snake_case, 响应保持原样返回,
因此前端类型定义也与本模块的 Pydantic 模型字段名对齐。
"""

from __future__ import annotations

import logging
import platform
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from backend.data.database import get_database
from backend.data.feedback_repo import (
    FeedbackConversation,
    FeedbackMessage,
    FeedbackRepo,
    FeedbackSearchHit,
)
from backend.services.feedback_log_tail import collect_log_tail
from backend.services.multimodal.media_store import MEDIA_ROOT, MediaKind, MediaStore

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/feedback", tags=["feedback"])

MAX_TITLE_CHARS = 200
MAX_BODY_CHARS = 20000
MAX_SEARCH_QUERY_CHARS = 200
MAX_ATTACHMENT_BYTES = 5 * 1024 * 1024
VALID_ROLES = ("user", "admin")
VALID_STATUSES = ("open", "resolved", "closed")
VALID_TAGS = ("bug", "feature", "other")


# ==================== Models ====================


class FeedbackMessageDto(BaseModel):
    id: str
    conversation_id: str
    role: str
    body: str
    media_ids: List[str] = []
    created_at: int
    synced_at: Optional[int] = None


class FeedbackConversationDto(BaseModel):
    id: str
    title: str
    status: str
    tag: str = "other"
    app_version: str
    os_info: str
    remote_ticket_id: Optional[str] = None
    remote_ticket_url: Optional[str] = None
    last_activity_at: int
    created_at: int
    updated_at: int


class ConversationDetailDto(BaseModel):
    conversation: FeedbackConversationDto
    messages: List[FeedbackMessageDto] = []


class CreateConversationRequest(BaseModel):
    id: Optional[str] = None
    title: str
    tag: str = "other"
    app_version: Optional[str] = None
    os_info: Optional[str] = None
    body: str = ""
    media_ids: List[str] = []


class AppendMessageRequest(BaseModel):
    id: Optional[str] = None
    role: str = "user"
    body: str
    media_ids: List[str] = []


class AppendMessageResponse(BaseModel):
    id: str
    conversation_id: str
    created_at: int
    received: bool = True


class AttachmentResponse(BaseModel):
    id: str
    conversation_id: str
    filename: str
    mime_type: str
    size_bytes: int


class UpdateStatusRequest(BaseModel):
    status: str


class LogTailResponse(BaseModel):
    text: str
    lines: List[str] = []


class MarkSyncedResponse(BaseModel):
    id: str
    synced_at: int


class FeedbackSearchHitDto(BaseModel):
    conversation_id: str
    conversation_title: str
    message_id: str
    role: str
    body: str
    created_at: int


# ==================== Helpers ====================


def _repo() -> FeedbackRepo:
    return FeedbackRepo(get_database().get_connection())


def _default_app_version() -> str:
    try:
        from backend import __version__  # type: ignore

        return str(__version__)
    except Exception:
        return "unknown"


def _default_os_info() -> str:
    return platform.platform()


def _to_conversation_dto(conv: FeedbackConversation) -> FeedbackConversationDto:
    return FeedbackConversationDto(
        id=conv.id,
        title=conv.title,
        status=conv.status,
        tag=conv.tag,
        app_version=conv.app_version,
        os_info=conv.os_info,
        remote_ticket_id=conv.remote_ticket_id,
        remote_ticket_url=conv.remote_ticket_url,
        last_activity_at=conv.last_activity_at,
        created_at=conv.created_at,
        updated_at=conv.updated_at,
    )


def _to_message_dto(msg: FeedbackMessage) -> FeedbackMessageDto:
    return FeedbackMessageDto(
        id=msg.id,
        conversation_id=msg.conversation_id,
        role=msg.role,
        body=msg.body,
        media_ids=list(msg.media_ids),
        created_at=msg.created_at,
        synced_at=msg.synced_at,
    )


def _to_search_hit_dto(hit: FeedbackSearchHit) -> FeedbackSearchHitDto:
    return FeedbackSearchHitDto(
        conversation_id=hit.conversation_id,
        conversation_title=hit.conversation_title,
        message_id=hit.message_id,
        role=hit.role,
        body=hit.body,
        created_at=hit.created_at,
    )


def _require_conversation(repo: FeedbackRepo, conversation_id: str) -> FeedbackConversation:
    conv = repo.get_conversation(conversation_id)
    if conv is None:
        raise HTTPException(status_code=404, detail="反馈会话不存在")
    return conv


# ==================== Routes ====================


@router.post("/conversations", response_model=FeedbackConversationDto)
def create_conversation(payload: CreateConversationRequest) -> FeedbackConversationDto:
    """创建反馈会话。带 id 时幂等 —— 已存在则直接返回原会话。"""
    title = payload.title.strip()
    if not title:
        raise HTTPException(status_code=422, detail="标题不能为空")
    if len(title) > MAX_TITLE_CHARS:
        raise HTTPException(status_code=422, detail=f"标题超过 {MAX_TITLE_CHARS} 字上限")
    body = payload.body.strip()
    if len(body) > MAX_BODY_CHARS:
        raise HTTPException(status_code=422, detail=f"正文超过 {MAX_BODY_CHARS} 字上限")
    tag = payload.tag.strip().lower()
    if tag not in VALID_TAGS:
        raise HTTPException(
            status_code=422, detail=f"tag 必须是 {'/'.join(VALID_TAGS)} 之一"
        )

    repo = _repo()
    if payload.id:
        existing = repo.get_conversation(payload.id)
        if existing is not None:
            return _to_conversation_dto(existing)

    conv = repo.create_conversation(
        id=payload.id,
        title=title,
        app_version=payload.app_version or _default_app_version(),
        os_info=payload.os_info or _default_os_info(),
        tag=tag,
    )
    if body or payload.media_ids:
        repo.add_message(
            conv.id,
            role="user",
            body=body,
            media_ids=list(payload.media_ids),
        )
        conv = repo.get_conversation(conv.id) or conv
    return _to_conversation_dto(conv)


@router.get("/conversations", response_model=List[FeedbackConversationDto])
def list_conversations(limit: int = 50) -> List[FeedbackConversationDto]:
    """列出最近的反馈会话(按最后活动时间降序)。"""
    limit = max(1, min(limit, 200))
    return [_to_conversation_dto(c) for c in _repo().list_conversations(limit=limit)]


@router.get("/search", response_model=List[FeedbackSearchHitDto])
def search_messages(q: str = "", limit: int = 50) -> List[FeedbackSearchHitDto]:
    """按关键词搜索消息正文(空查询返回空列表,不报错)。"""
    query = q.strip()
    if not query:
        return []
    if len(query) > MAX_SEARCH_QUERY_CHARS:
        raise HTTPException(
            status_code=422, detail=f"搜索词超过 {MAX_SEARCH_QUERY_CHARS} 字上限"
        )
    limit = max(1, min(limit, 200))
    return [_to_search_hit_dto(hit) for hit in _repo().search_messages(query, limit=limit)]


@router.get("/conversations/{conversation_id}", response_model=ConversationDetailDto)
def get_conversation(conversation_id: str) -> ConversationDetailDto:
    """会话详情 + 全部消息。"""
    repo = _repo()
    conv = _require_conversation(repo, conversation_id)
    messages = repo.list_messages(conversation_id)
    return ConversationDetailDto(
        conversation=_to_conversation_dto(conv),
        messages=[_to_message_dto(m) for m in messages],
    )


@router.get(
    "/conversations/{conversation_id}/pending",
    response_model=List[FeedbackMessageDto],
)
def list_pending_messages(conversation_id: str) -> List[FeedbackMessageDto]:
    """尚未转发到管理员侧的消息(outbox)。Electron FeedbackSyncer 定期消费此端点。"""
    repo = _repo()
    _require_conversation(repo, conversation_id)
    return [_to_message_dto(m) for m in repo.list_unsynced_messages(conversation_id)]


@router.post(
    "/conversations/{conversation_id}/messages",
    response_model=AppendMessageResponse,
)
def append_message(
    conversation_id: str, payload: AppendMessageRequest
) -> AppendMessageResponse:
    """追加一条消息(用户补充或中继回来的管理员回复)。"""
    if payload.role not in VALID_ROLES:
        raise HTTPException(status_code=422, detail="role 必须是 user 或 admin")
    body = payload.body.strip()
    if not body and not payload.media_ids:
        raise HTTPException(status_code=422, detail="消息内容不能为空")
    if len(body) > MAX_BODY_CHARS:
        raise HTTPException(status_code=422, detail=f"正文超过 {MAX_BODY_CHARS} 字上限")

    repo = _repo()
    _require_conversation(repo, conversation_id)
    msg = repo.add_message(
        conversation_id,
        role=payload.role,
        body=body,
        media_ids=list(payload.media_ids),
        id=payload.id,
    )
    return AppendMessageResponse(
        id=msg.id,
        conversation_id=msg.conversation_id,
        created_at=msg.created_at,
    )


@router.post(
    "/conversations/{conversation_id}/attachments",
    response_model=AttachmentResponse,
)
async def upload_attachment(conversation_id: str, request: Request) -> AttachmentResponse:
    """上传截图。请求体是原始二进制(Content-Type: image/png 等)。"""
    repo = _repo()
    conv = _require_conversation(repo, conversation_id)

    body = await request.body()
    if not body:
        raise HTTPException(status_code=422, detail="附件内容为空")
    if len(body) > MAX_ATTACHMENT_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"附件超过 {MAX_ATTACHMENT_BYTES // (1024 * 1024)}MB 上限",
        )

    content_type = request.headers.get("content-type") or "image/png"
    filename = request.headers.get("x-filename") or "screenshot.png"

    store = MediaStore(root=MEDIA_ROOT)
    ref = store.save(
        body,
        kind=MediaKind.IMAGE,
        source="feedback_upload",
        metadata={"conversation_id": conv.id, "content_type": content_type},
    )
    repo.add_attachment(
        conv.id,
        filename=filename,
        mime_type=ref.mime_type,
        size_bytes=ref.file_size,
        id=ref.id,
    )
    return AttachmentResponse(
        id=ref.id,
        conversation_id=conv.id,
        filename=filename,
        mime_type=ref.mime_type,
        size_bytes=ref.file_size,
    )


@router.patch(
    "/conversations/{conversation_id}/status", response_model=FeedbackConversationDto
)
def update_status(
    conversation_id: str, payload: UpdateStatusRequest
) -> FeedbackConversationDto:
    """更新会话状态(open / resolved / closed)。"""
    if payload.status not in VALID_STATUSES:
        raise HTTPException(status_code=422, detail="status 必须是 open/resolved/closed")
    repo = _repo()
    _require_conversation(repo, conversation_id)
    repo.update_conversation_status(conversation_id, payload.status)
    updated = repo.get_conversation(conversation_id)
    if updated is None:
        raise HTTPException(status_code=404, detail="反馈会话不存在")
    return _to_conversation_dto(updated)


@router.post("/messages/{message_id}/synced", response_model=MarkSyncedResponse)
def mark_message_synced(message_id: str) -> MarkSyncedResponse:
    """标记消息已成功转发到管理员侧。"""
    repo = _repo()
    ok = repo.mark_synced(message_id)
    if not ok:
        raise HTTPException(status_code=404, detail="反馈消息不存在")
    msg = repo.get_message(message_id)
    if msg is None:
        raise HTTPException(status_code=500, detail="内部错误:消息写入后无法读回")
    return MarkSyncedResponse(id=msg.id, synced_at=msg.synced_at or 0)


@router.get("/log-tail", response_model=LogTailResponse)
def get_log_tail(max_lines: int = 200) -> LogTailResponse:
    """采集最近的日志尾部(逐行脱敏),供用户附在反馈里。"""
    max_lines = max(1, min(max_lines, 500))
    text = collect_log_tail(max_lines=max_lines)
    return LogTailResponse(text=text, lines=text.splitlines() if text else [])
