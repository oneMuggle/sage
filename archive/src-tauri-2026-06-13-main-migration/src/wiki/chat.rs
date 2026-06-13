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

/// 流式 chunk 回调(用于 wiki_chat_stream)
pub type ChatStreamChunkFn<'a> = &'a mut dyn FnMut(&str);

/// Chat 检索+上下文构造(纯函数,不调 LLM,便于复用 + 测试)
pub struct ChatContext {
    pub context: String,
    pub citations: Vec<String>,
    pub stats: RetrievalStats,
}

/// 构造 RAG context(检索 + 拼装 prompt,但不调 LLM)
pub async fn build_chat_context(
    config: &RagConfig,
    http: &HttpClient,
    project_root: &Path,
    query: &str,
) -> Result<(ChatContext, ChatRequest), String> {
    let token_resp = search_wiki(project_root, query, config.retrieval_limit)?;
    let token_paths: Vec<String> = token_resp.results.iter().map(|r| r.path.clone()).collect();

    let (vector_paths, vector_hits_count) =
        vector_search(config, http, project_root, query).await?;

    let fused = rrf_fuse(&token_paths, &vector_paths, DEFAULT_RRF_K);

    if fused.is_empty() {
        let ctx = ChatContext {
            context: String::new(),
            citations: Vec::new(),
            stats: RetrievalStats {
                token_hits: token_paths.len(),
                vector_hits: vector_hits_count,
                fused_top_score: 0.0,
                total_context_tokens: 0,
            },
        };
        let req = ChatRequest {
            messages: vec![ChatMessage {
                role: "user".to_string(),
                content: "未在 wiki 中找到相关内容。请先导入一些源文档,或者手动创建 wiki 页面。".to_string(),
            }],
            max_tokens: 1024,
            temperature: 0.3,
        };
        return Ok((ctx, req));
    }

    let top_k: Vec<(String, f64)> = fused.into_iter().take(config.final_top_k).collect();
    let top_score = top_k.first().map(|(_, s)| *s).unwrap_or(0.0);

    let mut pages: Vec<(String, String)> = Vec::new();
    let mut citations: Vec<String> = Vec::new();
    for (path, _) in &top_k {
        let full = project_root.join(path);
        if let Ok(content) = fs::read_to_string(&full) {
            citations.push(path.clone());
            pages.push((path.clone(), content));
        }
    }

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
    let ctx = ChatContext {
        context,
        citations,
        stats: RetrievalStats {
            token_hits: token_paths.len(),
            vector_hits: vector_hits_count,
            fused_top_score: top_score,
            total_context_tokens,
        },
    };
    Ok((ctx, req))
}

// ============================================================================
// 入口
// ============================================================================

/// 完整 RAG 管线(非流式,返回完整回答)
pub async fn chat_with_wiki(
    config: &RagConfig,
    http: &HttpClient,
    project_root: &Path,
    query: &str,
) -> Result<WikiChatOutcome, String> {
    let (ctx, req) = build_chat_context(config, http, project_root, query).await?;
    if ctx.citations.is_empty() && ctx.context.is_empty() {
        return Ok(WikiChatOutcome {
            answer: "未在 wiki 中找到相关内容。请先导入一些源文档,或者手动创建 wiki 页面。"
                .to_string(),
            citations: Vec::new(),
            stats: ctx.stats,
        });
    }
    let http_req = build_chat_request(&config.llm, &req)?;
    let body = http
        .post_json(&http_req.url, &http_req.headers, &http_req.body)
        .await?;
    let resp = parse_chat_response(&config.llm.provider, &body)?;
    Ok(WikiChatOutcome {
        answer: resp.content,
        citations: ctx.citations,
        stats: ctx.stats,
    })
}

/// 流式 RAG 管线(用 chunk 回调推送每个 token)
/// 注意:MVP 用非流式 LLM 端点,一次性返回完整内容,然后 chunk 模拟流(逐段推送)。
/// 真正流式 SSE 解析留 Phase 8 E2E 验证或后续优化。
pub async fn chat_with_wiki_stream(
    config: &RagConfig,
    http: &HttpClient,
    project_root: &Path,
    query: &str,
    on_chunk: &mut ChatStreamChunkFn<'_>,
) -> Result<WikiChatOutcome, String> {
    let (ctx, req) = build_chat_context(config, http, project_root, query).await?;
    if ctx.citations.is_empty() && ctx.context.is_empty() {
        let msg = "未在 wiki 中找到相关内容。请先导入一些源文档,或者手动创建 wiki 页面。";
        on_chunk(msg);
        return Ok(WikiChatOutcome {
            answer: msg.to_string(),
            citations: Vec::new(),
            stats: ctx.stats,
        });
    }
    let http_req = build_chat_request(&config.llm, &req)?;
    let body = http
        .post_json(&http_req.url, &http_req.headers, &http_req.body)
        .await?;
    let resp = parse_chat_response(&config.llm.provider, &body)?;

    // 模拟流:每 30 字符一个 chunk
    let mut acc = String::new();
    let chars: Vec<char> = resp.content.chars().collect();
    for chunk in chars.chunks(30) {
        let s: String = chunk.iter().collect();
        acc.push_str(&s);
        on_chunk(&s);
    }
    Ok(WikiChatOutcome {
        answer: acc,
        citations: ctx.citations,
        stats: ctx.stats,
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
