// Wiki LLM prompt 模板
//
// 设计要点:
// - 所有 prompt 字符串集中在本文件,便于迭代
// - 不引入 poml 之类的框架,纯 format! 模板
// - 模板参数在 fn 中显式声明,避免 format! 漏传或拼写错

// ============================================================================
// 常量:Prompt 模板
// ============================================================================

/// Step 1: 让 LLM 分析源文档,提取实体/概念/标签/相关主题
pub const STEP1_ANALYZE: &str = r#"You are analyzing a source document for a personal wiki.

Output a strict JSON object with these fields:
- entities: list of {{name, type, brief}} (type 可为 person/org/concept/place/other)
- concepts: list of {{name, brief}} (key concepts or methods mentioned)
- tags: list of 3-7 short strings (lowercase, kebab-case)
- related_topics: list of short strings (potential wiki page titles)
- summary: 2-3 sentence summary of the document

Constraints:
- Output ONLY the JSON object, no markdown fencing, no commentary
- Keep briefs under 30 words
- Use Chinese for names when the source is in Chinese, English when source is English

SOURCE DOCUMENT:
{source_content}

JSON:"#;

/// Step 2: 让 LLM 基于源文档和分析结果,写出完整 wiki 页面
pub const STEP2_WRITE: &str = r#"You are writing a wiki page based on a source document and its pre-analysis.

Output format (strict, no deviation):

---
title: <页面标题,使用源语言>
type: source
tags: [{tags_csv}]
related: [{related_links}]
sources: [raw/sources/{filename}]
created: {today}
updated: {today}
---

# <页面标题>

<2-4 段摘要>

## 关键观点

- ...
- ...

## 关键事实

- ...
- ...

## 相关页面

- [[X]] — brief
- [[Y]] — brief

Constraints:
- related 字段用 [[Page Title]] 双中括号形式,使用分析结果中的 related_topics
- 至少 3 条相关页面,不超过 8 条
- 中文文档用中文写,英文文档用英文写
- 不要捏造未在源文档中出现的事实

SOURCE FILENAME: {filename}
SOURCE CONTENT (truncated to 50KB):
{content}

PRE-ANALYSIS JSON:
{analysis}

Now write the page:"#;

/// RAG 模式:系统提示词(用于 wiki_chat)
pub const RAG_SYSTEM: &str = r#"你是一个基于用户个人 wiki 回答问题的助手。

严格遵循以下规则:
1. 仅基于提供的 wiki 片段回答,不引入外部知识
2. 如果 wiki 中没有相关信息,直接说"我在 wiki 中没有找到相关信息",不要编造
3. 回答时引用具体页面,使用 [[Page Title]] 格式(对应 sources 列表中的路径)
4. 回答用中文(除非用户用其他语言提问)
5. 简洁准确,避免冗长

可用的 wiki 片段如下(每段以 --- 文件: <path> --- 开头):"#;

/// RAG 模式:用户问题模板
pub const RAG_USER_TEMPLATE: &str = r#"请基于以上 wiki 内容回答以下问题:

{query}
"#;

// ============================================================================
// 便利函数
// ============================================================================

/// Format Step 1 analyze prompt with source content
pub fn format_step1_prompt(source_content: &str) -> String {
    STEP1_ANALYZE.replace("{source_content}", source_content)
}

/// Format Step 2 write prompt with all parameters
pub fn format_step2_prompt(
    filename: &str,
    content: &str,
    analysis: &str,
    tags_csv: &str,
    related_links: &str,
    today: &str,
) -> String {
    STEP2_WRITE
        .replace("{filename}", filename)
        .replace("{content}", content)
        .replace("{analysis}", analysis)
        .replace("{tags_csv}", tags_csv)
        .replace("{related_links}", related_links)
        .replace("{today}", today)
}

/// Format RAG user message with query
pub fn format_rag_user_message(query: &str) -> String {
    RAG_USER_TEMPLATE.replace("{query}", query)
}

// ============================================================================
// Tests
// ============================================================================

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn step1_prompt_includes_source_content() {
        let p = format_step1_prompt("my source text");
        assert!(p.contains("my source text"));
        assert!(p.contains("JSON:"));
        assert!(!p.contains("{source_content}"));
    }

    #[test]
    fn step2_prompt_replaces_all_placeholders() {
        let p = format_step2_prompt(
            "doc.md",
            "DOC BODY",
            r#"{"entities":[]}"#,
            "tag1,tag2",
            "[[X]] [[Y]]",
            "2026-06-12",
        );
        assert!(p.contains("doc.md"));
        assert!(p.contains("DOC BODY"));
        assert!(p.contains(r#"{"entities":[]}"#));
        assert!(p.contains("tag1,tag2"));
        assert!(p.contains("[[X]] [[Y]]"));
        assert!(p.contains("2026-06-12"));
        // 不留未替换的占位符
        assert!(!p.contains("{filename}"));
        assert!(!p.contains("{content}"));
        assert!(!p.contains("{analysis}"));
        assert!(!p.contains("{tags_csv}"));
        assert!(!p.contains("{related_links}"));
        assert!(!p.contains("{today}"));
    }

    #[test]
    fn step2_prompt_contains_frontmatter_template() {
        let p = format_step2_prompt("f.md", "c", "{}", "t", "r", "2026-01-01");
        assert!(p.contains("---\ntitle:"));
        assert!(p.contains("type: source"));
        assert!(p.contains("sources: [raw/sources/f.md]"));
    }

    #[test]
    fn rag_user_message_includes_query() {
        let msg = format_rag_user_message("X 是什么?");
        assert!(msg.contains("X 是什么?"));
    }

    #[test]
    fn rag_system_emphasizes_no_external_knowledge() {
        assert!(RAG_SYSTEM.contains("不引入外部知识"));
        assert!(RAG_SYSTEM.contains("[[Page Title]]"));
    }
}
