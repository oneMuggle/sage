# 2026-09-09 Office 对标 Round 2 计划（批次 1-3 落地后的再分析）

> 前序：批次 1（#554，PDF/模板工具接线、Excel 公式、快照管理、前端 PDF/归档）、批次 2（#561，图表/图片、office_analyze、样式、diff 预览、富预览、PDF 导出）、批次 3（#563，模板库、Word 批注、生成自校验、沙箱设计文档）。
> 本文是落地后的**第二轮差距再分析**与可实施计划。

## 再分析：批次 1-3 之后仍然存在的差距

| # | 差距 | 现状证据 | 本轮处理 |
|---|---|---|---|
| R1 | **页面级应用编辑路由缺失** | 批次 2 的 OfficeEditPreviewDialog 只能预览，无 apply 端点（批次 2 代理实证：backend 无 HTTP update 路由）；「应用需在对话中进行」是临时妥协 | 本轮实施 |
| R2 | **读取保真度未完成**（2.4 只落了样式/图表相关） | `pdf.py:140-142` tables 仍是 stub（PyMuPDF `find_tables()` 未用）；`read_docx` 段落文本无 run 级粗斜体标记，LLM 看不到格式 | 本轮实施 |
| R3 | **批注未接入 LLM 面** | 批次 3 的 `read_docx_comments` 是独立函数：`OfficeWordReadResult` 无 comments 字段、@ 注入 digest 无批注信息、office_read 不返回批注 | 本轮实施 |
| R4 | **LLM 无 dry-run** | LLM 只能直接 update（有 self_check 但已落盘）；diff_preview 只有 HTTP 面，工具面没有 dry_run 参数 | 本轮实施 |
| R5 | **Excel 公式无法本地求值** | openpyxl 不计算公式；`office_read` 公式模式只能看到公式文本+缓存值缺失提示 | 本轮实施（formulas 库懒加载，main 通道） |
| R6 | **分析图表不进聊天** | office_analyze 图表只嵌在报告 xlsx 里，聊天中不可见 | 本轮实施（PNG artifact 注册） |
| R7 | **归档/恢复等其他工具无回读** | self_check 只覆盖 create/update | 本轮实施（archive/restore/snapshot-restore 附回读摘要） |
| R8 | office 页关键流无 e2e | e2e-pr-gate 有 tier 机制但 office 流未覆盖 | 评估工作量，可推 round 3 |
| R9 | Excel/PPT 模板缺失 | 模板库仅 Word | round 3 |
| R10 | **代码沙箱** | 设计文档已交付（2026-09-09_office-code-sandbox-design.md），待安全评审 | 评审后另行立项 |
| R11 | PDF→Word/PPT 转换、OCR | 未做 | round 3+ |

## 本轮（Round 2）实施范围：R1-R7

### R1 页面级应用编辑
- `POST /office/doc/{doc_id}/update` body `{ops}`：应用前自动 pre-edit snapshot（复用 storage.snapshot_pre_edit 语义），应用后 persist（status→edited）+ 附 self_check 回读，返回 `{ok, summary, self_check}`；页面操作为用户主动行为，不走 LLM 审批
- 前端：OfficeEditPreviewDialog 补「确认应用」按钮（预览 ok 后可一键应用），应用后刷新列表+预览；i18n
- electron/commands.ts 补 `office_doc_update` IPC

### R2 读取保真度收尾
- PDF：`read_pdf` 用 PyMuPDF `find_tables()` 填 `tables` stub（每页 `tables: List[List[List[str]]]`，已有模型字段；上限防超大表）
- Word：`read_docx` 段落文本带 run 级标记——粗体 `**text**`、斜体 `*text*`（跨 run 合并连续同样式区间；仅当整段非纯样式时保持原样），LLM 从此可见加粗/斜体

### R3 批注接入 LLM 面
- `WordCommentContent` 移入 models.py；`OfficeWordReadResult` 增 `comments: Optional[List[...]]`（additive）；`read_docx` 读取时填充
- @ 注入 word digest 附「批注 N 条」计数与前 3 条（作者+锚文本+内容摘要）

### R4 office_update dry_run
- `office_update` 工具新增 `dry_run?: boolean`（默认 false）：true 时走 `diff_preview.preview_update` 返回 changes 清单，不落盘；`profiles.py` 能力 prompt 同步

### R5 Excel 公式本地求值
- 新模块 `backend/office/excel_eval.py`：`formulas` 库懒加载（main 通道 only，`requirements.txt` 注明；win7 bundled/py38 不加），失败/超时/不支持函数时干净降级为「无法本地求值」
- `office_read` 的公式模式（`formulas=true`）输出增加 `evaluated` 值（求值成功时 `CELL=formula → 值`，覆盖缓存值缺失场景）

### R6 分析图表进聊天
- `office_analyze` 的 `write_report` 在生成聚合图表的同时输出 PNG（`charts.render_chart_png`）并按 artifact 机制注册（复用 #552 落地的 artifact 注册/检测路径），聊天中可直接预览图片

### R7 归档/恢复/快照回读
- `office_archive` / `office_restore` / snapshot-restore 工具结果附 `self_check`（文档计数/目标文档摘要），与 create/update 对齐

## 非目标（本轮不做）
R8 e2e（评估后如时间允许再做）、R9 Excel/PPT 模板、R10 沙箱实施（等安全评审）、R11 转换/OCR、在线协编辑/云同步（维持 Won't-v1 结论）。

## 验收
- R1：office 页预览 diff → 一键应用 → 列表/预览刷新、快照生成、self_check 返回
- R2：含表格的 PDF 读回 tables 非空；含加粗的 docx 读回 `**加粗**` 标记
- R3：office_read 返回批注；@ 注入含批注计数
- R4：dry_run=true 返回 changes 且源文件 mtime 不变
- R5：`=SUM(...)` 在无缓存值时本地求出数值（matplotlib 同款懒加载降级）
- R6：write_report 后聊天可见聚合图 PNG artifact
- 回归：既有 office/tools/chat 全 sweep 不新增失败；前端 tsc/eslint/vitest 全绿；py38 护栏 0 violations
