// Sage - 记忆型 AI 桌面助手
// Tauri 主入口

#![cfg_attr(
    all(not(debug_assertions), target_os = "windows"),
    windows_subsystem = "windows"
)]

use sage_lib::state::AppState;
use std::sync::Arc;

#[tokio::main]
async fn main() {
    // 初始化日志
    tracing_subscriber::fmt()
        .with_env_filter("info")
        .init();

    let app_state = Arc::new(AppState::new());

    // 启动 Python 后端
    let backend = app_state.python_backend.clone();
    let start_result = backend.start(None, None).await;
    match start_result {
        Ok(()) => tracing::info!("Python 后端启动成功"),
        Err(e) => tracing::warn!("Python 后端启动失败 (将使用本地模式): {}", e),
    }

    tauri::Builder::default()
        .manage(app_state)
        .setup(|_app| {
            tracing::info!("Sage 应用启动中...");
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![
            sage_lib::commands::create_session,
            sage_lib::commands::list_sessions,
            sage_lib::commands::get_session,
            sage_lib::commands::delete_session,
            sage_lib::commands::get_messages,
            sage_lib::commands::agent_chat,
            sage_lib::commands::interrupt_agent,
            sage_lib::commands::search_memory,
            sage_lib::commands::save_memory,
            sage_lib::commands::delete_memory,
            sage_lib::commands::delete_message, // PR-2
            sage_lib::commands::get_memories,
            sage_lib::commands::get_evolution_logs,
            sage_lib::commands::trigger_evolution,
            sage_lib::commands::get_evolution_status,
            sage_lib::commands::list_agents, // PR-3
            sage_lib::commands::update_agent, // PR-4
            sage_lib::commands::toggle_agent, // PR-5
            sage_lib::commands::agent_chat_stream, // PR-6
            // Wiki commands
            sage_lib::wiki::commands::create_wiki_project,
            sage_lib::wiki::commands::open_wiki_project,
            sage_lib::wiki::commands::wiki_list_directory,
            sage_lib::wiki::commands::wiki_read_file,
            sage_lib::wiki::commands::wiki_write_file,
            sage_lib::wiki::commands::wiki_delete_file,
            sage_lib::wiki::commands::wiki_rename_file,
            sage_lib::wiki::commands::wiki_search,
            sage_lib::wiki::commands::wiki_ingest_source,
            sage_lib::wiki::commands::wiki_chat,
        ])
        .run(tauri::generate_context!())
        .expect("启动 Sage 应用时发生错误");
}
