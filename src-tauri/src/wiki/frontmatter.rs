// Wiki frontmatter 解析 + wikilink 提取
//
// 设计要点:
// - 极简 YAML 子集解析:只支持 string / [a, b, c] / 多行
// - 不引 serde_yaml(减少依赖)
// - 字段集合:title, type, tags, related, sources, created, updated
// - wikilink 提取支持 [[X]] 和 [[X|Y]]

use std::collections::HashMap;

// ============================================================================
// 类型
// ============================================================================

/// 解析后的 frontmatter
#[derive(Debug, Clone, PartialEq, Default)]
pub struct Frontmatter {
    pub title: Option<String>,
    pub page_type: Option<String>,
    pub tags: Vec<String>,
    pub related: Vec<String>,
    pub sources: Vec<String>,
    pub created: Option<String>,
    pub updated: Option<String>,
    /// 未知字段(透传保留)
    pub extra: HashMap<String, String>,
}

/// 解析结果:(frontmatter, body)
#[derive(Debug, Clone, PartialEq)]
pub struct ParsedDoc {
    pub frontmatter: Frontmatter,
    pub body: String,
}

// ============================================================================
// 解析
// ============================================================================

/// 解析 `---\n...\n---\nbody` 格式
pub fn parse(content: &str) -> ParsedDoc {
    // 找前导 `---` 起始
    if !content.starts_with("---\n") && content != "---" {
        return ParsedDoc {
            frontmatter: Frontmatter::default(),
            body: content.to_string(),
        };
    }
    // 找第二个 `---` 结束
    let after_first = if content == "---" { "" } else { &content[4..] };
    let close = after_first.find("\n---");
    let (yaml, body) = match close {
        Some(pos) => {
            let yaml = &after_first[..pos];
            // body 跳过 `---` 和后续最多 2 个换行(对应 `---\n\n` 模式)
            let rest = &after_first[pos + 4..];
            let body = rest
                .strip_prefix('\n')
                .unwrap_or(rest)
                .strip_prefix('\n')
                .unwrap_or(rest.strip_prefix('\n').unwrap_or(rest))
                .to_string();
            (yaml, body)
        }
        None => return ParsedDoc {
            frontmatter: Frontmatter::default(),
            body: content.to_string(),
        },
    };
    let frontmatter = parse_yaml_subset(yaml);
    ParsedDoc { frontmatter, body }
}

fn parse_yaml_subset(yaml: &str) -> Frontmatter {
    let mut fm = Frontmatter::default();
    for line in yaml.lines() {
        let line = line.trim_end();
        if line.is_empty() || line.starts_with('#') {
            continue;
        }
        let Some((key, value)) = line.split_once(':') else {
            continue;
        };
        let key = key.trim();
        let value = value.trim();
        match key {
            "title" => fm.title = Some(value.to_string()),
            "type" => fm.page_type = Some(value.to_string()),
            "tags" => fm.tags = parse_list_value(value),
            "related" => fm.related = parse_related_value(value),
            "sources" => fm.sources = parse_list_value(value),
            "created" => fm.created = Some(value.to_string()),
            "updated" => fm.updated = Some(value.to_string()),
            _ => {
                fm.extra.insert(key.to_string(), value.to_string());
            }
        }
    }
    fm
}

/// 解析 `[a, b, c]` 或 `a, b, c` 格式
fn parse_list_value(value: &str) -> Vec<String> {
    let trimmed = value.trim();
    let inner = if trimmed.starts_with('[') && trimmed.ends_with(']') {
        &trimmed[1..trimmed.len() - 1]
    } else {
        trimmed
    };
    inner
        .split(',')
        .map(|s| s.trim().to_string())
        .filter(|s| !s.is_empty())
        .collect()
}

/// related 字段特殊处理:每项是 `[[X]]` 或 `[[X|Y]]`,提取 X
fn parse_related_value(value: &str) -> Vec<String> {
    extract_wikilinks(value)
}

// ============================================================================
// 序列化
// ============================================================================

/// 序列化为 `---\n...\n---\nbody` 格式
pub fn serialize(doc: &ParsedDoc) -> String {
    let mut out = String::from("---\n");
    if let Some(t) = &doc.frontmatter.title {
        out.push_str(&format!("title: {}\n", t));
    }
    if let Some(t) = &doc.frontmatter.page_type {
        out.push_str(&format!("type: {}\n", t));
    }
    if !doc.frontmatter.tags.is_empty() {
        out.push_str(&format!("tags: [{}]\n", doc.frontmatter.tags.join(", ")));
    }
    if !doc.frontmatter.related.is_empty() {
        let links: Vec<String> = doc.frontmatter.related.iter().map(|r| format!("[[{}]]", r)).collect();
        out.push_str(&format!("related: {}\n", links.join(" ")));
    }
    if !doc.frontmatter.sources.is_empty() {
        out.push_str(&format!("sources: [{}]\n", doc.frontmatter.sources.join(", ")));
    }
    if let Some(c) = &doc.frontmatter.created {
        out.push_str(&format!("created: {}\n", c));
    }
    if let Some(u) = &doc.frontmatter.updated {
        out.push_str(&format!("updated: {}\n", u));
    }
    for (k, v) in &doc.frontmatter.extra {
        out.push_str(&format!("{}: {}\n", k, v));
    }
    out.push_str("---\n");
    if !doc.body.is_empty() {
        out.push_str(&doc.body);
        if !doc.body.ends_with('\n') {
            out.push('\n');
        }
    }
    out
}

// ============================================================================
// wikilink 提取
// ============================================================================

/// 从内容中提取所有 `[[X]]` 或 `[[X|Y]]`,返回 X 列表(顺序,去重)
pub fn extract_wikilinks(content: &str) -> Vec<String> {
    let mut out = Vec::new();
    let bytes = content.as_bytes();
    let mut i = 0;
    while i + 1 < bytes.len() {
        if bytes[i] == b'[' && bytes[i + 1] == b'[' {
            // 找 `]]`
            let mut j = i + 2;
            while j + 1 < bytes.len() && !(bytes[j] == b']' && bytes[j + 1] == b']') {
                j += 1;
            }
            if j + 1 < bytes.len() {
                let inner = &content[i + 2..j];
                // 可能有 `|` 分隔符
                let target = inner.split('|').next().unwrap_or(inner).trim();
                if !target.is_empty() && !out.contains(&target.to_string()) {
                    out.push(target.to_string());
                }
                i = j + 2;
                continue;
            }
        }
        i += 1;
    }
    out
}

// ============================================================================
// Tests
// ============================================================================

#[cfg(test)]
mod tests {
    use super::*;

    // ---- parse ----

    #[test]
    fn parse_no_frontmatter_returns_empty() {
        let content = "# Hello\n\nBody text.";
        let p = parse(content);
        assert_eq!(p.frontmatter, Frontmatter::default());
        assert_eq!(p.body, content);
    }

    #[test]
    fn parse_simple_frontmatter() {
        let content = "---\ntitle: Albert Einstein\ntype: entity\n---\n\n# Body";
        let p = parse(content);
        assert_eq!(p.frontmatter.title.as_deref(), Some("Albert Einstein"));
        assert_eq!(p.frontmatter.page_type.as_deref(), Some("entity"));
        assert_eq!(p.body, "# Body");
    }

    #[test]
    fn parse_list_field_brackets() {
        let content = "---\ntags: [physicist, nobel-prize]\n---\n";
        let p = parse(content);
        assert_eq!(p.frontmatter.tags, vec!["physicist", "nobel-prize"]);
    }

    #[test]
    fn parse_list_field_csv() {
        let content = "---\ntags: a, b, c\n---\n";
        let p = parse(content);
        assert_eq!(p.frontmatter.tags, vec!["a", "b", "c"]);
    }

    #[test]
    fn parse_related_field_with_wikilinks() {
        let content = "---\nrelated: [[Theory of Relativity]] [[Nobel Prize]]\n---\n";
        let p = parse(content);
        assert_eq!(p.frontmatter.related, vec!["Theory of Relativity", "Nobel Prize"]);
    }

    #[test]
    fn parse_related_with_alias() {
        let content = "---\nrelated: [[X|Y]]\n---\n";
        let p = parse(content);
        assert_eq!(p.frontmatter.related, vec!["X"]);
    }

    #[test]
    fn parse_sources_field() {
        let content = "---\nsources: [raw/sources/a.pdf, raw/sources/b.md]\n---\n";
        let p = parse(content);
        assert_eq!(p.frontmatter.sources, vec!["raw/sources/a.pdf", "raw/sources/b.md"]);
    }

    #[test]
    fn parse_dates_field() {
        let content = "---\ncreated: 2026-06-12\nupdated: 2026-06-13\n---\n";
        let p = parse(content);
        assert_eq!(p.frontmatter.created.as_deref(), Some("2026-06-12"));
        assert_eq!(p.frontmatter.updated.as_deref(), Some("2026-06-13"));
    }

    #[test]
    fn parse_unknown_fields_go_to_extra() {
        let content = "---\ncustom_field: hello\n---\n";
        let p = parse(content);
        assert_eq!(p.frontmatter.extra.get("custom_field").map(String::as_str), Some("hello"));
    }

    // ---- serialize ----

    #[test]
    fn serialize_roundtrip() {
        let original = "---\ntitle: X\ntype: source\ntags: [a, b]\n---\n\nbody text";
        let p = parse(original);
        let s = serialize(&p);
        let p2 = parse(&s);
        assert_eq!(p.frontmatter, p2.frontmatter);
    }

    #[test]
    fn serialize_empty_frontmatter_still_has_delimiters() {
        let p = ParsedDoc {
            frontmatter: Frontmatter::default(),
            body: "body".to_string(),
        };
        let s = serialize(&p);
        assert!(s.starts_with("---\n"));
        assert!(s.contains("\n---\n"));
    }

    // ---- extract_wikilinks ----

    #[test]
    fn extract_simple_wikilink() {
        let s = "see [[Theory of Relativity]] for details";
        assert_eq!(extract_wikilinks(s), vec!["Theory of Relativity"]);
    }

    #[test]
    fn extract_multiple_wikilinks() {
        let s = "links: [[A]] and [[B]] and [[C]]";
        assert_eq!(extract_wikilinks(s), vec!["A", "B", "C"]);
    }

    #[test]
    fn extract_wikilink_with_alias() {
        let s = "see [[Page Name|display text]]";
        assert_eq!(extract_wikilinks(s), vec!["Page Name"]);
    }

    #[test]
    fn extract_dedupes_repeated_links() {
        let s = "[[A]] [[B]] [[A]]";
        assert_eq!(extract_wikilinks(s), vec!["A", "B"]);
    }

    #[test]
    fn extract_no_wikilinks() {
        assert!(extract_wikilinks("plain text").is_empty());
    }

    #[test]
    fn extract_unclosed_bracket_ignored() {
        // `[[X` 没有 `]]` 结尾应忽略
        assert!(extract_wikilinks("broken [[X").is_empty());
    }
}
