# Word 模板 M1c：图片槽位

> 日期：2026-10-31 · 分支：`feat/word-template-images`
> 基线：`origin/main` = `85a7d46c9`（M1b 合并后）
> 范围：模板 Profile 识别图片占位符，填充时用 docxtpl InlineImage 渲染。

## 1. 目标

模板中的 logo/照片字段（如 `{{logo}}`、`{{company_logo}}`、`{{图片}}`）需要插入图片而非文本。
M1c 增加：

- 分析时把名称包含 `image/logo/photo/avatar/icon/图片` 的占位符标记为 `type: "image"`；
- 填充请求新增 `images: {name: 工作区路径或 data URL}`；
- 手动文本填充跳过图片槽位；用 docxtpl `InlineImage` 渲染；
- 必填图片缺失、路径越界、超限/无效图片均拒绝。

## 2. 契约

分析槽位：

```json
{"name": "logo", "kind": "jinja", "type": "image", "required": true, "current_value": "{{logo}}"}
```

填充请求：

```json
{
  "workspace_path": "/ws",
  "template_path": "/ws/template.docx",
  "output_filename": "filled.docx",
  "data": {"title": "Sage"},
  "images": {"logo": "assets/logo.png"}
}
```

响应新增 `images_rendered`。

## 3. 实现

- `word_template_profile.py`：`_placeholder_slots` 根据名称 hints 设置 `type="image"`；
- `word_template_profile_fill.py`：
  - `images` 参数；图片槽位必填校验走 `images` 而非 `data`；
  - 手动占位符替换 `skip_names=image_names`；
  - 有图片或 Jinja 控制流时用 docxtpl 渲染：`InlineImage(template, _load_image_descriptor(...))`；
  - 相对路径按 workspace 根解析；沿用 10 MiB 限制与 `resolve_within`；
- 路由 `WordTemplateProfileFillRequest` 增加可选 `images`。

## 4. 验收

- `{{logo}}` 被识别为 image；
- 填充后输出 DOCX 含 1 个 inline shape，无残留占位符；
- 缺图片/越界/无效图片拒绝；
- 现有 M1a/M1b 测试保持通过；ruff/py38/architecture 通过。

## 5. 非目标

- 富文本（docxtpl RichText）槽位；
- 图片尺寸/裁剪/格式转换参数；
- 重复表格行 schema、前端表单。
