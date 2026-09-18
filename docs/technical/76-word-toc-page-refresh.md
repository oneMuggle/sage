# 76 — Word 目录真页码（Word COM 刷新域可选通道，Round 39）

> 日期: 2026-09-18 · 分支: `feat/toc-page-refresh-r39`
> 系列: Word/Office 写作能力增强第 40 轮（R29 静态缓存目录 72 号的收口）

## 1. 定位

R29 的 TOC 是 fldChar 复杂域 + 静态缓存行：文档打开即有目录骨架，但
页码是生成期占位缓存，用户需在 Word 里手动"更新域"（Ctrl+A → F9）
才得到真页码。跨平台排版引擎不可得（docx 页码由布局决定，纯 Python
无法重排），本轮把口径收窄为**可选通道**：本机有 Word + pywin32 就用
Word COM 一键刷新域，没有则降级为带安装引导的可读失败——与
export_pdf 的 Word COM 导出通道（`word_com_available` 能力位）完全同构。

## 2. 变更

- 新模块 `backend/office/toc_refresh.py`：
  - `refresh_toc_page_numbers(source, workspace) -> TocRefreshResult`：
    路径三层把守（`validate_workspace` + `resolve_within` + `.docx`
    白名单）→ `DispatchEx("Word.Application")` 可写打开 →
    `TablesOfContents` 逐个 `Update()`（重分页 + 重算页码条目）→
    `doc.Save()`。无 TOC 时成功返回 `toc_count=0`（no-op，不 Save）。
  - 契约：**绝不向调用层抛异常**（镜像 `export_to_pdf`）。
  - 安全：`AutomationSecurity=3` 强制禁宏（可写打开比导出通道多一层）、
    `DisplayAlerts=0`、finally 兜底 `Close(SaveChanges=False)` +
    `Quit()` + `CoUninitialize`，绝不泄漏 WINWORD.EXE；模块级
    `_TOC_REFRESH_LOCK` 串行化 COM。
- 新工具 `office_refresh_toc`（`tools/office_toc_refresh_tool.py`）：
  `WRITE_LOCAL` + `requires_tool_context=True`（与 office_repair_word
  同姿态）；`_enforce_workspace` + 绝对路径 + 后缀白名单；workspace
  取值走 file_path 模式先例（绑定工作区优先，ad-hoc 回退父目录）。
- 注册链：`domain/tool_names.py` OFFICE_TOOLS 登记（primary 经
  `*OFFICE_TOOLS` 自动继承）；profiles writer 白名单 +
  `_WRITER_CURRENT_DEFAULT_TOOLS`；`test_profiles_office_tools`
  primary 21 → 22 件 / writer 20 → 21 件。
- 技能可发现化：report-writing SKILL.md 交付步骤接入
  `office_refresh_toc`（含无 Word 环境的 F9 降级提示），并搭车补上
  R36 Word 表头行样式 `header_style` 的文档（R38 文档轮遗漏项）。
- 依赖：`requirements-optional.txt` 新增 pywin32 一节（懒加载可选，
  与 PDF 导出共用通道；win7 手动启用钉 306）。

## 3. Win7 对齐与测试

**新功能不 cherry-pick 到 release/win7**（31-win7-lts.md §2）；模块仍
保持 py38 注解风格以与 `backend/office` 家族同口径。零新增默认依赖。
`test_toc_refresh.py` 10 项：全量 Update+Save+Close+Quit 调用序列、
无 TOC no-op、pywin32 缺失降级文案、Update/Open 中途抛错仍清理、
后缀/存在性/越界/非法 workspace 拒绝、平台门与模型 extra=forbid。
win32com 经 sys.modules stub 注入（镜像 test_export_pdf），linux CI
可跑。
