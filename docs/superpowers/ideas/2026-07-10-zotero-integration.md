# 想法：Zotero 学术文献集成（AI 阅读 + 知识图谱沉淀）

> 状态：💭 Backlog
> 日期：2026-07-10
> 关联：[docs/technical/25-llm-wiki-integration.md](../../technical/25-llm-wiki-integration.md) · [`backend/wiki/`](../../../backend/wiki/) · [`backend/memory/`](../../../backend/memory/) · Zotero 6/7 本地 SQLite

## 动机

研究人员读论文是知识工作的瓶颈：几十到几百篇 PDF，靠肉眼筛、靠记忆连。

Zotero 已经管文献元数据 + PDF 路径 + 个人批注，但**和 AI 工作流是割裂的**——要靠手动复制摘要到 ChatGPT，写笔记又是另一份文档，"读到的东西"和"积累的知识"之间永远隔一层。

Sage 已经有 wiki / graph / memory / skills 的完整沉淀链条。Zotero 集成让"读文献"成为这套链条的**输入端**：每篇论文 ingest 成 wiki 页面，AI 抽取概念进 graph，用户批注进 memory，引用关系自动编织。

痛点：
- 读完 10 篇相关工作，跨论文的概念连接靠记忆
- 想"3 个月前读过的那篇讲 X 的论文"时检索不到
- PDF 批注是金矿，但躺在 Zotero 里没法被 AI 利用

## 想法草图

**三层集成**（沿用 Sage 现有架构，不发明新东西）：

```
Zotero SQLite ──► backend/zotero/client.py ──► backend/wiki/ingest.py
                                                 │
                                                 ├─ 轻量：metadata + abstract → LLM 重写摘要 → wiki page
                                                 └─ 重量：PDF 全文 (PyMuPDF) + 可选 vision → 深度分析 → 增强 wiki page
                                                   │
                                                   ├─► backend/wiki/graph.py (新增 AuthorNode + CitationEdge)
                                                   ├─► backend/memory/episodic.py (用户批注 → episodic memory)
                                                   └─► src/widgets/zotero/ (UI: 选择 collection → 批量 import)
```

**关键设计选择（已和用户确认）**：
- **数据源**：本地 SQLite 直读（不走 Web API）—— 单机用户为主、annotations 拿得到、零认证
- **AI 介入深度**：默认轻量（metadata + abstract），重量模式（PDF + vision）按需触发
- **图谱节点**：完整学术图（Paper + Author + Concept + Citation 边），与现有 4-signal wiki graph 并存

**复用现有**：
- `wiki/ingest.py` 6 步管线（SHA256 缓存、frontmatter 解析、embeddings）
- `wiki/graph.py` 4-signal，加 `CitationEdge` 新 signal type
- `wiki/llm_prompts.py` 加 `ZOTERO_LIGHT_SUMMARIZE` / `ZOTERO_DEEP_ANALYZE` 两个新 prompt
- `wiki/file_parser.py` 加 PDF 解析器扩展（PyMuPDF）
- `memory/manager.py` 加"论文批注→episodic"通路
- `llm_context.py` LLMContext 抽象无缝复用

**新增**：
- `backend/zotero/{client,sync,models}.py` — SQLite reader + 增量同步 + WikiPage 映射
- `src/widgets/zotero/ZoteroImportDialog.tsx` — 选 collection / 选 papers / 选轻量/重量 模式
- `docs/technical/31-zotero-integration.md` — 完成后归档

## 触发条件 / 何时做

- **必触发**：release/win7 的 M1-M9 + post-M8 sync 全部完成（避免双线维护负担）
- **必触发**：Sage Wiki 主线稳定运行 ≥1 个月（无重大重构）
- **应触发**：用户实际积累 ≥50 篇 Zotero 文献后（避免过早投入）
- **可选触发**：用户主动表达"读论文效率低"时
- 没有明确触发条件 = 默认 Backlog，偶尔 review

## 升级路径

升级到 `docs/superpowers/specs/2026-07-10-zotero-integration-design.md` 时：
- 在本文件加 `> 已升级到: specs/2026-07-10-zotero-integration-design.md (commit xxx)`
- 重点展开：`SQLite schema 兼容性（Zotero 6 vs 7）` · `PDF 解析策略与 fallback` · `CitationEdge 边的数据来源（arXiv ID / DOI / Semantic Scholar API）` · `vision 模式成本估算与限流` · `图谱节点类型与现有 4-signal 的合并渲染策略`
- 删除本文件（feature-development.md 约定）

实施后归档到 `docs/technical/31-zotero-integration.md`。

## 风险 / 待澄清

- **PDF 解析准确率**：公式/复杂表格/双栏布局 PyMuPDF 抽取不一定准确，需要 fallback 策略（重量模式下 vision 兜底？）
- **Zotero 版本兼容**：6.x (SQLite) vs 7.x (Beta) schema 不同，方案 A 主要面向 6.x 稳定版
- **引用关系来源**：从 PDF 解析 references section 准确率有限，可能要结合 arXiv API / Semantic Scholar API / Crossref 做权威引用
- **隐私/合规**：本地 SQLite 含用户所有文献元数据 + 批注，需确认存储路径不冲突 `.llm-wiki/`