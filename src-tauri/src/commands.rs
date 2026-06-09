// Tauri Commands - 通过 Python 后端通信
use crate::models::{Agent, ChatRequest, ChatResponse, EvolutionLog, EvolutionTaskStatus, Memory, Message, Session, TriggerRequest};
use crate::state::AppState;
use std::sync::Arc;
use tauri::State;

/// 创建新会话
#[tauri::command]
pub async fn create_session(
    title: String,
    state: State<'_, Arc<AppState>>,
) -> Result<Session, String> {
    tracing::info!("创建会话: {}", title);
    state.python_backend.post("/sessions", &serde_json::json!({
        "title": title
    })).await
}

/// 获取会话列表
#[tauri::command]
pub async fn list_sessions(
    state: State<'_, Arc<AppState>>,
) -> Result<Vec<Session>, String> {
    tracing::info!("获取会话列表");
    state.python_backend.get("/sessions?limit=100").await
}

/// 获取单个会话
#[tauri::command]
pub async fn get_session(
    id: String,
    state: State<'_, Arc<AppState>>,
) -> Result<Session, String> {
    tracing::info!("获取会话: {}", id);
    state.python_backend.get(&format!("/sessions/{}", id)).await
}

/// 删除会话
#[tauri::command]
pub async fn delete_session(
    id: String,
    state: State<'_, Arc<AppState>>,
) -> Result<(), String> {
    tracing::info!("删除会话: {}", id);
    let _: serde_json::Value = state.python_backend.post(&format!("/sessions/{}/delete", id), &serde_json::json!({})).await?;
    Ok(())
}

/// 获取会话消息
#[tauri::command]
pub async fn get_messages(
    session_id: String,
    state: State<'_, Arc<AppState>>,
) -> Result<Vec<Message>, String> {
    tracing::info!("获取消息: session_id={}", session_id);
    state.python_backend.get(&format!("/sessions/{}/messages", session_id)).await
}

/// 聊天
#[tauri::command]
pub async fn agent_chat(
    session_id: String,
    message: String,
    api_key: Option<String>,
    api_url: Option<String>,
    model: Option<String>,
    max_context: Option<i32>,
    temperature: Option<f64>,
    state: State<'_, Arc<AppState>>,
) -> Result<ChatResponse, String> {
    tracing::info!("聊天: session_id={}, message={}", session_id, message);
    state.python_backend.post("/chat", &ChatRequest {
        session_id,
        message,
        api_key,
        api_url,
        model,
        max_context,
        temperature,
    }).await
}

/// 中断 Agent
#[tauri::command]
pub async fn interrupt_agent(
    state: State<'_, Arc<AppState>>,
) -> Result<(), String> {
    tracing::info!("中断 Agent");
    state.set_interrupt().await;
    let _: serde_json::Value = state.python_backend.post("/interrupt", &serde_json::json!({})).await.unwrap_or_default();
    Ok(())
}

// ==================== 记忆命令 ====================

#[derive(serde::Serialize, serde::Deserialize)]
struct MemorySaveRequest {
    content: String,
    memory_type: String,
    importance: i32,
    tags: Vec<String>,
}

#[derive(serde::Serialize, serde::Deserialize)]
struct MemoryDeleteRequest {
    id: String,
}

/// 搜索记忆
#[tauri::command]
pub async fn search_memory(
    query: String,
    memory_type: Option<String>,
    limit: Option<i32>,
    state: State<'_, Arc<AppState>>,
) -> Result<Vec<Memory>, String> {
    tracing::info!("搜索记忆: query={}, type={:?}", query, memory_type);
    let limit = limit.unwrap_or(20);
    let path = format!("/memory/search?query={}&limit={}", query, limit);
    let path = if let Some(ref t) = memory_type {
        format!("{}&type={}", path, t)
    } else {
        path
    };
    state.python_backend.get(&path).await
}

/// 保存记忆
#[tauri::command]
pub async fn save_memory(
    content: String,
    memory_type: String,
    importance: Option<i32>,
    tags: Option<Vec<String>>,
    state: State<'_, Arc<AppState>>,
) -> Result<Memory, String> {
    tracing::info!("保存记忆: type={}, importance={:?}", memory_type, importance);
    state.python_backend.post("/memory/save", &MemorySaveRequest {
        content,
        memory_type,
        importance: importance.unwrap_or(5),
        tags: tags.unwrap_or_default(),
    }).await
}

/// 删除记忆
#[tauri::command]
pub async fn delete_memory(
    id: String,
    state: State<'_, Arc<AppState>>,
) -> Result<(), String> {
    tracing::info!("删除记忆: id={}", id);
    let _: serde_json::Value = state.python_backend.post("/memory/delete", &MemoryDeleteRequest { id }).await?;
    Ok(())
}

/// 获取记忆列表
#[tauri::command]
pub async fn get_memories(
    memory_type: Option<String>,
    page: Option<i32>,
    page_size: Option<i32>,
    state: State<'_, Arc<AppState>>,
) -> Result<Vec<Memory>, String> {
    tracing::info!("获取记忆列表: type={:?}, page={:?}", memory_type, page);
    let page = page.unwrap_or(1);
    let page_size = page_size.unwrap_or(20);
    let path = format!("/memory/list?page={}&page_size={}", page, page_size);
    let path = if let Some(ref t) = memory_type {
        format!("{}&type={}", path, t)
    } else {
        path
    };
    state.python_backend.get(&path).await
}

// ==================== 进化命令 ====================

/// 获取进化日志
#[tauri::command]
pub async fn get_evolution_logs(
    limit: Option<i32>,
    offset: Option<i32>,
    state: State<'_, Arc<AppState>>,
) -> Result<Vec<EvolutionLog>, String> {
    tracing::info!("获取进化日志: limit={:?}, offset={:?}", limit, offset);
    let limit = limit.unwrap_or(50);
    let offset = offset.unwrap_or(0);
    state.python_backend.get(&format!("/evolution/logs?limit={}&offset={}", limit, offset)).await
}

/// 手动触发进化任务
#[tauri::command]
pub async fn trigger_evolution(
    task_name: String,
    state: State<'_, Arc<AppState>>,
) -> Result<(), String> {
    tracing::info!("手动触发进化任务: {}", task_name);
    let _: serde_json::Value = state.python_backend.post("/evolution/trigger", &TriggerRequest { task_name }).await?;
    Ok(())
}

/// 获取进化任务状态
#[tauri::command]
pub async fn get_evolution_status(
    state: State<'_, Arc<AppState>>,
) -> Result<Vec<EvolutionTaskStatus>, String> {
    tracing::info!("获取进化任务状态");
    state.python_backend.get("/evolution/status").await
}

// ==================== Agent 命令 (PR-3) ====================

/// 列出所有 agent (含 disabled)
/// 对应后端 GET /api/v1/agents
#[tauri::command]
pub async fn list_agents(
    state: State<'_, Arc<AppState>>,
) -> Result<Vec<Agent>, String> {
    tracing::info!("获取 agent 列表");
    state.python_backend.get("/agents").await
}
