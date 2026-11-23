# PDF 页码引用与图表内联引用

> 计划日期：2026-11-15
> 分支：`feat/pdf-figure-citation`（基于 `release/win7`）
> 关联调研：会话中 LLM 图片能力评估（2026-11-15）

## 1. 背景与目标

现状：用户把 PDF 拖进聊天后，后端只用 PyMuPDF 抽取纯文本，**页边界、图片、图注全部丢失**；模型无法标注页码，更无法在回答中引用 PDF 里的图。AI 侧也没有一等公民的图片输出通道。

目标（按用户可感知的顺序）：

1. **页码可引用**：模型回答 PDF 内容时能准确标注"第 N 页"，附件注入块与 RAG 引用卡片都带页码。
2. **图表可引用**：上传的 PDF 自动抽取插图（含图注与页码），AI 在提到相关要点时用 Markdown 图片内联展示原图缩略图，并标注"第 N 页 · 图 X"。
3. **渲染可用**：修掉 Markdown 图片被默认 URL 消毒器误杀的问题（`data:`、`sage-file:`、Windows 盘符路径），保证内联图在 win7/桌面端可显示。

非目标（本期不做）：

- PDF 全页高 DPI 视觉通道（`docs/technical/131-attachment-pipeline.md` 已列为后续项）。
- 图级 bbox 高亮、点击引用跳到预览指定页（列为 M2，见 §5）。
<<<<<<< HEAD
- 矢量图（非嵌入位图）的裁切，复杂版式接入 MinerU（§157 部署方案）。
=======
- 矢量图（非嵌入位图）的裁切，复杂版式接入 MinerU（§154 部署方案）。
>>>>>>> origin/main

## 2. 现状与根因

| 编号 | 根因 | 位置 |
| --- | --- | --- |
| R1 | PDF 逐页取文本后按 `\n` 合并，页边界丢失 | `backend/api/chat_attachment_routes.py:144-150` |
| R2 | 上传路径不调用 `office/pdf.py` 的 OCR 兜底，扫描件直接 `empty_text` | `backend/api/legacy_routes.py:1620-1624` |
| R3 | PDF 图片从未抽取；`PdfPageContent.images` 硬编码 `[]` | `backend/office/pdf.py:259-266` |
| R4 | RAG chunk 只有 `{index, score}`，无页码 | `backend/services/attachment_context.py:30-45` |
| R5 | 聊天 Markdown 图片走 react-markdown 默认 `urlTransform`，`data:` / `sage-file:` / `C:\` 被清空 | `src/widgets/markdown/Markdown.tsx:97-103` |
| R6 | 工具结果序列化把 `MediaRef` dataclass 转成 Python repr，图片工具内联渲染不可靠 | `backend/core/legacy/agent.py:3013-3029` |

## 3. 技术方案

### 3.1 新增模块 `backend/services/attachment_pdf.py`

```
PdfPageText(page_number, text)
ExtractedFigure(page_number, index_in_page, image_bytes, ext,
                width, height, bbox, caption)

extract_pdf_pages(content) -> List[PdfPageText]
render_page_marked_text(pages) -> str          # "--- page N ---" 分隔
extract_pdf_figures(content, ...) -> List[ExtractedFigure]
get_or_build_figure_manifest(store, media_id, content) -> List[dict]
```

- **页文本**：逐页 `page.get_text()`；文本近乎为空时复用
  `backend/office/ocr.py:ocr_page_if_needed`（受 `SAGE_OCR=1` 门控，win7 同样可用）。
- **页标记**：`--- page N ---`，与 `@file` 工作区 PDF 摘要的既有格式一致。
- **图抽取**：`page.get_images(full=True)` + `page.get_image_rects()` 取 bbox，
  `doc.extract_image(xref)` 取字节；过滤小图标（宽 <80 或高 <60）、整页扫描背景
  （面积 ≥ 85% 页面积）、跨页重复图（sha1 去重）；单文档上限 40 张。
- **图注**：在图片下方 120pt 内找以 `图/表/Figure/Fig./Table` 开头的文本块，
  找不到则取最近的下方文本块前 120 字符。
- **持久化**：裁出的图经 `MediaStore.save(kind=IMAGE, source="pdf_figure")` 落盘，
  清单写入媒体同目录 `<media_id>.figures.json`（原子写，二次调用直接读缓存）。
  清单项：`{figure_id, page, caption, media_id, width, height, bbox}`。

### 3.2 注入格式

PDF 附件注入块内追加页标记文本与图清单：

```xml
<attached_document id='abc' name='paper.pdf' type='application/pdf'>
--- page 1 ---
...
--- page 12 ---
...
<attached_figures document='paper.pdf'>
<figure id='f-p12-1' page='12' caption='图 3 系统架构'
        media='/api/v1/media/def456' />
</attached_figures>
</attached_document>
```

本请求存在任何图片时追加一次引用说明：

```
[附件图片引用说明] 回答涉及 <attached_figures> 中的图片时，使用
![简短图注](media 属性值 "第N页 · 图X") 内联展示原图。
```

模型引用 PDF 正文时要求标注页码（`（第 12 页）`），页码来自注入文本里的页标记。

### 3.3 RAG 引用页码

`ChunkCitation` 增加可选 `page_start/page_end`。检索注入时用命中 chunk 文本在
全文中的偏移反查页标记，得到页码范围；事件与 `RagCitation` 线协议透传，
前端在附件引用明细里显示「第 12-13 页」。

### 3.4 前端

- `Markdown` 增加 `urlTransform`：`src` 放行 `http(s)`、`blob:`、`sage-file:`、
  `data:image/*`、应用内绝对路径（`/api/...`）、Windows 盘符路径；其余协议
  仍走 react-markdown 默认白名单（`javascript:` 等照旧拦截）。
- `MarkdownImage` 增加 `title` 展示为图注（含页码），沿用现有点击放大 Lightbox。
- `RagCitation` / 附件状态类型增加页码与图片计数字段，引用明细展示页码。
- `agent.py` 工具结果序列化对 dataclass 走 `dataclasses.asdict`，修复
  `generate_image` 等工具图片的 `media_refs` 结构。

## 4. 实施步骤

### M1 页码感知文本

- [x] `attachment_pdf.py`：页文本抽取 + 页标记渲染 + OCR 兜底
- [x] `_extract_document_text` PDF 分支改用页标记文本
- [x] 发送侧注入块带 `pages` 属性；附件状态增加 `pages`
- [x] `ChunkCitation` / RAG 事件 / 前端类型增加页码并渲染
- [x] 后端单测：页标记、扫描件 OCR 门控、RAG 页码反查

### M3 图表抽取与内联引用

- [x] `attachment_pdf.py`：图抽取（过滤/去重/图注）+ 清单缓存
- [x] 发送侧构建清单并注入 `<attached_figures>` + 引用说明
- [x] 前端 URL 消毒白名单 + 图注展示
- [x] `agent.py` dataclass 序列化修复
- [x] 后端单测：图抽取、清单缓存幂等；前端单测：urlTransform、图注、引用页码

### M2 预览跳页

- [x] 附件 chip 点击打开 PDF 预览（媒体 blob + `#page=N`）
- [x] 引用页码 chip 点击定位到对应页

> 已实现（2026-11-15）：`MediaPdfPreview` 组件 + 附件卡片 / 引用页码两个入口。

### 文档

<<<<<<< HEAD
- [x] `docs/technical/159-pdf-figure-citation.md` + README 索引
=======
- [x] `docs/technical/156-pdf-figure-citation.md` + README 索引
>>>>>>> origin/main
- [x] `docs/user-manual/52-pdf-figure-citation.md` + README 索引
- [x] 更新 `docs/technical/131-attachment-pipeline.md` 的「未完成项」

## 5. 风险与依赖

| 风险 | 处理 |
| --- | --- |
| PR #3090（附件格式统一）未合并，同样修改 `chat_attachment_routes.py` / `legacy_routes.py` | 本分支改动限定在 PDF 分支与注入块；#3090 合并后 rebase，冲突点集中在提取函数 PDF 分支 |
| win7 / Python 3.8 | 全部使用 `Optional[...]` / `List[...]`，不用 PEP 604；PyMuPDF 已在依赖内 |
| 图表抽取耗时 | 发送侧线程池执行 + 清单缓存；解析失败 fail-safe 跳过，不阻断聊天 |
<<<<<<< HEAD
| 矢量图/复杂版式漏抽 | 文档声明边界；后续接 MinerU（§157）或页渲染兜底 |
=======
| 矢量图/复杂版式漏抽 | 文档声明边界；后续接 MinerU（§154）或页渲染兜底 |
>>>>>>> origin/main
| Token 成本 | 只注入图清单（文字），不注入图片字节；模型按需引用 URL |
| 隐私 | 裁图只落本地 `data/media`；仅当模型需看图时才会发往模型端点 |

## 6. 验证

- 后端：`pytest backend/tests/unit -k "attachment or media or pdf"`；
  新增 `test_attachment_pdf.py`、补充 `test_attachment_context.py`。
- 前端：`npx vitest run src/widgets/markdown src/widgets/chat`。
- 门禁：`npm run typecheck`、`node scripts/architecture-check.mjs`、
  `node scripts/check-font-scale.mjs`、`npm run build`。
- 手工：上传一份含插图的 PDF → 提问 → 回复出现「第 N 页」与内联原图。

## 7. 双分支

纯后端 + 前端变更，win7 侧注意 py38 语法与 pydantic v1 兼容；无依赖升级。
main 同步时 cherry-pick + 跑 main 的后端测试。
