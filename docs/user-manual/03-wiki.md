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

## 摄入队列（高级）

侧栏 → "摄入队列" 视图。适用于批量导入场景:

- **状态**：pending / processing / completed / failed / cancelled 五态
- **操作**：取消 pending 任务 / 重试 failed 任务 / 清空已完成
- **崩溃恢复**：任务持久化在 `.llm-wiki/ingest-queue.json`，重启后自动续传
- **重试策略**：默认 3 次，失败后标 failed 等待人工干预

## 质量检查（Lint）

侧栏 → "质量检查" 视图。自动扫描 wiki 目录的结构合规性:

- **error**：缺必需目录（`wiki/entities`、`wiki/concepts`、`wiki/sources`）或缺必需文件（`wiki/index.md`、`wiki/overview.md`、`wiki/schema.md`）
- **warning**：缺 frontmatter / frontmatter title 与文件名不一致 / `[[wikilink]]` 断链
- **info**：孤儿页（零入链）

顶部 toolbar 显示 severity 过滤 tabs + 计数 + 上次运行时间。挂载时自动跑一次。

## 内容审核（Review）

侧栏 → "内容审核" 视图。检测需要人工复核的内容质量问题:

- **缺页**（missing-page）：`[[wikilink]]` 指向不存在的页（置信度 1.0）
- **重复**（duplicate）：标题 token 集合 Jaccard ≥ 0.6（例如"Deep Transformer Model Architecture" vs "Deep Transformer Model Implementation"）
- **矛盾**（contradiction）：frontmatter `created > updated`（日期倒置）
- **建议**（suggestion）：内容 < 150 字符的短页或缺 title 的页
- **待确认**（confirm）：孤儿页（零入链，豁免 `wiki/schema.md`、`wiki/overview.md`）

审核是**确定性**的（无 LLM 调用），毫秒级完成。每项有稳定 ID（`rv-<16hex>`），跨次运行可对比。

操作：每张卡片右上角 X 忽略，或点击 action 标为 resolved。

## Chrome Web Clipper（浏览器扩展）

位置：`extension/wiki-clipper/`。需手动加载到 Chrome:

1. `chrome://extensions/` → 开启"开发者模式"
2. "加载已解压的扩展程序" → 选 `extension/wiki-clipper/` 目录
3. 在任意网页点扩展图标 → 选目标项目 → 点 Clip

扩展会用 Readability.js 提取正文、Turndown.js 转 Markdown、POST 到 `/api/v1/wiki/clip` 保存。

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
- 完整性优化（队列/Lint/Review/Clipper）: [`docs/technical/50-wiki-completeness-optimization.md`](../technical/50-wiki-completeness-optimization.md)
- 参考实现: `/home/fz/project/llm_wiki`
