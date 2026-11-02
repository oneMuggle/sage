# 122 — Word 规则包 LLM 工具（M6a）

> 日期：2026-11-01 · 分支：`feat/word-rule-tools`
> 方案：`docs/plans/2026-11-01_word-tools-m6a.md`

## 1. 定位

把规则包能力暴露给 LLM agent（primary/writer），无需前端即可完成
“审校 → 修复 → 抽取规则 → 原生修订”闭环。

| 工具 | 风险 | 行为 |
|---|---|---|
| `office_audit_word` | READ | 按规则包审校 .docx，返回锚点/期望/实测/issues/warnings |
| `office_fix_word` | WRITE_LOCAL | 机械修复 + 复检；默认 `<stem>-fixed.docx`，overwrite 原子覆盖 |
| `office_extract_rules` | READ | 规范/范本 → 候选规则包（含来源/置信度/冲突），不保存 |
| `office_revise_word` | WRITE_LOCAL | 原生 `w:ins/w:del` + 批注 + 复检；changes 可显式或自动生成 |

所有工具：

- `requires_tool_context=True`：无活动 ToolExecutionContext 时隐藏/拒绝；
- 绝对路径 + `_enforce_workspace` 工作区围栏 + `.docx`（抽取还接受 .txt/.md）白名单；
- `rulepack` 内联优先，否则 `rulepack_id`（缺省 `general-quality`）；
- 输出截断：issues 200、candidates 100、changes 200，截断时附加计数。

## 2. 注册与反漂移

新增工具必须同时更新（本阶段已全部覆盖）：

- `backend/tools/tool_bundles.py`：`_install_office_quality` 注册；
- `backend/tools/__init__.py`：导入与 `__all__`；
- `backend/domain/tool_names.py`：`OFFICE_TOOLS`；
- `backend/agents/profiles.py`：writer tools + `_WRITER_CURRENT_DEFAULT_TOOLS`；
- `backend/tests/unit/test_tool_bundles_parity.py`：golden 顺序与计数；
- `backend/tests/unit/test_profiles_office_tools.py`：primary/writer 可见列表。

全量工具数：online 109 / intranet 108 / offline 104（headless 108）。

## 3. 测试

- `backend/tests/unit/tools/test_office_word_intelligence_tools.py`（7）：
  无上下文拒绝、审校锚点、修复输出、抽取规则、修订写入、越界拒绝、注册/writer 可见；
- parity/profile 测试更新（57 passed）；
- ruff 0.4.4、py38 兼容、architecture 门禁通过。
