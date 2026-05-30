// Source ingestion pipeline
use std::fs;
use std::path::Path;

use crate::wiki::models::IngestResult;
use crate::wiki::util::{append_log_entry, extract_title, update_wiki_index};

/// Ingest a source document into the wiki.
/// Copies the source to raw/sources/, calls LLM to generate a wiki page.
pub async fn ingest_source(
    source_file_path: &str,
    project_root: &Path,
    _api_url: &str,
    _api_key: &str,
    _model: &str,
) -> Result<IngestResult, String> {
    let source_path = std::path::Path::new(source_file_path);
    if !source_path.exists() {
        return Err("源文件不存在".to_string());
    }

    let file_name = source_path
        .file_name()
        .ok_or("无法获取文件名")?
        .to_string_lossy()
        .to_string();

    // Copy to raw/sources/
    let dest_path = project_root.join("raw/sources").join(&file_name);
    fs::copy(source_path, &dest_path)
        .map_err(|e| format!("无法复制源文件: {}", e))?;

    let content = fs::read_to_string(&dest_path).map_err(|e| format!("无法读取源文件: {}", e))?;

    let slug = file_name
        .replace(".md", "")
        .replace(".txt", "")
        .replace(|c: char| !c.is_alphanumeric() && c != '-' && c != '_', "-")
        .to_lowercase();

    let wiki_page_path = format!("wiki/sources/{}.md", slug);
    let full_wiki_path = project_root.join(&wiki_page_path);

    // TODO: Call LLM to generate wiki page
    let title = extract_title(&content);
    let wiki_content = format!(
        "# {}\n\n> 源文件: {}\n\n## 摘要\n\n_(待 LLM 生成摘要)_\n\n## 原文\n\n```\n{}\n```\n",
        title,
        file_name,
        if content.len() > 5000 { &content[..5000] } else { &content }
    );

    fs::write(&full_wiki_path, wiki_content)
        .map_err(|e| format!("无法创建 wiki 页面: {}", e))?;

    update_wiki_index(project_root)?;
    append_log_entry(project_root, &format!("ingest | 导入 {}", file_name))?;

    Ok(IngestResult {
        source_path: format!("raw/sources/{}", file_name),
        wiki_page_path,
        page_type: "source".to_string(),
    })
}
