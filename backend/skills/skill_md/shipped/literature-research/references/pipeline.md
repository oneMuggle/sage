# 文献调研运行目录契约

本文件是 `literature-research` 技能的参考：定义运行目录、数据结构、引用语法
与门禁语义。所有路径相对于 `<run_dir>`。

## meta.json

```json
{
  "run_id": "20261121-093000",
  "topic": "大模型综述",
  "site_id": "<site_id>",
  "created_at": "2026-11-21T09:30:00+00:00",
  "status": "active"
}
```

## papers.jsonl

每行一个 `PaperRecord`：

```json
{
  "paper_key": "doi:10.1000/demo",
  "title": "示例论文",
  "authors": ["张三", "李四"],
  "year": "2024",
  "venue": "示例期刊",
  "abstract": "……",
  "url": "https://example.org/paper",
  "doi": "10.1000/demo",
  "source_site": "<site_id>",
  "source_query": "机器学习 综述",
  "retrieved_at": "2026-11-21T09:35:00+00:00",
  "fulltext_path": "/path/to/paper.pdf",
  "language": "zh",
  "extra": {}
}
```

`paper_key` 唯一；重复记录会被 `record_papers` 去重。

## evidence.jsonl

```json
{
  "evidence_id": "e1",
  "paper_key": "doi:10.1000/demo",
  "kind": "finding",
  "text": "该文报告了 X 在 Y 上的提升",
  "locator": "p.3",
  "quote": "原文片段（可选）",
  "confidence": 0.8
}
```

`kind` 建议取值：`task` / `method` / `data` / `metric` / `finding` /
`limitation` / `quote`。`paper_key` 必须存在于 papers.jsonl。

## claims.jsonl（M2a）

```json
{
  "claim_id": "c0001",
  "section": "body",
  "text": "带 [cite:doi:10.1000/demo] 的段落原文",
  "citation_keys": ["doi:10.1000/demo"],
  "verdict": "supported",
  "notes": "",
  "metadata_schema_ok": true
}
```

`verdict` 取值：`unverified` / `supported` / `flagged` / `unsupported` /
`unresolved`。`unresolved` 表示引用 key 不在文献池；`unsupported` 表示 claim
无引用；`flagged` 表示引用存在但引用论文没有任何 evidence 记录（Layer 3a）。
`extract-claims` 从 draft.md 按段落重建账本；`verify-claims` 重跑 Layer 1+2a、
应用证据级支持并覆盖写入。语义 claim support（Layer 3b）尚未实现。

## metadata_verification.json（M2b）

```json
{
  "min_consensus": 2,
  "items": [
    {
      "paper_key": "doi:10.1000/demo",
      "status": "verified",
      "matched": 2,
      "checks": [
        {"lookup": "crossref", "ok": true, "title": "示例论文", "year": "2024"},
        {"lookup": "openalex", "ok": true, "title": "示例论文", "year": "2024"},
        {"lookup": "semantic_scholar", "ok": false, "reason": "no_data"}
      ]
    }
  ],
  "verified": 1,
  "partial": 0,
  "unverified": 0,
  "skipped": 0
}
```

`verify-metadata` 对有 DOI/arXiv 的文献查询 Crossref / OpenAlex /
Semantic Scholar；至少 `min_consensus`（默认 2）家标题/年份/作者匹配 →
`verified`；1 家 → `partial`；0 → `unverified`；无外部 ID → `skipped`。

## claim_support.json（M2c）

```json
[
  {
    "claim_id": "c0001",
    "support": "supported",
    "rationale": "证据 e1 的发现直接支持该句",
    "evidence_refs": ["e1"]
  }
]
```

`support`：`supported` / `flagged` / `unsupported` / `unclear`。
`apply-claim-support` 校验并合并到 claims.jsonl；`unresolved` / `unsupported`
的 claim 不被覆盖。

## ledger.json（M2c）

```json
{
  "count": 1,
  "entries": [
    {
      "entry_id": "evidence:e1",
      "paper_key": "doi:10.1000/demo",
      "source_type": "evidence",
      "source_id": "e1",
      "claim_id": null,
      "locator": "p.3",
      "quote": "原文片段",
      "text": "证据正文"
    }
  ]
}
```

`source_type` 可为 `evidence` / `claim` / `attachment` / `wiki` / `specialist` /
`word` / `zotero` / `external`；外部来源用 `ingest_external` 以 dict 接入。

## export/verification_report.{md,json}（M2c）

四态分组（supported / flagged / unsupported / unclear）+ 元数据核验摘要 +
EvidenceLedger 统计；由 `report` 命令生成，可直接作为 artifact 预览。

## export/rubric_review.{md,json}（M2c）

四维 rubric 评审（方法 / 覆盖 / 逻辑 / 写作，各 0–5 分，总分 20）：

```json
{
  "generated_at": "2026-11-22T12:00:00+00:00",
  "total_score": 14,
  "max_score": 20,
  "band": "良",
  "disclaimer": "本评审由确定性规则自动生成，是写作自检而非同行评审；...",
  "dimensions": [
    {"id": "method", "title": "方法", "score": 4, "max_score": 5,
     "issues": ["部分被引文献缺少证据（覆盖率 67%）"]}
  ]
}
```

由 `rubric` 命令生成。评分只反映流程完整度（检索次数、证据覆盖率、元数据
通过率、被引比例、来源多样性、大纲覆盖、claims 状态、正文体量与引用密度），
不评价学术价值；必须向用户说明"模拟评审，不是同行评审"。

## outline.json

```json
{
  "title": "大模型综述",
  "sections": [
    {
      "id": "s1",
      "title": "引言",
      "summary": "背景与研究问题",
      "source_keys": ["doi:10.1000/demo"]
    }
  ]
}
```

`sections` 非空；`id` 唯一；`source_keys` 必须存在于 papers.jsonl。

## draft.md 与引用语法

- 正文引用：`[cite:KEY]` 或 `[cite:KEY1, KEY2]`。
- 只允许引用 papers.jsonl 中的 key；不要手写 `[1]` 编号。
- `gates.build_references` 按首次出现顺序生成 `[1] [2] ...` 参考文献；
  未被正文引用的文献只产生 warning。

## verification.json（门禁报告）

```json
{
  "ok": true,
  "errors": [],
  "warnings": ["文献未被正文引用: p2"],
  "citations": ["p1"]
}
```

门禁 errors 清零才允许 export。

## export/

- `final.md`：正文 + `## 参考文献`（仅列实际引用）。
- `references.json`：`{"style": "gbt7714", "entries": [{"key", "number", "paper"}]}`；
  `export --style ieee` 时 `style` 为 `ieee`。
- `papers.bib`：仅包含实际引用的 BibTeX 条目。

参考文献样式：默认 GB/T 7714（`[1] 作者. 题名[J]. 刊名, 年.`）；
`ieee` 输出 `[1] A. Author, "Title," Venue, Year.`（英文名缩写首字母，
超过 3 位作者用 `et al.`）。APA/CSL 未实现。

## paper-writing 交接

`export.build_handoff(run)` 返回：

```json
{
  "references": [
    {
      "key": "doi:10.1000/demo",
      "ref_type": "journal",
      "title": "示例论文",
      "authors": ["张三", "李四"],
      "year": "2024",
      "source": "示例期刊",
      "doi": "10.1000/demo"
    }
  ],
  "draft_path": "<run_dir>/draft.md"
}
```

把 `references` 与分章 Markdown 交给 `paper-writing` 的 `office_create`，
由其生成 GB/T 7714 docx 并跑 `office_lint_word`。

## 交互式检索（`search.mode: interactive`）

```yaml
search:
  mode: interactive
  url_template: "https://example.org/entry"   # 入口页（无需 {query}）
  entry_url: "https://example.org/entry"
  entry_click: "检索入口"                     # 可选
  input_selectors: ["input[placeholder*='检索词']"]
  submit_key: Enter
  wait_after_s: 5
  result_hint: 结果条目结构说明
```

`search_with_profile` 会依次尝试 `input_selectors`，命中后按 `submit_key`，
等待 `wait_after_s` 再抓快照。真实浏览器通过 `SageToolDriver(sage.call)` 接入。

## 站点 profile 示例

可复制的示例 profile 在 `docs/templates/literature-sites/`（不参与运行时加载）。
启用：`cp docs/templates/literature-sites/<site>.yaml ~/.sage/literature_sites/`。
`interactive` 模式字段（`entry_url` / `input_selectors` / `submit_key` / `wait_after_s`）
的规范见 `backend/literature/README.md`；具体站点的选择器与实测要点写在该站点
profile 的注释与模板 README 中，不要写进本数据契约文档。
