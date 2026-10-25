# office_create 一键 TOC 刷新 + rollback 测试竞态修复 Round 40 实施计划

> 日期: 2026-09-18 · 分支: `feat/word-create-toc-refresh` · 基于 main @ 38a55bc7
> 系列: Word/Office 写作能力增强第 41 轮（R39 目录真页码 #1073 的编排收口）
> Win7 对齐: **新功能，不 cherry-pick 到 release/win7**（31-win7-lts.md §2）。
> 依赖: 零新增（pywin32 仍为 R39 引入的可选依赖）。

## 背景

R39 落地 `office_refresh_toc`（Word COM 刷新 TOC 域为真页码）后，带目录
文档的完整交付是两步：office_create → office_refresh_toc。高频组合
（"生成带目录的报告并要真页码"）值得一步到位：office_create 增加
`refresh_toc` 标志，生成成功后原地刷新，省一次 LLM 往返；COM 不可用
时降级为附加说明而不毁掉生成结果。

搭车：R38 轮观测到的 CI flake
`updateManager.test.ts > rollback > reports rollback event to backend`
——`rollback()` 里 `void this.reportRollbackEvent(...)` 是 fire-and-forget，
测试 `await rollback()` 后立即断言 fetch，存在时序竞态（同文件 1551 行
已有 `vi.waitFor` 先例）。测试侧等待修复，不动产品语义（遥测刻意不阻塞
本地恢复）。

## 批次任务

### A. office_create 工具：`refresh_toc` 参数（主项）

- schema 新增顶层 `refresh_toc: boolean`（word 专用，描述写明
  "需本机 Word + pywin32；不可用时生成照常成功、附加 toc_refresh 说明"）。
- `_generate_document` word 分支：生成成功且 `refresh_toc=true` →
  调 `refresh_toc_page_numbers(output, workspace)`（workspace 取绑定
  工作区优先、回退输出父目录——与 R39 工具同款本地 helper）；
  - 成功：`result_content["toc_refresh"] = {ok, toc_count}`；
  - 失败/降级：`{ok: false, error}`——**生成结果保持 success=True**，
    绝不因刷新失败回滚已落盘文档；
- 非 word + refresh_toc=true → 显式报错
  `refresh_toc_only_supported_for_word`（strict，与 column_widths
  越界即抛同姿态，防 LLM 静默误解）。

### B. rollback 测试竞态修复（搭车，test-only）

- `electron/tests/updateManager.test.ts` ~997 行：fetch 调用断言包进
  `await vi.waitFor(() => ...)`；body 断言保持在 waitFor 之后（fetch
  已发生）。零产品代码变更。

### C. 契约与文档

- 前端零变更（refresh_toc 是 LLM 工具编排参数，不进
  OfficeWordGenerateRequest 模型、无 UI 表单项）。
- report-writing SKILL.md step 4/5：生成时可带 `refresh_toc: true`
  一步到位（两步工具仍是显式刷新的替代路径）。
- 测试：`refresh_toc` word 成功/降级/非 word 拒绝 三态（stub
  win32com + 真实 docx 生成太重——直接 monkeypatch
  `office_create_tool.refresh_toc_page_numbers`）+ electron 侧仅改测试。
- 计划文档、技术文档 77 号、CHANGELOG。

## 验证

- pytest 增量（office_create 工具三态 + 既有 office 工具面回归）
- ruff/mypy 增量
- 前端不跑 tsc 相关（零前端源变更；electron 测试属 Frontend job 会跑）

## Round 41 候选

- Word 横排分节+宽表组合场景文档（技能层微轮）
- TOC 刷新接入 office_update（修订后刷新）
- Word COM 前端徽章细分（capabilities UI，需前端协调）
