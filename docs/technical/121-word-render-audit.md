# 121 — Word 渲染级校验（M5a）

> 日期：2026-11-01 · 分支：`feat/word-render-audit`
> 方案：`docs/plans/2026-10-31_word-document-intelligence.md`（M5）、`docs/plans/2026-11-01_word-render-audit-m5a.md`

## 1. 定位

结构审校（119）读取 DOCX XML；本模块校验**渲染后的真实排版**：经本机
LibreOffice / Word COM 转 PDF，再用 PyMuPDF 检查页面尺寸、页边距、字体与页码。

- 转换复用 `backend/office/export_pdf.py`（进程内串行、超时、失败不抛错）；
- 无转换器时返回 `rendered=false` + `render_unavailable` warning，不影响结构审校；
- 生成的 PDF 落在源文件旁（`<stem>.pdf`），与既有导出行为一致。

## 2. 接口

`POST /api/v1/office/word/audit/render`

```json
{
  "workspace_path": "/ws",
  "file_path": "/ws/doc.docx",
  "expected_size": "A4",
  "margins_cm": {"top": 3.7, "bottom": 3.5, "left": 2.8, "right": 2.6},
  "allowed_fonts": ["仿宋_GB2312", "Times New Roman"],
  "require_page_number": true,
  "margin_tolerance_cm": 0.3,
  "page_number_band": 0.15,
  "timeout_seconds": 120
}
```

响应：

```json
{
  "ok": false,
  "source_path": "doc.docx",
  "rendered": true,
  "method": "libreoffice",
  "page_count": 3,
  "issues": [
    {"page_index": 0, "category": "margin", "severity": "error",
     "message": "第 1 页左侧正文距页面边缘 1.20cm，小于期望 2.8cm",
     "expected": "2.8cm", "actual": "1.20cm"}
  ],
  "warnings": []
}
```

- `expected_size` 缺省：以首页尺寸为基准，其余页偏差 >1mm 报 warning；
- `margins_cm` 缺省：跳过边距检查；正文块排除页眉/页脚 10% 带；
- `allowed_fonts` 缺省：跳过字体检查；字体名去子集前缀并允许互为子串；
- `require_page_number=true`：页面底部 `page_number_band`（默认 15%）内需有数字；
- `ok=false` 仅当存在 `error`（页面尺寸/页边距）；字体与页码为 warning。

## 3. 降级与安全

- 路径/扩展名/工作区围栏与 50 MiB 上限复用既有约定；
- `export_to_pdf` 失败 → `rendered=false` + warning；
- PyMuPDF 缺失/PDF 解析失败 → `rendered=true` + `render_audit_failed` warning；
- 只读源 DOCX；输出 PDF 为转换器正常产物。

## 4. 限制（后续）

- 批量审计与报告导出（M5b）；
- 前端渲染审计面板（M5c）；
- 单元格内溢出、分栏、图表越界等专业排版检查；
- 页码/页眉页脚定位为文本带近似，非 Word 结构级识别。

## 5. 批量审校（M5b）

`POST /api/v1/office/word/audit/batch`

- `file_paths` 显式列表优先，否则按 `pattern`（默认 `**/*.docx`）扫描工作区；
- 跳过隐藏目录与 `.git/.sage/node_modules/dist/build/...`；
- `max_files` 上限（1–100）；单文件超限/解析失败记为失败文件，不中断整批；
- 响应 `totals{files,ok_files,failed_files,issue_count,error_count,warning_count}` +
  `files[{source_path,ok,issue_count,error_count,warning_count,issues,warnings,error}]` +
  `report_markdown`（include_report 控制，单文件最多列 20 条 issue）；
- `ok` = 无失败文件且无 error 级 issue；只读，不生成 PDF。

```json
{"workspace_path": "/ws", "pattern": "**/*.docx", "max_files": 20, "rulepack_id": "general-quality", "include_report": true}
```

## 6. 测试

- `backend/tests/unit/office/test_word_render_audit.py`（5）：
  A4 尺寸/越界边距/非允许字体/缺失页码、无转换器降级、注入导出 PDF、非 docx 拒绝；
- `backend/tests/integration/test_office_word_render_route.py`（2）：
  选项透传、超限/越界拒绝；
- `backend/tests/unit/office/test_word_batch_audit.py`（5）：
  显式/模式收集、隐藏目录跳过、越界/非法 pattern、汇总/报告、坏文件与大小上限；
- `backend/tests/integration/test_office_word_batch_route.py`（2）：
  工作区批量审校、非法 pattern/越界拒绝；
- ruff 0.4.4、py38 兼容、architecture 门禁通过。
