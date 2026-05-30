// Wiki Tauri commands
use std::fs;
use std::path::Path;

use tauri::command;

use crate::wiki::models::*;
use crate::wiki::util::*;

/// Create a new wiki project directory
#[command]
pub async fn create_wiki_project(name: String, base_path: String) -> Result<WikiProject, String> {
    let id = uuid::Uuid::new_v4().to_string();
    let project_path = Path::new(&base_path).join(&name);

    if project_path.exists() {
        return Err("该目录已存在，请选择其他名称或位置".to_string());
    }

    create_wiki_structure(&project_path)?;

    let path = project_path
        .to_string_lossy()
        .replace('\\', "/");

    Ok(WikiProject {
        id,
        name,
        path,
    })
}

/// Open an existing wiki project
#[command]
pub async fn open_wiki_project(path: String) -> Result<WikiProject, String> {
    let project_path = Path::new(&path);

    if !project_path.exists() {
        return Err("项目目录不存在".to_string());
    }

    if !project_path.join("schema.md").exists() && !project_path.join("wiki").exists() {
        return Err("这不是一个有效的 wiki 项目目录".to_string());
    }

    let canonical = project_path
        .canonicalize()
        .map_err(|e| format!("无法解析路径: {}", e))?;

    let name = canonical
        .file_name()
        .map(|n| n.to_string_lossy().to_string())
        .unwrap_or_else(|| "未命名项目".to_string());

    Ok(WikiProject {
        id: "local".to_string(),
        name,
        path: canonical.to_string_lossy().replace('\\', "/"),
    })
}

/// List files in a wiki directory path
#[command]
pub async fn wiki_list_directory(path: String, project_path: String) -> Result<Vec<FileNode>, String> {
    let canonical = validate_wiki_path(&project_path, &path)?;
    let project_root = Path::new(&project_path)
        .canonicalize()
        .map_err(|e| format!("无法访问项目目录: {}", e))?;

    build_file_tree(&canonical, &project_root)
}

/// Read a wiki file
#[command]
pub async fn wiki_read_file(path: String, project_path: String) -> Result<String, String> {
    let canonical = validate_wiki_path(&project_path, &path)?;

    if canonical.is_dir() {
        return Err("无法读取目录".to_string());
    }

    fs::read_to_string(&canonical).map_err(|e| format!("无法读取文件: {}", e))
}

/// Write a wiki file
#[command]
pub async fn wiki_write_file(path: String, content: String, project_path: String) -> Result<(), String> {
    let full_path = validate_new_path(&project_path, &path)?;

    if let Some(parent) = full_path.parent() {
        fs::create_dir_all(parent).map_err(|e| format!("无法创建目录: {}", e))?;
    }

    // Atomic write: write to temp file then rename
    let temp_path = full_path.with_extension("tmp");
    fs::write(&temp_path, &content).map_err(|e| format!("无法写入文件: {}", e))?;
    fs::rename(&temp_path, &full_path).map_err(|e| format!("无法保存文件: {}", e))?;

    // Update index if this is a wiki page
    if full_path.to_string_lossy().contains("wiki/")
        && full_path.extension().and_then(|s| s.to_str()) == Some("md")
        && full_path.file_name().and_then(|s| s.to_str()) != Some("index.md")
        && full_path.file_name().and_then(|s| s.to_str()) != Some("log.md")
    {
        let project_root = Path::new(&project_path)
            .canonicalize()
            .map_err(|e| format!("无法访问项目目录: {}", e))?;
        let _ = update_wiki_index(&project_root);
    }

    Ok(())
}

/// Delete a wiki file or directory
#[command]
pub async fn wiki_delete_file(path: String, project_path: String) -> Result<(), String> {
    let canonical = validate_wiki_path(&project_path, &path)?;
    let project_root = Path::new(&project_path)
        .canonicalize()
        .map_err(|_| String::new())
        .unwrap_or_default();

    if canonical == project_root {
        return Err("无法删除项目根目录".to_string());
    }

    if canonical.is_dir() {
        fs::remove_dir_all(&canonical).map_err(|e| format!("无法删除目录: {}", e))
    } else {
        fs::remove_file(&canonical).map_err(|e| format!("无法删除文件: {}", e))
    }
}

/// Rename/move a wiki file
#[command]
pub async fn wiki_rename_file(old_path: String, new_path: String, project_path: String) -> Result<(), String> {
    let old_canonical = validate_wiki_path(&project_path, &old_path)?;
    let new_full = validate_new_path(&project_path, &new_path)?;

    if let Some(parent) = new_full.parent() {
        fs::create_dir_all(parent).map_err(|e| format!("无法创建目录: {}", e))?;
    }

    fs::rename(&old_canonical, &new_full).map_err(|e| format!("无法重命名: {}", e))
}

/// Search wiki pages by query
#[command]
pub async fn wiki_search(
    query: String,
    project_path: String,
    limit: Option<usize>,
) -> Result<SearchResponse, String> {
    use crate::wiki::search::search_wiki;

    let project_root = Path::new(&project_path)
        .canonicalize()
        .map_err(|e| format!("无法访问项目目录: {}", e))?;

    search_wiki(&project_root, &query, limit.unwrap_or(20))
}

/// Ingest a source document into the wiki
#[command]
pub async fn wiki_ingest_source(
    source_file_path: String,
    project_path: String,
    api_url: String,
    api_key: String,
    model: String,
) -> Result<IngestResult, String> {
    use crate::wiki::ingest::ingest_source;

    let project_root = Path::new(&project_path)
        .canonicalize()
        .map_err(|e| format!("无法访问项目目录: {}", e))?;

    ingest_source(&source_file_path, &project_root, &api_url, &api_key, &model).await
}

/// Chat with the wiki
#[command]
pub async fn wiki_chat(
    query: String,
    project_path: String,
    api_url: String,
    api_key: String,
    model: String,
) -> Result<WikiChatResponse, String> {
    use crate::wiki::chat::chat_with_wiki;

    let project_root = Path::new(&project_path)
        .canonicalize()
        .map_err(|e| format!("无法访问项目目录: {}", e))?;

    chat_with_wiki(&project_root, &query, &api_url, &api_key, &model).await
}
