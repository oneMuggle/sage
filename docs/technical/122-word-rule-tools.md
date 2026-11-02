# 122 — Word 规则包 LLM 工具（M6a/M6b）

> 日期：2026-11-01 · 分支：`feat/word-rule-tools` / `feat/word-audit-tools`
> 方案：`docs/plans/2026-11-01_word-tools-m6a.md`、`docs/plans/2026-11-02_word-audit-tools-m6b.md`

## 1. 定位

把规则包能力暴露给 LLM agent（primary/writer），无需前端即可完成
“审校 → 修复 → 抽取规则 → 原生修订 → 批量扫 → 渲染后复核”闭环。

| 工具 | 风险 | 行为 |
|---|---|---|
| `office_audit_word` | READ | 按规则包审校 .docx，返回锚点/期望/实测/issues/warnings |
| `office_fix_word` | WRITE_LOCAL | 机械修复 + 复检；默认 `<stem>-fixed.docx`，overwrite 原子覆盖 |
| `office_extract_rules` | READ | 规范/范本 → 候选规则包（含来源/置信度/冲突），不保存 |
| `office_revise_word` | WRITE_LOCAL | 原生 `w:ins/w:del` + 批注 + 复检；changes 可显式或自动生成 |
| `office_batch_audit` | READ | 批量扫工作区 .docx，返回汇总 + 逐文件 issues + Markdown 报告 |
| `office_render_audit` | WRITE_LOCAL | 渲染 PDF 复核页面/边距/字体/页码；无转换器时 graceful 降级 |

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

全量工具数：online 111 / intranet 110 / offline 106 / headless 110。

## 3. 测试

- `backend/tests/unit/tools/test_office_word_intelligence_tools.py`（9）：
  无上下文拒绝、审校锚点、修复输出、抽取规则、修订写入、越界拒绝、
  注册/writer 可见、批量扫描、渲染审计 graceful 降级；
- parity/profile 测试更新（66 passed）；
- ruff 0.4.4、py38 兼容、architecture 门禁通过。

## 4. 前端批量审校面板（M5c）

> 分支：`feat/word-audit-panels-m5c` · 上游：§1 中 `office_batch_audit` 工具

### 4.1 组件位置

`WordBatchAuditPanel` 挂在 `/office` 页工作区底部面板区，
与单文件预览的 `DocumentAuditPanel` 并列，面向工作区级别的批量扫描。

- `src/features/office/WordBatchAuditPanel.tsx`
- 由 `src/pages/Office.tsx` 直接 import 并渲染（workspacePath 来自工作区选择器）；
- `electron/commandRoutes/office.ts` +1 IPC 路由（`office_word_audit_batch`，rawBody）。

### 4.2 交互

- 通配符模式：`<input>` 默认 `**/*.docx`，空值时不下发（后端按默认模式匹配）；
- 最多文件数：`<input type="number">` 1–50（超出时自动 clamp 到上限）；
- 规则包：`<select>`，挂载时拉取 `officeApi.listWordRulePacks`，失败或为空时回退到 `wordRulePackDefaults.ts`（`general-quality` / `gb-t-9704-general`）；
- 点击「运行批量审校」→ `officeApi.batchAuditWord({...})` → 展示：
  - 顶部汇总：通过/存在错误 · 文件数（成功/失败）· error · warning · 规则包 id；
  - 逐文件 `<details>`：相对路径 + error/warning 计数，展开后列出前 20 条 issue（超出提示「还有 N 条，见下报告」）；
  - `report_markdown` 存在时显示「展开 Markdown 报告」折叠按钮。

### 4.3 共享默认值

`src/features/office/wordRulePackDefaults.ts` 抽离出 `DEFAULT_PACKS` + `DEFAULT_PACK_ID`，
被 `DocumentAuditPanel`（M2c）与 `WordBatchAuditPanel`（M5c）共用，
避免 Fast Refresh 时两个面板各自硬编码导致的不一致。

### 4.4 测试

`src/features/office/__tests__/WordBatchAuditPanel.test.tsx`（4）：

- 汇总 + 逐文件展开 + Markdown 报告折叠切换；
- 规则包选择 + max_files 超过 50 时 clamp 到上限；
- 空结果：`files=[]` 时显示空状态，报告按钮不渲染；
- 错误路径：请求失败时展示错误消息。

### 4.5 数据流

```
Office.tsx
  └── WordBatchAuditPanel({workspacePath})
        ├── useEffect → officeApi.listWordRulePacks({workspacePath}) → packs
        └── officeApi.batchAuditWord({workspace_path, pattern?, max_files?, rulepack_id, include_report: true})
              └── POST /api/v1/office/word/audit/batch (rawBody)
                    └── WordBatchAuditService.run() → totals + per-file issues + report_markdown
```
