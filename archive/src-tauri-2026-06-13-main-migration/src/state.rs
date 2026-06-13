// 应用状态管理
use crate::python::PythonBackend;
use std::sync::Arc;
use tokio::sync::Mutex;

/// 应用全局状态
pub struct AppState {
    /// Python 后端进程管理器
    pub python_backend: Arc<PythonBackend>,
    /// 中断标志
    pub interrupt_flag: Mutex<bool>,
}

impl AppState {
    pub fn new() -> Self {
        Self {
            python_backend: Arc::new(PythonBackend::new()),
            interrupt_flag: Mutex::new(false),
        }
    }

    pub async fn set_interrupt(&self) {
        let mut flag = self.interrupt_flag.lock().await;
        *flag = true;
    }

    pub async fn reset_interrupt(&self) {
        let mut flag = self.interrupt_flag.lock().await;
        *flag = false;
    }

    pub async fn is_interrupted(&self) -> bool {
        let flag = self.interrupt_flag.lock().await;
        *flag
    }
}
