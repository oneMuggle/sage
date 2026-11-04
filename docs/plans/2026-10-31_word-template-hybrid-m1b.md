# Word 模板 M1b：Jinja 控制流混合渲染 + 页眉页脚

> 日期：2026-10-31 · 分支：`feat/word-template-profile`
> 基线：`origin/main` = `9fda6607a`（M1a 合并后）
> 范围：在 M1a Profile 上补 Jinja 控制流与页眉/页脚槽位。

## 1. 目标

- 不再拒绝含 `{%`/`{#` 的模板；先完成内容控件/书签/占位符替换，再用现有 docxtpl/SandboxedEnvironment 渲染 Jinja 控制流与循环。
- 扫描并填充页眉/页脚中的占位符与内容控件。
- 保留 M1a 的必填校验、输出不覆盖、residual 检查与安全校验（`_validate_template_safety`）。

## 2. 实现

`word_template_profile.py`
- `_story_slots`：遍历每节 header/footer 的段落/表格，识别占位符与内容控件；anchor 增加 `part/section/story`。
- `has_jinja_control` 同时扫描正文与页眉页脚文本。

`word_template_profile_fill.py`
- `_iter_paragraphs` 覆盖正文、表格、页眉页脚；
- `_fill_story_content_controls` 填充页眉页脚中的 `w:sdt`；
- 手动填充后写临时 docx：
  - 无控制流 → 临时文件 rename 为输出；
  - 有控制流 → `_validate_template_safety` + `DocxTemplate.render(data, SandboxedEnvironment)` → 输出；
- 结果新增 `jinja_rendered`。

## 3. 验收

- 含 `{% if %}` 的模板成功渲染，同时 `<<name>>` 被填充；
- 页眉 `<<running>>`、页脚 `{{note}}` 正确填充，residual 为空；
- 现有 M1a 测试继续通过；
- ruff / py38 / architecture 通过。

## 4. 非目标

- 重复表格行/条件块建模（docxtpl 自身循环仍可用，但不做自定义 schema）；
- 图片/富文本槽位；
- 前端表单、模板库 instantiate 工具。
