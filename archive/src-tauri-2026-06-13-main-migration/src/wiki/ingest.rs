// Wiki source ingestion - LLM 驱动的两步 CoT
//
// 设计要点:
// - 两步 CoT:Step 1 (LLM 分析 JSON) → Step 2 (LLM 写作 markdown)
// - SHA256 增量缓存:未变更的源文件跳过 LLM 调用
// - 整合所有 Phase 1+2+3 模块:llm_provider / llm_prompts / embeddings / vectorstore / frontmatter
// - HTTP 调用通过 http::HttpClient(Phase 3.2)
//
// 流程:
//   1. 复制源到 raw/sources/
//   2. SHA256 缓存检查;命中 → skip
//   3. 读文件内容(限 max_content_chars)
//   4. Step 1: 调 LLM 提取 entities/concepts/tags/related_topics/summary
//   5. Step 2: 调 LLM 写完整 wiki 页面
//   6. 解析 frontmatter + body
//   7. 写 wiki/sources/{slug}.md
//   8. chunk_markdown + 嵌入 + 写 VectorStore
//   9. 更新 ingest-cache.json

use std::collections::HashMap;
use std::fs;
use std::path::{Path, PathBuf};

use chrono::Local;
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};

use crate::wiki::embeddings::{
    build_embed_request, chunk_markdown, parse_embed_response, EmbeddingConfig,
};
use crate::wiki::frontmatter::{parse as parse_frontmatter, ParsedDoc};
use crate::wiki::http::HttpClient;
use crate::wiki::llm_provider::{
    build_request as build_chat_request, parse_response as parse_chat_response, ChatMessage,
    ChatRequest, LlmProviderConfig,
};
use crate::wiki::llm_prompts::{format_step1_prompt, format_step2_prompt};
use crate::wiki::vectorstore::VectorStore;

// ============================================================================
// 类型
// ============================================================================

/// Ingest 配置
#[derive(Debug, Clone)]
pub struct IngestConfig {
    pub llm: LlmProviderConfig,
    pub embedding: EmbeddingConfig,
    /// 单源文件最大字符数(超出截断,默认 50KB)
    pub max_content_chars: usize,
}

/// Ingest 输出
#[derive(Debug, Clone, PartialEq)]
pub struct IngestOutcome {
    /// 复制后的相对路径
    pub source_path: String,
    /// 生成的 wiki 页面相对路径
    pub wiki_page_path: String,
    /// 页面类型(source/entity/concept/...)
    pub page_type: String,
    /// true = SHA256 命中,跳过 LLM 调用
    pub cached: bool,
}

/// 进度事件(用于 Tauri emit)
#[derive(Debug, Clone, PartialEq, Serialize)]
pub struct IngestProgress {
    /// 当前阶段名(copy_source / step1_analyze / step2_write / embedding / finalize)
    pub stage: String,
    /// 进度百分比 0-100
    pub percent: u8,
    /// 可选消息
    pub message: Option<String>,
}

/// 进度回调(无 → 不报进度)
pub type ProgressFn = Box<dyn Fn(IngestProgress) + Send + Sync>;

/// Step 1 分析结果(从 LLM 输出的 JSON 解析)
#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct Analysis {
    #[serde(default)]
    pub entities: Vec<AnalysisEntity>,
    #[serde(default)]
    pub concepts: Vec<AnalysisConcept>,
    #[serde(default)]
    pub tags: Vec<String>,
    #[serde(default)]
    pub related_topics: Vec<String>,
    #[serde(default)]
    pub summary: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct AnalysisEntity {
    pub name: String,
    #[serde(default)]
    pub entity_type: String,
    #[serde(default)]
    pub brief: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct AnalysisConcept {
    pub name: String,
    #[serde(default)]
    pub brief: String,
}

/// 缓存项
#[derive(Debug, Clone, Serialize, Deserialize)]
struct CacheEntry {
    sha256: String,
    wiki_page_path: String,
    page_type: String,
}

type Cache = HashMap<String, CacheEntry>;

// ============================================================================
// 入口
// ============================================================================

/// 完整 ingest 管线(异步,带可选进度回调)
pub async fn ingest_source(
    config: &IngestConfig,
    http: &HttpClient,
    project_root: &Path,
    source_file_path: &Path,
    progress: Option<ProgressFn>,
) -> Result<IngestOutcome, String> {
    if !source_file_path.exists() {
        return Err(format!("源文件不存在: {}", source_file_path.display()));
    }

    let report = |stage: &str, percent: u8, message: Option<String>| {
        if let Some(p) = &progress {
            p(IngestProgress {
                stage: stage.to_string(),
                percent,
                message,
            });
        }
    };

    report("started", 0, Some("开始导入".to_string()));

    // 1. 复制源到 raw/sources/
    let file_name = source_file_path
        .file_name()
        .ok_or("无法获取文件名")?
        .to_string_lossy()
        .to_string();
    let raw_sources_dir = project_root.join("raw/sources");
    fs::create_dir_all(&raw_sources_dir).map_err(|e| format!("创建 raw/sources 失败: {}", e))?;
    let dest = raw_sources_dir.join(&file_name);
    fs::copy(source_file_path, &dest).map_err(|e| format!("复制源文件失败: {}", e))?;
    let rel_source = format!("raw/sources/{}", file_name);
    report("copy_source", 10, None);

    // 2. SHA256 缓存检查
    let content = fs::read_to_string(&dest).map_err(|e| format!("读取源文件失败: {}", e))?;
    let truncated = if content.len() > config.max_content_chars {
        content[..config.max_content_chars].to_string()
    } else {
        content.clone()
    };
    let sha = compute_sha256(&content);

    let mut cache = read_cache(project_root);
    if let Some(entry) = cache.get(&rel_source) {
        if entry.sha256 == sha {
            report("completed", 100, Some("缓存命中,跳过".to_string()));
            return Ok(IngestOutcome {
                source_path: rel_source,
                wiki_page_path: entry.wiki_page_path.clone(),
                page_type: entry.page_type.clone(),
                cached: true,
            });
        }
    }

    // 3. Step 1: LLM 分析
    report("step1_analyze", 20, Some("调用 LLM 分析".to_string()));
    let step1_prompt = format_step1_prompt(&truncated);
    let step1_analysis = run_step1(config, http, &step1_prompt).await?;
    report("step1_analyze", 40, Some("分析完成".to_string()));

    // 4. Step 2: LLM 写作
    report("step2_write", 45, Some("调用 LLM 写作".to_string()));
    let slug = slugify(&file_name);
    let today = Local::now().format("%Y-%m-%d").to_string();
    let analysis_json = serde_json::to_string(&step1_analysis).unwrap_or_else(|_| "{}".to_string());
    let tags_csv = step1_analysis.tags.join(", ");
    let related_links = step1_analysis
        .related_topics
        .iter()
        .map(|t| format!("[[{}]]", t))
        .collect::<Vec<_>>()
        .join(" ");
    let step2_prompt = format_step2_prompt(
        &file_name,
        &truncated,
        &analysis_json,
        &tags_csv,
        &related_links,
        &today,
    );
    let step2_content = run_step2(config, http, &step2_prompt).await?;
    report("step2_write", 70, Some("写作完成".to_string()));

    // 5. 解析 LLM 输出,提取 frontmatter + body
    let parsed = parse_frontmatter(&step2_content);
    let page_type = parsed
        .frontmatter
        .page_type
        .clone()
        .unwrap_or_else(|| "source".to_string());

    // 6. 写 wiki/sources/{slug}.md
    let wiki_dir = project_root.join("wiki/sources");
    fs::create_dir_all(&wiki_dir).map_err(|e| format!("创建 wiki/sources 失败: {}", e))?;
    let wiki_page_path = format!("wiki/sources/{}.md", slug);
    let full_wiki_path = project_root.join(&wiki_page_path);
    let final_doc = ParsedDoc {
        frontmatter: parsed.frontmatter,
        body: parsed.body,
    };
    let final_md = crate::wiki::frontmatter::serialize(&final_doc);
    write_atomic(&full_wiki_path, &final_md)?;

    // 7. 嵌入 + VectorStore
    report("embedding", 80, Some("嵌入 + 写向量库".to_string()));
    embed_and_store(config, http, project_root, &wiki_page_path, &final_md).await?;
    report("embedding", 90, Some("嵌入完成".to_string()));

    // 8. 更新缓存
    cache.insert(
        rel_source.clone(),
        CacheEntry {
            sha256: sha,
            wiki_page_path: wiki_page_path.clone(),
            page_type: page_type.clone(),
        },
    );
    write_cache(project_root, &cache)?;

    report("completed", 100, Some("导入完成".to_string()));
    Ok(IngestOutcome {
        source_path: rel_source,
        wiki_page_path,
        page_type,
        cached: false,
    })
}

// ============================================================================
// Step 1 / Step 2 辅助
// ============================================================================

async fn run_step1(
    config: &IngestConfig,
    http: &HttpClient,
    prompt: &str,
) -> Result<Analysis, String> {
    let req = ChatRequest {
        messages: vec![
            ChatMessage {
                role: "system".to_string(),
                content: "You are a JSON-only assistant. Output strict JSON.".to_string(),
            },
            ChatMessage {
                role: "user".to_string(),
                content: prompt.to_string(),
            },
        ],
        max_tokens: config.llm.max_tokens,
        temperature: 0.0,
    };
    let http_req = build_chat_request(&config.llm, &req)?;
    let body = http
        .post_json(&http_req.url, &http_req.headers, &http_req.body)
        .await?;
    let resp = parse_chat_response(&config.llm.provider, &body)?;
    parse_analysis_json(&resp.content)
}

/// 宽松解析 LLM 输出的 JSON(可能包在 ```json ... ``` 中或前后有杂文本)
fn parse_analysis_json(content: &str) -> Result<Analysis, String> {
    let trimmed = content.trim();
    // 提取首个 `{` 到最后 `}` 之间的内容
    let start = trimmed
        .find('{')
        .ok_or("Step 1 输出未包含 JSON 对象")?;
    let end = trimmed.rfind('}').ok_or("Step 1 输出未包含完整 JSON")?;
    if end <= start {
        return Err("Step 1 输出 JSON 格式错误".to_string());
    }
    let json_str = &trimmed[start..=end];
    serde_json::from_str(json_str).map_err(|e| format!("Step 1 JSON 解析失败: {}", e))
}

async fn run_step2(
    config: &IngestConfig,
    http: &HttpClient,
    prompt: &str,
) -> Result<String, String> {
    let req = ChatRequest {
        messages: vec![ChatMessage {
            role: "user".to_string(),
            content: prompt.to_string(),
        }],
        max_tokens: config.llm.max_tokens,
        temperature: 0.3,
    };
    let http_req = build_chat_request(&config.llm, &req)?;
    let body = http
        .post_json(&http_req.url, &http_req.headers, &http_req.body)
        .await?;
    let resp = parse_chat_response(&config.llm.provider, &body)?;
    Ok(resp.content)
}

async fn embed_and_store(
    config: &IngestConfig,
    http: &HttpClient,
    project_root: &Path,
    page_path: &str,
    page_content: &str,
) -> Result<(), String> {
    let chunks = chunk_markdown(page_content, 500);
    if chunks.is_empty() {
        return Ok(());
    }
    let embed_req = build_embed_request(&config.embedding, &chunks);
    let body = http
        .post_json(&embed_req.url, &embed_req.headers, &embed_req.body)
        .await?;
    let vectors = parse_embed_response(&body, config.embedding.dim)?;

    // upsert 到 VectorStore
    let mut store = VectorStore::open(project_root, config.embedding.dim)?;
    let chunk_data: Vec<(u32, String, Vec<f32>)> = chunks
        .into_iter()
        .enumerate()
        .zip(vectors.into_iter())
        .map(|((idx, text), vec)| (idx as u32, text, vec))
        .collect();
    store.upsert_chunks(page_path, &chunk_data)?;
    Ok(())
}

// ============================================================================
// 工具函数
// ============================================================================

/// 计算字符串的 SHA256 十六进制摘要
pub fn compute_sha256(content: &str) -> String {
    let mut hasher = Sha256::new();
    hasher.update(content.as_bytes());
    let result = hasher.finalize();
    result.iter().map(|b| format!("{:02x}", b)).collect()
}

/// 文件名转 URL-safe slug(去扩展名 + 小写 + 替换非字母数字)
pub fn slugify(filename: &str) -> String {
    let stem = filename
        .strip_suffix(".md")
        .or_else(|| filename.strip_suffix(".txt"))
        .or_else(|| filename.strip_suffix(".markdown"))
        .unwrap_or(filename);
    let mut out = String::new();
    let mut prev_dash = false;
    for ch in stem.chars() {
        if ch.is_alphanumeric() {
            for low in ch.to_lowercase() {
                out.push(low);
            }
            prev_dash = false;
        } else if !prev_dash {
            out.push('-');
            prev_dash = true;
        }
    }
    out.trim_matches('-').to_string()
}

/// 原子写文件(临时文件 + rename)
fn write_atomic(path: &Path, content: &str) -> Result<(), String> {
    if let Some(parent) = path.parent() {
        fs::create_dir_all(parent).map_err(|e| format!("创建目录失败: {}", e))?;
    }
    let tmp = path.with_extension("md.tmp");
    fs::write(&tmp, content).map_err(|e| format!("写临时文件失败: {}", e))?;
    fs::rename(&tmp, path).map_err(|e| format!("rename 失败: {}", e))?;
    Ok(())
}

fn cache_path(project_root: &Path) -> PathBuf {
    project_root.join(".llm-wiki/ingest-cache.json")
}

fn read_cache(project_root: &Path) -> Cache {
    let p = cache_path(project_root);
    if !p.exists() {
        return HashMap::new();
    }
    let body = fs::read_to_string(&p).unwrap_or_default();
    serde_json::from_str(&body).unwrap_or_default()
}

fn write_cache(project_root: &Path, cache: &Cache) -> Result<(), String> {
    let p = cache_path(project_root);
    if let Some(parent) = p.parent() {
        fs::create_dir_all(parent).map_err(|e| format!("创建 .llm-wiki 目录失败: {}", e))?;
    }
    let json = serde_json::to_string_pretty(cache)
        .map_err(|e| format!("序列化缓存失败: {}", e))?;
    let tmp = p.with_extension("json.tmp");
    fs::write(&tmp, json).map_err(|e| format!("写缓存失败: {}", e))?;
    fs::rename(&tmp, &p).map_err(|e| format!("rename 缓存失败: {}", e))?;
    Ok(())
}

// ============================================================================
// Tests
// ============================================================================

#[cfg(test)]
mod tests {
    use super::*;
    use std::env;

    // ---- 工具函数 ----

    #[test]
    fn sha256_of_empty_string() {
        assert_eq!(
            compute_sha256(""),
            "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
        );
    }

    #[test]
    fn sha256_of_hello() {
        assert_eq!(
            compute_sha256("hello"),
            "2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824"
        );
    }

    #[test]
    fn slugify_basic() {
        assert_eq!(slugify("Albert Einstein.md"), "albert-einstein");
        assert_eq!(slugify("hello world.txt"), "hello-world");
    }

    #[test]
    fn slugify_special_chars() {
        assert_eq!(slugify("What is AI?.md"), "what-is-ai");
        assert_eq!(slugify("__test__"), "test");
    }

    #[test]
    fn slugify_chinese_kept() {
        // 中文字符保留
        assert_eq!(slugify("爱因斯坦.md"), "爱因斯坦");
    }

    #[test]
    fn slugify_consecutive_separators_collapse() {
        assert_eq!(slugify("a   b.md"), "a-b");
        assert_eq!(slugify("a---b.md"), "a-b");
    }

    // ---- JSON 宽松解析 ----

    #[test]
    fn parse_step1_strict_json() {
        let content = r#"{"entities":[{"name":"A","entity_type":"person","brief":"x"}],"tags":["t1"],"summary":"s"}"#;
        let a = parse_analysis_json(content).unwrap();
        assert_eq!(a.tags, vec!["t1"]);
        assert_eq!(a.entities.len(), 1);
    }

    #[test]
    fn parse_step1_with_markdown_fence() {
        let content = "```json\n{\"tags\":[\"x\"],\"summary\":\"y\"}\n```";
        let a = parse_analysis_json(content).unwrap();
        assert_eq!(a.tags, vec!["x"]);
    }

    #[test]
    fn parse_step1_with_preamble() {
        let content = "Sure! Here is the JSON:\n\n{\"tags\":[\"a\"]}";
        let a = parse_analysis_json(content).unwrap();
        assert_eq!(a.tags, vec!["a"]);
    }

    #[test]
    fn parse_step1_invalid_json_errors() {
        let content = "not json at all";
        assert!(parse_analysis_json(content).is_err());
    }

    // ---- 缓存 ----

    #[test]
    fn cache_roundtrip() {
        let dir = env::temp_dir().join(format!("sage-wiki-ingest-test-{}", std::process::id()));
        let _ = fs::remove_dir_all(&dir);
        fs::create_dir_all(&dir).unwrap();

        let mut cache = Cache::new();
        cache.insert(
            "raw/sources/a.md".to_string(),
            CacheEntry {
                sha256: "abc".to_string(),
                wiki_page_path: "wiki/sources/a.md".to_string(),
                page_type: "source".to_string(),
            },
        );
        write_cache(&dir, &cache).unwrap();

        let loaded = read_cache(&dir);
        assert_eq!(loaded.len(), 1);
        assert_eq!(loaded["raw/sources/a.md"].sha256, "abc");
    }

    #[test]
    fn read_cache_when_missing_returns_empty() {
        let dir = env::temp_dir().join(format!("sage-wiki-missing-cache-{}", std::process::id()));
        let _ = fs::remove_dir_all(&dir);
        fs::create_dir_all(&dir).unwrap();
        let cache = read_cache(&dir);
        assert!(cache.is_empty());
    }
}
