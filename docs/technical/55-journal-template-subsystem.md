# 55 — Journal Template Article Generation & Validation Subsystem

> 期刊模板文章生成与格式校验子系统（journal/）。本章节是 8-PR 系列的实施追踪文档，按 N1…N8 顺序追加。

## N1 子包骨架（2026-09-10 落地）

- 子包 `backend/office/journal/`：errors / models / pandoc_adapter
- `JournalError` 继承 `OfficeError`，6 个细分错误码稳定
- `JournalSpec` / `JournalContent` / `JournalViolation` / `JournalGenerationRecord` 4 个 Pydantic v2 模型
- `.doc` → `.docx` 经 `pandoc --from doc --to docx` 透明转换，按 sha256 缓存到 `<cache_dir>/<sha256>.docx`
- 4 个 docx fixture：`simple_chinese_template.docx` / `bad_template_corrupt.docx` / `good_filled_paper.docx` / `bad_filled_paper.docx`
