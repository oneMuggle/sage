# office_update 修订后 TOC 刷新 + 横排宽表场景文档 Round 41 实施计划

> 日期: 2026-09-18 · 分支: `feat/word-update-toc-refresh` · 基于 main @ a988acec
> 系列: Word/Office 写作能力增强第 42 轮（R39/R40 TOC 真页码故事线收口）
> Win7 对齐: **新功能，不 cherry-pick 到 release/win7**（31-win7-lts.md §2）。
> 依赖: 零新增。

## 背景

R40 给 office_create 加了 `refresh_toc` 一步到位；但文档**修订**同样会
让目录过期（增删段落 → 页码漂移/条目增减）。本轮把同一标志补到
office_update：修订成功后原地刷新目录域，TOC 真页码故事线闭环
（生成/修订 → 真页码）。搭车补 SKILL.md 的 R37 横排分节+宽表场景文档
（实测技能正文未覆盖，可发现化缺口）。

## 批次任务

### A. office_update 工具：`refresh_toc` 参数（主项）

- schema 新增 `refresh_toc: boolean`（word 专用；dry_run 预览下无意义
  不生效——写明于描述）。
- doc_id 受管路径（`_execute_bound`）：service.update 成功后经
  binding + doc row 定位落盘文件刷新，附加 `toc_refresh` 摘要
  （ok/toc_count/error，不回显受管绝对路径——不变式同 R40）；
  **upfront 守卫**：service 调用前 best-effort 解析 doc row，非 word
  直接 `refresh_toc_only_supported_for_word`（此时修订尚未发生，
  报错语义准确）。
- file_path 路径（`_execute_by_path`）：`_infer_doc_type` 已知类型 →
  非 word upfront 严格拒绝；word 成功后刷新并附加摘要（workspace 取
  绑定优先、回退输出父目录）。
- 降级契约同 R40：刷新失败不改写修订成功态。

### B. 搭车：SKILL.md 横排分节+宽表场景（R37 缺口）

- report-writing SKILL.md 工作流补一段：宽表/财务页横排场景——
  `format_spec.section_breaks: [{start_paragraph, page_setup:
  {orientation: "landscape"}}]`（NEW_PAGE 分节 + 新节 page_setup，
  0-based 段落下标），配组合示例。

### C. 测试与文档

- `test_office_update_tool.py`（或新建）：file_path word 成功附加摘要 /
  非 word upfront 拒绝 / COM 不可用降级 / doc_id 受管路径摘要附加不泄漏
  路径（monkeypatch DB 链，模式同 R40）。
- 计划文档、技术文档 78 号、CHANGELOG。

## 验证

- pytest 增量 + office 工具面回归；ruff 增量（CI mypy 只查 domain/ports，
  tools 层与 main 既有口径一致）。

## Round 42 候选

- Word COM 前端徽章细分（capabilities UI，需前端协调）
- 图目录/表目录（TOF 域，期刊论文场景）
- 交叉引用（正文"如图N"与题注联动，工程量大需评估）
