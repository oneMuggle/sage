// Tauri Commands - 通过 Python 后端通信
use crate::models::{Agent, AgentEvent, AgentUpdateRequest, ChatRequest, ChatResponse, EvolutionLog, EvolutionTaskStatus, Memory, Message, Session, Skill, SkillExecuteResult, TriggerRequest};
use crate::state::AppState;
use futures_util::StreamExt;
use std::sync::Arc;
use tauri::{AppHandle, Emitter, State};

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

/// 删除单条消息 (PR-2)
/// 对应后端 POST /api/v1/messages/{message_id}/delete
#[tauri::command]
pub async fn delete_message(
    id: String,
    state: State<'_, Arc<AppState>>,
) -> Result<(), String> {
    tracing::info!("删除消息: id={}", id);
    let path = format!("/messages/{}/delete", id);
    let _: serde_json::Value = state.python_backend.post(&path, &serde_json::json!({})).await?;
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

/// 部分更新 agent (PR-4)
/// 对应后端 PATCH /api/v1/agents/{id}
/// - update: 仅含需要修改的字段 (None = 不动该字段)
/// - 后端 AgentUpdate Pydantic 校验 role 白名单 / max_iterations 范围
#[tauri::command]
pub async fn update_agent(
    id: String,
    update: AgentUpdateRequest,
    state: State<'_, Arc<AppState>>,
) -> Result<Agent, String> {
    tracing::info!("更新 agent: id={}", id);
    let path = format!("/agents/{}", id);
    state
        .python_backend
        .patch(&path, &update)
        .await
}

/// 启用/禁用 agent (PR-5)
/// 对应后端 PATCH /api/v1/agents/{id}/toggle
/// - 与 update_agent 的区别: 单独端点便于审计与未来权限模型
/// - 返回完整 profile, 前端可一次性 setState (含新 enabled / updated_at)
#[tauri::command]
pub async fn toggle_agent(
    id: String,
    enabled: bool,
    state: State<'_, Arc<AppState>>,
) -> Result<Agent, String> {
    tracing::info!("切换 agent: id={}, enabled={}", id, enabled);
    let path = format!("/agents/{}/toggle", id);
    state
        .python_backend
        .patch(&path, &serde_json::json!({ "enabled": enabled }))
        .await
}

// ==================== 流式聊天命令 (PR-6) ====================

/// 流式聊天 — 后端走 POST /api/v1/chat/stream (NDJSON)
/// 本命令立刻返回 `stream_id` (UUID),不阻塞 Tauri 通道。
/// 后台 task 拉取 Python 流,逐行解析为 AgentEvent 后通过
/// `app.emit("chat-stream-{stream_id}", payload)` 推送到前端。
/// 前端用 `listen` 订阅该事件,stream_id 让多次并行流互不干扰。
/// 流结束 (done / failed / error) 时多 emit 一个 `{ state: "done" }` 终止信号。
#[tauri::command]
pub async fn agent_chat_stream(
    session_id: String,
    message: String,
    api_key: Option<String>,
    api_url: Option<String>,
    model: Option<String>,
    max_context: Option<i32>,
    temperature: Option<f64>,
    app: AppHandle,
    state: State<'_, Arc<AppState>>,
) -> Result<String, String> {
    let stream_id = uuid::Uuid::new_v4().to_string();
    tracing::info!(
        "流式聊天: session_id={}, stream_id={}, message={}",
        session_id,
        stream_id,
        message
    );

    let backend = state.python_backend.clone();
    let body = ChatRequest {
        session_id: session_id.clone(),
        message,
        api_key,
        api_url,
        model,
        max_context,
        temperature,
    };
    let event_name = format!("chat-stream-{}", stream_id);
    let app_clone = app.clone();
    let sid_for_log = stream_id.clone();

    // 后台 task: 拉流 → 解析 → emit
    tokio::spawn(async move {
        let mut line_stream = match backend.post_stream("/chat/stream", &body).await {
            Ok(s) => s,
            Err(e) => {
                tracing::error!("[stream {}] post_stream 失败: {}", sid_for_log, e);
                let _ = app_clone.emit(
                    &event_name,
                    AgentEvent {
                        state: "failed".to_string(),
                        iteration: 0,
                        content: None,
                        tool_call: None,
                        tool_result: None,
                        error: Some(e),
                    },
                );
                return;
            }
        };

        while let Some(line_result) = line_stream.next().await {
            match line_result {
                Ok(line) => {
                    // 解析 NDJSON 一行 → AgentEvent
                    match serde_json::from_str::<AgentEvent>(&line) {
                        Ok(evt) => {
                            let is_terminal = matches!(evt.state.as_str(), "done" | "failed");
                            if let Err(e) = app_clone.emit(&event_name, &evt) {
                                tracing::warn!(
                                    "[stream {}] emit 失败: {}",
                                    sid_for_log,
                                    e
                                );
                            }
                            if is_terminal {
                                tracing::info!("[stream {}] 流结束: state={}", sid_for_log, evt.state);
                                return;
                            }
                        }
                        Err(e) => {
                            tracing::warn!(
                                "[stream {}] 解析 NDJSON 失败: line={:?}, err={}",
                                sid_for_log,
                                line,
                                e
                            );
                            // 把原始 line 作为 content 推送,前端拿到 raw 可排查
                            let _ = app_clone.emit(
                                &event_name,
                                AgentEvent {
                                    state: "observing".to_string(),
                                    iteration: 0,
                                    content: Some(line),
                                    tool_call: None,
                                    tool_result: None,
                                    error: Some(format!("NDJSON parse error: {}", e)),
                                },
                            );
                        }
                    }
                }
                Err(e) => {
                    tracing::error!("[stream {}] 读流失败: {}", sid_for_log, e);
                    let _ = app_clone.emit(
                        &event_name,
                        AgentEvent {
                            state: "failed".to_string(),
                            iteration: 0,
                            content: None,
                            tool_call: None,
                            tool_result: None,
                            error: Some(e),
                        },
                    );
                    return;
                }
            }
        }
        // 流自然结束但后端没发 done/failed — 补一个 done
        tracing::info!("[stream {}] 流自然结束,补发 done", sid_for_log);
        let _ = app_clone.emit(
            &event_name,
            AgentEvent {
                state: "done".to_string(),
                iteration: 0,
                content: None,
                tool_call: None,
                tool_result: None,
                error: None,
            },
        );
    });

    Ok(stream_id)
}

// ==================== 技能命令 (PR-7) ====================

/// 列出所有已注册技能 (PR-7)
/// 对应后端 GET /api/v1/skills
#[tauri::command]
pub async fn list_skills(
    state: State<'_, Arc<AppState>>,
) -> Result<Vec<Skill>, String> {
    tracing::info!("获取技能列表");
    state.python_backend.get("/skills").await
}

/// 启用/禁用技能 (PR-7)
/// 对应后端 POST /api/v1/skills/{name}/toggle
/// - 返回完整 skill dict (含新 enabled)
/// - 不存在 → 后端 404, Tauri 命令透传为 Err
#[tauri::command]
pub async fn toggle_skill(
    name: String,
    enabled: bool,
    state: State<'_, Arc<AppState>>,
) -> Result<Skill, String> {
    tracing::info!("切换技能: name={}, enabled={}", name, enabled);
    let path = format!("/skills/{}/toggle", name);
    state
        .python_backend
        .post(&path, &serde_json::json!({ "enabled": enabled }))
        .await
}

/// 执行技能 (PR-7)
/// 对应后端 POST /api/v1/skills/{name}/execute
/// - 资源不存在 → 404 透传
/// - 资源存在但 disabled / 工具未注入 → 200 + success=False (SkillExecuteResult)
#[tauri::command]
pub async fn execute_skill(
    name: String,
    action: Option<String>,
    args: Option<serde_json::Value>,
    state: State<'_, Arc<AppState>>,
) -> Result<SkillExecuteResult, String> {
    tracing::info!("执行技能: name={}, action={:?}", name, action);
    let path = format!("/skills/{}/execute", name);
    let action = action.unwrap_or_default();
    let args = args.unwrap_or_else(|| serde_json::json!({}));
    state
        .python_backend
        .post(&path, &serde_json::json!({ "action": action, "args": args }))
        .await
}
