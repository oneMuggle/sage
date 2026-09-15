# Prompt 模板导入/导出（第三十轮批次 A）实施计划

> 日期: 2026-09-14 · 分支: `feat/prompt-io-r30` · 基于 main @ 775a61ce
> 来源: R27/#716 与 R28/#718 的收口项——模板无法迁出/迁入新环境
> （对标 R19 记忆导出/导入的对称能力）。与并发车道零交集。
> Win7 对齐: **新功能不 cherry-pick 到 release/win7**。

## 实施

### A. 后端（S）

`prompt_routes.py` 增补：

- `GET /prompts/templates/export` → `{app, kind: prompt_templates,
  version, exported_at, templates}` 信封；
- `POST /prompts/templates/import` ← 同构信封（`templates` 宽松
  `List[Any]`，单条非法由循环跳过计数而非整体 422）：
  - 按 name 去重（同名跳过）、空名/空内容跳过、长度超限计 failed；
  - 总量受 `_MAX_TEMPLATES`(100) 约束，超出计 skipped；
  - 有导入才写盘，返回 `{imported, skipped, failed, errors[:10]}`。

### B. IPC + API + UI（S）

- `commands.ts`: `prompts_export` / `prompts_import`（导入信封即 body）；
- `promptApi.ts`: `exportTemplates()` / `importTemplates(envelope)` +
  `PromptTemplateEnvelope` 类型；
- `PromptTemplatesTab` 工具栏: 导出（Blob 下载 JSON）/ 导入（文件
  选择 → 解析 → 报告 alert + 列表刷新）按钮。

## 测试

- `test_prompt_import_export` 5 例: 信封结构 / 导入往返 + 同名去重 +
  非法与超限计数 / 版本防御 / 上限约束（fake KV monkeypatch）。
- 前端 `PromptTemplatesTab` 7 例（新增导出调用链）。
- ruff CI 验证；tsc/eslint 全绿。

## 本批不做

- 模板导入的冲突合并策略（现为同名跳过）
- 变量记忆（S）
