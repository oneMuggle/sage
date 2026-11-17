# 156 — PDF 页码引用与图表内联引用

> 文档编号：156
> 状态：已实现（2026-11-15，分支 `feat/pdf-figure-citation`）
> 来源计划：`docs/plans/2026-11-15_pdf-figure-citation.md`

## 1. 背景

改造前聊天附件里的 PDF 只用 PyMuPDF 逐页取文本后按换行拼接：

- 页边界丢失，模型无法回答「在第几页」；
- 插图、图注从未抽取（`PdfPageContent.images` 长期硬编码 `[]`）；
- 扫描件在上传路径没有 OCR 兜底，直接 `empty_text` 跳过；
- RAG 命中片段只有 `{index, score}`，没有页码；
- 聊天 Markdown 图片源被 react-markdown 默认消毒器误杀
  （`data:image`、`sage-file:`、Windows 盘符路径被清空）。

本改造让 AI 能在回答里标注页码、在提到图表时内联展示 PDF 原图。

## 2. 后端：`backend/services/attachment_pdf.py`

### 2.1 页级文本

```python
PdfPageText(page_number, text)
extract_pdf_pages(content) -> List[PdfPageText]
render_page_marked_text(pages) -> str
```

- 逐页 `page.get_text()`，保留真实页码（1 起始）；
- 文本层为空时调用 `backend/office/ocr.py:ocr_page_if_needed`
  （仅 `SAGE_OCR=1` 且 OCR 可用时生效），扫描件自动兜底；
- 注入格式：

```
--- page 1 ---
第一页正文...

--- page 12 ---
第十二页正文...
```

空页跳过，但页码保持真实。`_extract_document_text` 的 PDF 分支改为
`render_page_marked_text(extract_pdf_pages(content))`，上传、取全文、RAG 索引、
发送侧注入共用同一实现。

### 2.2 图表抽取

```python
ExtractedFigure(page_number, index_in_page, image_bytes, ext,
                width, height, bbox, caption)
extract_pdf_figures(content) -> List[ExtractedFigure]
```

- `page.get_images(full=True)` + `page.get_image_rects(xref)` 取 bbox，
  `doc.extract_image(xref)` 取原始字节；
- 过滤：宽 < 80 或高 < 60 的小图标；占页面积 ≥ 85% 的整页扫描背景；
  sha1 跨页/跨文档重复图；单文档最多 40 张；
- 图注：图片下方 120pt 内优先找以 `图/表/Figure/Fig./Table + 序号` 开头的
  文本块，否则取最近下方文本前 120 字符；
- **边界**：只覆盖嵌入位图；矢量图（Office 图表 / LaTeX 绘图）与复杂版式
  留待 MinerU 接入（§154）或页渲染兜底。

### 2.3 清单持久化

```python
get_or_build_figure_manifest(store, media_ref, content) -> List[dict]
figures_manifest_path(media_file) -> Path
```

- 裁出的图经 `MediaStore.save(kind=IMAGE, source="pdf_figure")` 落盘，
  sidecar 元数据含 `source_media_id/page/figure_id/caption`；
- 清单缓存到媒体同目录 `<media_id>.figures.json`（原子写，损坏自动重建）：

```json
{
  "version": 1,
  "source_media_id": "abc123def456",
  "figures": [
    {
      "figure_id": "f-p12-1",
      "page": 12,
      "caption": "图 3 系统架构",
      "media_id": "def456abc123",
      "media_url": "/api/v1/media/def456abc123",
      "width": 120,
      "height": 90,
      "bbox": [50.0, 70.0, 250.0, 220.0]
    }
  ]
}
```

### 2.4 注入格式

发送侧在 `<attached_document>` 内追加图清单，并为本请求追加一次引用说明：

```xml
<attached_document id='abc123' name='paper.pdf' type='application/pdf' pages="20">
--- page 1 ---
...
--- page 12 ---
...
<attached_figures document="paper.pdf">
<figure id="f-p12-1" page="12" caption="图 3 系统架构"
        media="/api/v1/media/def456abc123" />
</attached_figures>
</attached_document>
```

```
[附件图片引用说明] 回答涉及 <attached_figures> 中的图片时，使用
![简短图注](media属性值 "第N页 · 图X") 内联展示原图；引用 PDF 正文时标注页码。
```

无文本层但有图时（扫描页），注入占位说明而不是 `empty_text` 跳过。
附件状态 `attachments_processed` 增加 `pages`（页标记数）与 `figures`（图数）。

## 3. RAG 引用页码

`backend/services/attachment_context.py`：

- `ChunkCitation` 增加 `page_start/page_end`；
- `locate_chunk_pages(full_text, chunk_text)` 用命中 chunk 在带页标记全文中的
  偏移反查页码范围（定位失败返回 `None`，前端不展示页码）；
- `attachment_rag_used` 事件与 `RagCitation` 线协议透传页码；
- 前端附件引用明细显示 `#0 (0.91) · 第12-13页`。

## 4. 前端

- `src/widgets/markdown/links.ts:safeUrlTransform`：图片源放行
  `http(s)`、`blob:`、`sage-file:`、`data:image/*`、应用内绝对路径
  （`/api/...`）、Windows 盘符路径；`javascript:`/`vbscript:`/`file:`/`ftp:`
  始终拦截；链接仍走 react-markdown 默认白名单；
- `Markdown` 将 `urlTransform` 传给 ReactMarkdown；
- `MarkdownImage` 新增 `title` 图注（`data-testid="markdown-image-caption"`），
  模型输出的 `"第12页 · 图3"` 显示在原图下方，点击仍走 Lightbox；
- 新增 `MediaPdfPreview`：附件卡片与 RAG 引用页码点击后，经 IPC 取媒体 blob，
  交给 Chromium 内置阅读器并用 `#page=N` 定位；Esc / 遮罩 / 关闭按钮退出；
- 附件卡片 tooltip 显示「N 页 · M 图」。

## 5. 工具结果序列化修复

`backend/core/legacy/agent.py` 的工具结果曾用 `json.dumps(default=str)`，
把 `MediaRef` dataclass 变成 Python repr 字符串，前端拿不到 `id/mime_type`。
新增 `_json_default`：dataclass → `dataclasses.asdict`、Enum → `value`，
其余回退 `str`。`generate_image` 等图片工具的 `media_refs` 现在能正常内联渲染。

## 6. 测试

| 层次 | 文件 | 覆盖 |
| --- | --- | --- |
| 后端 | `backend/tests/unit/test_attachment_pdf.py` | 页标记、OCR 门控、图抽取/过滤/去重/图注、清单缓存与损坏重建 |
| 后端 | `backend/tests/unit/test_attachment_context_pages.py` | 页码反查（单页/跨页/无标记）与 RAG citation 页码 |
| 后端 | `backend/tests/unit/test_agent_json_default.py` | MediaRef dataclass 序列化为对象、未知对象回退 |
| 前端 | `src/widgets/markdown/__tests__/urlTransform.test.ts` | 图片源白名单与危险协议拦截 |
| 前端 | `src/widgets/chat/__tests__/MarkdownImage.test.tsx` | title 图注渲染 |
| 前端 | `src/widgets/chat/__tests__/Message.trust.test.tsx` | 引用页码展示（单页/跨页）与点击跳页 |
| 前端 | `src/widgets/chat/__tests__/MediaPdfPreview.test.tsx` | blob 加载、`#page` 定位、Esc/关闭/失败占位 |
| 前端 | `src/widgets/chat/__tests__/Message.clientMeta.test.tsx` | 附件卡片页数/图数 tooltip 与 PDF 预览入口 |

## 7. 边界与后续

- 矢量图、跨页表格、复杂版式：后续接 MinerU（§154）或命中页低 DPI 渲染；
- 视觉模型逐页读图（PDF 视觉通道）仍未实现，见 §131「未完成项」；
- 引用页码与附件卡片已支持点击打开 PDF 指定页（`MediaPdfPreview` +
  Chromium 内置阅读器 `#page=N`）。
