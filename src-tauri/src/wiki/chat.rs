// Wiki RAG chat - 完整 hybrid retrieval + LLM 综合
//
// 流程:
//   1. token search (search_wiki)
//   2. embed query + 向量 search (VectorStore::search)
//   3. RRF 融合 (rrf_fuse) → 取 top_k
//   4. 读 wiki 页面内容
//   5. token 预算 + truncate (ContextBudget)
//   6. 拼装 RAG prompt (RAG_SYSTEM + 截断后的 pages + query)
//   7. 调 LLM 综合回答
//   8. 返回 { answer, citations, stats }

use std::fs;
use std::path::Path;

use crate::wiki::context_budget::{truncate_pages, ContextBudget};
use crate::wiki::embeddings::{build_embed_request, parse_embed_response, EmbeddingConfig};
use crate::wiki::http::HttpClient;
use crate::wiki::llm_prompts::{format_rag_user_message, RAG_SYSTEM};
use crate::wiki::llm_provider::{
    build_request as build_chat_request, parse_response as parse_chat_response, ChatMessage,
    ChatRequest, LlmProviderConfig, Provider,
};
use crate::wiki::rrf::{rrf_fuse, DEFAULT_RRF_K};
use crate::wiki::search::search_wiki;
use crate::wiki::vectorstore::VectorStore;

// ============================================================================
// 类型
// ============================================================================

/// RAG 配置
#[derive(Debug, Clone)]
pub struct RagConfig {
    pub llm: LlmProviderConfig,
    pub embedding: EmbeddingConfig,
    /// LLM max_tokens,用于 token 预算
    pub max_tokens: u32,
    /// token search + 向量 search 各自取的命中数
    pub retrieval_limit: usize,
    /// 最终送入 LLM 的 top_k page 数
    pub final_top_k: usize,
}

impl Default for RagConfig {
    fn default() -> Self {
        Self {
            llm: LlmProviderConfig {
                provider: Provider::OpenAI,
                base_url: "https://api.openai.com/v1".to_string(),
                api_key: String::new(),
                model: "gpt-4o-mini".to_string(),
                max_tokens: 4096,
                temperature: 0.3,
                custom_headers: std::collections::HashMap::new(),
            },
            embedding: EmbeddingConfig {
                base_url: "https://api.openai.com/v1".to_string(),
                api_key: String::new(),
                model: "text-embedding-3-small".to_string(),
                dim: 1536,
            },
            max_tokens: 4096,
            retrieval_limit: 20,
            final_top_k: 5,
        }
    }
}

/// 检索统计(用于前端展示)
#[derive(Debug, Clone, Default, PartialEq)]
pub struct RetrievalStats {
    pub token_hits: usize,
    pub vector_hits: usize,
    pub fused_top_score: f64,
    pub total_context_tokens: u32,
}

/// RAG 输出
#[derive(Debug, Clone, PartialEq)]
pub struct WikiChatOutcome {
    pub answer: String,
    pub citations: Vec<String>,
    pub stats: RetrievalStats,
}

// ============================================================================
// 入口
// ============================================================================

/// 完整 RAG 管线
pub async fn chat_with_wiki(
    config: &RagConfig,
    http: &HttpClient,
    project_root: &Path,
    query: &str,
) -> Result<WikiChatOutcome, String> {
    // 1. token search
    let token_resp = search_wiki(project_root, query, config.retrieval_limit)?;
    let token_paths: Vec<String> = token_resp.results.iter().map(|r| r.path.clone()).collect();

    // 2. embed query + 向量 search
    let (vector_paths, vector_hits_count) =
        vector_search(config, http, project_root, query).await?;

    // 3. RRF 融合
    let fused = rrf_fuse(&token_paths, &vector_paths, DEFAULT_RRF_K);

    if fused.is_empty() {
        return Ok(WikiChatOutcome {
            answer: "未在 wiki 中找到相关内容。请先导入一些源文档,或者手动创建 wiki 页面。"
                .to_string(),
            citations: Vec::new(),
            stats: RetrievalStats {
                token_hits: token_paths.len(),
                vector_hits: vector_hits_count,
                fused_top_score: 0.0,
                total_context_tokens: 0,
            },
        });
    }

    // 4. 取 top_k fused
    let top_k: Vec<(String, f64)> = fused.into_iter().take(config.final_top_k).collect();
    let top_score = top_k.first().map(|(_, s)| *s).unwrap_or(0.0);

    // 5. 读 wiki 页面内容
    let mut pages: Vec<(String, String)> = Vec::new();
    let mut citations: Vec<String> = Vec::new();
    for (path, _) in &top_k {
        let full = project_root.join(path);
        if let Ok(content) = fs::read_to_string(&full) {
            citations.push(path.clone());
            pages.push((path.clone(), content));
        }
    }

    // 6. token 预算 + truncate
    let budget = ContextBudget::compute(config.max_tokens);
    let chunks = truncate_pages(&pages, &budget);
    let mut context = String::new();
    let mut total_context_tokens = 0u32;
    for chunk in &chunks {
        context.push_str(&format!(
            "\n--- 文件: {} ---\n{}\n",
            chunk.page_path, chunk.content
        ));
        total_context_tokens += ContextBudget::estimate_tokens(&chunk.content);
    }

    // 7. 拼装 RAG prompt
    let system = format!("{}{}", RAG_SYSTEM, context);
    let user = format_rag_user_message(query);
    let req = ChatRequest {
        messages: vec![
            ChatMessage {
                role: "system".to_string(),
                content: system,
            },
            ChatMessage {
                role: "user".to_string(),
                content: user,
            },
        ],
        max_tokens: budget.response_reserve,
        temperature: 0.3,
    };
    let http_req = build_chat_request(&config.llm, &req)?;
    let body = http
        .post_json(&http_req.url, &http_req.headers, &http_req.body)
        .await?;
    let resp = parse_chat_response(&config.llm.provider, &body)?;

    Ok(WikiChatOutcome {
        answer: resp.content,
        citations,
        stats: RetrievalStats {
            token_hits: token_paths.len(),
            vector_hits: vector_hits_count,
            fused_top_score: top_score,
            total_context_tokens,
        },
    })
}

// ============================================================================
// 辅助
// ============================================================================

async fn vector_search(
    config: &RagConfig,
    http: &HttpClient,
    project_root: &Path,
    query: &str,
) -> Result<(Vec<String>, usize), String> {
    let req = build_embed_request(&config.embedding, &[query.to_string()]);
    let body = http
        .post_json(&req.url, &req.headers, &req.body)
        .await?;
    let vectors = parse_embed_response(&body, config.embedding.dim)?;
    let query_vec = vectors.into_iter().next().ok_or("embedding 返回为空")?;

    let store = VectorStore::open(project_root, config.embedding.dim)?;
    let hits = store.search(&query_vec, config.retrieval_limit)?;
    let count = hits.len();
    let paths: Vec<String> = hits.into_iter().map(|h| h.page_path).collect();
    Ok((paths, count))
}

// ============================================================================
// Tests
// ============================================================================

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn rag_config_default_top_k() {
        let c = RagConfig::default();
        assert_eq!(c.final_top_k, 5);
        assert_eq!(c.retrieval_limit, 20);
    }

    #[test]
    fn retrieval_stats_default_is_zero() {
        let s = RetrievalStats::default();
        assert_eq!(s.token_hits, 0);
        assert_eq!(s.vector_hits, 0);
    }

    #[test]
    fn wiki_chat_outcome_partial_eq() {
        let a = WikiChatOutcome {
            answer: "hi".to_string(),
            citations: vec!["p1".to_string()],
            stats: RetrievalStats::default(),
        };
        let b = WikiChatOutcome {
            answer: "hi".to_string(),
            citations: vec!["p1".to_string()],
            stats: RetrievalStats::default(),
        };
        assert_eq!(a, b);
    }
}
