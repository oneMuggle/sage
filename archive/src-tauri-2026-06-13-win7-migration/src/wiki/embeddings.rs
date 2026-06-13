// Wiki Embedding 客户端 + chunk_markdown
//
// 设计要点:
// - build_request / parse_response 分离(同 llm_provider),便于单元测试
// - 实际 HTTP 调用由 Phase 4 写(用 reqwest),这里只构造请求
// - 兼容 OpenAI 格式(绝大多数 embedding 服务都兼容)
// - chunk_markdown 简单实现:按段落分 + 合并/切分到目标大小

use serde_json::{json, Value};

// ============================================================================
// 常量
// ============================================================================

/// 默认目标 chunk 字符数(~500 字符,在大多数 embedding 模型限制内)
pub const DEFAULT_CHUNK_SIZE: usize = 500;
/// 块间最小重叠字符数(避免切到关键句子)
pub const DEFAULT_CHUNK_OVERLAP: usize = 50;

// ============================================================================
// 公共类型
// ============================================================================

/// Embedding 请求配置
#[derive(Debug, Clone)]
pub struct EmbeddingConfig {
    pub base_url: String,
    pub api_key: String,
    pub model: String,
    /// 用于校验返回向量维度(默认 1536 维,text-embedding-3-small)
    pub dim: u32,
}

/// 构造的 HTTP 请求(同 llm_provider::HttpRequest 的简化版)
#[derive(Debug, Clone)]
pub struct EmbedHttpRequest {
    pub url: String,
    pub method: String,
    pub headers: std::collections::HashMap<String, String>,
    pub body: Value,
}

// ============================================================================
// chunk_markdown
// ============================================================================

/// 把 markdown 内容按段落切分为目标大小的字符串列表
///
/// 策略:
/// 1. 先按空行(\n\n)切成段落
/// 2. 合并过短段落(累加直到接近 target_chunk_size)
/// 3. 切分过长段落(按 target_chunk_size 强制切,带 overlap)
pub fn chunk_markdown(content: &str, target_chunk_size: usize) -> Vec<String> {
    chunk_markdown_with_overlap(content, target_chunk_size, DEFAULT_CHUNK_OVERLAP)
}

pub fn chunk_markdown_with_overlap(
    content: &str,
    target_chunk_size: usize,
    overlap: usize,
) -> Vec<String> {
    if content.trim().is_empty() {
        return Vec::new();
    }
    // 1. 按空行切段落
    let paragraphs: Vec<&str> = content.split("\n\n").map(|p| p.trim()).collect();
    let mut chunks: Vec<String> = Vec::new();
    let mut current = String::new();

    for p in paragraphs {
        if p.is_empty() {
            continue;
        }
        // 当前段落 + 已有 current 不超 target?合并
        let merged_len = current.len() + 2 + p.len(); // 2 for "\n\n"
        if merged_len <= target_chunk_size {
            if !current.is_empty() {
                current.push_str("\n\n");
            }
            current.push_str(p);
        } else {
            // current 满了,先 flush
            if !current.is_empty() {
                chunks.push(std::mem::take(&mut current));
            }
            // 段落本身可能比 target 大,需要切
            if p.len() > target_chunk_size {
                chunks.extend(split_long_paragraph(p, target_chunk_size, overlap));
            } else {
                current.push_str(p);
            }
        }
    }
    if !current.is_empty() {
        chunks.push(current);
    }
    chunks
}

fn split_long_paragraph(p: &str, size: usize, overlap: usize) -> Vec<String> {
    let chars: Vec<char> = p.chars().collect();
    let mut out = Vec::new();
    let mut start = 0;
    while start < chars.len() {
        let end = (start + size).min(chars.len());
        let slice: String = chars[start..end].iter().collect();
        out.push(slice);
        if end == chars.len() {
            break;
        }
        // 下一步:start += size - overlap (向前回退 overlap 字符)
        start += size.saturating_sub(overlap);
    }
    out
}

// ============================================================================
// build_embed_request
// ============================================================================

/// 构造 embedding HTTP 请求(OpenAI 兼容格式)
pub fn build_embed_request(
    config: &EmbeddingConfig,
    texts: &[String],
) -> EmbedHttpRequest {
    let url = format!("{}/embeddings", config.base_url.trim_end_matches('/'));
    let mut headers = std::collections::HashMap::new();
    if !config.api_key.is_empty() {
        headers.insert("Authorization".to_string(), format!("Bearer {}", config.api_key));
    }
    headers.insert("Content-Type".to_string(), "application/json".to_string());
    let body = json!({
        "model": config.model,
        "input": texts,
    });
    EmbedHttpRequest {
        url,
        method: "POST".to_string(),
        headers,
        body,
    }
}

/// 解析 OpenAI 兼容 embedding 响应
pub fn parse_embed_response(body: &str, expected_dim: u32) -> Result<Vec<Vec<f32>>, String> {
    let parsed: Value = serde_json::from_str(body)
        .map_err(|e| format!("embedding 响应不是合法 JSON: {}", e))?;
    let data = parsed["data"]
        .as_array()
        .ok_or_else(|| "embedding 响应缺少 data 数组".to_string())?;
    let mut out = Vec::with_capacity(data.len());
    for (i, item) in data.iter().enumerate() {
        let vec = item["embedding"]
            .as_array()
            .ok_or_else(|| format!("data[{}] 缺少 embedding 数组", i))?;
        let floats: Vec<f32> = vec
            .iter()
            .enumerate()
            .map(|(j, v)| {
                v.as_f64()
                    .ok_or_else(|| format!("data[{}].embedding[{}] 不是 float", i, j))
                    .map(|f| f as f32)
            })
            .collect::<Result<Vec<f32>, String>>()?;
        if expected_dim > 0 && floats.len() as u32 != expected_dim {
            return Err(format!(
                "data[{}] 向量维度 {} 与期望 {} 不匹配",
                i,
                floats.len(),
                expected_dim
            ));
        }
        out.push(floats);
    }
    Ok(out)
}

// ============================================================================
// Tests
// ============================================================================

#[cfg(test)]
mod tests {
    use super::*;

    // ---- chunk_markdown ----

    #[test]
    fn chunk_empty_returns_empty() {
        assert!(chunk_markdown("", 500).is_empty());
        assert!(chunk_markdown("   \n\n  ", 500).is_empty());
    }

    #[test]
    fn chunk_single_paragraph_returns_one() {
        let chunks = chunk_markdown("hello world", 500);
        assert_eq!(chunks.len(), 1);
        assert_eq!(chunks[0], "hello world");
    }

    #[test]
    fn chunk_short_paragraphs_merged() {
        let content = "para 1\n\npara 2\n\npara 3";
        let chunks = chunk_markdown(content, 500);
        // 3 个短段落应合并为 1 个 chunk
        assert_eq!(chunks.len(), 1);
        assert!(chunks[0].contains("para 1"));
        assert!(chunks[0].contains("para 2"));
        assert!(chunks[0].contains("para 3"));
    }

    #[test]
    fn chunk_long_content_splits_into_multiple() {
        // 10 段,每段 100 字符 → target 250 → 至少 4 块
        let p = "x".repeat(100);
        let content: Vec<String> = (0..10).map(|_| p.clone()).collect();
        let content = content.join("\n\n");
        let chunks = chunk_markdown(&content, 250);
        assert!(chunks.len() >= 4);
    }

    #[test]
    fn chunk_huge_paragraph_gets_split_with_overlap() {
        let p = "y".repeat(2000);
        let chunks = chunk_markdown(&p, 500);
        // 2000 / 500 = 4 段(无 overlap),或 5 段(有 50 overlap)
        assert!(chunks.len() >= 4);
        // 每块 ≤ 500
        for c in &chunks {
            assert!(c.len() <= 500);
        }
    }

    #[test]
    fn chunk_preserves_markdown_structure() {
        let content = "# Title\n\nFirst paragraph with **bold**.\n\n- item 1\n- item 2";
        let chunks = chunk_markdown(content, 500);
        assert_eq!(chunks.len(), 1);
        assert!(chunks[0].contains("# Title"));
        assert!(chunks[0].contains("**bold**"));
    }

    // ---- build_embed_request ----

    #[test]
    fn embed_request_url_and_auth() {
        let cfg = EmbeddingConfig {
            base_url: "https://api.openai.com/v1".to_string(),
            api_key: "sk-test".to_string(),
            model: "text-embedding-3-small".to_string(),
            dim: 1536,
        };
        let req = build_embed_request(&cfg, &["hello".to_string()]);
        assert_eq!(req.url, "https://api.openai.com/v1/embeddings");
        assert_eq!(
            req.headers.get("Authorization").map(String::as_str),
            Some("Bearer sk-test")
        );
        assert_eq!(req.body["model"], "text-embedding-3-small");
        assert_eq!(req.body["input"][0], "hello");
    }

    #[test]
    fn embed_request_omits_auth_when_no_key() {
        let cfg = EmbeddingConfig {
            base_url: "http://localhost:11434/v1".to_string(),
            api_key: String::new(),
            model: "nomic-embed-text".to_string(),
            dim: 768,
        };
        let req = build_embed_request(&cfg, &["x".to_string()]);
        assert!(!req.headers.contains_key("Authorization"));
    }

    #[test]
    fn embed_request_batch_input() {
        let cfg = EmbeddingConfig {
            base_url: "https://x".to_string(),
            api_key: "k".to_string(),
            model: "m".to_string(),
            dim: 0,
        };
        let texts: Vec<String> = (0..5).map(|i| format!("t{}", i)).collect();
        let req = build_embed_request(&cfg, &texts);
        let arr = req.body["input"].as_array().unwrap();
        assert_eq!(arr.len(), 5);
        assert_eq!(arr[3], "t3");
    }

    // ---- parse_embed_response ----

    #[test]
    fn parse_response_extracts_vectors() {
        let body = r#"{
            "data": [
                {"index": 0, "embedding": [0.1, 0.2, 0.3]},
                {"index": 1, "embedding": [0.4, 0.5, 0.6]}
            ]
        }"#;
        let vecs = parse_embed_response(body, 3).unwrap();
        assert_eq!(vecs.len(), 2);
        assert_eq!(vecs[0], vec![0.1, 0.2, 0.3]);
        assert_eq!(vecs[1], vec![0.4, 0.5, 0.6]);
    }

    #[test]
    fn parse_response_with_no_dim_check() {
        let body = r#"{"data": [{"embedding": [0.1]}]}"#;
        // dim=0 表示不校验
        let vecs = parse_embed_response(body, 0).unwrap();
        assert_eq!(vecs.len(), 1);
    }

    #[test]
    fn parse_response_wrong_dim_errors() {
        let body = r#"{"data": [{"embedding": [0.1, 0.2]}]}"#;
        let res = parse_embed_response(body, 3);
        assert!(res.is_err());
    }

    #[test]
    fn parse_response_invalid_json_errors() {
        let res = parse_embed_response("not json", 3);
        assert!(res.is_err());
    }

    #[test]
    fn parse_response_missing_data_errors() {
        let res = parse_embed_response(r#"{"error": "bad"}"#, 3);
        assert!(res.is_err());
    }
}
