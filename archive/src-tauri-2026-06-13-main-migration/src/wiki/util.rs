// Wiki utilities - path validation, file tree building, title extraction
use std::fs;
use std::path::{Path, PathBuf};

use crate::wiki::models::FileNode;

/// Validate that a path is within the wiki project directory.
/// Returns the canonicalized absolute path if valid, or an error if not.
pub fn validate_wiki_path(project_path: &str, target_path: &str) -> Result<PathBuf, String> {
    let project_root = Path::new(project_path)
        .canonicalize()
        .map_err(|e| format!("无法访问项目目录: {}", e))?;

    let full_path = if Path::new(target_path).is_absolute() {
        PathBuf::from(target_path)
    } else {
        project_root.join(target_path)
    };

    let canonical = full_path
        .canonicalize()
        .map_err(|e| format!("无法解析路径: {}", e))?;

    // Ensure the canonical path starts with the project root
    if !canonical.starts_with(&project_root) {
        return Err("路径超出项目目录范围".to_string());
    }

    Ok(canonical)
}

/// Validate that a new file path (not yet existing) would be within the project.
/// Returns the full path if valid.
pub fn validate_new_path(project_path: &str, target_path: &str) -> Result<PathBuf, String> {
    let project_root = Path::new(project_path)
        .canonicalize()
        .map_err(|e| format!("无法访问项目目录: {}", e))?;

    let full_path = if Path::new(target_path).is_absolute() {
        PathBuf::from(target_path)
    } else {
        project_root.join(target_path)
    };

    // For non-existing paths, verify parent is within project
    let parent = full_path.parent().ok_or("无效的文件路径")?;
    let mut check = parent;
    loop {
        if check.exists() {
            if let Ok(canon) = check.canonicalize() {
                if !canon.starts_with(&project_root) {
                    return Err("路径超出项目目录范围".to_string());
                }
            }
            break;
        }
        let Some(p) = check.parent() else {
            return Err("路径超出项目目录范围".to_string());
        };
        check = p;
    }

    Ok(full_path)
}

/// Build a file tree from a directory path.
pub fn build_file_tree(dir_path: &Path, project_root: &Path) -> Result<Vec<FileNode>, String> {
    let mut nodes = Vec::new();
    let entries = fs::read_dir(dir_path).map_err(|e| format!("无法读取目录: {}", e))?;

    let mut entries: Vec<_> = entries.filter_map(|e| e.ok()).collect();
    entries.sort_by(|a, b| {
        let a_is_dir = a.path().is_dir();
        let b_is_dir = b.path().is_dir();
        match (a_is_dir, b_is_dir) {
            (true, false) => std::cmp::Ordering::Less,
            (false, true) => std::cmp::Ordering::Greater,
            _ => a.file_name().cmp(&b.file_name()),
        }
    });

    for entry in entries {
        let path = entry.path();
        let name = entry.file_name().to_string_lossy().to_string();

        // Skip hidden files/directories
        if name.starts_with('.') {
            continue;
        }

        let rel_path = path
            .strip_prefix(project_root)
            .unwrap_or(&path)
            .to_string_lossy()
            .replace('\\', "/");

        let is_dir = path.is_dir();
        let children = if is_dir {
            Some(build_file_tree(&path, project_root)?)
        } else {
            None
        };

        nodes.push(FileNode {
            name,
            path: rel_path,
            is_dir,
            children,
        });
    }

    Ok(nodes)
}

/// Extract title from markdown content.
pub fn extract_title(content: &str) -> String {
    for line in content.lines() {
        let trimmed = line.trim();
        if trimmed.starts_with("# ") {
            return trimmed[2..].trim().to_string();
        }
        if trimmed.starts_with("## ") {
            return trimmed[3..].trim().to_string();
        }
        if trimmed == "---" {
            continue;
        }
        if !trimmed.is_empty() && !trimmed.starts_with("---") {
            return trimmed.chars().take(80).collect();
        }
    }
    "未命名页面".to_string()
}

/// Create the standard wiki project directory structure.
pub fn create_wiki_structure(project_path: &Path) -> Result<(), String> {
    let dirs = [
        "raw/sources",
        "raw/assets",
        "wiki/entities",
        "wiki/concepts",
        "wiki/sources",
        "wiki/queries",
    ];

    for dir in &dirs {
        fs::create_dir_all(project_path.join(dir))
            .map_err(|e| format!("无法创建目录 {}: {}", dir, e))?;
    }

    let schema_path = project_path.join("schema.md");
    if !schema_path.exists() {
        fs::write(
            &schema_path,
            "# Wiki Schema\n\n这个文档定义了 wiki 的结构、命名约定和工作流。\n\n## 页面类型\n\n- **entities/**: 实体页面（人物、组织、地点）\n- **concepts/**: 概念页面（理论、方法、思想）\n- **sources/**: 源文档摘要页面\n- **queries/**: 查询和分析结果页面\n\n## 命名约定\n\n- 使用 kebab-case 作为文件名\n- 使用中文作为页面标题\n\n## 工作流程\n\n1. **Ingest**: 将源文档放入 raw/sources/，然后运行导入\n2. **Query**: 针对 wiki 提问，答案可以保存为新的 wiki 页面\n3. **Lint**: 定期检查 wiki 的一致性\n",
        )
        .map_err(|e| format!("无法创建 schema.md: {}", e))?;
    }

    let overview_path = project_path.join("wiki/overview.md");
    if !overview_path.exists() {
        fs::write(
            &overview_path,
            "# Wiki 总览\n\n欢迎使用 LLM Wiki！这是一个持续演进的知识库。\n\n## 快速开始\n\n1. 导入源文档到 raw/sources/\n2. 运行导入，LLM 会自动生成 wiki 页面\n3. 浏览生成的页面，提出你的问题\n",
        )
        .map_err(|e| format!("无法创建 overview.md: {}", e))?;
    }

    let index_path = project_path.join("wiki/index.md");
    if !index_path.exists() {
        fs::write(
            &index_path,
            "# Wiki 索引\n\n## 总览\n- [总览](overview.md)\n\n## 实体\n_(暂无实体页面)_\n\n## 概念\n_(暂无概念页面)_\n\n## 源文档\n_(暂无源文档)_\n\n## 查询\n_(暂无查询结果)_\n",
        )
        .map_err(|e| format!("无法创建 index.md: {}", e))?;
    }

    let log_path = project_path.join("wiki/log.md");
    if !log_path.exists() {
        let today = chrono::Local::now().format("%Y-%m-%d");
        fs::write(
            &log_path,
            format!("# Wiki 活动日志\n\n## [{}] init | 项目初始化\n\n- 创建了 wiki 项目结构\n", today),
        )
        .map_err(|e| format!("无法创建 log.md: {}", e))?;
    }

    Ok(())
}

/// Update wiki index.md by scanning all wiki pages
pub fn update_wiki_index(project_path: &Path) -> Result<(), String> {
    let wiki_dir = project_path.join("wiki");
    if !wiki_dir.exists() {
        return Ok(());
    }

    let mut entities = Vec::new();
    let mut concepts = Vec::new();
    let mut sources = Vec::new();
    let mut queries = Vec::new();
    let mut other = Vec::new();

    // Scan top-level wiki markdown files
    if let Ok(entries) = fs::read_dir(&wiki_dir) {
        for entry in entries.filter_map(|e| e.ok()) {
            let path = entry.path();
            if path.extension().and_then(|s| s.to_str()) == Some("md") {
                let name = entry.file_name().to_string_lossy().to_string();
                if name == "index.md" || name == "log.md" {
                    continue;
                }
                let content = fs::read_to_string(&path).unwrap_or_default();
                let title = extract_title(&content);
                let rel_path = path
                    .strip_prefix(project_path)
                    .unwrap_or(&path)
                    .to_string_lossy()
                    .replace('\\', "/");
                other.push((title, rel_path));
            }
        }
    }

    // Scan subdirectories
    for subdir in &["entities", "concepts", "sources", "queries"] {
        let dir = wiki_dir.join(subdir);
        if !dir.exists() {
            continue;
        }
        if let Ok(entries) = fs::read_dir(&dir) {
            for entry in entries.filter_map(|e| e.ok()) {
                let path = entry.path();
                if path.extension().and_then(|s| s.to_str()) != Some("md") {
                    continue;
                }
                let content = fs::read_to_string(&path).unwrap_or_default();
                let title = extract_title(&content);
                let rel_path = path
                    .strip_prefix(project_path)
                    .unwrap_or(&path)
                    .to_string_lossy()
                    .replace('\\', "/");
                match *subdir {
                    "entities" => entities.push((title, rel_path)),
                    "concepts" => concepts.push((title, rel_path)),
                    "sources" => sources.push((title, rel_path)),
                    "queries" => queries.push((title, rel_path)),
                    _ => other.push((title, rel_path)),
                }
            }
        }
    }

    let mut index = String::from("# Wiki 索引\n\n");

    index.push_str("## 总览\n");
    if other.is_empty() {
        index.push_str("- [总览](overview.md)\n");
    } else {
        for (title, path) in &other {
            index.push_str(&format!("- [{}]({})\n", title, path));
        }
    }
    index.push('\n');

    let sections = [
        ("实体", &entities),
        ("概念", &concepts),
        ("源文档", &sources),
        ("查询", &queries),
    ];

    for (section_name, items) in &sections {
        index.push_str(&format!("## {}\n", section_name));
        if items.is_empty() {
            index.push_str(&format!("_(暂无{}页面)_\n\n", section_name));
        } else {
            for (title, path) in *items {
                index.push_str(&format!("- [{}]({})\n", title, path));
            }
            index.push('\n');
        }
    }

    fs::write(wiki_dir.join("index.md"), index)
        .map_err(|e| format!("无法更新 index.md: {}", e))
}

/// Append an entry to wiki log.md
pub fn append_log_entry(project_path: &Path, entry: &str) -> Result<(), String> {
    let log_path = project_path.join("wiki/log.md");
    let today = chrono::Local::now().format("%Y-%m-%d");
    let new_entry = format!("\n## [{}] {}\n", today, entry);

    if log_path.exists() {
        let mut content = fs::read_to_string(&log_path).unwrap_or_default();
        if let Some(pos) = content.find('\n') {
            content.insert_str(pos + 1, &new_entry);
            fs::write(&log_path, content).map_err(|e| format!("无法更新 log.md: {}", e))
        } else {
            fs::write(&log_path, format!("# Wiki 活动日志\n{}", new_entry))
                .map_err(|e| format!("无法更新 log.md: {}", e))
        }
    } else {
        fs::write(&log_path, format!("# Wiki 活动日志\n{}", new_entry))
            .map_err(|e| format!("无法创建 log.md: {}", e))
    }
}
