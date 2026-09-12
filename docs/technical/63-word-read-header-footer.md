# 63 — read_docx 补页眉/页脚/目录域提取（Round 15）

> 日期: 2026-09-12 · 分支: `feat/word-read-header-footer` · 方案:
> `docs/plans/2026-09-12_word-read-hf-r15-plan.md`
> 系列: Word/Office 写作能力增强第 9 轮（R7-R14 见 55-62 号技术文档）

## 1. 定位

R7-13 生成的文档带页眉/页脚/目录域，但 `read_docx` 明确"does NOT
extract headers / footers"（docstring 注明）——用户上传旧文档或编辑
R7-13 产物时，这些元素在读取与 @引用回路不可见。本轮补齐读取侧，
形成"生成 → 读取 → 编辑"全链路闭环。

## 2. 变更

- **`WordHeaderFooterContent`**（models.py）：`section`（1-based 节号）/
  `header_text` / `footer_text` / `has_page_number_field`（页脚含
  `w:fldSimple instr=PAGE` 域）
- **`OfficeWordReadResult`** 新增 `headers_footers`（逐节）与
  `toc_fields`（instr 以 TOC 开头的域列表）
- **提取规则**：linked（继承前节）的节文本取空；**全空且未断开链接的
  节不产出记录**（避免纯文档出现空壳条目）；提取失败不阻断正文读取
  （comments 同款 best-effort 语义）
- word.py docstring 的 "does NOT extract headers / footers" 非目标声明
  同步移除

## 3. Win7 对齐与测试

零新增依赖、零 API 面变更（read result 追加可选字段，旧消费者忽略）；
不 cherry-pick（31-win7-lts.md §2）。
`tests/integration/test_office_word_read_hf.py` 4 项：带页眉/页码域/目录
的往返读取、纯文档空提取、占位文本可见、多节文档逐节报告（linked 跳过
语义）。office 回归 64 项 + ruff/tsc/eslint 全绿。

## 4. 系列状态（R7-R15）与 Round 16 候选

九轮：Word 侧（版式/元素/引用/校验/技能/自愈/目录/读取闭环）+ Excel
数据表格式。Round 16 候选：@引用注入升级（页眉页脚进 chat_refs 摘要）、
journal 接入引用引擎、Excel 条件格式/数据条、Pillow 图片管线。
