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
#[derive(Debug, Deserialize)]
pub struct ChatRequest {
    pub session_id: String,
    pub message: String,
}

/// 聊天响应
#[derive(Debug, Serialize)]
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
