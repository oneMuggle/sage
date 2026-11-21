# 文献调研运行目录契约

本文件是 `literature-research` 技能的参考：定义运行目录、数据结构、引用语法
与门禁语义。所有路径相对于 `<run_dir>`。

## meta.json

```json
{
  "run_id": "20261121-093000",
  "topic": "大模型综述",
  "site_id": "xueshu789",
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
  "source_site": "xueshu789",
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
- `references.json`：`{"style": "gbt7714", "entries": [{"key", "number", "paper"}]}`。
- `papers.bib`：仅包含实际引用的 BibTeX 条目。

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

## xueshu789 现状

- profile：`backend/literature/sites/xueshu789.yaml`（`status: draft`）。
- 已实测：卡号+密码登录、成功后 URL 进入 `/dbList/`、下载入口 `a.downloadlink`。
- 待录制：搜索 URL 模板与结果字段选择器。首次使用时通过
  `python -m backend.literature.cli draft-profile --observation <json> --out <yaml>`
  生成用户 profile，或手动补齐后 `validate-profile` 校验。
- 合规：仅本人账号/机构授权；不绕过付费墙；验证码交还用户。
