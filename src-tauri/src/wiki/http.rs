// Wiki HTTP 客户端
//
// 设计要点:
// - 包装 reqwest,提供 post_json 通用方法
// - 接受构造好的 URL/headers/body(由 build_request 函数产生)
// - 30 分钟 backstop timeout(同 llm_wiki)
// - 实际 HTTP 调用由 Phase 3.4 端到端测试覆盖(可对真实 LLM API 或本地 mock)

use std::collections::HashMap;
use std::time::Duration;

use serde_json::Value;

/// HTTP 客户端(包装 reqwest::Client)
#[derive(Debug, Clone)]
pub struct HttpClient {
    client: reqwest::Client,
    timeout: Duration,
}

impl HttpClient {
    /// 创建默认客户端(30 分钟 timeout)
    pub fn new() -> Self {
        Self::with_timeout(Duration::from_secs(30 * 60))
    }

    /// 指定 timeout
    pub fn with_timeout(timeout: Duration) -> Self {
        let client = reqwest::Client::builder()
            .timeout(timeout)
            .build()
            .unwrap_or_else(|_| reqwest::Client::new());
        Self { client, timeout }
    }

    /// 当前 timeout(秒)
    pub fn timeout_secs(&self) -> u64 {
        self.timeout.as_secs()
    }

    /// POST JSON 请求,返回响应体字符串
    pub async fn post_json(
        &self,
        url: &str,
        headers: &HashMap<String, String>,
        body: &Value,
    ) -> Result<String, String> {
        let mut req = self.client.post(url).json(body);
        for (k, v) in headers {
            req = req.header(k, v);
        }
        let resp = req
            .send()
            .await
            .map_err(|e| format!("HTTP 请求失败 ({}): {}", url, e))?;
        let status = resp.status();
        let text = resp
            .text()
            .await
            .map_err(|e| format!("读取响应体失败: {}", e))?;
        if !status.is_success() {
            return Err(format!(
                "HTTP {} ({}): {}",
                status.as_u16(),
                url,
                text.chars().take(500).collect::<String>()
            ));
        }
        Ok(text)
    }
}

impl Default for HttpClient {
    fn default() -> Self {
        Self::new()
    }
}

// ============================================================================
// Tests
// ============================================================================

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn new_client_has_30min_timeout() {
        let c = HttpClient::new();
        assert_eq!(c.timeout_secs(), 30 * 60);
    }

    #[test]
    fn with_timeout_uses_given_value() {
        let c = HttpClient::with_timeout(Duration::from_secs(60));
        assert_eq!(c.timeout_secs(), 60);
    }

    #[test]
    fn with_timeout_zero_is_allowed() {
        // 不 panic 即可
        let _c = HttpClient::with_timeout(Duration::from_secs(0));
    }

    #[test]
    fn default_equals_new() {
        let a = HttpClient::default();
        let b = HttpClient::new();
        assert_eq!(a.timeout_secs(), b.timeout_secs());
    }
}
