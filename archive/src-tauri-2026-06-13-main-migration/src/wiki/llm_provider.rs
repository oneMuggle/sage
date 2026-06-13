// Wiki LLM provider abstraction
//
// 设计要点:
// - 一个公共入口 `build_request` / `parse_response`,按 Provider 分发
// - 不做实际 HTTP 调用,纯请求构造 + 响应解析,便于单元测试
// - 4 个 provider 协议细节见各分支

use std::collections::HashMap;

use serde_json::{json, Value};

// ============================================================================
// 公共类型
// ============================================================================

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum Provider {
    OpenAI,
    Anthropic,
    Ollama,
    Custom,
}

#[derive(Debug, Clone)]
pub struct LlmProviderConfig {
    pub provider: Provider,
    pub base_url: String,
    pub api_key: String,
    pub model: String,
    pub max_tokens: u32,
    pub temperature: f32,
    pub custom_headers: HashMap<String, String>,
}

#[derive(Debug, Clone)]
pub struct ChatMessage {
    pub role: String,
    pub content: String,
}

#[derive(Debug, Clone)]
pub struct ChatRequest {
    pub messages: Vec<ChatMessage>,
    pub max_tokens: u32,
    pub temperature: f32,
}

#[derive(Debug, Clone)]
pub struct ChatResponse {
    pub content: String,
    pub prompt_tokens: u32,
    pub completion_tokens: u32,
}

#[derive(Debug, Clone)]
pub struct HttpRequest {
    pub url: String,
    pub method: String,
    pub headers: HashMap<String, String>,
    pub body: Value,
}

// ============================================================================
// 公共入口(分发到 provider-specific 实现)
// ============================================================================

pub fn build_request(
    config: &LlmProviderConfig,
    request: &ChatRequest,
) -> Result<HttpRequest, String> {
    match config.provider {
        Provider::OpenAI => build_openai_request(config, request),
        Provider::Anthropic => build_anthropic_request(config, request),
        Provider::Ollama => build_ollama_request(config, request),
        Provider::Custom => build_custom_request(config, request),
    }
}

pub fn parse_response(provider: &Provider, body: &str) -> Result<ChatResponse, String> {
    match provider {
        Provider::OpenAI => parse_openai_response(body),
        Provider::Anthropic => parse_anthropic_response(body),
        Provider::Ollama => parse_ollama_response(body),
        Provider::Custom => parse_custom_response(body),
    }
}

// ============================================================================
// OpenAI provider
// ============================================================================

fn build_openai_request(
    config: &LlmProviderConfig,
    request: &ChatRequest,
) -> Result<HttpRequest, String> {
    let url = format!("{}/chat/completions", config.base_url.trim_end_matches('/'));
    let mut headers = HashMap::new();
    if !config.api_key.is_empty() {
        headers.insert("Authorization".to_string(), format!("Bearer {}", config.api_key));
    }
    headers.insert("Content-Type".to_string(), "application/json".to_string());
    for (k, v) in &config.custom_headers {
        headers.insert(k.clone(), v.clone());
    }
    let body = json!({
        "model": config.model,
        "messages": request.messages.iter().map(|m| json!({
            "role": m.role,
            "content": m.content,
        })).collect::<Vec<_>>(),
        "max_tokens": request.max_tokens,
        "temperature": request.temperature,
        "stream": false,
    });
    Ok(HttpRequest {
        url,
        method: "POST".to_string(),
        headers,
        body,
    })
}

fn parse_openai_response(body: &str) -> Result<ChatResponse, String> {
    let parsed: Value = serde_json::from_str(body)
        .map_err(|e| format!("OpenAI 响应不是合法 JSON: {}", e))?;
    let content = parsed["choices"][0]["message"]["content"]
        .as_str()
        .ok_or_else(|| "OpenAI 响应缺少 choices[0].message.content".to_string())?
        .to_string();
    let prompt_tokens = parsed["usage"]["prompt_tokens"].as_u64().unwrap_or(0) as u32;
    let completion_tokens = parsed["usage"]["completion_tokens"].as_u64().unwrap_or(0) as u32;
    Ok(ChatResponse {
        content,
        prompt_tokens,
        completion_tokens,
    })
}

// ============================================================================
// Anthropic provider
// ============================================================================

fn build_anthropic_request(
    config: &LlmProviderConfig,
    request: &ChatRequest,
) -> Result<HttpRequest, String> {
    if config.api_key.is_empty() {
        return Err("Anthropic provider 需要 api_key".to_string());
    }
    let url = format!("{}/v1/messages", config.base_url.trim_end_matches('/'));
    let mut headers = HashMap::new();
    headers.insert("x-api-key".to_string(), config.api_key.clone());
    headers.insert("anthropic-version".to_string(), "2023-06-01".to_string());
    headers.insert("Content-Type".to_string(), "application/json".to_string());
    for (k, v) in &config.custom_headers {
        headers.insert(k.clone(), v.clone());
    }
    // Anthropic 要求 system 消息独立到顶层
    let mut system_content: Option<String> = None;
    let messages: Vec<Value> = request
        .messages
        .iter()
        .filter_map(|m| {
            if m.role == "system" {
                system_content = Some(m.content.clone());
                None
            } else {
                Some(json!({
                    "role": m.role,
                    "content": m.content,
                }))
            }
        })
        .collect();
    let mut body = json!({
        "model": config.model,
        "messages": messages,
        "max_tokens": request.max_tokens,
        "temperature": request.temperature,
    });
    if let Some(sys) = system_content {
        body["system"] = json!(sys);
    }
    Ok(HttpRequest {
        url,
        method: "POST".to_string(),
        headers,
        body,
    })
}

fn parse_anthropic_response(body: &str) -> Result<ChatResponse, String> {
    let parsed: Value = serde_json::from_str(body)
        .map_err(|e| format!("Anthropic 响应不是合法 JSON: {}", e))?;
    let content = parsed["content"][0]["text"]
        .as_str()
        .ok_or_else(|| "Anthropic 响应缺少 content[0].text".to_string())?
        .to_string();
    let prompt_tokens = parsed["usage"]["input_tokens"].as_u64().unwrap_or(0) as u32;
    let completion_tokens = parsed["usage"]["output_tokens"].as_u64().unwrap_or(0) as u32;
    Ok(ChatResponse {
        content,
        prompt_tokens,
        completion_tokens,
    })
}

// ============================================================================
// Ollama provider (OpenAI 兼容协议,默认 localhost:11434)
// ============================================================================

fn build_ollama_request(
    config: &LlmProviderConfig,
    request: &ChatRequest,
) -> Result<HttpRequest, String> {
    // Ollama 支持 OpenAI 兼容端点(/v1/chat/completions)
    let url = format!("{}/chat/completions", config.base_url.trim_end_matches('/'));
    let mut headers = HashMap::new();
    headers.insert("Content-Type".to_string(), "application/json".to_string());
    for (k, v) in &config.custom_headers {
        headers.insert(k.clone(), v.clone());
    }
    let body = json!({
        "model": config.model,
        "messages": request.messages.iter().map(|m| json!({
            "role": m.role,
            "content": m.content,
        })).collect::<Vec<_>>(),
        "max_tokens": request.max_tokens,
        "temperature": request.temperature,
        "stream": false,
    });
    Ok(HttpRequest {
        url,
        method: "POST".to_string(),
        headers,
        body,
    })
}

fn parse_ollama_response(body: &str) -> Result<ChatResponse, String> {
    // Ollama 的 OpenAI 兼容响应格式与 OpenAI 一致
    parse_openai_response(body)
}

// ============================================================================
// Custom provider (OpenAI 兼容,支持任意 base_url + 自定义头)
// ============================================================================

fn build_custom_request(
    config: &LlmProviderConfig,
    request: &ChatRequest,
) -> Result<HttpRequest, String> {
    // Custom 与 OpenAI 协议一致,但允许自定义头覆盖
    let mut req = build_openai_request(config, request)?;
    // Custom 总是包含自定义头(OpenAI 不一定有)
    for (k, v) in &config.custom_headers {
        req.headers.insert(k.clone(), v.clone());
    }
    Ok(req)
}

fn parse_custom_response(body: &str) -> Result<ChatResponse, String> {
    // Custom 协议与 OpenAI 兼容
    parse_openai_response(body)
}

// ============================================================================
// Tests
// ============================================================================

#[cfg(test)]
mod tests {
    use super::*;

    fn openai_config() -> LlmProviderConfig {
        LlmProviderConfig {
            provider: Provider::OpenAI,
            base_url: "https://api.openai.com/v1".to_string(),
            api_key: "sk-test".to_string(),
            model: "gpt-4o-mini".to_string(),
            max_tokens: 1024,
            temperature: 0.7,
            custom_headers: HashMap::new(),
        }
    }

    fn basic_request() -> ChatRequest {
        ChatRequest {
            messages: vec![ChatMessage {
                role: "user".to_string(),
                content: "hi".to_string(),
            }],
            max_tokens: 512,
            temperature: 0.5,
        }
    }

    // ---- OpenAI ----

    #[test]
    fn openai_build_request_url_is_chat_completions() {
        let req = build_request(&openai_config(), &basic_request()).unwrap();
        assert_eq!(req.url, "https://api.openai.com/v1/chat/completions");
    }

    #[test]
    fn openai_build_request_includes_bearer_auth() {
        let req = build_request(&openai_config(), &basic_request()).unwrap();
        assert_eq!(
            req.headers.get("Authorization").map(String::as_str),
            Some("Bearer sk-test")
        );
    }

    #[test]
    fn openai_build_request_body_has_model_messages_max_tokens() {
        let req = build_request(&openai_config(), &basic_request()).unwrap();
        assert_eq!(req.body["model"], "gpt-4o-mini");
        assert_eq!(req.body["messages"][0]["role"], "user");
        assert_eq!(req.body["messages"][0]["content"], "hi");
        assert_eq!(req.body["max_tokens"], 512);
        assert_eq!(req.body["temperature"], 0.5);
        assert_eq!(req.body["stream"], false);
    }

    #[test]
    fn openai_parse_response_extracts_content_and_usage() {
        let body = r#"{
            "id": "chatcmpl-1",
            "choices": [{"message": {"role": "assistant", "content": "hello"}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}
        }"#;
        let resp = parse_response(&Provider::OpenAI, body).unwrap();
        assert_eq!(resp.content, "hello");
        assert_eq!(resp.prompt_tokens, 10);
        assert_eq!(resp.completion_tokens, 5);
    }

    #[test]
    fn openai_parse_response_missing_choices_returns_err() {
        let body = r#"{"error": "bad request"}"#;
        assert!(parse_response(&Provider::OpenAI, body).is_err());
    }

    // ---- Anthropic ----

    #[test]
    fn anthropic_build_request_url_is_v1_messages() {
        let mut cfg = openai_config();
        cfg.provider = Provider::Anthropic;
        cfg.base_url = "https://api.anthropic.com".to_string();
        cfg.model = "claude-3-5-sonnet".to_string();
        let req = build_request(&cfg, &basic_request()).unwrap();
        assert_eq!(req.url, "https://api.anthropic.com/v1/messages");
    }

    #[test]
    fn anthropic_build_request_uses_x_api_key_and_anthropic_version() {
        let mut cfg = openai_config();
        cfg.provider = Provider::Anthropic;
        cfg.base_url = "https://api.anthropic.com".to_string();
        let req = build_request(&cfg, &basic_request()).unwrap();
        assert_eq!(req.headers.get("x-api-key").map(String::as_str), Some("sk-test"));
        assert_eq!(
            req.headers.get("anthropic-version").map(String::as_str),
            Some("2023-06-01")
        );
        assert!(!req.headers.contains_key("Authorization"));
    }

    #[test]
    fn anthropic_build_request_extracts_system_to_top_level() {
        let mut cfg = openai_config();
        cfg.provider = Provider::Anthropic;
        cfg.base_url = "https://api.anthropic.com".to_string();
        let req = ChatRequest {
            messages: vec![
                ChatMessage {
                    role: "system".to_string(),
                    content: "You are helpful".to_string(),
                },
                ChatMessage {
                    role: "user".to_string(),
                    content: "hi".to_string(),
                },
            ],
            max_tokens: 256,
            temperature: 0.0,
        };
        let http = build_request(&cfg, &req).unwrap();
        assert_eq!(http.body["system"], "You are helpful");
        assert_eq!(http.body["messages"][0]["role"], "user");
        assert!(http.body["messages"]
            .as_array()
            .unwrap()
            .iter()
            .all(|m| m["role"] != "system"));
    }

    #[test]
    fn anthropic_build_request_requires_api_key() {
        let mut cfg = openai_config();
        cfg.provider = Provider::Anthropic;
        cfg.base_url = "https://api.anthropic.com".to_string();
        cfg.api_key = String::new();
        assert!(build_request(&cfg, &basic_request()).is_err());
    }

    #[test]
    fn anthropic_parse_response_extracts_content_and_input_output_tokens() {
        let body = r#"{
            "id": "msg_1",
            "content": [{"type": "text", "text": "hi there"}],
            "usage": {"input_tokens": 12, "output_tokens": 7}
        }"#;
        let resp = parse_response(&Provider::Anthropic, body).unwrap();
        assert_eq!(resp.content, "hi there");
        assert_eq!(resp.prompt_tokens, 12);
        assert_eq!(resp.completion_tokens, 7);
    }

    // ---- Ollama ----

    #[test]
    fn ollama_build_request_url_uses_default_base() {
        let mut cfg = openai_config();
        cfg.provider = Provider::Ollama;
        cfg.base_url = "http://localhost:11434/v1".to_string();
        cfg.api_key = String::new();
        cfg.model = "llama3.1".to_string();
        let req = build_request(&cfg, &basic_request()).unwrap();
        assert_eq!(req.url, "http://localhost:11434/v1/chat/completions");
        // Ollama 不发 Authorization
        assert!(!req.headers.contains_key("Authorization"));
    }

    #[test]
    fn ollama_parse_response_uses_openai_compatible_format() {
        let body = r#"{
            "choices": [{"message": {"role": "assistant", "content": "from ollama"}}],
            "usage": {"prompt_tokens": 3, "completion_tokens": 4}
        }"#;
        let mut cfg = openai_config();
        cfg.provider = Provider::Ollama;
        let resp = parse_response(&cfg.provider, body).unwrap();
        assert_eq!(resp.content, "from ollama");
    }

    // ---- Custom ----

    #[test]
    fn custom_build_request_passes_through_custom_headers() {
        let mut cfg = openai_config();
        cfg.provider = Provider::Custom;
        cfg.base_url = "https://my-proxy.example.com/v1".to_string();
        cfg.custom_headers
            .insert("X-Org-ID".to_string(), "acme".to_string());
        let req = build_request(&cfg, &basic_request()).unwrap();
        assert_eq!(req.url, "https://my-proxy.example.com/v1/chat/completions");
        assert_eq!(req.headers.get("X-Org-ID").map(String::as_str), Some("acme"));
        // 仍然走 OpenAI 协议,带 Authorization
        assert_eq!(
            req.headers.get("Authorization").map(String::as_str),
            Some("Bearer sk-test")
        );
    }

    #[test]
    fn custom_parse_response_uses_openai_compatible_format() {
        let body = r#"{"choices": [{"message": {"content": "ok"}}]}"#;
        let mut cfg = openai_config();
        cfg.provider = Provider::Custom;
        let resp = parse_response(&cfg.provider, body).unwrap();
        assert_eq!(resp.content, "ok");
    }

    // ---- Dispatch ----

    #[test]
    fn build_request_dispatches_by_provider() {
        // 4 个 provider 都能 build 不出错
        for p in [Provider::OpenAI, Provider::Anthropic, Provider::Ollama, Provider::Custom] {
            let mut cfg = openai_config();
            cfg.provider = p.clone();
            if p == Provider::Ollama {
                cfg.api_key = String::new();
            }
            let r = build_request(&cfg, &basic_request());
            assert!(r.is_ok(), "{:?} build_request 失败: {:?}", p, r);
        }
    }
}
