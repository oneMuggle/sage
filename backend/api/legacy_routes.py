# ruff: noqa: UP006, UP007, UP035 — pydantic v1 + Python 3.8 兼容：
# pydantic v1 resolve_annotations 用 eval() 处理 forward refs，
# eval 在 Python 3.8 上无法解析 PEP 585 (list[X]) 和 PEP 604 (X | Y)，
# 所以本文件保留 typing.List/Optional/Union 写法
"""
API 路由定义
"""

from __future__ import annotations

import asyncio
from typing import List

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
from typing import Any, Dict, Optional, Union

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, StrictBool

from backend.api.chat_stream_registry import SENTINEL, StreamEntry, StreamRegistry
from backend.api.orch_routes import router as orch_routes_router
from backend.chat.executors import resolve_attachments
from backend.core.errors import LLMError
from backend.core.legacy.agent import SageAgent
from backend.data.database import get_database
from backend.data.session_repo import Message as DbMessage, MessageRepository, SessionRepository
from backend.memory import get_memory_manager
from backend.office.chat_refs import ChatOfficeRef, authorize_chat_office_request
from backend.office.workspace_errors import (
    WorkspaceDocumentNotFoundError,
    WorkspaceNotBoundError,
    WorkspacePathMismatchError,
    WorkspaceSessionNotFoundError,
)
from backend.orchestration.chat_dispatcher import _classify_orchestration_mode
from backend.orchestration.orch_settings import load_orch_settings
from backend.scheduler import get_evolution_logs, get_scheduler

logger = logging.getLogger(__name__)

router = APIRouter()


# §1.2 修复（PR #294）配套：全局 SQLite 串行化锁。
#
# Why: 34 个 `async def` handler 降级为 `def` 后，FastAPI 自动把它们 dispatch 到 anyio
# threadpool（默认 40 worker 线程）。`backend/data/database.py` 维护**单例**
# `sqlite3.Connection(check_same_thread=False)`，多线程并发访问同一连接会触发
# `cannot start a transaction within a transaction` 异常（实测，30 并发 session POST
# 即触发）。`busy_timeout=5000` 只能吸收 SQLITE_BUSY 锁冲突，不能吸收应用层事务嵌套错误。
#
# How: 用一个模块级 `threading.Lock` 串行化所有走 `_db._connection` 的写操作。锁
# 在 threadpool worker 线程内等待，**不阻塞事件循环**（事件循环的 SSE/chat handler
# 仍能持续响应）。这把"事件循环上串行跑 sync"语义平移到了"threadpool 上串行跑 sync"，
# 既修了 §1.2 阻塞问题，又避开单连接多线程冲突。
#
# Future: 计划在 PR B 把单连接拆成 thread-local connection pool（每 thread 一个
# sqlite3.Connection），那时可移除本锁。详见 `docs/plans/2026-08-09_*.md` §1.2。
import functools

# PR B §1.2 (CRITICAL fix): 共用 backend.data.database._SQLITE_LOCK,
# 而不是本模块私有的 threading.Lock。PR B 的 SqliteStorageAdapter._sync_X
# 在 to_thread worker 内获取同一把锁,两条路径才能在同一 sqlite3.Connection
# (check_same_thread=False) 上互斥,避免 "cannot start a transaction within
# a transaction"。
#
# 注意:with_db_lock 必须定义在本模块(而非 database.py)。FastAPI 在
# get_typed_signature 里用 ``call.__globals__`` 解析 `from __future__ import
# annotations` 产生的字符串注解(wrapper.__globals__ 是**定义装饰器的模块**
# 的 dict)。若 decorator 定义在 database.py,本文件 34 个带 body 模型的
# handler(ChatRequest 等)会报 PydanticUndefinedAnnotation。orch_routes.py
# 因此也保留同构的本地定义,共用同一把 _SQLITE_LOCK。
from backend.data.database import _SQLITE_LOCK


def with_db_lock(func):
    """装饰器：把 sync 函数包在全局 `_SQLITE_LOCK` 内,串行化 SQLite 访问。

    适用对象：34 个降级为 `def` 的 FastAPI handler —— 它们跑在 anyio threadpool,
    内部 `SessionRepository`/`MessageRepository` 等 sync 调用必须串行访问单连接。
    """

    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        with _SQLITE_LOCK:
            return func(*args, **kwargs)

    return wrapper


def _safe_log_field(value: object, max_length: int = 64) -> str:
    """Sanitize a user-controlled field for safe logging.

    - Strip newlines and control chars to prevent log injection
    - Truncate to max_length to prevent log spam
    """
    s = str(value)
    s = "".join(c for c in s if c.isprintable() or c == " ")
    return s[:max_length]


def _should_use_orchestrator(message: str) -> bool:
    """启发式分流：多步骤/复杂任务走编排器，简单消息走单 agent。

    判定规则 (满足任一即走 orchestrator):
    - 消息包含多步骤关键词 (对比/比较/总结并/然后/接着/分析/multi)
    - 消息长度 > 200 字

    Args:
        message: 用户消息

    Returns:
        True 表示应走 AgentOrchestrator, False 表示走单 SageAgent
    """
    keywords = ["对比", "比较", "总结", "然后", "接着", "分析", "multi"]
    if any(kw in message for kw in keywords):
        return True
    if len(message) > 200:
        return True
    return False


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
    workspace_path: Optional[str] = None
    api_key: Optional[str] = None

    api_url: Optional[str] = None

    model: Optional[str] = None

    max_context: Optional[int] = None

    temperature: Optional[float] = None

    # 透传字段:provider 让后端不再硬写,reasoning_effort/thinking_budget
    # 让上游 LLM 启用 thinking 输出(provider 决定哪种 key 会被接受)
    # - provider: openai / claude / gemini / deepseek / ollama / custom
    # - reasoning_effort: OpenAI o1/o3/5 + DeepSeek OpenAI 兼容代理
    # - thinking_budget: Gemini 2.5 OpenAI 兼容模式
    provider: Optional[str] = None

    reasoning_effort: Optional[str] = None

    thinking_budget: Optional[int] = None

    # Task 6 (M1-M2 chat-read): frontend 把 @mention 解析成
    # ``backend.office.chat_refs.ChatOfficeRef`` 列表,``chat_stream_create``
    # 在调 LLM 前同步授权. 空列表 = legacy 路径(attachment_resolver).
    office_refs: List[ChatOfficeRef] = Field(default_factory=list)

    # Multi-Agent Orchestration (spec 2026-08-11): 编排模式开关。
    # auto（默认）—— 轻量 LLM 二分类决定；force_multi / force_single ——
    # 用户斜杠命令 /orchestrate / /single 覆盖，跳过语义判定。
    # Optional: 兼容渲染进程 IPC payload 里显式 null(undefined ?? null 序列化的产物)。
    # Pydantic 默认值只在字段缺失时生效，显式 null 仍按类型校验 →
    # 不加 Optional 会被 422 拒绝。业务层 `data.orchestration_mode or "auto"` 已兜底。
    orchestration_mode: Optional[str] = "auto"

    # Wave 3 A10 (2026-08-14): resume 恢复流 —— plan_override 非空时跳过 LLM
    # 拆解，直接用存储计划建 dispatcher；run_id 复用 resume 返回的 new_run_id。
    plan_override: Optional[List[Dict[str, Any]]] = None
    run_id: Optional[str] = None


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


#: agent role 白名单（PATCH/POST 共用）。
_VALID_AGENT_ROLES = {
    "coordinator",
    "researcher",
    "coder",
    "memory_manager",
    "writer",
    "reviewer",
}


class AgentToggle(BaseModel):
    """PATCH /agents/{id}/toggle 请求体 (PR-5)。

    单字段 ``enabled`` 必填 — 缺失走 Pydantic 自动 422。专门用来对
    enable/disable 这一高频操作做语义化端点 (审计 + 未来权限),不
    与 PATCH /agents/{id} 重叠。

    注: 用 ``StrictBool`` 而非 ``bool`` — Pydantic v2 默认 lax 模式会把
    "yes"/"1"/1 等强转 True, 在 API 边界宁可 422 也不要静默转换。前端
    Type[Script 永远传真 bool, 严格模式不会误伤。
    """

    enabled: StrictBool


class AgentUpdate(BaseModel):
    """PATCH /agents/{id} 请求体 (PR-4)。

    所有字段可选 — 不传视为"该字段不更新"。role / max_iterations
    走 Pydantic 校验, 非法值 422 (由 FastAPI 自动处理)。
    """

    # 注: Pydantic 默认对 "model_" 前缀的字段名有保留命名空间保护.
    # 实际字段用 model_config_data (避开保留名), 路由层映射到 model_config.
    class Config:
        protected_namespaces = ()

    name: Optional[str] = None

    role: Union[str, None] = None  # 校验放在路由层 (依赖 Pydantic Literal 不直观)

    system_prompt: Optional[str] = None

    tools: Optional[List[str]] = None

    memory_access: Optional[List[str]] = None

    model_config_data: Union[dict, None] = (
        None  # 字段名避开 Pydantic 保留名, 路由层映射到 model_config
    )

    max_iterations: Optional[int] = None  # 路由层校验 1..50

    enabled: Optional[bool] = None

    description: Optional[str] = None


class AgentCreate(BaseModel):
    """POST /agents 请求体（US-4 角色可扩展）。

    id / name 必填；其余字段带默认值。
    ``model_config_data`` 字段名避开 Pydantic 保留名（同 AgentUpdate）。
    """

    model_config = {"protected_namespaces": ()}

    id: str = Field(min_length=1, max_length=64, pattern=r"^[a-zA-Z0-9_-]+$")
    name: str = Field(min_length=1, max_length=64)
    role: str = "general"
    system_prompt: str = ""
    tools: Optional[List[str]] = None
    memory_access: Optional[List[str]] = None
    model_config_data: Optional[dict] = None
    max_iterations: Optional[int] = None
    enabled: Optional[bool] = None
    description: Optional[str] = None


# ==================== 依赖注入 ====================


def get_session_repo() -> SessionRepository:
    return SessionRepository()


def get_agent() -> SageAgent:
    return SageAgent()


# ==================== 会话 API ====================


@router.post("/sessions", response_model=dict)
@with_db_lock
def create_session(data: SessionCreate, repo: SessionRepository = Depends(get_session_repo)):
    """创建新会话"""
    session = repo.create(title=data.title, parent_id=data.parent_id)
    return session.to_dict()


@router.get("/sessions", response_model=List[dict])
@with_db_lock
def list_sessions(
    limit: int = 100, offset: int = 0, repo: SessionRepository = Depends(get_session_repo)
):
    """获取会话列表"""
    sessions = repo.list(limit=limit, offset=offset)
    return [s.to_dict() for s in sessions]


@router.get("/sessions/{session_id}", response_model=dict)
@with_db_lock
def get_session(session_id: str, repo: SessionRepository = Depends(get_session_repo)):
    """获取单个会话"""
    session = repo.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="会话不存在")
    return session.to_dict()


@router.patch("/sessions/{session_id}", response_model=dict)
@with_db_lock
def update_session(
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
@with_db_lock
def delete_session(session_id: str, repo: SessionRepository = Depends(get_session_repo)):
    """删除会话"""
    if not repo.delete(session_id):
        raise HTTPException(status_code=404, detail="会话不存在")
    return {"status": "ok"}


# ==================== 消息 API ====================


@router.post("/messages/{message_id}/delete")
@with_db_lock
def delete_message(message_id: str):
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
@with_db_lock
def list_agents():
    """列出所有 agent (含 disabled), 按 id 排序。

    对应 Tauri command ``list_agents`` (PR-3)。
    """
    from backend.data.agent_repo import AgentRepository

    return AgentRepository().list_all()


@router.get("/agents/{agent_id}")
@with_db_lock
def get_agent_by_id(agent_id: str):
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
@with_db_lock
def update_agent(agent_id: str, data: AgentUpdate):
    """部分更新 agent (PR-4)。

    - 200 + 更新后完整 profile
    - 404 + 结构化 detail (id 不存在)
    - 422 (FastAPI 自动) — 字段类型 / role 白名单 / max_iterations 范围
    - PATCH 是 partial update: 缺省字段保留原值
    - 空 body: 视为 no-op, 返回当前 profile, updated_at 不动
    """
    from backend.data.agent_repo import AgentRepository

    # 字段级校验: role 白名单
    valid_roles = _VALID_AGENT_ROLES
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
    update_payload = data.dict(exclude_none=True)
    if "model_config_data" in update_payload:
        update_payload["model_config"] = update_payload.pop("model_config_data")

    repo.update(agent_id, update_payload)
    return repo.get(agent_id)


@router.patch("/agents/{agent_id}/toggle")
@with_db_lock
def toggle_agent(agent_id: str, data: AgentToggle):
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


@router.post("/agents")
@with_db_lock
def create_agent(data: AgentCreate):
    """创建自定义 agent（US-4）。

    - 200 + 完整 profile
    - 409 + 结构化 detail（id 已存在）
    - 422 — role 白名单 / max_iterations 范围
    """
    from backend.data.agent_repo import AgentRepository

    if data.role not in _VALID_AGENT_ROLES and data.role != "general":
        raise HTTPException(
            status_code=422,
            detail={
                "type": "invalid_role",
                "message": (
                    f"role must be one of {sorted(_VALID_AGENT_ROLES)} "
                    f"or 'general', got {data.role!r}"
                ),
            },
        )

    if data.max_iterations is not None and not (1 <= data.max_iterations <= 50):
        raise HTTPException(
            status_code=422,
            detail={
                "type": "invalid_max_iterations",
                "message": f"max_iterations must be in 1..50, got {data.max_iterations}",
            },
        )

    repo = AgentRepository()
    if repo.get(data.id) is not None:
        raise HTTPException(
            status_code=409,
            detail={
                "type": "agent_already_exists",
                "message": f"agent {data.id!r} already exists",
            },
        )

    payload = data.dict(exclude_none=True)
    if "model_config_data" in payload:
        payload["model_config"] = payload.pop("model_config_data")
    payload.setdefault("tools", [])
    payload.setdefault("memory_access", [])
    payload.setdefault("model_config", {})
    payload.setdefault("max_iterations", 10)
    payload.setdefault("enabled", True)
    payload.setdefault("description", "")

    repo.upsert(payload)
    return repo.get(data.id)


# ==================== 技能 API (PR-7) ====================

# 进程内单例缓存已搬到 ``backend.adapters.out.skill.inproc``（M2b 重构：
# 断开 tools -> api 的反向 import 链，修 import-linter 违规）。本模块只
# 保留一个 thin wrapper 委托到 ``inproc.get_singleton()``，保证 REST 路由
# 与 ``SkillTool`` 共享同一注册表状态（enabled / usage_count 等内存字段）。


def _get_skill_adapter():
    """委托到 ``inproc.get_singleton()``（M2b 重构）。

    返回的 adapter 与 ``backend.tools.skill_tool.SkillTool._resolve_adapter``
    共享同一缓存 — 即所有 REST 路由与 in-loop 工具调用看到同一份
    ``InprocSkillAdapter`` 实例（enabled / usage_count 一致）。
    """
    from backend.adapters.out.skill.inproc import get_singleton

    return get_singleton()


def _skill_to_dict(ext: dict, enabled: bool, usage_count: int) -> dict:
    """把扩展 SkillSpec dict + 路由层 enabled/usage_count 序列化为响应 dict。

    ``ext`` 来自 ``InprocSkillAdapter.list_skills_extended()``,
    含 ``source / body / base_dir / version`` 等字段 (SKILL.md 时填充, builtin 时不存在)。

    复制一份避免修改 adapter 返回的共享 dict (immutable-ish 风格)。
    """
    out = dict(ext)
    out["enabled"] = enabled
    out["usage_count"] = usage_count
    return out


@router.get("/skills")
@with_db_lock
def list_skills():
    """列出所有已注册技能 (含 disabled 与 usage_count + SKILL.md 扩展字段)。"""
    adapter = _get_skill_adapter()
    return [
        _skill_to_dict(ext, adapter.is_enabled(ext["name"]), adapter.usage_count(ext["name"]))
        for ext in adapter.list_skills_extended()
    ]


class SkillToggle(BaseModel):
    """``POST /skills/{name}/toggle`` 请求体。"""

    enabled: StrictBool


@router.post("/skills/{name}/toggle")
@with_db_lock
def toggle_skill(name: str, data: SkillToggle):
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
    # 返回完整 skill dict (与 list 接口一致) —— 用 list_skills_extended 拿带 source/body 的版本
    ext = next((e for e in adapter.list_skills_extended() if e["name"] == name), None)
    assert ext is not None  # set_enabled 已 guard
    return _skill_to_dict(ext, adapter.is_enabled(name), adapter.usage_count(name))


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


# ==================== M10: slash command 暴露 ====================


class SkillCommandRequest(BaseModel):
    """``POST /skills/command`` 请求体 (M10)。

    - command: slash command 名 (带或不带 ``/``,如 ``/review`` 或 ``review``)
    - args: 命令参数列表 (透传给 SkillMdSkill.execute_v2 params['args'])
    """

    command: str
    args: List[str] = []


@router.post("/skills/command")
async def execute_slash_command(data: SkillCommandRequest):
    """执行 slash command (M10)。

    - 200 + SkillResult (success / content / metadata / error)
      - success=True → content 是 SKILL.md body,供聊天层注入 system prompt
      - success=False → 内部执行失败(脚本异常等),前端按 success 字段判定
    - 404 + 结构化 detail — command 未注册 (无 user_invocable 技能匹配)
    - 422 (FastAPI 自动) — command 缺失或类型错

    设计: chat 层剥离 ``/`` 前缀后 POST 此端点;不需要再走 SkillRegistry.exists()
    (slash registry 本身就是 user_invocable 技能的子集,索引已构建完成)。
    """
    adapter = _get_skill_adapter()
    try:
        result = await adapter.execute_command(data.command, data.args)
    except LookupError as exc:
        # 命令未注册 → 404 (与 skill_not_found 语义一致)
        raise HTTPException(
            status_code=404,
            detail={"type": "command_not_found", "message": str(exc)},
        ) from exc
    return {
        "success": result.success,
        "content": result.content,
        "metadata": result.metadata,
        "error": result.error,
    }


@router.get("/skills/commands")
@with_db_lock
def list_slash_commands():
    """列出所有已注册的 slash command (M10)。

    用于前端自动补全 / chat 输入提示。
    返回命令名列表 (带 ``/`` 前缀,如 ``["/review", "/commit"]``)。
    """
    adapter = _get_skill_adapter()
    return {"commands": adapter.list_slash_commands()}


# ========== PR-A: Skills management - 物理删除 SKILL.md ==========


@router.post("/skills/{name}/delete")
@with_db_lock
def delete_skill(name: str):
    """物理删除一个 SKILL.md 技能 (用户主动管理, PR-A Task 3)。

    - 200 + ``{"deleted": true, "name": ..., "base_dir": ...}``
    - 400 + detail=str(exc): builtin 不可删 / name 非法 / base_dir 跑出
      SAGE_SKILLS_DIR
    - 404 + detail=str(exc): skill 不存在 (registry 或磁盘)
    - 500 + detail=str(exc): SAGE_SKILLS_DIR 未配置 / 其他文件系统错误
    """
    # 延迟导入避免循环 (legacy_routes → inproc → delete → registry → builtin)
    from backend.skills.skill_md.delete import (
        BuiltinSkillError,
        SkillMdNotFoundError,
    )

    adapter = _get_skill_adapter()
    try:
        result = adapter.delete_skill_md(name)
    except BuiltinSkillError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except SkillMdNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        # name 非法 / base_dir 跑出 SAGE_SKILLS_DIR
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        # SAGE_SKILLS_DIR 未配置 / 其他 fs 错误 — 路由层转 500
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return result


# ========== PR-C: Skills load-new (rescan + import) ==========


@router.post("/skills/rescan")
@with_db_lock
def rescan_skills():
    """重扫 SAGE_SKILLS_DIR / ~/.sage/skills / ./skills, 增量加载新 SKILL.md。

    - 200 + ``{"loaded": [{"name", "source", "path"}], "skipped": [...], "total_loaded": int}``
    - 不抛 4xx/5xx (内部失败 → 500 via FastAPI 默认, 但 adapter 层已 try/except)
    """
    adapter = _get_skill_adapter()
    return adapter.rescan_skill_mds()


@router.post("/skills/import")
async def import_skills(files: List[UploadFile] = File(default=[])):
    """导入 SKILL.md 文件 (multipart)。

    - 200 + ``{"imported": [{"name", "path"}], "skipped": [{"name", "reason"}]}``
    - 400 + detail: multipart 没 files (空列表)
    - 500 + detail: skills_dir 无法创建 (NoSkillsDirError)

    partial success 策略: 即使部分文件失败, HTTP 仍 200, 在 skipped 数组中报告。
    """
    if not files:
        raise HTTPException(
            status_code=400,
            detail={"type": "invalid_request", "message": "no files provided"},
        )

    from backend.skills.skill_md.exceptions import NoSkillsDirError

    adapter = _get_skill_adapter()
    try:
        result = await adapter.import_skill_mds(files)
    except NoSkillsDirError as exc:
        raise HTTPException(
            status_code=500,
            detail={"type": "no_skills_dir", "message": str(exc)},
        ) from exc

    return result


# ==================== Settings & Preferences API ====================
#
# 这些端点在 hex_routes 中也有定义。legacy 模式下 hex_routes 不注册，
# 但 Electron 前端需要 /settings 和 /preferences/{key} 来加载配置，
# 因此在 legacy_routes 中也提供，确保两种 API_MODE 下都能工作。


class LegacySettingsRequest(BaseModel):
    """PUT /settings 请求体（legacy 路径）。所有字段可选。"""

    class Config:
        extra = "allow"

    api_base_url: Optional[str] = None

    api_key: Optional[str] = None  # noqa: S105

    model: Optional[str] = None


class LegacySettingsResponse(BaseModel):
    """PUT /settings 响应体。"""

    status: str = "ok"
    changed_fields: List[str] = []


class LegacyPreferenceItem(BaseModel):
    """GET/PUT /preferences/{key} 请求/响应体。"""

    value: Optional[str] = None

    value_type: str = "string"
    category: str = "general"


@router.get("/settings")
@with_db_lock
def legacy_get_settings() -> Optional[dict]:
    """读取持久化的 settings；不存在返回 null。

    翻译历史 snake_case 残留到 camelCase 返回，与 AppSettings 类型对齐。
    JSON 损坏 / 顶层非 dict (list / scalar) → null fallback，不抛 500，与 hex GET 对齐。
    """
    from backend.data.settings_canonicalizer import (
        detect_legacy_snake_pollution,
        to_camel,
    )
    from backend.data.settings_repo import SettingsRepository

    repo = SettingsRepository()
    try:
        raw = repo.get_json("app_settings")
    except (ValueError, TypeError):
        logger.warning("[LEGACY] /settings: corrupted app_settings JSON, returning null")
        return None
    if raw is None:
        return None
    if not isinstance(raw, dict):
        # get_json 可返回任意合法 JSON; app_settings 必须是 dict; 与 hex GET 对齐。
        logger.warning("[LEGACY] /settings: top-level non-dict JSON, returning null")
        return None
    detect_legacy_snake_pollution(raw)
    return to_camel(raw)


@router.put("/settings", response_model=LegacySettingsResponse)
@with_db_lock
def legacy_update_settings(req: LegacySettingsRequest) -> LegacySettingsResponse:
    """持久化 settings 到 preferences 表。

    v3.1 修复：合并而非覆盖。
    LegacySettingsRequest 只有 api_base_url/api_key/model 三个字段，
    如果直接替换，会丢失 endpoints、model_selections 等其他数据。
    修复策略：先读现有 settings，再把请求字段 merge 进去。

    Task 2 (settings-schema-canonicalization):
    - 整树翻译到 camelCase (to_camel)
    - 白名单校验 (validate_settings_shape) 拒绝白名单外字段 → 400
    """
    from backend.data.settings_canonicalizer import (
        strip_unknown_fields,
        to_camel,
        validate_settings_shape,
    )
    from backend.data.settings_repo import SettingsRepository

    repo = SettingsRepository()
    try:
        existing = repo.get_json("app_settings") or {}
    except (ValueError, TypeError):
        # DB 行 JSON 损坏 → 当空树处理, 避免 500 阻断合法的 PUT
        existing = {}
    if not isinstance(existing, dict):
        # existing 是 list/scalar (脏数据) → 用空树, 不阻断合法 PUT; 与 hex PUT 对齐.
        existing = {}

    # LegacySettingsRequest 是 extra="allow", dict(exclude_none=True) 会包含所有 set 字段
    # (含 extras, 如 streaming/foo/endpoints) — 这是设计: 旧客户端 PUT schema 之外字段不丢。
    #
    # win7 Note: Pydantic v1 不识 ``model_dump()``, 用 ``dict()`` 拿已 set 的字段;
    # 等价语义 (与 v2 model_dump(exclude_none=True) 行为一致)。
    payload = req.dict(exclude_none=True)

    # 剥离 legacy compatibility 3 字段: api_base_url / api_key / model.
    # 这 3 字段不进 DB (与 hex PUT 对齐, 见 eebbedd), 仅用于审计和 changed_fields.
    # 原因: 这 3 个 snake 字段通过 to_camel 翻译后 (apiKey) 或原样保留 (api_base_url/model)
    # 都不在 LEGAL_TOP_KEYS, 会触发 validate_settings_shape 400, 但它们是合法 legacy schema 字段.
    legacy_compat_fields = {"api_base_url", "api_key", "model"}
    legacy_compat_payload = {k: payload.pop(k) for k in list(payload) if k in legacy_compat_fields}

    # existing 里的历史残留字段（compactMode / proxyMode 等前端已删）会让
    # validate_settings_shape 对整棵合并树报 400。只剥离 existing 侧的残留，
    # payload 侧的未知字段仍原样保留并触发 400（与 hex PUT 对齐）。
    camel_existing = strip_unknown_fields(to_camel(existing))
    camel_merged = {**camel_existing, **to_camel(payload)}
    try:
        validate_settings_shape(camel_merged)
    except ValueError as exc:
        logger.warning(f"[LEGACY] /settings rejected unknown field: {exc}")
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    repo.set_json("app_settings", camel_merged, category="general")
    changed_fields = [k for k in payload if k != "api_key"]
    if "api_key" in payload:
        changed_fields.append("api_key")
    # 同时把 legacy 兼容字段记进 changed_fields (审计可见), 即使不进 DB
    changed_fields.extend(k for k in legacy_compat_payload if k not in changed_fields)
    logger.info(f"[LEGACY] /settings updated: changed={changed_fields}")
    return LegacySettingsResponse(status="ok", changed_fields=changed_fields)


@router.get("/preferences/{key}", response_model=LegacyPreferenceItem)
@with_db_lock
def legacy_get_preference(key: str) -> LegacyPreferenceItem:
    """通用 KV 读取（白名单限定 key）。"""
    from backend.data.settings_repo import SettingsRepository

    if key not in SettingsRepository.KEYS:
        raise HTTPException(status_code=400, detail=f"key {key!r} not in whitelist")
    val = SettingsRepository().get(key)
    return LegacyPreferenceItem(value=val)


@router.put("/preferences/{key}", response_model=LegacyPreferenceItem)
@with_db_lock
def legacy_put_preference(key: str, item: LegacyPreferenceItem) -> LegacyPreferenceItem:
    """通用 KV 写入（白名单限定 key）。"""
    from backend.data.settings_repo import SettingsRepository

    if key not in SettingsRepository.KEYS:
        raise HTTPException(status_code=400, detail=f"key {key!r} not in whitelist")
    if item.value is not None:
        SettingsRepository().set(
            key, item.value, value_type=item.value_type, category=item.category
        )
    return item


# ==================== 聊天 API ====================


@router.post("/chat", response_model=ChatResponse)
async def chat(
    data: ChatRequest,
    request: Request,
):
    """发送聊天消息。

    阶段 2: 根据消息复杂度分流 — 简单消息走单 SageAgent, 复杂消息走 AgentOrchestrator。
    分流逻辑由 _should_use_orchestrator() 决定。

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

        # 阶段 2: 分流 — 复杂消息走 orchestrator, 简单消息走单 agent
        if _should_use_orchestrator(data.message):
            logger.info(f"[REQ {request_id}] /chat routing through AgentOrchestrator")
            from backend.core.legacy.llm_client import LLMClient, LLMConfig
            from backend.core.legacy.orchestrator import AgentOrchestrator

            orch_llm_client = LLMClient(LLMConfig(**llm_config)) if llm_config else None
            orchestrator = AgentOrchestrator(llm_client=orch_llm_client)
            orch_result = await orchestrator.process_request(
                session_id=data.session_id,
                user_message=data.message,
            )
            # 适配 orchestrator 返回格式到 ChatResponse 形态
            assistant_now = int(time.time() * 1000)
            result = {
                "message": {
                    "id": str(uuid.uuid4()),
                    "session_id": data.session_id,
                    "role": "assistant",
                    "content": orch_result.get("response", ""),
                    "created_at": assistant_now,
                    "model": llm_config.get("model") if llm_config else "local",
                },
                "session": None,  # orchestrator 暂不更新 session (后续迭代)
            }
            # 持久化 assistant 消息
            try:
                MessageRepository().save(
                    DbMessage(
                        id=result["message"]["id"],
                        session_id=data.session_id,
                        role="assistant",
                        content=result["message"]["content"],
                        created_at=assistant_now,
                        model=result["message"]["model"],
                    )
                )
            except Exception as db_err:
                logger.warning(f"[REQ {request_id}] orchestrator 助手消息持久化失败: {db_err}")
        else:
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

    # Task 6 (M1-M2): 同步授权 ChatOfficeRef. 这一步必须在
    # ``registry.create`` 之前完成 — 一旦 stream id 进入注册表,
    # 失败路径就必须显式清理才能避免孤儿. 把授权放到 producer 启动
    # 之前还有一个好处:授权失败时既不消耗 stream slot,也不浪费 LLM token.
    # 错误映射见 ``backend.office.workspace_errors`` 模块注释.
    try:
        db = get_database()
        _auth_conn = db.get_connection()
        _auth_result = authorize_chat_office_request(
            _auth_conn,
            data.session_id,
            data.workspace_path,
            data.office_refs,
        )
    except WorkspacePathMismatchError as exc:
        logger.warning(
            f"[REQ {request_id}] /chat/stream office-ref path mismatch: {exc.safe_message}"
        )
        raise HTTPException(
            status_code=400,
            detail={
                "type": exc.code,
                "message": exc.safe_message,
            },
        )
    except WorkspaceNotBoundError as exc:
        logger.warning(f"[REQ {request_id}] /chat/stream office-ref not bound: {exc.safe_message}")
        raise HTTPException(
            status_code=403,
            detail={
                "type": exc.code,
                "message": exc.safe_message,
            },
        )
    except WorkspaceSessionNotFoundError as exc:
        logger.warning(
            f"[REQ {request_id}] /chat/stream office-ref session not found: {exc.safe_message}"
        )
        raise HTTPException(
            status_code=404,
            detail={
                "type": exc.code,
                "message": exc.safe_message,
            },
        )
    except WorkspaceDocumentNotFoundError as exc:
        logger.warning(
            f"[REQ {request_id}] /chat/stream office-ref doc not found: {exc.safe_message}"
        )
        raise HTTPException(
            status_code=404,
            detail={
                "type": exc.code,
                "message": exc.safe_message,
            },
        )

    registry: StreamRegistry = request.app.state.streams

    async def producer(entry: StreamEntry) -> None:
        """后台跑 agent.run_loop,事件入 entry.queue。

        这里把 AgentEvent.to_dict() 在入队时序列化,避免对象跨 task 边界泄漏
        内部状态(detached Pydantic / cyclic ref 等)。
        """
        # Task 9 (M1-M2): build a ToolExecutionContext from the captured
        # authorization so Office tools can read the session's binding.
        # set/reset around ``agent.run_loop`` via try/finally so the
        # ContextVar never leaks across producer invocations.
        from backend.tools.context import (
            ToolExecutionContext,
            reset_tool_context,
            set_tool_context,
        )

        _tool_ctx_token = None
        if _auth_result is not None:
            _tool_ctx = ToolExecutionContext(
                session_id=_auth_result.session_id,
                stream_id=stream_id,
                binding_generation=_auth_result.binding_generation,
                office_doc_scope=_auth_result.office_doc_scope,
            )
        else:
            # F2 (2026-08-12): 普通聊天（无 office 授权）也设置上下文 —— 否则
            # write_file 等工具的 artifact 记录会因 current_tool_context() 为
            # None 静默早退，产物无法在 Artifacts 面板展示。binding_generation
            # = 0 表示无 workspace 绑定；office 工具不在普通聊天 profile 白名单
            # （primary/researcher/coder/memory_manager/writer 均无）。
            _tool_ctx = ToolExecutionContext(
                session_id=data.session_id,
                stream_id=stream_id,
                binding_generation=0,
                office_doc_scope=frozenset(),
            )
        _tool_ctx_token = set_tool_context(_tool_ctx)
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

            # Build system prompt with optional diagram tool guidance
            from backend.agents.profiles import build_system_base

            system_content = build_system_base()

            # ===== Multi-Agent Orchestration (spec 2026-08-11) =====
            # tool-toggle 门: 语义判定（独立轻量 LLM 二分类）决定 mode。
            # single → 不注册 dispatch_subagents 工具、不跑 decompose_request
            #          （简单任务结构上无法被过度拆解 — 硬约束 2）
            # multi  → 复用 Planner 预规划 + conductor 经 dispatch 工具执行
            #          （复杂任务必出 task_plan + 必注册工具 — 硬约束 1）
            from backend.orchestration.llm_factory import (
                build_llm_client_from_settings,
            )

            # A10 (2026-08-14): plan_override 非空 → 视为 force_multi，跳过语义判定。
            if data.plan_override:
                mode = "multi"
            else:
                try:
                    mode = await _classify_orchestration_mode(
                        data.message,
                        data.orchestration_mode or "auto",
                        llm_client=build_llm_client_from_settings(),
                    )
                except Exception as exc:  # noqa: BLE001 — 编排判定失败必须降级 single
                    logger.warning("编排语义判定失败，降级 single: %s", exc)
                    mode = "single"
            run_id: Optional[str] = None
            if mode == "multi":
                from backend.orchestration.chat_dispatcher import (
                    _ACTIVE_DISPATCHERS,
                    ChatDispatcher,
                )
                from backend.orchestration.planner import Planner
                from backend.orchestration.task_registry import TaskRegistry
                from backend.orchestration.team_registry import TeamRegistry
                from backend.tools.subagent_tool import DispatchSubagentsTool

                if data.plan_override:
                    # A10 (2026-08-14): override 路径 —— items 自带 task_id，
                    # 直接透传，不重枚举；run_id 复用 resume 返回的 new_run_id。
                    plan_tasks = data.plan_override
                    run_id = data.run_id or f"orch-{uuid.uuid4()}"
                else:
                    # P2-8 (2026-08-14): orchestration_mode=template:<id> → 确定性模板拆解。
                    orchestration_mode = data.orchestration_mode or "auto"
                    template_id = (
                        orchestration_mode.split(":", 1)[1]
                        if orchestration_mode.startswith("template:")
                        else None
                    )
                    try:
                        if template_id is not None:
                            plan = await Planner(
                                task_registry=TaskRegistry(),
                                team_registry=TeamRegistry(),
                                llm_client=build_llm_client_from_settings(),
                            ).decompose_from_template(template_id, data.message)
                        else:
                            plan = await Planner(
                                task_registry=TaskRegistry(),
                                team_registry=TeamRegistry(),
                                llm_client=build_llm_client_from_settings(),
                            ).decompose_request(data.message)
                        plan_tasks = list(plan.tasks if plan else [])
                    except Exception as exc:  # noqa: BLE001 — 模板/规划失败降级 single
                        if template_id is not None:
                            logger.warning(
                                "编排模板 %s 拆解失败，降级 single: %s", template_id, exc
                            )
                        else:
                            logger.warning("编排规划失败，降级 single: %s", exc)
                        mode = "single"
                        plan_tasks = []
                    run_id = f"orch-{uuid.uuid4()}"
                if len(plan_tasks) <= 1 and not data.plan_override:
                    # LLM 没拆开（或降级单任务）→ 视为没开编排；
                    # override 单任务仍保持 multi（恢复流尊重用户指定计划）。
                    mode = "single"
                if mode == "multi":
                    # 归一为 {task_id, agent_id, goal, depends_on} 列表 —— 下游
                    # plan_block / init / task_plan 事件同构。override 路径透传
                    # 自带 task_id；decompose 路径从 Task 对象重新编号 t1..tN。
                    plan_items: List[Dict[str, Any]]
                    if data.plan_override:
                        plan_items = [
                            {
                                "task_id": str(it["task_id"]),
                                "agent_id": str(it.get("agent_id", "primary")),
                                "goal": str(it.get("goal", "")),
                                "depends_on": list(it.get("depends_on") or []),
                            }
                            for it in data.plan_override
                        ]
                    else:
                        plan_items = [
                            {
                                "task_id": f"t{i}",
                                "agent_id": t.parameters.get("agent_hint", "primary"),
                                "goal": t.description or t.name,
                                "depends_on": list(t.blocked_by),
                            }
                            for i, t in enumerate(plan_tasks, 1)
                        ]
                    dispatcher = ChatDispatcher(
                        stream_id=stream_id,
                        entry_queue=entry.queue,
                        run_id=run_id,
                        llm_config=llm_config,
                        total_tasks=len(plan_items),
                        settings=load_orch_settings(),
                    )
                    # P2-9 (2026-08-14): 进程内注册表登记 —— 长连接期间 run 级
                    # cancel 端点能定位到本 dispatcher 并置位取消事件。
                    _ACTIVE_DISPATCHERS[run_id] = dispatcher
                    agent.tool_registry.register(DispatchSubagentsTool(dispatcher))
                    if (
                        agent.profile is not None
                        and agent.profile.get("tools") is not None
                    ):
                        agent.profile["tools"].append("dispatch_subagents")
                    # 计划块注入 system prompt —— conductor 依据计划调用工具
                    # 注: system_content 已在插入点之前由 build_system_base()
                    # 赋值（L1598），这里只追加计划块，不再重新赋值（否则覆盖）。
                    plan_block = "\n".join(
                        f"- {i}. [{it['agent_id']}] {it['goal']}"
                        for i, it in enumerate(plan_items, 1)
                    )
                    system_content += (
                        "\n\n以下为已确认的任务计划，请调用 dispatch_subagents "
                        "工具并行执行这些子任务（可合并/调整）。不要复述计划，直接执行。\n"
                        + plan_block
                        # 进度可视化 P0-2 后置 (2026-08-12): 强化"必须全量执行完
                        # 才汇总"约束。dispatch_subagents 每次调用可能只派发部分
                        # 子任务（分批/合并），若聚合头只反映"本批已收到 X/X"，
                        # LLM 可能误以为全部完成而提前总结。这里显式给出总数 N，
                        # 要求必须等到 N 个全部有结果才输出最终汇总。
                        + "\n\n必须执行完计划中的全部"
                        + str(len(plan_items))
                        + " 个子任务，等到所有子任务都返回结果后，才能输出最终汇总。"
                        "若本次 dispatch 只执行了部分子任务，请继续调用工具执行剩余任务，"
                        "不要提前给出结论。"
                    )
                    # 计划先行：子 agent 跑之前先推 task_plan（可展示、可取消）
                    # Wave 2 P1-4: 首次 dispatch 前把 run + plan 落库,供 resume 端点重建。
                    # 失败降级（logger.warning）,绝不阻塞聊天。
                    # A10: reasoning 捕获 —— override 路径 plan 未定义 → 常量
                    # "plan_override"；decompose 路径 plan.reasoning（可为空串）。
                    # 避免 override 路径直接引用未定义的 plan 抛 NameError。
                    reasoning = (
                        "plan_override"
                        if data.plan_override
                        else (plan.reasoning if plan else "")
                    )
                    try:
                        if dispatcher is not None and hasattr(dispatcher, "init_orch_run"):
                            dispatcher.init_orch_run(
                                session_id=data.session_id,
                                plan_json=json.dumps(
                                    {"tasks": plan_items, "reasoning": reasoning},
                                    ensure_ascii=False,
                                ),
                                # Wave 3 A9: resume 恢复流逐字重发原始请求。
                                original_request=data.message,
                            )
                    except Exception as exc:  # noqa: BLE001 — 降级铁律
                        logger.warning("dispatcher.init_orch_run 失败: %s", exc)
                    await entry.queue.put(
                        {
                            "state": "task_plan",
                            "run_id": run_id,
                            "plan": plan_items,
                        }
                    )
                    # 进度可视化 P0-2 (2026-08-12): task_plan 之后立即推
                    # 一次 task_progress 初始化事件,前端 taskBoard 在子
                    # agent 跑之前就能拿到 total,UI 可立即渲染"已拆解为 N
                    # 个子任务,等待结果中…"。后续 5 元组由 reducer 从
                    # task_status 实时聚合。
                    await entry.queue.put(
                        {
                            "state": "task_progress",
                            "run_id": run_id,
                            "total": len(plan_items),
                            "done": 0,
                            "running": 0,
                            "queued": len(plan_items),
                            "failed": 0,
                        }
                    )
            try:
                from backend.core.diagram_prompt import (
                    DIAGRAM_TOOL_PROMPT,
                    registry_has_drawio_tool,
                )

                # Check if any drawio MCP tools are registered. Prefix
                # scan (mcp__drawio__*) — M3 renamed tools to
                # mcp__<server>__<tool>, and a fixed-name exists() check
                # would silently die on the next server-side rename.
                _registry = getattr(agent, "tool_registry", None)
                if _registry and registry_has_drawio_tool(_registry):
                    system_content += DIAGRAM_TOOL_PROMPT
            except Exception:
                pass  # Graceful fallback if diagram module unavailable

            attachment_block = await resolve_attachments(
                data.message, data.workspace_path or ""
            )
            messages = [{"role": "system", "content": system_content}]
            if attachment_block:
                messages.append(
                    {
                        "role": "system",
                        "content": (
                            "The user has referenced the following attached documents. "
                            "Treat them as primary context for the user's request.\n\n"
                            f"{attachment_block}"
                        ),
                    }
                )
            messages.append({"role": "user", "content": data.message})
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

            done_content: Optional[str] = None

            done_reasoning: Optional[str] = None

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
                elif evt.state.value == "reasoning" and evt.reasoning:
                    # PR-7b: 累积 reasoning 事件,持久化时一起写入 DB
                    if done_reasoning is None:
                        done_reasoning = evt.reasoning
                    else:
                        done_reasoning += evt.reasoning
                    # 流式输出 reasoning: 拆成小块逐个入队,模拟逐字显示效果
                    reasoning = evt.reasoning
                    for i in range(0, len(reasoning), _STREAMING_CHUNK_SIZE):
                        delta = reasoning[i : i + _STREAMING_CHUNK_SIZE]
                        await entry.queue.put(
                            {
                                "state": "reasoning_delta",
                                "iteration": evt.iteration,
                                "reasoning": delta,
                                "agent_id": evt.agent_id,
                            }
                        )
                        await asyncio.sleep(_STREAMING_CHUNK_DELAY_S)
                    # 最终 reasoning 事件携带累积全量 (而非单次 evt.reasoning)。
                    # 这样: 持久化、最终事件、前端累积 三者 reasoning 文本一致,
                    # 不依赖前端每个 delta 都没丢。
                    final_reasoning_event = evt.to_dict()
                    final_reasoning_event["reasoning"] = done_reasoning
                    await entry.queue.put(final_reasoning_event)
                else:
                    await entry.queue.put(evt.to_dict())

            # run_loop 正常结束 (DONE) → 持久化 assistant + 更新 session。
            # LLMError 走 except 分支,此块不执行 (无 assistant 可保存)。
            if done_content:
                assistant_now = int(time.time() * 1000)
                assistant_message_id: Optional[str] = None
                try:
                    saved = message_repo.save(
                        DbMessage(
                            id=str(uuid.uuid4()),
                            session_id=data.session_id,
                            role="assistant",
                            content=done_content,
                            reasoning_content=done_reasoning,
                            created_at=assistant_now,
                            model=(llm_config.get("model") if llm_config else "local"),
                        )
                    )
                    assistant_message_id = getattr(saved, "id", None)
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
                # Important-1 (final review) — 生产聊天路径驱动生命周期:
                # 让 legacy /chat/stream (renderer 唯一聊天命令) 也触发
                # on_turn_complete → 提取 + 持久化 + memory_written → SSE
                # /memory/events → 前端实时 toast/prepend。source_message_id
                # 用真实持久化的 assistant 消息 id,保证 MemoryCard
                # click-to-trace 命中 Chat 的 data-turn-id。auto_memory gate
                # 在 lifecycle 内部处理 — 该开关从此对生产路径生效。
                # 全程 try/except — 记忆系统故障绝不打断聊天流。
                lifecycle = getattr(request.app.state, "lifecycle", None)
                if lifecycle is not None:
                    try:
                        await lifecycle.on_turn_complete(
                            data.session_id,
                            [
                                {"role": "user", "content": data.message},
                                {"role": "assistant", "content": done_content},
                            ],
                            source_message_id=assistant_message_id,
                        )
                    except Exception as exc:
                        logger.warning(
                            f"[REQ {request_id}] lifecycle on_turn_complete failed: {exc}"
                        )
        except LLMError as e:
            logger.warning(
                f"[REQ {request_id}] /chat/stream LLM error: "
                f"type={e.type.value}, message={e.message}"
            )
            await entry.queue.put({"error": e.to_dict(), "state": "failed"})
        finally:
            # P2-9 (2026-08-14): 长连接结束注销注册表条目（run 级 cancel 不再命中）。
            # run_id 为 None（single 路径）时跳过 —— 从未注册过。
            if run_id:
                _ACTIVE_DISPATCHERS.pop(run_id, None)
            # Task 9 (M1-M2): always reset the tool context so the
            # ContextVar never leaks into the next producer invocation.
            if _tool_ctx_token is not None:
                reset_tool_context(_tool_ctx_token)

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
@with_db_lock
def interrupt(agent: SageAgent = Depends(get_agent)):
    """中断 Agent"""
    agent.interrupt()
    return {"status": "ok"}


# ==================== 消息 API ====================


@router.get("/sessions/{session_id}/messages", response_model=List[dict])
@with_db_lock
def get_messages(session_id: str, limit: int = 100, offset: int = 0):
    """获取会话消息"""
    repo = MessageRepository()
    messages = repo.get_by_session(session_id, limit=limit, offset=offset)
    return [m.to_dict() for m in messages]


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


@router.post("/evolution/trigger", response_model=TriggerResponse)
@with_db_lock
def trigger_evolution(data: TriggerEvolutionRequest):
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
@with_db_lock
def get_evolution_status():
    """获取进化任务状态"""
    try:
        scheduler = get_scheduler()
        return scheduler.get_task_status()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ==================== 记忆 API ====================

# get_memory_manager 从 backend.memory 导入（全局单例）


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
    id: Optional[str] = None
    # Gap E (Task 5): the renderer bridge (T1) sends { memory_id } — the
    # preload's `delete(args: { memory_id })` passes it straight through.
    # Accept both spellings so the Memory page delete works end-to-end.
    memory_id: Optional[str] = None

    def resolve_id(self) -> Optional[str]:
        """优先 memory_id（渲染器桥），兼容 legacy { id }。"""
        if self.memory_id and self.id and self.memory_id != self.id:
            raise HTTPException(status_code=422, detail="memory id mismatch")
        return self.memory_id or self.id


@router.get("/memory/search")
@with_db_lock
def search_memory(query: str, limit: int = 20, type: Optional[str] = None):
    """搜索记忆"""
    try:
        mm = get_memory_manager()
        return mm.search_memories(query=query, memory_type=type, limit=limit)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/memory/save")
@with_db_lock
def save_memory(data: MemorySaveRequest):
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
@with_db_lock
def delete_memory(data: MemoryDeleteRequest):
    """删除记忆"""
    try:
        mm = get_memory_manager()
        target_id = data.resolve_id()
        if not target_id:
            raise HTTPException(status_code=422, detail="memory id required")
        # 尝试从所有类型中删除
        for mtype in ["episodic", "semantic"]:
            if mm.delete_memory(target_id, mtype):
                return {"status": "ok"}
        raise HTTPException(status_code=404, detail="记忆不存在")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/memory/list")
@with_db_lock
def list_memories(page: int = 1, page_size: int = 20, type: Optional[str] = None):
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


# ==================== 记忆可追溯性 API (Gap E / Task 5) ====================


def _get_memory_port(request: Request):
    """返回 MemoryAdapter（MemoryPort 实现）。

    生产路径：``main.py`` lifespan 把 adapter 挂在 ``app.state.memory_port``。
    测试路径（不走 lifespan）：惰性构造一个绑定当前 MemoryManager 的
    adapter —— conftest 已把 MemoryManager 重置到临时 DB，因此查询
    打到测试库。
    """
    port = getattr(request.app.state, "memory_port", None)
    if port is not None:
        return port
    from backend.adapters.out.memory.adapter import MemoryAdapter

    return MemoryAdapter(get_memory_manager())


@router.get("/memory/by-turn/{turn_id}")
async def get_memories_by_turn(turn_id: str, request: Request):
    """按来源 turn 查询记忆（可追溯性：从记忆点击跳回产生它的轮次）。"""
    memory_port = _get_memory_port(request)
    memories = await memory_port.find_by_turn(turn_id)
    return {"memories": list(memories)}


@router.get("/memory/profile")
async def get_user_profile(request: Request):
    """用户档案聚合：偏好（importance>=7）+ 决策 + 项目事实。"""
    memory_port = _get_memory_port(request)
    prefs = await memory_port.find_by_category("user_pref", limit=50)
    decisions = await memory_port.find_by_category("decision", limit=20)
    facts = await memory_port.find_by_category("project_fact", limit=50)
    return {
        "preferences": [m for m in prefs if m.get("importance", 0) >= 7],
        "decisions": list(decisions),
        "facts": list(facts),
        "total_count": len(prefs) + len(decisions) + len(facts),
    }


@router.get("/memory/summary/{session_id}")
async def get_session_summary(session_id: str, request: Request):
    """按会话聚合 task_summary 记忆（会话摘要 Tab）。"""
    memory_port = _get_memory_port(request)
    summaries = await memory_port.find_by_category_and_session("task_summary", session_id)
    return {"summaries": list(summaries), "session_id": session_id}


# ==================== 记忆 SSE 流 (Task 6) ====================


@router.get("/memory/events")
async def memory_events(request: Request):
    """SSE 流：订阅 ``memory_written`` 生命周期事件 (Task 6)。

    每个连接持有独立的 ``asyncio.Queue(maxsize=100)``；进程内
    HookRegistry 触发 ``memory_written`` 时把事件序列化后推给连接。
    15s 无事件时发心跳 ``: heartbeat`` 保持连接。客户端断开
    (``request.is_disconnected()``) 或请求取消时在 ``finally`` 注销
    监听器，避免 per-connection 闭包泄漏。

    Electron 主进程 (``electron/main.ts``) 通过 EventSource 消费此流，
    再通过 IPC ``sage:memory:event`` 转发给渲染进程。
    """
    from backend.memory.hooks import HookRegistry
    from backend.memory.lifecycle import MemoryWriteEvent

    hooks: HookRegistry = getattr(request.app.state, "hooks", None)
    if hooks is None:
        raise HTTPException(
            status_code=503,
            detail="memory hook registry not initialized",
        )

    queue: asyncio.Queue = asyncio.Queue(maxsize=100)

    def on_memory_written(event: object) -> None:
        """Hook 监听器（同步）：入队；队列满则丢弃并告警，绝不上抛。"""
        try:
            queue.put_nowait(event)
        except asyncio.QueueFull:
            logger.warning("memory events queue full, dropping event")

    hooks.on("memory_written", on_memory_written)

    async def event_stream():
        try:
            while True:
                if await request.is_disconnected():
                    break
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=15.0)
                except asyncio.TimeoutError:  # noqa: UP041 — Py3.10 asyncio.TimeoutError
                    yield ": heartbeat\n\n"
                    continue
                if not isinstance(event, MemoryWriteEvent):
                    continue
                payload = json.dumps(
                    {
                        "memory_id": event.memory_id,
                        "content": event.content,
                        "memory_type": event.memory_type,
                        "memory_category": event.memory_category,
                        "session_id": event.session_id,
                        "turn_id": event.turn_id,
                        "timestamp": event.timestamp.isoformat(),
                    },
                    ensure_ascii=False,
                )
                yield f"data: {payload}\n\n"
        finally:
            hooks.off("memory_written", on_memory_written)

    return StreamingResponse(event_stream(), media_type="text/event-stream")

# Wave 2 P1-4 (2026-08-14): 编排 run 读取/resume/计划更新端点挂载。
# orch_routes 用独立 APIRouter(prefix="/orch")，经 include_router 并入
# legacy_router → main.py 挂载后最终前缀 /api/v1/orch。
router.include_router(orch_routes_router)
