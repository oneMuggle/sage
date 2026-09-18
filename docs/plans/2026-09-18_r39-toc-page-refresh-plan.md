# Word 目录真页码（Word COM 刷新域可选通道）Round 39 实施计划

> 日期: 2026-09-18 · 分支: `feat/toc-page-refresh-r39` · 基于 main @ fffdef44
> 系列: Word/Office 写作能力增强第 40 轮
> Win7 对齐: **新功能，不 cherry-pick 到 release/win7**（31-win7-lts.md §2）。
> 依赖: 零新增默认依赖；pywin32 进 requirements-optional.txt（懒加载，
> 沿用 Pillow/image_optimize 先例）。

## 背景

R29 落地的 TOC 是 fldChar 复杂域 + 静态缓存行（72-word-toc-static-cache.md）：
文档打开即有目录骨架，但页码是生成期的占位缓存，用户需在 Word 里手动
"更新域"才得到真页码。此前候选清单多轮搁置真页码版，原因是"跨平台排版
引擎不可得"。本轮收口：**不强求跨平台**——Word COM 通道已在 export_pdf.py
（`_convert_with_word_com`）与 capabilities.py（`word_com_available`）
存在先例，把"刷新域"做成同款可选通道：本机有 Word + pywin32 就能一键
把 TOC 更新成真页码，没有则给出可读降级理由。

## 批次任务

### A. `backend/office/toc_refresh.py`（核心模块）

- `TocRefreshResult(BaseModel)`: ok / toc_count / error（契约与
  ExportPdfResult 一致：绝不向调用层抛异常）。
- `refresh_toc_page_numbers(source, workspace)`：
  - 路径三层把守：`validate_workspace` + `resolve_within`（越界拒绝）+
    `.docx` 后缀 + 常规文件检查（镜像 export_pdf 内层校验）。
  - 懒 `import win32com.client`，ImportError → ok=False 带安装引导文案。
  - `DispatchEx("Word.Application")` 独立实例 + `Visible=False` +
    `DisplayAlerts=0` + `AutomationSecurity=3`（强制禁宏——本通道以可写
    打开文档，比导出通道多一层防线）。
  - `TablesOfContents` 逐个 `.Update()`（重分页 + 重算页码与条目）→
    `doc.Save()`；finally `Close(SaveChanges=False)` + `Quit()` +
    `CoUninitialize`（进线程前 `CoInitialize`），绝不泄漏 WINWORD.EXE。
  - 模块级 `_TOC_REFRESH_LOCK` 串行化（镜像 `_EXPORT_LOCK`）。
  - 平台不硬闸：非 Windows / 无 pywin32 统一走 ImportError 与
    `word_com_applicable()` 提示路径（与导出通道同口径）。

### B. 工具层 `office_refresh_toc`（WRITE_LOCAL，工作区绑定）

- `backend/tools/office_toc_refresh_tool.py`：镜像 office_lint_tool 姿态
  （`requires_tool_context=True`，与最近亲 office_repair_word 一致）。
  file_path 经 `_enforce_workspace` + 绝对路径 + 后缀白名单；workspace
  取值复用 `_workspace_for_input`（绑定工作区优先，ad-hoc 回退父目录）。
- 注册链三件套：`domain/tool_names.py` OFFICE_TOOLS 登记；
  `tools/__init__.py` register + `__all__`；profiles writer 白名单 +
  `_WRITER_CURRENT_DEFAULT_TOOLS`（primary 经 `*OFFICE_TOOLS` 自动继承）。

### C. 契约测试与 profile 可见性

- `backend/tests/unit/office/test_toc_refresh.py`：注入假 `win32com`
  模块（linux CI 可跑）：成功路径（2 个 TOC → Update×2 + Save + Close +
  Quit）、无 TOC（ok, toc_count=0）、pywin32 缺失降级文案、后缀/存在性/
  越界拒绝、Update 抛错时 finally 仍 Close/Quit、路径在 Save 前不会被改。
- `test_profiles_office_tools.py`：primary 21 → 22 件、writer 20 → 21 件
  （按字母序插在 office_read_pdf_form 与 office_restore 之间），未绑定
  隐藏清单不变。

### D. 技能可发现化 + 依赖清单（搭车项）

- report-writing/SKILL.md：
  - TOC 真页码说明（生成后让 Sage 刷新目录域；需本机 Word + pywin32；
    无 Word 时在 Word 里 Ctrl+A → F9 手动更新）。
  - 搭车：补 Word 表格表头行样式 header_style 一段（R36 已交付、R38 文档
    轮遗漏的 3 行，内容沿用被废弃草稿 feat-skill-docs-r38 的成稿）。
- `requirements-optional.txt`：pywin32 一节（为什么单独放：Windows-only、
  非 pure-python、TOC 刷新与 PDF 导出共用通道；py38/win7 手动启用钉
  pywin32==306）。
- `test_shipped_writing_skills.py`：补 `office_refresh_toc` 可发现化断言。

### E. 文档与账目

- 技术文档 `docs/technical/76-word-toc-page-refresh.md`。
- CHANGELOG.md [Unreleased] 条目。
- 前端零变更（OfficeCapabilities 未动，word_com_available 复用）。

## 验证

- pytest：test_toc_refresh / test_profiles_office_tools /
  test_shipped_writing_skills / tools 注册冒烟。
- ruff + mypy 增量；py38 注解风格（UP006/UP007/UP035 noqa 头）。

## Round 40 候选

- TOC 刷新接入 office_create 一步到位（refresh_toc 标志，二次轮评估）。
- Word 横排分节+宽表组合场景文档（技能层）。
- Word COM 通道接入 capabilities 引导文案（前端徽章细分 TOC 刷新）。
