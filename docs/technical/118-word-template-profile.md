# 118 — Word 模板 Profile 与填充（M1a）

> 日期：2026-10-31 · 分支：`feat/word-template-profile`
> 方案：`docs/plans/2026-10-31_word-document-intelligence.md`（M1）、`docs/plans/2026-10-31_word-template-profile-m1a.md`

## 1. 定位

在现有 docxtpl/Jinja 模板路径之外，增加**统一槽位 Profile**：内容控件、书签、通用占位符与简单 Jinja 占位符；页眉/页脚也会被扫描。填充到新 `.docx`，保留槽位首个 run 的格式；含 Jinja 控制流时在手动槽位填充后交给 docxtpl/SandboxedEnvironment 渲染。

旧 `/office/word/template/analyze` 与 `/template/fill` 契约不变。

## 2. 槽位类型

| kind | 来源 | 必填 |
|---|---|---|
| `content_control` | `w:sdt` 的 `w:tag` / `w:alias` | 是 |
| `bookmark` | `w:bookmarkStart/End`（非 `_` 开头） | 否 |
| `placeholder` | `<<name>>` / `[[name]]` / `【name】` | 是 |
| `jinja` | `{{ name }}`（无控制流） | 是 |

槽位包含：`name`、`kind`、`type`、`required`、`description`、`current_value`、`confidence`、`anchor`。

## 3. 接口

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
    {"name": "funding", "kind": "placeholder", "type": "text", "required": true, "current_value": "<<funding>>", "anchor": {"paragraph_index": 2}}
  ],
  "warnings": [],
  "summary": {"slots": 3, "kinds": {"content_control": 1, "bookmark": 1, "placeholder": 1}, "has_jinja_control": false}
}
```

`POST /api/v1/office/word/template/profile/fill`

```json
{"workspace_path": "/ws", "template_path": "/ws/template.docx", "output_filename": "filled.docx", "data": {"project_title": "Sage", "company": "New Co", "funding": "NSF"}}
```

响应：

```json
{"ok": true, "template_path": "template.docx", "output_path": "filled.docx", "filename": "filled.docx", "filled_count": 3, "unfilled_slots": [], "residual_placeholders": [], "warnings": []}
```

## 4. 填充规则

- 内容控件：替换 `w:sdtContent` 内文本；多行转换为 `w:br`；首个 run 格式保留；
- 书签：仅同段落内；跨段落书签拒绝；
- 占位符/Jinja：正文、表格、页眉页脚文本替换；跨 run 时保留首个受影响 run 格式；
- `{{ name | filter }}` 使用基础变量名，写入字符串值；
- 含 `{%`/`{#` 控制流时：先完成手动槽位填充，再写临时 docx，经 `_validate_template_safety` 后用 docxtpl 渲染并输出；结果 `jinja_rendered=true`；
- 输出文件名不允许路径分隔符；不覆盖模板/已有文件；workspace 边界校验；
- 填充后重新分析，残留占位符写入 `residual_placeholders` 并 warning。

## 5. 限制（后续）

- Jinja 控制流通过 docxtpl 渲染，但尚未做自定义重复表格行/条件块 schema；
- 图片/富文本槽位暂不支持；
- 书签跨段落暂不支持；
- 前端表单/模板库 instantiate 工具未接入。

## 6. 测试

- `backend/tests/unit/office/test_word_template_profile.py`（6）：内容控件/书签/占位符/Jinja 识别、填充与格式保留、Jinja 控制流混合渲染、页眉页脚、必填/覆盖拒绝；
- `backend/tests/integration/test_office_routes.py`：analyze/fill 端点；
- ruff / py38 / architecture 门禁通过。
