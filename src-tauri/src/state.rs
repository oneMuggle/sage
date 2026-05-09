// 应用状态管理
use std::sync::Mutex;
use crate::models::Session;

/// 应用全局状态
pub struct AppState {
    /// 当前 Python Agent 实例
    pub agent: Mutex<Option<PyAgent>>,
    /// 中断标志
    pub interrupt_flag: Mutex<bool>,
}

/// Python Agent 引用（预留）
pub struct PyAgent {
    pub running: bool,
}

impl Default for AppState {
    fn default() -> Self {
        Self {
            agent: Mutex::new(None),
            interrupt_flag: Mutex::new(false),
        }
    }
}

impl AppState {
    pub fn new() -> Self {
        Self::default()
    }

    pub fn set_interrupt(&self) {
        if let Ok(mut flag) = self.interrupt_flag.lock() {
            *flag = true;
        }
    }

    pub fn reset_interrupt(&self) {
        if let Ok(mut flag) = self.interrupt_flag.lock() {
            *flag = false;
        }
    }

    pub fn is_interrupted(&self) -> bool {
        if let Ok(flag) = self.interrupt_flag.lock() {
            *flag
        } else {
            false
        }
    }
}
