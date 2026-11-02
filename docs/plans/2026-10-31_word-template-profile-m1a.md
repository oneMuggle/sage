# Word 模板 Profile 与填充 M1a 实施计划

> 日期：2026-10-31 · 分支：`feat/word-template-profile`
> 基线：`origin/main` = `c4d49f2b8`（M0a 合并后）
> 前置：`docs/plans/2026-10-31_word-document-intelligence.md` 的 M1
> 范围：内容控件 / 书签 / 通用占位符 / 简单 Jinja 的 profile 分析与保格式填充；不处理 Jinja 控制流。

## 1. 目标

现有 `word_template.py` 只支持 docxtpl 的 Jinja 占位符，且不暴露统一的槽位 profile。
M1a 增加：

- 统一分析内容控件（`w:sdt` tag/alias）、书签、`<<>>`/`[[]]`/`【】`/`{{}}` 占位符；
- 生成可编辑 `slots`（name/kind/type/required/current_value/anchor）；
- 填充到新 `.docx`，保留首个 run 的字体/字号/粗体等格式；
- 必填校验、输出不覆盖、填充后 residual 检查；
- 含 Jinja 控制流时拒绝并提示使用现有 `/office/word/template/fill`。

## 2. 接口

`POST /api/v1/office/word/template/profile`

```json
{"workspace_path": "/ws", "file_path": "/ws/template.docx"}
```

响应：

```json
{
  "ok": true,
  "kind": "word-template-profile",
  "source_path": "template.docx",
  "slots": [
    {"name": "project_title", "kind": "content_control", "type": "text", "required": true, "current_value": "Old", "anchor": {"sdt_index": 0, "tag": "project_title"}},
    {"name": "company", "kind": "bookmark", "type": "text", "required": false, "current_value": "Old Co", "anchor": {"paragraph_index": 1, "bookmark": "company"}},
    {"name": "funding", "kind": "placeholder", "type": "text", "required": true, "current_value": "<<funding>>", "anchor": {"paragraph_index": 2}},
    {"name": "author", "kind": "jinja", "type": "text", "required": true, "current_value": "{{author}}", "anchor": {"paragraph_index": 3}}
  ],
  "warnings": [],
  "summary": {"slots": 4, "kinds": {"content_control": 1, "bookmark": 1, "placeholder": 1, "jinja": 1}, "has_jinja_control": false}
}
```

`POST /api/v1/office/word/template/profile/fill`

```json
{"workspace_path": "/ws", "template_path": "/ws/template.docx", "output_filename": "filled.docx", "data": {"project_title": "Sage"}}
```

响应：`{ok, template_path, output_path, filename, filled_count, unfilled_slots, residual_placeholders, warnings}`。

## 3. 填充规则

- 内容控件：替换 `w:sdtContent` 内文本；多行用 `w:br`；保留首个 run 格式；
- 书签：仅支持同一段落内的书签；跨段落书签拒绝；
- 占位符/Jinja：在段落文本中替换；跨 run 时保留首个受影响 run 的格式；
- `{{ name | filter }}` 取基础变量名并写入值的字符串形式；
- 含 `{%`/`{#` 控制流时直接拒绝，交给旧 docxtpl 端点；
- 输出文件名不允许路径分隔符/覆盖已有文件/覆盖模板；
- 填充后重新分析，残留 `placeholder`/`jinja` 写入 `residual_placeholders`。

## 4. 文件

```
backend/office/word_template_profile.py
backend/office/word_template_profile_fill.py
backend/api/office_word_template_profile_routes.py
backend/api/office_routes.py          # include router
backend/tests/unit/office/test_word_template_profile.py
backend/tests/integration/test_office_routes.py
docs/technical/118-word-template-profile.md
```

## 5. 非目标（M1b）

- 不做 Jinja 控制流/循环（交给现有 docxtpl）；
- 不做重复表格行/条件块建模；
- 不做图片/富文本槽位；
- 不做页眉页脚扫描与填充；
- 不做前端表单/模板库 instantiate 工具。
