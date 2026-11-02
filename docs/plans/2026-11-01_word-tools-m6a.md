# Word M6a：规则包工具暴露给 LLM

> 日期：2026-11-01 · 分支：`feat/word-rule-tools`
> 基线：`origin/main` = `85f2e4731`（M5b 合并后）
> 上游方案：`docs/plans/2026-10-31_word-document-intelligence.md`（M2/M3/M4 工具面）

## 1. 目标

把已有的规则包审校/修复/抽取/修订能力暴露为 LLM 工具，让写作/主 agent
不依赖前端即可完成“规范检查 → 修复 → 抽取规则 → 原生修订”：

| 工具 | 风险 | 说明 |
|---|---|---|
| `office_audit_word` | READ | 规则包审校，返回带锚点/期望/实测/issues |
| `office_fix_word` | WRITE_LOCAL | 可机械修复 + 复检（默认新文件） |
| `office_extract_rules` | READ | 从规范/范本抽取候选规则（不保存） |
| `office_revise_word` | WRITE_LOCAL | 原生 tracked changes + 批注 + 复检 |

全部 `requires_tool_context=True`，路径经 `_enforce_workspace` + 绝对路径
`.docx` 白名单，与 `office_lint_word` / `office_repair_word` 同一安全姿态。
tool 输出上限：issues 200、candidates 100、changes 200，超出标注截断。

## 2. 反漂移同步点（本 PR 全部覆盖）

- `backend/tools/office_word_intelligence_tools.py`（实现）
- `backend/tools/tool_bundles.py`：`_install_office_quality` 注册（lint 之后）
- `backend/tools/__init__.py`：导入与 `__all__`
- `backend/domain/tool_names.py`：`OFFICE_TOOLS`
- `backend/agents/profiles.py`：writer tools 列表 + `_WRITER_CURRENT_DEFAULT_TOOLS`
- `backend/tests/unit/test_tool_bundles_parity.py`：golden 名称/计数（109/108/104）
- `backend/tests/unit/test_profiles_office_tools.py`：primary/writer 可见列表
- 新增 `backend/tests/unit/tools/test_office_word_intelligence_tools.py`

## 3. 实施步骤

- [x] 4 个工具类 + schema + 上下文/路径/pack 解析
- [x] bundle/导出/名称/profile/迁移常量同步
- [x] 反漂移测试更新 + 工具单测 7 项
- [x] 文档：122 + README
- [x] 门禁：ruff / py38 / architecture / pytest / CI

## 4. 验收

- writer/primary 绑定工作区时可看到 4 个新工具；未绑定时隐藏；
- 工具调用审计/修复/抽取/修订结果与 REST 一致（含截断上限）；
- 越界路径、缺上下文、缺参数 fail-closed；
- 既有 lint/repair 工具与排序不受影响。

## 5. 非目标

- 工具内调用 LLM 语义候选（`office_extract_rules` 确定性版本）；
- 批量审校/渲染校验工具（可后续加 `office_batch_audit`）；
- 远程 MCP knowledge 镜像；
- Win7 同步。
