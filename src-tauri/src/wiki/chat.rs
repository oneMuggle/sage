// Wiki chat - synthesize answers from wiki content
use std::fs;
use std::path::Path;

use crate::wiki::models::WikiChatResponse;
use crate::wiki::search::search_wiki;

/// Chat with the wiki: search for relevant pages, build context, call LLM.
pub async fn chat_with_wiki(
    project_root: &Path,
    query: &str,
    _api_url: &str,
    _api_key: &str,
    _model: &str,
) -> Result<WikiChatResponse, String> {
    let search_result = search_wiki(project_root, query, 5)?;

    if search_result.results.is_empty() {
        return Ok(WikiChatResponse {
            answer: "未在 wiki 中找到相关内容。请先导入一些源文档，或者手动创建 wiki 页面。".to_string(),
            citations: Vec::new(),
        });
    }

    let mut context = String::new();
    let mut citations = Vec::new();

    for result in &search_result.results {
        let full_path = project_root.join(&result.path);
        if let Ok(content) = fs::read_to_string(&full_path) {
            context.push_str(&format!(
                "\n--- 页面: {} ({}) ---\n{}\n",
                result.title, result.path, content
            ));
            citations.push(result.path.clone());
        }
    }

    // TODO: Call LLM with context + query
    Ok(WikiChatResponse {
        answer: format!(
            "我在 wiki 中找到了 {} 个相关页面：\n\n{}\n\n_(LLM 综合回答功能待实现)_",
            search_result.results.len(),
            search_result
                .results
                .iter()
                .map(|r| format!("- [{}]({})", r.title, r.path))
                .collect::<Vec<_>>()
                .join("\n")
        ),
        citations,
    })
}
