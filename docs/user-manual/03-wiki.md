# 03. Wiki 知识库

> 适用版本: sage v0.1.1+ (PR-8 全 8 阶段合入后)

## 概述

Wiki 是一个**由 LLM 增量维护的个人知识库**——导入源文档(网页、笔记、PDF 转 Markdown 等),LLM 会自动提取实体、概念、标签、相关主题,生成结构化页面;再通过 hybrid 检索(token + 向量) + RAG 综合回答你的问题。

四个视图:

- **浏览**: 文件树 + Markdown 编辑器
- **搜索**: CJK 全文搜索 + 评分排序
- **对话**: RAG 聊天(基于 wiki 内容回答)
- **图谱**: 4-signal 知识图谱可视化

## 创建 / 打开 Wiki 项目

进入"知识库"页 → 项目选择器(顶部) → "创建新项目" 或 "打开现有项目"。

创建新项目时需要填写:
- **项目名**: 例如 `my-research`
- **基础路径**: wiki 项目根目录(例如 `/Users/me/wikis`)

创建后会自动生成目录结构:
```
my-research/
├── purpose.md          # wiki 灵魂(目标/范围)
├── schema.md           # 结构配置(页面类型等)
├── raw/sources/        # 不可变源文档
└── wiki/               # LLM 生成的页面
    ├── sources/
    ├── entities/
    ├── concepts/
    ├── overview.md
    ├── index.md
    └── log.md
```

## 导入源文档

Wiki 工具栏 → "导入"按钮(Phase 7+ 上线后) → 选择 .md / .txt 文件。

导入过程(共 5 阶段,UI 实时显示进度):
1. **复制源文件** (0-10%): 复制到 `raw/sources/`
2. **LLM 分析** (20-40%): 提取实体、概念、标签、相关主题
3. **LLM 写作** (45-70%): 生成完整 wiki 页面 + frontmatter
4. **嵌入 + 写向量库** (80-90%): chunk 后用 embedding 模型向量化
5. **完成** (100%): 更新 index.md / log.md

⚠️ **重复导入跳过**: 系统用 SHA256 校验,内容未变更则直接返回缓存结果,不会重复调用 LLM。

## 浏览与编辑

工具栏 → "浏览" 视图:
- 左侧: 文件树(右键新建/删除/重命名)
- 右侧: Markdown 编辑器 + 实时预览

页面 frontmatter 规范:
```yaml
---
title: <页面标题>
type: source | entity | concept | query
tags: [tag1, tag2]
related: [[Other Page Title]]
sources: [raw/sources/foo.pdf]
created: 2026-06-12
updated: 2026-06-12
---
```

`related` 用 `[[wikilink]]` 引用其他页面 — 会被 Phase 5 图谱解析为 `DirectLink` 边。

## 搜索

工具栏 → "搜索" 视图 → 输入关键词。

搜索是 CJK 友好的 BM25-like 评分:
- 标题命中权重 ×10
- 正文出现次数 ×0.5
- 多 token 查询首个 token 权重 ×1.5

搜索结果点击可跳转到对应文件。

## 对话(RAG)

工具栏 → "对话" 视图 → 输入问题。

底层是 **hybrid 检索**:
1. **Token 搜索** (CJK 友好)
2. **向量搜索** (cosine similarity,需要 embedding 模型)
3. **RRF 融合** (k=60) → 取 top 5 页面
4. **Token 预算分配** (50% pages / 30% history / 5% index / 15% reserve)
5. **LLM 综合回答**(带引用)

回答附带 `[引用]` 列表,点击可跳转到对应 wiki 页面。

MVP 复用 chat 端点作 embedding 端点(需要端点支持 `/v1/embeddings`)。

## 图谱

工具栏 → "图谱" 视图 → 看到 4-signal 知识图谱。

边类型与权重(数值越大关联越强):
| Signal | 权重 | 含义 |
|---|---|---|
| **DirectLink** | ×3.0 | `[[wikilink]]` 引用 |
| **SourceOverlap** | ×4.0 | 两页共享源文件 |
| **TypeAffinity** | ×1.0 | 同 type 字段(如两 entity) |

节点按 `page_type` 颜色编码(source 蓝 / entity 紫 / concept 绿)。

顶部搜索框可高亮匹配节点,节点 click 跳到浏览视图。

## LLM 配置

Wiki 用 sage 已配置的端点。Settings → 模型选择:
- Chat 模型:用于 Step 1 分析 + Step 2 写作 + RAG 综合
- Embedding 模型:用于向量化(默认 `text-embedding-3-small`,1536 维)

支持的 4 个 provider:
- **OpenAI** (默认,任意 OpenAI 兼容端点)
- **Anthropic** (Claude 系列)
- **Ollama** (本地 `http://localhost:11434/v1`)
- **Custom** (Azure、自部署网关等)

## 常见问题

### Q1. 导入后 LLM 没生成完整页面

可能 Step 2 输出不规范。检查 `wiki/log.md` 看错误信息,或手动检查 `wiki/sources/{slug}.md` 是否有 frontmatter。

### Q2. 图谱没显示节点

确保至少有 1 个 `.md` 文件在 `wiki/` 子目录(不是 `wiki/index.md` 或 `wiki/log.md`,这两个元数据被跳过)。

### Q3. RAG 回答无关

向量库可能没被正确填充。检查 `.llm-wiki/vectors.json` 是否存在且 `dim` 字段为 1536。

### Q4. 切换 embedding 模型后检索错乱

`.llm-wiki/vectors.json` 缓存了原 embedding 维度的向量。切换后需要删除该文件,触发重建。

## 相关文档

- 技术: [`docs/technical/25-llm-wiki-integration.md`](../technical/25-llm-wiki-integration.md)
- 参考实现: `/home/fz/project/llm_wiki`
