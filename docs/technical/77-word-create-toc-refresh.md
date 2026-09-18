# 77 — office_create 一键 TOC 刷新（Round 40）

> 日期: 2026-09-18 · 分支: `feat/word-create-toc-refresh`
> 系列: Word/Office 写作能力增强第 41 轮（R39 目录真页码 76 号的编排收口）

## 1. 定位

R39 的 `office_refresh_toc` 让"带目录报告拿真页码"成为两步调用
（create → refresh）。高频组合值得一步到位：office_create 新增
`refresh_toc` 标志，生成成功后原地刷新——省一次 LLM 往返；COM 不可用
时降级为结果内说明而**不毁掉生成结果**。

## 2. 变更

- `office_create` 工具新增顶层 `refresh_toc: boolean`（word 专用）：
  - 双路径接线：受管委托路径（`_attach_toc_refresh_managed`——doc_id →
    `document_path` 定位落盘文件，刷新摘要只含 ok/toc_count/error，
    维持「不回显受管绝对路径」不变式）与 legacy `output_dir` 路径
    （`_attach_toc_refresh_local`——绑定工作区优先、回退输出父目录）；
  - strict 守卫：非 word + refresh_toc → 显式
    `refresh_toc_only_supported_for_word`（不静默忽略，防 LLM 误判）；
  - 降级契约：刷新失败/不可用时生成结果保持 `success=True`，仅附加
    `toc_refresh: {ok: false, error: ...}`（安装引导文案与 R39 一致）。
- 搭车（test-only）：`electron/tests/updateManager.test.ts` rollback
  遥测断言包进 `await vi.waitFor(...)`——`rollback()` 的
  `void this.reportRollbackEvent(...)` 是刻意 fire-and-forget，测试
  立即断言与微任务调度存在竞态（R38 轮 CI 实际 flake 一次）。零产品
  代码变更。
- 前端零变更（编排参数不进 `OfficeWordGenerateRequest` 模型）。

## 3. Win7 对齐与测试

新功能不 cherry-pick 到 release/win7（31-win7-lts.md §2）；零新增依赖。
`test_office_create_tool.py` +4 项：非 word 严格拒绝、刷新成功摘要附加、
COM 不可用降级不毁生成、受管路径摘要附加且路径不泄漏（monkeypatch
DB/binding/doc 定位链）。schema 可见性断言同步 `refresh_toc` 键。
electron 侧修复由 Frontend job 既有测试覆盖。
