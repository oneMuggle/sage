// Wiki full-text search engine with CJK support
use std::fs;
use std::path::Path;

use crate::wiki::models::{SearchResponse, SearchResult};
use crate::wiki::util::extract_title;

/// Tokenize a query string, handling CJK characters as individual tokens.
fn tokenize_query(query: &str) -> Vec<String> {
    let query = query.to_lowercase();
    let mut tokens = Vec::new();
    let mut current_word = String::new();

    for ch in query.chars() {
        if ch.is_whitespace() || ch.is_ascii_punctuation() {
            if !current_word.is_empty() {
                tokens.push(current_word.clone());
                current_word.clear();
            }
        } else if is_cjk(ch) {
            if !current_word.is_empty() {
                tokens.push(current_word.clone());
                current_word.clear();
            }
            tokens.push(ch.to_string());
        } else {
            current_word.push(ch);
        }
    }

    if !current_word.is_empty() {
        tokens.push(current_word);
    }

    tokens.retain(|t| !is_stop_word(t));
    tokens
}

fn is_cjk(ch: char) -> bool {
    let cp = ch as u32;
    (0x4E00..=0x9FFF).contains(&cp)
        || (0x3400..=0x4DBF).contains(&cp)
        || (0xF900..=0xFAFF).contains(&cp)
}

fn is_stop_word(word: &str) -> bool {
    matches!(
        word,
        "的" | "了" | "是" | "在" | "我" | "有" | "和" | "就" | "不" | "人" | "都" | "一"
            | "一个" | "上" | "也" | "很" | "到" | "说" | "要" | "去" | "你" | "会" | "着"
            | "没有" | "看" | "好" | "自己" | "这" | "那" | "吗" | "呢" | "啊" | "哦" | ""
            | "the" | "a" | "an" | "is" | "are" | "was" | "were" | "be" | "been" | "being"
            | "have" | "has" | "had" | "do" | "does" | "did" | "will" | "would" | "could"
            | "should" | "may" | "might" | "shall" | "can" | "to" | "of" | "in" | "for"
            | "on" | "with" | "at" | "by" | "from" | "as" | "into" | "through" | "during"
            | "before" | "after" | "and" | "but" | "or" | "nor" | "not" | "so" | "yet"
            | "both" | "either" | "neither" | "each" | "every" | "all" | "any" | "few"
            | "more" | "most" | "other" | "some" | "such" | "no" | "only" | "own" | "same"
            | "than" | "too" | "very" | "just" | "because" | "if" | "when" | "where"
            | "which" | "who" | "whom" | "what" | "that" | "this" | "these" | "those"
            | "it" | "its"
    )
}

pub fn search_wiki(
    project_root: &Path,
    query: &str,
    limit: usize,
) -> Result<SearchResponse, String> {
    let wiki_dir = project_root.join("wiki");
    if !wiki_dir.exists() {
        return Ok(SearchResponse {
            results: Vec::new(),
            total: 0,
        });
    }

    let tokens = tokenize_query(query);
    if tokens.is_empty() {
        return Ok(SearchResponse {
            results: Vec::new(),
            total: 0,
        });
    }

    let mut all_results = Vec::new();
    let mut md_files = Vec::new();
    collect_markdown_files(&wiki_dir, &mut md_files);

    for file_path in &md_files {
        let content = fs::read_to_string(file_path).unwrap_or_default();
        let title = extract_title(&content);
        let content_lower = content.to_lowercase();

        let mut score = 0.0f64;
        let mut best_snippet = String::new();

        for (i, token) in tokens.iter().enumerate() {
            let token_weight = if i == 0 { 1.5 } else { 1.0 };

            if title.to_lowercase().contains(token) {
                score += 10.0 * token_weight;
            }

            let mut positions = Vec::new();
            let mut start = 0;
            while let Some(pos) = content_lower[start..].find(token) {
                positions.push(start + pos);
                start += pos + token.len();
                if start >= content_lower.len() {
                    break;
                }
            }

            if !positions.is_empty() {
                score += positions.len() as f64 * 0.5 * token_weight;

                if best_snippet.is_empty() {
                    let pos = positions[0];
                    let snippet_start = pos.saturating_sub(80);
                    let snippet_end = (pos + token.len() + 120).min(content.len());
                    let snippet = &content[snippet_start..snippet_end];
                    let snippet = snippet
                        .replace('\n', " ")
                        .replace('\r', "")
                        .chars()
                        .filter(|c| !c.is_control())
                        .collect::<String>();
                    let prefix = if snippet_start > 0 { "..." } else { "" };
                    let suffix = if snippet_end < content.len() { "..." } else { "" };
                    best_snippet = format!("{}{}{}", prefix, snippet, suffix);
                }
            }
        }

        if score > 0.0 {
            let rel_path = file_path
                .strip_prefix(project_root)
                .unwrap_or(file_path)
                .to_string_lossy()
                .replace('\\', "/");

            if best_snippet.is_empty() {
                best_snippet = content.chars().take(200).collect::<String>().replace('\n', " ");
            }

            all_results.push(SearchResult {
                path: rel_path,
                title,
                snippet: best_snippet,
                score,
            });
        }
    }

    all_results.sort_by(|a, b| b.score.partial_cmp(&a.score).unwrap_or(std::cmp::Ordering::Equal));
    let total = all_results.len();
    all_results.truncate(limit);

    Ok(SearchResponse {
        results: all_results,
        total,
    })
}

fn collect_markdown_files(dir: &Path, files: &mut Vec<std::path::PathBuf>) {
    if let Ok(entries) = fs::read_dir(dir) {
        for entry in entries.filter_map(|e| e.ok()) {
            let path = entry.path();
            if path.is_dir() {
                let name = entry.file_name().to_string_lossy().to_string();
                if name.starts_with('.') {
                    continue;
                }
                collect_markdown_files(&path, files);
            } else if path.extension().and_then(|s| s.to_str()) == Some("md") {
                let name = entry.file_name().to_string_lossy().to_string();
                if name == "index.md" || name == "log.md" || name == "schema.md" {
                    continue;
                }
                files.push(path);
            }
        }
    }
}
