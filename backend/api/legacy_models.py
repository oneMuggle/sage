# ruff: noqa: UP006, UP007, UP035, UP045 — release/win7 Python 3.8 兼容，保留 typing 注解
"""legacy API 请求/响应模型（C1e，DSH 对标 R27，自 legacy_routes.py 迁出）。

13 个 Pydantic DTO（会话 / 聊天 / 消息 / agent / 中断 / steering / learn）
的唯一归属。legacy_routes.py 再导出全部名字——既有 import 路径（含
20 处测试文件）不变；FastAPI 注解解析按真实定义模块进行，无影响。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Union

from pydantic import BaseModel, Field, StrictBool

from backend.office.chat_refs import ChatOfficeRef


class SessionCreate(BaseModel):
    title: str = "新对话"
    parent_id: Optional[str] = None


class SessionUpdate(BaseModel):
    title: Optional[str] = None

    is_pinned: Optional[bool] = None


class ChatRequest(BaseModel):
    session_id: str
    message: str
    # client_message_id (2026-09, 同步 #1155): 前端乐观 user 消息 id 与服务端
    # 落库 id 对齐的根方案。传入时 user 消息落库 id = f"u-{client_message_id}"。
    client_message_id: Optional[str] = Field(
        default=None,
        pattern=r"^[0-9a-f-]{8,64}$",
        description="前端生成的消息身份 id (UUID), 用于乐观 id 对齐与幂等",
    )
    workspace_path: Optional[str] = None
    # 2026-07-30: 选 agent 的入口。None / 空字符串 → 端点 fallback 到 "primary"。
    # 真正的路由由 SageAgent(agent_id=...) 内部完成:从 SQLite 读 profile,
    # 透传到 get_available_tools → ToolRegistry.get_schemas_for_llm(allowed_tools=...)
    # 这样 memory_manager 之类的窄权限 agent 不会拿到 list_dir/read_file。
    agent_id: Optional[str] = None
    api_key: Optional[str] = None

    api_url: Optional[str] = None

    model: Optional[str] = None

    max_context: Optional[int] = None

    # Task 5 (2026-09-15): auto-context resolution flag.
    # true = backend resolves effective window from catalog; false = use max_context as fixed cap.
    auto_context: Optional[bool] = None

    # Task 5 (2026-09-15): endpoint identifier from the request.
    # Takes priority over persisted settings when resolving context window / usage attribution.
    endpoint_id: Optional[str] = None

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
    # 用 forward ref 避免 route→domain 循环导入; ``model_rebuild`` 在
    # legacy_routes 模块加载完毕时自动被 Pydantic v2 调用.
    office_refs: List[ChatOfficeRef] = Field(default_factory=list)

    # R37: 聊天文本文档附件 —— 已上传媒体 id 列表（POST /chat/attachments
    # 返回的 media_ref.id）。producer 按 id 读全文，注入上下文附件块。
    attachment_media_ids: List[str] = Field(default_factory=list)

    # G6 (2026-09-06): 聊天图片输入 —— base64 data URL 列表（data:image/png;base64,...）。
    # 非空时 user 消息转 OpenAI 多模态 content（text + image_url 分段），
    # 依赖 llm_client._convert_messages 对 list 型 content 的原样透传。
    # 上限 4 张 / 单张 5MiB（解码后字节计）—— 防上下文爆炸。
    images: List[str] = Field(default_factory=list)

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

    # Task 4 (2026-09-17): 上下文重置标记。True 时 chat_stream_create 在持久化
    # 当前消息前调用 MessageRepository.advance_segment(session_id)，开启新 segment；
    # 历史加载改用 get_active_segment 只取当前段。
    context_reset: bool = False

    # C2 (对话阅读体验第二轮): 原位重新生成 —— 锚点 user 消息 id。设置时不再落
    # user 消息, 历史剔除锚点与旧回答; 旧回答在本轮首次落库前归档为版本。
    regenerate_of: Optional[str] = None

    # PM1 (round8): 单 agent 计划模式 —— 本次 run 只读（权限执行器 override
    # READ_ONLY）+ 计划指令 system 块；DONE 后前端出批准条，批准后普通执行。
    plan_mode: Optional[bool] = False

    # 对标 S2（2026-09-13）：临时聊天（无记忆）模式。``"off"`` 时本轮
    # 既不注入 L13 记忆上下文，也不做对话后记忆提取；与 ChatGPT
    # "Temporary chat" / Claude 无记忆会话对齐。缺省 ``"on"``。
    memory_mode: Optional[str] = "on"



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

    session: Optional[Dict] = None

    error: Optional[ChatErrorInfo] = None


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
    # win7 (Pydantic 1/2 双兼容): 用 ``class Config`` 关掉该保护.
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
    model_config_data: Optional[Dict] = None
    max_iterations: Optional[int] = None
    enabled: Optional[bool] = None
    description: Optional[str] = None



class InterruptRequest(BaseModel):
    """/interrupt 请求体 —— stream_id 可选，兼容不带 body 的旧调用方。"""

    stream_id: Optional[str] = None



class SteerRequest(BaseModel):
    """/chat/steer 请求体 —— 向运行中的主 agent 注入用户补充消息（RT5）。"""

    stream_id: str
    content: str



class LearnRequest(BaseModel):
    """POST /learn 请求体。

    - session_id: 要 review 的会话 (必填)
    - prompt: 用户附加的提示,传给 LLM 作为 review 上下文 (可选)
    """

    session_id: str
    prompt: str = ""



