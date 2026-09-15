# 2026-09-09 Office 对标 Round 3 计划（批次 1-3 + Round 2 之后的第三轮）

> 前序已落地：批次 1（#554）、批次 2（#561）、批次 3（#563）、Round 2（#564）。
> 本轮是第三轮差距再分析；范围聚焦**验证基建、模板横向扩展、转换长尾、信任历史**。

## 再分析：Round 2 之后的剩余差距

| # | 差距 | 现状 | 本轮处理 |
|---|---|---|---|
| N1 | **office 流零 e2e 覆盖** | e2e-pr-gate 有 tier 机制但不含任何 office 场景；三次批次回归全靠单测/vitest | 本轮实施 |
| N2 | **模板库仅 Word** | batch 3 只做了 docx 模板（docxtpl）；Excel/PPT 模板缺失 | 本轮实施 |
| N3 | **PDF→Word 转换缺失** | 方案 G14 长尾；文本版 PDF 可低成本重建 docx（有限保真需声明） | 本轮实施（文本级） |
| N4 | **self_check 无历史** | 每次回读即抛即弃；用户无法回顾「AI 改了什么、验证结果如何」 | 本轮实施（SQLite 历史表 + 详情 UI） |
| N5 | **归档视图无批量操作** | 逐条归档/恢复 | 本轮实施（多选批量） |
| N6 | 大 PDF @ 注入预算 | 已有预算截断 | 不动 |
| N7 | 沙箱实施 | 设计文档已交付（评审门控中） | 维持等待评审 |
| N8 | OCR / PDF→PPT / 数字签名 | 重依赖、场景窄 | round 4+ |
| N9 | Excel/PPT 公式求值外的 deepseek 类表格推理 | 超出桌面端定位 | 不做 |

## 本轮实施：N1、N2、N3、N4、N5

### N1 office 关键流 e2e（Playwright，e2e-pr-gate tier 体系）
- 新增 tier-1 用例 2 个：
  1. `office-pdf-generate-preview`：/office 页生成 PDF → 预览面板出页卡 → 文档列表出现 pdf 行
  2. `office-template-edit-apply`：从模板创建 Word → 编辑预览（diff）→ 一键应用 → 列表/预览刷新（覆盖 round-2 R1 全链路）
- 遵循 `e2e/` 现有 tier/fixture 约定（stub 后端模式，不依赖真实 LLM）

### N2 模板库横向扩展（Excel + PPT）
- Excel 模板：`template_library.py` 扩 `doc_type='excel'`，build 用 openpyxl 构造（表头/样式/冻结首行/示例公式），`instantiate` 走 generate_xlsx 同级路径；模板 placeholder 语义 = 表名/表头/示例行约定（docxtpl 无 xlsx 等价物，采用「单元格标记 `{{var}}` 文本 + 实例化时全簿扫描替换」的轻方案）
- PPT 模板：python-pptx 构造标题/正文/图片占位版式，同样 `{{var}}` 文本替换
- 前端：模板选择器落到 Excel/PPT 页签；placeholder 表单复用
- 后端 instantiate 分派按 doc_type；文档列表入库照旧

### N3 PDF→Word（文本级）
- `backend/office/pdf_to_word.py`：PyMuPDF 逐页 blocks（保留块序/近似标题字号→heading 映射）→ python-docx 重建；表格（round-2 find_tables 结果）转 docx 表格
- 新 route `POST /office/pdf/to-word`；产物入库（doc_type=word, derived_from=pdf doc id）
- 明确保真边界：仅文本层；扫描件提示需 OCR（非目标）

### N4 self_check 验证历史
- SQLite 新表 `office_self_checks(id, doc_id, action, ok, summary_json, created_at)`（migration 追加）
- 写入点：office_create/office_update/apply-update/archive/restore 的 self_check 生成处（工具层 + apply_update.py 统一 helper）
- 前端：文档详情（快照面板旁）新增「验证历史」列表（时间/动作/结果/摘要）
- Route：`GET /office/doc/{doc_id}/self-checks`

### N5 归档视图批量操作
- OfficeDocumentList 归档视图支持多选 + 批量恢复/批量归档（循环调既有 API，进度 toast）

## 非目标
N7 沙箱实施（等安全评审，设计文档已在 main）；N8 OCR/签名；在线协编辑/云同步（Won't-v1 不变）。

## win7 对齐说明
批次 1 已 cherry-pick 到 release/win7（#560）。批次 2/3/Round2 **不进 win7**（matplotlib/formulas 无法进 py38 bundled 清单；测试依赖其存在），属方案既定的 main 通道特性。本轮新增依赖：无（全部复用现有库）。

## 验收
- N1：两个 e2e 用例在 stub 模式稳定通过并进 e2e-pr-gate 对应 tier
- N2：Excel/PPT 模板可列出、可实例化、产物入库出现在文档列表
- N3：文本版 PDF 一键转 Word，产物可读、来源 lineage 正确
- N4：任意 office 写操作后验证历史可查、UI 可见
- N5：归档视图可多选批量恢复
- 回归：全 sweep 不新增失败；前端 tsc/eslint/vitest 全绿；py38 护栏 0 violations
