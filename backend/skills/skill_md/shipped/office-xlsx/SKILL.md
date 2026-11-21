---
name: office-xlsx
description: Excel 工作簿工作流——结构化生成、公式与格式编辑、本地数据分析、读侧校验（图表/条件格式/数据验证）与公式缓存处理。处理 .xlsx/.csv 任务时使用。
license: Apache-2.0
compatibility: 需要 office_create/office_read/office_update/office_analyze；公式重算/健康检查需工作台（LibreOffice 可选）
when_to_use: 当用户要"做一张 Excel 表""按模板生成月报""改这个表格的公式/格式""分析这份销售数据""检查公式有没有报错"时使用
allowed-tools: office_list office_read office_create office_update office_analyze office_restore ask_user_question
triggers: []
---

# Excel 工作簿（.xlsx/.csv）

> shipped 基础版。复杂排版/打印设置走 `content.format_spec` 与
> `office_create` 的 Excel 参数；本技能负责结构与数据，不臆造数据源。

## 工作流

### 1. 明确表结构

先确认：sheet 名、列头、数据类型（文本/数值/日期/公式）、是否需要图表。
缺关键信息用 `ask_user_question`，**不猜业务列**。

### 2. 生成

`office_create` + `doc_type="excel"`，`content.sheets[]`：
- `headers` + `rows`；数字按 Excel 录入语义转换；
- 公式写 `=SUM(B2:B10)` 形式，**不要写死计算结果**；
- 图表写 `charts[]`（line/bar/pie + anchor + data_ref）；
- 条件格式/数据验证/打印设置走生成参数的对应字段（见工具 schema）。

### 3. 读取与编辑

- `office_read` 返回单元格、公式视图、图表/条件格式/数据验证清单；
  公式单元格有缓存值时会显示 `→ 值`。
- `office_update` 支持：`set_cells`、`append_rows`、增删 sheet、图表、
  列宽/数字格式/填充/冻结，以及 `insert_rows/delete_rows/insert_cols/
  delete_cols`、`merge_cells`。
- 行列增删**不会自动迁移公式引用/图表锚点/条件格式范围**，op 结果会带
  `formula_refs_merged_ranges_and_charts_not_migrated` 警告；据此向用户
  说明并在 Excel 中复核。

### 4. 公式缓存与健康

- openpyxl 保存后公式无缓存值：交付前在工作台执行「公式重算」（soffice，
  不可用时提示用户在 Excel 打开保存一次）。
- 工作台「公式健康」会列出 `#REF!/#DIV/0!/#VALUE!` 等错误与缺缓存单元格；
  有错误值时**不要直接交付**，先修复公式或告知用户。

### 5. 自检

`office_read` 回读：sheet 数/行数/公式清单/图表数；必要时用
`office_analyze` 做 describe/groupby 交叉核对关键合计。
