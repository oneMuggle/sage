// Python Agent 子进程管理器
// 负责启动、停止、健康检查和 HTTP 调用

use reqwest::Client;
use std::process::{Child, Command};
use std::sync::atomic::{AtomicBool, AtomicU16, Ordering};
use std::sync::Arc;
use std::time::{Duration, Instant};
use tokio::sync::Mutex;
use tokio::time::sleep;

/// 检查 Python 版本是否在 Win7 上可能不兼容
/// Python 3.9+ 已放弃 Windows 7 支持
fn check_python_win7_compat(python: &str) -> Option<String> {
    let output = Command::new(python)
        .args(["--version"])
        .output();

    match output {
        Ok(out) if out.status.success() => {
            let version_str = String::from_utf8_lossy(&out.stdout)
                + &String::from_utf8_lossy(&out.stderr);
            if let Some(version_part) = version_str.split_whitespace().nth(1) {
                if let Some(minor_str) = version_part.split('.').nth(1) {
                    if let Ok(minor) = minor_str.parse::<u32>() {
                        if minor >= 9 {
                            return Some(format!(
                                "检测到 Python {}，该版本不支持 Windows 7。\
                                AI 对话功能可能无法使用，建议安装 Python 3.8。",
                                version_part
                            ));
                        }
                    }
                }
            }
            None
        }
        _ => None,
    }
}

/// Python 后端进程管理器
pub struct PythonBackend {
    process: Arc<Mutex<Option<Child>>>,
    running: Arc<AtomicBool>,
    port: Arc<AtomicU16>,
    http_client: Client,
}

impl PythonBackend {
    /// 创建新的 Python 后端管理器
    pub fn new() -> Self {
        Self {
            process: Arc::new(Mutex::new(None)),
            running: Arc::new(AtomicBool::new(false)),
            port: Arc::new(AtomicU16::new(8765)),
            http_client: Client::builder()
                .timeout(Duration::from_secs(120))
                .build()
                .expect("创建 HTTP 客户端失败"),
        }
    }

    /// 获取端口
    pub fn port(&self) -> u16 {
        self.port.load(Ordering::Relaxed)
    }

    /// 获取基础 URL
    pub fn base_url(&self) -> String {
        format!("http://127.0.0.1:{}", self.port())
    }

    /// 检查是否正在运行
    pub fn is_running(&self) -> bool {
        self.running.load(Ordering::Relaxed)
    }

    /// 启动 Python FastAPI 后端
    pub async fn start(&self, python_path: Option<&str>, working_dir: Option<&str>) -> Result<(), String> {
        if self.is_running() {
            // 检查进程是否存活
            let mut guard = self.process.lock().await;
            if let Some(ref mut child) = *guard {
                match child.try_wait() {
                    Ok(Some(_)) => {
                        // 进程已退出，清理
                        *guard = None;
                    }
                    _ => return Ok(()),
                }
            } else {
                // 没有进程
            }
        }

        let python = python_path.unwrap_or("python");

        // Win7 兼容性: 检测 Python 版本
        if let Some(warning) = check_python_win7_compat(python) {
            tracing::warn!("{}", warning);
        }
        let port = self.port();

        let mut cmd = Command::new(python);
        cmd.args(["-m", "uvicorn", "backend.main:app", "--host", "127.0.0.1", "--port", &port.to_string()]);

        if let Some(dir) = working_dir {
            cmd.current_dir(dir);
        }

        cmd.env("PYTHONUNBUFFERED", "1");

        tracing::info!("启动 Python 后端: port={}", port);

        let child = cmd.spawn().map_err(|e| format!("启动 Python 进程失败: {}", e))?;

        {
            let mut guard = self.process.lock().await;
            *guard = Some(child);
        }

        self.running.store(true, Ordering::Relaxed);

        self.wait_for_ready(Duration::from_secs(30)).await?;

        tracing::info!("Python 后端已就绪: {}", self.base_url());
        Ok(())
    }

    /// 等待后端就绪
    async fn wait_for_ready(&self, timeout: Duration) -> Result<(), String> {
        let start = Instant::now();
        let health_url = format!("{}/health", self.base_url());

        while start.elapsed() < timeout {
            match self.http_client.get(&health_url).send().await {
                Ok(resp) if resp.status().is_success() => return Ok(()),
                _ => {}
            }
            sleep(Duration::from_millis(500)).await;
        }

        Err(format!("Python 后端未在 {} 秒内就绪", timeout.as_secs()))
    }

    /// 停止 Python 后端
    pub async fn stop(&self) -> Result<(), String> {
        self.running.store(false, Ordering::Relaxed);

        let mut guard = self.process.lock().await;
        if let Some(mut child) = guard.take() {
            let _ = child.kill();
            let _ = child.wait();
            tracing::info!("Python 后端已停止");
        }

        Ok(())
    }

    /// 调用后端 API (GET)
    pub async fn get<T: serde::de::DeserializeOwned>(&self, path: &str) -> Result<T, String> {
        let url = format!("{}/api/v1{}", self.base_url(), path);
        tracing::debug!("GET {}", url);

        let resp = self
            .http_client
            .get(&url)
            .send()
            .await
            .map_err(|e| format!("HTTP GET 请求失败: {}", e))?;

        let status = resp.status();
        let body = resp
            .text()
            .await
            .map_err(|e| format!("读取响应体失败: {}", e))?;

        if !status.is_success() {
            return Err(format!("API 返回错误 ({}): {}", status, body));
        }

        serde_json::from_str(&body)
            .map_err(|e| format!("解析 JSON 失败: {}", e))
    }

    /// 调用后端 API (POST)
    pub async fn post<T: serde::de::DeserializeOwned, B: serde::Serialize>(
        &self,
        path: &str,
        body: &B,
    ) -> Result<T, String> {
        let url = format!("{}/api/v1{}", self.base_url(), path);
        tracing::debug!("POST {}", url);

        let resp = self
            .http_client
            .post(&url)
            .json(body)
            .send()
            .await
            .map_err(|e| format!("HTTP POST 请求失败: {}", e))?;

        let status = resp.status();
        let text = resp
            .text()
            .await
            .map_err(|e| format!("读取响应体失败: {}", e))?;

        if !status.is_success() {
            return Err(format!("API 返回错误 ({}): {}", status, text));
        }

        serde_json::from_str(&text)
            .map_err(|e| format!("解析 JSON 失败: {}", e))
    }

    /// 健康检查
    pub async fn health_check(&self) -> bool {
        let url = format!("{}/health", self.base_url());
        self.http_client
            .get(&url)
            .send()
            .await
            .map_or(false, |r| r.status().is_success())
    }
}

impl Default for PythonBackend {
    fn default() -> Self {
        Self::new()
    }
}
