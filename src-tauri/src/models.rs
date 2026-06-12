// 数据模型定义
use serde::{Deserialize, Serialize};

/// 会话
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Session {
    pub id: String,
    pub title: String,
    pub created_at: i64,
    pub updated_at: i64,
    pub last_message_at: Option<i64>,
    pub message_count: i32,
    pub is_pinned: bool,
    pub metadata: Option<String>,
}

/// 消息
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Message {
    pub id: String,
    pub session_id: String,
    pub role: String,
    pub content: String,
    pub created_at: i64,
    pub model: Option<String>,
    pub provider: Option<String>,
    pub tool_calls: Option<String>,
    pub tool_call_id: Option<String>,
}

/// 聊天请求
#[derive(Debug, Deserialize, Serialize)]
pub struct ChatRequest {
    pub session_id: String,
    pub message: String,
    #[serde(default)]
    pub api_key: Option<String>,
    #[serde(default)]
    pub api_url: Option<String>,
    #[serde(default)]
    pub model: Option<String>,
    #[serde(default)]
    pub max_context: Option<i32>,
    #[serde(default)]
    pub temperature: Option<f64>,
}

/// 聊天响应
#[derive(Debug, Serialize, Deserialize)]
pub struct ChatResponse {
    pub message: Message,
    pub session: Option<Session>,
}

/// 工具调用
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ToolCall {
    pub name: String,
    pub args: String,
    pub result: Option<String>,
}

/// 记忆类型枚举
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Memory {
    pub id: String,
    pub content: String,
    pub summary: Option<String>,
    pub memory_type: Option<String>,
    pub session_id: Option<String>,
    pub importance: i32,
    pub tags: Vec<String>,
    pub created_at: i64,
    pub accessed_at: Option<i64>,
    pub access_count: i32,
}

/// 进化日志
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct EvolutionLog {
    pub id: String,
    pub evolution_type: String,
    pub description: String,
    pub before_state: Option<String>,
    pub after_state: Option<String>,
    pub trigger_type: String,
    pub trigger_condition: Option<String>,
    pub status: String,
    pub error_message: Option<String>,
    pub tokens_used: Option<i64>,
    pub created_at: i64,
    pub completed_at: Option<i64>,
}

/// 进化任务状态
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct EvolutionTaskStatus {
    pub name: String,
    pub schedule: String,
    pub last_run: Option<String>,
    pub next_run: Option<String>,
    pub running: bool,
}

/// 手动触发请求
#[derive(Debug, Deserialize, Serialize)]
pub struct TriggerRequest {
    pub task_name: String,
}

/// Agent 配置 (PR-3)
/// 字段与后端 AgentRepository._row_to_dict() 输出一致 (snake_case from Python)
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Agent {
    pub id: String,
    pub name: String,
    pub role: String,
    pub system_prompt: String,
    pub tools: Vec<String>,
    pub memory_access: Vec<String>,
    pub model_config: serde_json::Value,
    pub max_iterations: i32,
    pub enabled: bool,
    pub description: String,
    pub updated_at: i64, // PR-4 补: PATCH 后必刷新
}

/// Agent 部分更新请求 (PR-4)
/// 所有字段 Optional — 不传视为"该字段不更新"。前端用 patch_agent 全对象透传
/// (类似 serde flatten), Rust 端转 JSON body 后端仅接非 None 字段.
/// 注: `model_config` 序列化时 rename 成 `model_config_data` (避开后端
/// Pydantic v2 保留命名空间, 路由层再 map 回 `model_config`).
#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct AgentUpdateRequest {
    #[serde(skip_serializing_if = "Option::is_none")]
    pub name: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub role: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub system_prompt: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub tools: Option<Vec<String>>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub memory_access: Option<Vec<String>>,
    #[serde(skip_serializing_if = "Option::is_none", rename = "model_config_data")]
    pub model_config: Option<serde_json::Value>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub max_iterations: Option<i32>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub enabled: Option<bool>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub description: Option<String>,
}

/// 流式聊天工具调用 (PR-6)
/// 对应后端 backend.core.legacy.agent_state.ToolCallRequest.to_dict()
/// (OpenAI 工具调用格式)
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct AgentToolCall {
    pub id: String,
    #[serde(rename = "type")]
    pub kind: String, // "function"
    pub function: AgentToolCallFunction,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct AgentToolCallFunction {
    pub name: String,
    /// 字符串化的 JSON (与 OpenAI tool_calls 格式一致)
    pub arguments: String,
}

/// 流式聊天工具结果 (PR-6)
/// 对应后端 backend.core.legacy.agent_state.ToolCallResult.to_dict()
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct AgentToolResult {
    pub tool_call_id: String,
    pub role: String, // "tool"
    pub content: String,
}

/// 流式聊天事件 (PR-6)
/// 对应后端 backend.core.legacy.agent_state.AgentEvent.to_dict()
/// - `state` 取值: "idle" | "thinking" | "acting" | "observing" | "done" | "failed"
/// - 失败时 `error` 为非 None 字符串(后端为结构化 LLMError,这里只透传原始 JSON)
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct AgentEvent {
    pub state: String,
    pub iteration: i32,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub content: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub tool_call: Option<AgentToolCall>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub tool_result: Option<AgentToolResult>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub error: Option<String>,
}
