// Tauri Commands - 与 Python 后端通信
use crate::models::{Session, Message, ChatResponse};
use crate::state::AppState;
use std::sync::Arc;
use tauri::State;

/// 调用 Python 后端 API
fn call_python_api<T: serde::de::DeserializeOwned>(
    endpoint: &str,
    body: Option<&serde_json::Value>,
) -> Result<T, String> {
    // TODO: 后续阶段实现真正的 Python 后端调用
    // 当前返回空数据作为骨架
    tracing::info!("调用 Python API: {} with body: {:?}", endpoint, body);
    
    Err("Python 后端尚未实现".to_string())
}

/// 创建新会话
#[tauri::command]
pub async fn create_session(
    title: String,
    state: State<'_, Arc<AppState>>,
) -> Result<Session, String> {
    tracing::info!("创建会话: {}", title);
    
    // TODO: 调用 Python 后端 API
    // 临时返回模拟数据
    let now = chrono::Timestamp::now().timestamp_millis();
    Ok(Session {
        id: uuid::Uuid::new_v4().to_string(),
        title,
        created_at: now,
        updated_at: now,
        last_message_at: None,
        message_count: 0,
        is_pinned: false,
        metadata: None,
    })
}

/// 获取会话列表
#[tauri::command]
pub async fn list_sessions(
    state: State<'_, Arc<AppState>>,
) -> Result<Vec<Session>, String> {
    tracing::info!("获取会话列表");
    
    // TODO: 调用 Python 后端 API
    Ok(vec![])
}

/// 获取单个会话
#[tauri::command]
pub async fn get_session(
    id: String,
    state: State<'_, Arc<AppState>>,
) -> Result<Session, String> {
    tracing::info!("获取会话: {}", id);
    
    // TODO: 调用 Python 后端 API
    Err("会话不存在".to_string())
}

/// 删除会话
#[tauri::command]
pub async fn delete_session(
    id: String,
    state: State<'_, Arc<AppState>>,
) -> Result<(), String> {
    tracing::info!("删除会话: {}", id);
    
    // TODO: 调用 Python 后端 API
    Ok(())
}

/// 获取会话消息
#[tauri::command]
pub async fn get_messages(
    session_id: String,
    state: State<'_, Arc<AppState>>,
) -> Result<Vec<Message>, String> {
    tracing::info!("获取消息: session_id={}", session_id);
    
    // TODO: 调用 Python 后端 API
    Ok(vec![])
}

/// 聊天
#[tauri::command]
pub async fn agent_chat(
    session_id: String,
    message: String,
    state: State<'_, Arc<AppState>>,
) -> Result<ChatResponse, String> {
    tracing::info!("聊天: session_id={}, message={}", session_id, message);
    
    // TODO: 调用 Python 后端 API
    Err("Agent 尚未实现".to_string())
}

/// 中断 Agent
#[tauri::command]
pub async fn interrupt_agent(
    state: State<'_, Arc<AppState>>,
) -> Result<(), String> {
    tracing::info!("中断 Agent");
    
    state.set_interrupt();
    Ok(())
}
