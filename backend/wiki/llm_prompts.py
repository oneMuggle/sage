"""LLM Prompt 模板。

定义 Ingest 和 RAG Chat 的 prompt 模板。
"""

# Step 1: 分析源文档
STEP1_ANALYZE = """分析以下源文档，提取关键实体、概念、标签和相关主题。

输出严格 JSON 格式:
{{
  "entities": [{{"name": "...", "type": "person|org|concept|place|other", "brief": "..."}}],
  "concepts": [{{"name": "...", "brief": "..."}}],
  "tags": ["tag1", "tag2", ...],
  "related_topics": ["topic1", "topic2", ...],
  "summary": "2-3 句话总结"
}}

约束:
- 仅输出 JSON，不要 markdown 代码块
- brief 少于 30 字
- 匹配源文档语言（中文/英文）
- tags: 3-7 个小写 kebab-case 字符串

源文档:
{source_content}"""


# Step 2: 写入 Wiki 页面
STEP2_WRITE = """基于分析结果，写入完整的 Wiki 页面（Markdown + YAML frontmatter）。

输出格式:
---
title: <页面标题>
type: source
tags: [{tags_csv}]
related: [[topic1]] [[topic2]] ...
sources: [raw/sources/{filename}]
created: {today}
updated: {today}
---

# <标题>

<2-4 段总结>

## 关键观点

## 关键事实

## 相关页面

- [[X]] — 简要说明

约束:
- related 使用 [[Page Title]] 格式
- 3-8 个相关页面
- 匹配源文档语言
- 不要编造事实

文件名: {filename}
内容:
{content}

分析结果:
{analysis}

标签: {tags_csv}
相关主题: {related_links}
今天日期: {today}"""


# RAG 系统 prompt
RAG_SYSTEM = """你是一个知识库助手。根据提供的 wiki 内容回答问题。

规则:
1. 仅从 wiki 片段中回答，不使用外部知识
2. 如果未找到相关信息，说"我在 wiki 中没有找到相关信息"
3. 使用 [[Page Title]] 格式引用页面
4. 用中文回答（除非用户用其他语言提问）
5. 简洁明了

Wiki 内容:
{context}"""


# RAG 用户 prompt
RAG_USER_TEMPLATE = """请基于以上 wiki 内容回答以下问题:
{query}"""


def format_step1_prompt(source_content: str) -> str:
    """格式化 Step 1 prompt。"""
    return STEP1_ANALYZE.format(source_content=source_content)


def format_step2_prompt(
    filename: str,
    content: str,
    analysis: str,
    tags_csv: str,
    related_links: str,
    today: str,
) -> str:
    """格式化 Step 2 prompt。"""
    return STEP2_WRITE.format(
        filename=filename,
        content=content,
        analysis=analysis,
        tags_csv=tags_csv,
        related_links=related_links,
        today=today,
    )


def format_rag_system(context: str) -> str:
    """格式化 RAG 系统 prompt。"""
    return RAG_SYSTEM.format(context=context)


def format_rag_user_message(query: str) -> str:
    """格式化 RAG 用户 prompt。"""
    return RAG_USER_TEMPLATE.format(query=query)
