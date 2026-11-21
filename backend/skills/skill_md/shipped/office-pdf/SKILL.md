---
name: office-pdf
description: PDF 读取与产出工作流——逐页文本/表格提取、结构化生成、AcroForm 表单读取与填写、页码引用；页面级编辑（合并/拆分/旋转/水印/页码）走文档工作台。处理 .pdf 任务时使用。
license: Apache-2.0
compatibility: 需要 office_read_pdf/office_generate_pdf/office_read_pdf_form/office_fill_pdf_form；扫描页 OCR 需本地 OCR 引擎（RapidOCR/Tesseract）
when_to_use: 当用户要"读这份 PDF 的表格""把内容做成 PDF""填这个 PDF 表单""提取 PDF 第几页的内容"时使用
allowed-tools: office_read_pdf office_generate_pdf office_read_pdf_form office_fill_pdf_form office_create ask_user_question
triggers: []
---

# PDF 读取与产出（.pdf）

> shipped 基础版。PDF 页面级编辑（合并/拆分/旋转/删页/抽页/水印/页码）
> 目前在文档工作台提供；本技能负责读取、生成与表单。

## 工作流

### 1. 读取

- `office_read_pdf`：逐页文本 + 表格 + 元数据；回答用户时**标注页码**。
- 扫描件/图片页：提示在工作台启用本地 OCR 或附件「识别文字」。
- 需要对比多个 PDF：分别读取后按页码列出差异；不要凭文件名猜测内容。

### 2. 生成

`office_generate_pdf`：标题 + 段落 + 表格；复杂排版（封面/多栏）优先用
Word/LaTeX 生成再导出 PDF（工作台「导出 PDF」需要本机 LibreOffice 或 Word）。

### 3. 表单

1. `office_read_pdf_form` 枚举字段（类型/必填/选项）；
2. 与用户确认每个字段的值——**不猜身份证号、金额等敏感值**；
3. `office_fill_pdf_form` 输出新文件（默认 `<stem>-filled.pdf`）；
   需要 flatten 时显式说明其效果（字段变只读）。

### 4. 引用与交付

- 聊天回答引用 PDF 时用"第 N 页"；图表引用写"第 N 页 · 图 M"。
- 页面操作（合并/拆分/水印等）引导用户到文档工作台，或在会话中使用
  对应工作台动作；不要在对话里声称已修改而实际未执行。

## 红线

- 扫描件识别结果必须标明"OCR 结果，请复核关键数字"。
- 不修改源 PDF；所有填写/生成输出新文件。
