// Sage - 记忆型 AI 桌面助手
// Tauri 主入口

#![cfg_attr(
    all(not(debug_assertions), target_os = "windows"),
    windows_subsystem = "windows"
)]

fn main() {
    // 初始化日志
    tracing_subscriber::fmt()
        .with_env_filter("info")
        .init();

    tauri::Builder::default()
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
        ])
        .run(tauri::generate_context!())
        .expect("启动 Sage 应用时发生错误");
}
