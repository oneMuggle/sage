# Office 结构化提取与 PDF 复杂表格兜底（M6b）

> 状态：已实现（2026-11-21 首版 / 2026-11-23 PDF 表格兜底）
> 相关计划：`docs/plans/2026-11-21_office-document-ai-upgrade.md`（M6）
> 代码位置：`backend/office/extractors/`、`backend/office/pdf.py`

## 1. 背景与目标

Office 文档此前有四套各说各话的读取路径（`read_docx` / `read_xlsx` / `read_ppt` / `read_pdf`），
每套返回自己的形状，下游（RAG、对比、工具面）无法统一消费。M6b 引入 **提取适配器层**：
无论后端是谁，都产出同一种 `StructuredDocument` —— 一份 Markdown + 一组带锚点的块。

PDF 是这一层最难伺候的格式：**表格**。轻量后端靠 PyMuPDF 的矢量线框重建网格，遇到
合并单元格、无边框表格、超宽表就会丢结构。本章记录 M6b(c) 的解法：**复杂度诊断 +
无边框探测 + 结构化后端兜底路由**。

## 2. 分层

```
backend/office/extractors/
├── base.py        # StructuredDocument / ExtractedBlock / Extractor 协议
├── registry.py    # 后端注册表 + 能力探测（extractor_available / get_extractor）
├── light.py       # 默认后端：包住既有的四个 reader
├── optional.py    # 可选后端：markitdown / docling（懒加载，缺失即 unavailable）
├── tables.py      # 策略层：表格 Markdown 渲染 + 复杂度判定
└── service.py     # 编排层：后端选择 + 兜底路由 + 结果裁剪
```

四个层次各有明确职责，**测量与判定分离**是本设计的关键：

| 层 | 文件 | 职责 | 不做什么 |
| --- | --- | --- | --- |
| 测量层 | `office/pdf.py` | 客观测量表格「长什么样」 | 不判断复不复杂 |
| 策略层 | `extractors/tables.py` | 由测量值推导复杂度 | 不碰 PDF |
| 适配层 | `extractors/{light,optional}.py` | 产出统一 `StructuredDocument` | 不决定换不换后端 |
| 编排层 | `extractors/service.py` | 选后端、决定兜底、裁剪结果 | 不重新实现测量 |

## 3. 提取后端

| 后端 | 依赖 | 覆盖格式 | 产出 table 块 |
| --- | --- | --- | --- |
| `light` | 无（复用既有 reader） | docx / xlsx / pptx / pdf / csv | 是（docx / xlsx / csv / pdf） |
| `markitdown` | `pip install markitdown` | docx / xlsx / pptx / pdf / csv / md / html / txt | 否（只出 Markdown） |
| `docling` | `pip install docling` | 同上 | 是（真网格） |

`light` 是默认后端；`auto` 模式下按 `docling → markitdown → light` 顺序挑第一个**可用**的
（可用 = 已安装且支持该扩展名）。所有可选后端都是懒加载：缺包时注册表探针把它标成
`unavailable`，调用方回退 `light`，**整次提取不失败**。

## 4. PDF 表格测量

`read_pdf` 返回的 `PdfReadResult.table_diagnostics` 只描述表格的**形状**，不含单元格正文：

| 字段 | 类型 | 含义 |
| --- | --- | --- |
| `table_count` | int | 识别到的框线表格数（跨页累计） |
| `null_cells` | int | PyMuPDF 填不出的格子数（合并单元格与缺格都表现为 `None`） |
| `total_cells` | int | 格子总数（跨页累计） |
| `max_rows` | int | 最长表格的行数 |
| `max_cols` | int | 最宽表格的列数 |
| `truncated` | bool | 是否触到每页 20000 格的提取上限 |
| `failed_pages` | int | 表格识别抛错的页数 |
| `borderless_candidate_pages` | int[] | 疑似无边框表格的页码（1-based） |

> **术语澄清**：PyMuPDF 对合并单元格和缺格一律返回 `None`，二者无法区分。因此字段名用
> `null_cells`（而不是 `merged_cells`），原因码才叫 `merged_cells`。

## 5. 无边框表格探测

PyMuPDF 的 `find_tables(strategy="text")` 按空白列对齐猜表格，**过于激进**：
普通散文会被打散成「每个词一列」的十几列假表格；而真正的无边框表格只有几列、每格都很短。

因此 `strategy="text"` **只作探测器**，绝不产出正文。命中条件（四条全满足才算候选）：

| 条件 | 常量 | 理由 |
| --- | --- | --- |
| ≥2 行有内容 | — | 单行不足以说明是表格 |
| 每行 ≥2 格被填充 | — | 单词流不会每行都有多列 |
| 列数 ≤ 8 | `BORDERLESS_PROBE_MAX_COLS` | **判别式**：散文碎裂会冲到十几列 |
| 最长单元格 ≤ 40 字符 | `BORDERLESS_PROBE_MAX_CELL_CHARS` | 表头/单元格短，散文整句长 |

**列数才是判别式，不是单元格长度** —— 只用「单元格短」会被等宽字体散文击穿
（散文被切成 12–15 个 ≤40 字符的词格）。

探测有三重成本闸：仅在「本页没有框线表格 + 正文 ≥40 字符 + 页码 <50」时才跑，
命中后**只记页码**，猜测出的网格绝不写进 Markdown。

## 6. 复杂度判定

`assess_table_complexity(diagnostics)` 返回稳定的原因码列表（空列表 = 不复杂）：

| 原因码 | 触发条件 | 中文标签 |
| --- | --- | --- |
| `merged_cells` | `null_cells > 0` | 合并单元格或缺格造成表格空洞 |
| `cell_cap_truncated` | `truncated` | 表格过大已被截断 |
| `wide_table` | `max_cols >= 12` | 超宽表格 |
| `tall_table` | `max_rows >= 40` | 超长表格 |
| `table_detection_failed` | `failed_pages > 0` | 部分页面的表格识别失败 |
| `borderless_table_candidate` | `borderless_candidate_pages` 非空 | 疑似无边框表格 |

诊断是**建议性**的：缺失或未知的键一律按「不复杂」处理，绝不因为诊断不全而让提取失败。

## 7. 兜底路由

`ExtractRequest.table_fallback` 三档：

| 值 | 行为 |
| --- | --- |
| `auto`（默认） | 检测到复杂表格时改用结构化后端（`docling`）重解析一次 |
| `force` | 始终用结构化后端（PDF） |
| `off` | 关闭兜底，保留轻量结果 |

失败语义（关键设计：**兜底失败不能让整次提取失败**）：

| 情形 | 结果 | warning code |
| --- | --- | --- |
| 兜底成功 | 结果替换为结构化后端产物，`extractor` 字段改为 `docling` | `table_fallback_docling` |
| 结构化后端未安装 | **保留 light 结果** | `table_fallback_unavailable` |
| 结构化后端不支持该格式 | 保留 light 结果 | `table_fallback_unavailable` |
| 兜底解析抛错 | 保留 light 结果（记 warning 日志） | `table_fallback_failed` |

light 后端本身在检测到复杂表格时也会发一条 `table_complex` warning，
消息里用中文列出命中的原因码。

## 8. API 契约

`POST /api/v1/office/extract`（`ExtractRequest`）新增字段：

```json
{ "workspace_path": "...", "file_path": "...", "backend": "auto", "table_fallback": "auto" }
```

`table_fallback` 取值 `auto` / `off` / `force`，缺省 `auto`。响应中的
`document.warnings` 数组元素形状为 `{"code": "...", "message": "..."}`。

## 9. 可选依赖安装

docling 会拖入 torch + transformers 推理栈（数百 MB），markitdown 轻量但覆盖格式多。
两者都**不进默认依赖**，登记在 `backend/requirements-optional.txt`（注释态 + 「为什么单独放」）：

```bash
pip install "docling>=2.0" "markitdown>=0.1"
python -c "from backend.office.extractors import extractor_available; \
           print(extractor_available('docling'), extractor_available('markitdown'))"
```

**Win7（Python 3.8）不装**：两者都要求 Python 3.9/3.10+，`backend/requirements-py38.txt` 保持不变。

## 10. 测试与门禁

- 单测：`backend/tests/unit/office/test_pdf_tables_m6b.py`（17 个）—— 渲染 / 6 个原因码 /
  合并表头 `null_cells` / 无边框探测对散文不误报 / light table 块 / 兜底 auto-off-force /
  后端不可用 / 兜底失败保留原结果。
- 门禁：ruff、py38 兼容门禁（`scripts/check_py38_compat.py`）、architecture 棘轮
  （`scripts/architecture-check.mjs`）、silent-exception 棘轮（`scripts/check_silent_exceptions.py`）。

## 11. 已知限制

1. **表格网格还原仍是启发式**：合并单元格在 light 后端里表现为空洞（渲染成 `| 00 |  |`），
   只有装了 docling 才能拿到真网格。
2. **无边框探测可能漏报**：判别式偏保守（要求每行 ≥2 格、列数 ≤8），
   一列一行的「伪表格」不会被识别。
3. **兜底会重解析一次**：docling 解析耗时明显高于 light，故只在命中复杂表格时才触发；
   `table_fallback="force"` 会无条件付出这份成本。
4. **docling 的表格 API 在版本间动过**：`_docling_table_rows` 对每种取法都做了保护
   （`data.grid` → `export_to_dataframe`），读不出的表格直接跳过而不是让整次提取失败。
