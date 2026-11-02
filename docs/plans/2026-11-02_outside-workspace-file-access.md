---
title: 工作区外文件访问放宽
status: in_progress
created: 2026-11-02
branch: feat/outside-workspace-file-access
worktree: .worktrees/feat-outside-workspace-file-access
---

# 工作区外文件访问放宽

## 背景

Sage 当前的工作区边界策略存在不一致：

- **`read_file` / `list_dir`**：主 agent 默认可读任意路径（`enforce_workspace=False`）
- **Office 读取工具**（`office_list` / `office_read` / `office_read_pdf` / `office_analyze`）：硬拒绝工作区外路径（`_enforce_workspace` 直接返回失败）
- **Office 辅助工具**（`office_lint` / `office_repair` / `office_latex_build` / `office_toc_refresh` / `office_journal_*` / `office_word_intelligence_*`）：硬拒绝
- **`@-mention` 附件**：工作区外文件被静默跳过，用户看不到任何反馈
- **`write_file`**：硬拒绝工作区外写入

对比主流 AI 应用：
- **Claude Code**：读任意路径；写工作区外硬拒绝
- **Cursor / Windsurf / Cline**：读+写工作区外均走用户审批

Sage 的问题：Office 读取工具比 `read_file` 更严格，且 `@-mention` 静默跳过造成用户困惑。

## 目标

1. 对齐 Office 读取工具与 `read_file` 的语义（读任意路径）
2. 将 Office 辅助工具的硬拒绝改为审批制
3. `@-mention` 不再静默跳过工作区外文件，改为告知用户原因
4. 项目级 `allowed_paths` 预填常用路径，减少审批频率
5. 更新系统提示与用户手册

## 实施步骤

### Phase 1（P0）— 对齐语义 + 审批制

- [x] Step 1: Office 读取工具移除 `_enforce_workspace` 硬拒绝
  - 新建 `backend/tools/office_workspace_scope.py` — 共享 `workspace_for_input` helper
  - `backend/tools/office_template_tool.py` / `office_pdf_tool.py` / `office_analyze_tool.py` / `office_toc_refresh_tool.py` / `office_ppt_template_tool.py` — `_workspace_for_input` 委托 helper
  - 语义：输入在绑定工作区内 → 用绑定工作区；否则 → 用输入父目录（读任意路径生效）
  - 更新测试 `test_read_pdf_allows_path_outside_policy_workspace` / `test_allows_path_outside_policy_workspace`

- [x] Step 2: Office 辅助工具改为审批制 + READ 工具对齐 read_file
  - `backend/tools/permissions.py` — `_BOUNDARY_SPECS` 已覆盖：
    - `office_create` / `office_update` / `office_delete`（原有）
    - `office_repair_word` / `office_refresh_toc`（新增）
    - `office_fill_word_template` / `office_fill_ppt_template` / `office_generate_pdf` / `office_fill_pdf_form` / `office_analyze`（新增/扩展）
    - `office_compile_latex` / `office_latexdiff` / `office_fix_word` / `office_revise_word` / `office_render_audit` / `office_fill_latex_template` / `office_extract_latex_project`（新增）
  - 写 gap 补 fence：
    - `OfficeFillWordTemplateTool.execute` in-place 分支加 `_enforce_workspace`
    - `OfficeFillPptTemplateTool.execute` 预测输出路径加 `_enforce_workspace`
    - `OfficeFillPdfFormTool.execute` in-place 分支加 `_enforce_workspace`
    - `OfficeAnalyzeTool.execute` write_report 分支加 `_enforce_workspace` + 降级模式
  - **审批后放行**：`backend/core/legacy/agent.py` 在审批闸口后调用
    `enter_approved_paths(tc.name, args, decision.allowed)` 注入 ContextVar
    作用域，`BaseTool._enforce_workspace` 据此放行；`finally` 清理 token。
    封装函数 `enter_approved_paths` / `exit_approved_paths` 置于
    `backend/tools/permissions.py`（避免 `context.py → permissions.py` 循环依赖）。
  - **LaTeX / Word intelligence READ 工具对齐 read_file**：
    - `office_read_latex` / `office_audit_latex` / `office_check_latex_compliance` /
      `office_audit_latex_pdf` / `office_analyze_latex_template` / `office_audit_word` /
      `office_extract_rules` — 全部移除 `_enforce_workspace` 硬拒绝
    - service 层围栏基座统一用 `workspace_for_policy()`（`office_workspace_scope.py`
      新增 helper）：输入在绑定工作区内 → 用绑定工作区；否则 → 用输入父目录
    - WRITE 工具（`office_fix_word` / `office_revise_word` / `office_render_audit` /
      `office_fill_latex_template` / `office_extract_latex_project`）保留
      `_enforce_workspace`（含 allowed_paths / approved 路径放行层），service 层
      围栏同样对齐 helper，避免批准后 resolve_within 因基座错位而误拦
    - `_WordToolBase._resolve_target` 按 `self.risk is RiskClass.READ` 跳边界
    - `office_batch_audit_word` 保持绑定工作区强要求（批量遍历语义）

- [x] Step 3: `@-mention` 附件不再静默跳过
  - `backend/chat/attachment_resolver.py` — 新增 `SkippedMention` + `_resolve_mentions_detailed()`；
    `resolve_mentions()` 签名不变（既有调用方零改动），跳过信息独立返回
  - 跳过原因短码：`outside_workspace` / `unreadable` / `no_workspace` / `invalid_workspace`
  - `render_attachment_block()` 新增可选 `skipped` 参数，输出 `<attachments_skipped>` 段随
    system prompt 下发，模型据此向用户解释为什么 @文件 没进来
  - 前端 chip 级提示留作后续（当前无结构化 notice 通道）

### Phase 2（P1）— 预填 allowed_paths + 白名单优先

- [x] Step 4: 项目创建时预填默认 `allowed_paths`
  - `backend/office/allowed_paths.py` — 新增 `default_allowed_paths(home=None)`
  - `backend/api/project_routes.py` — `register_project()` 在 `request.allowed_paths is None`
    时使用默认值；显式 `[]` 尊重用户清空选择，显式自定义列表不覆盖
  - 默认值（仅加入实际存在的目录）：
    - `~/Documents/**`
    - `~/Desktop/**`
    - `~/Downloads/**`
    - Windows 追加：`D:/Documents/**`, `E:/Documents/**`（如存在）
  - 幂等：`ProjectRepository.register` 的 `ON CONFLICT(path)` 不更新 `allowed_paths`，
    重新打开/登记不会重置用户编辑
  - 用户可在创建向导或设置页编辑（向导选中路径后走 `updateAllowedPaths` 覆盖）
  - 测试：`test_allowed_paths.py::TestDefaultAllowedPaths` +
    `test_project_routes.py` 三条注册预填用例

- [x] Step 5: ~~Office 读取工具检查 `allowed_paths`~~ **（作废，被 Step 2 取代）**
  - Step 2 已让 Office READ 工具对齐 `read_file`：直接接受任意路径、无审批闸口，
    「读取前先查白名单、未命中走审批」的设计已无适用点
  - 白名单只对**写入**（`_enforce_workspace`）与 **@-mention 注入**（Step 6）生效

- [x] Step 6: `attachment_resolver` 检查 `allowed_paths`
  - `backend/chat/attachment_resolver.py` — `_resolve_attachment_path()` 新增
    `allowed_paths` / `project_root` 参数：命中白名单 → 放行（读取基座回退到文件父目录，
    兼容底层 `read_*` 的 `resolve_within` 围栏，同时保留 symlink / `..` 防护）；
    未命中 → 仍走 `resolve_within(workspace)`，返回 `skipped_reason: "outside_workspace"`
  - `backend/chat/executors.py` — `resolve_attachments()` 透传两个新参数
  - `backend/api/hex_routes.py` / `backend/api/legacy_routes.py` — 在事件循环中调用
    `get_session_allowed_paths(session_id)` 后传入线程池（避免 DB 访问落在 worker 线程）
  - 测试：`test_attachment_resolver.py::test_resolve_mentions_allowed_path_outside_workspace`；
    既有 executor / legacy 注入测试同步断言新调用形状与 `<attachments_skipped>` 段

### Phase 3（P2）— 文档与提示

- [x] Step 7: 更新系统提示
  - `backend/agents/profiles.py` — `_OFFICE_CREATE_CAPABILITY_PROMPT`
  - 明确「Office 读取工具可读取任意路径、无需审批」
  - 明确写入工作区外：命中 allowed_paths 自动放行，未命中走审批
  - 补充 @-mention 白名单读取与跳过说明

- [x] Step 8: 更新用户手册
  - `docs/user-manual/16-allowed-paths.md` — 重写为「工作区边界 + allowed_paths」章节
    （读写规则一览、默认预填、审批流程、@-mention 行为）
  - `docs/user-manual/README.md` — 第 17 项简介同步
  - `docs/technical/75-allowed-paths.md` + `docs/technical/README.md` — 技术手册同步
    （读写分离、`_enforce_workspace` 四层判定、@-mention、默认预填）

## 风险评估

| 风险 | 影响 | 缓解 |
|------|------|------|
| Office 读取工具放开后，LLM 可能读取敏感文件 | 中 | 依赖 `allowed_paths` 白名单 + 审批制 |
| 审批弹窗过多影响体验 | 低 | 预填 `allowed_paths` 减少审批 |
| `@-mention` 跳过原因透出增加前端复杂度 | 低 | 复用现有 toast/提示组件 |
| `allowed_paths` 预填路径在某些系统不存在 | 低 | 仅预填用户主目录下常见路径，不存在则跳过 |

## 涉及文件

- `backend/tools/office_tool.py`
- `backend/tools/office_analyze_tool.py`
- `backend/tools/office_pdf_tool.py`
- `backend/tools/office_lint_tool.py`
- `backend/tools/office_repair_tool.py`
- `backend/tools/office_latex_build_tool.py`
- `backend/tools/office_toc_refresh_tool.py`
- `backend/tools/office_journal_tool.py`
- `backend/tools/office_word_intelligence_tools.py`
- `backend/tools/permissions.py`
- `backend/chat/attachment_resolver.py`
- `backend/api/project_routes.py`
- `backend/agents/profiles.py`
- `docs/user-manual/`

## 验收标准

1. Office 读取工具可读取工作区外文件（与 `read_file` 对齐）
2. Office 辅助工具写入工作区外路径时弹出审批框
3. `@-mention` 工作区外文件时，前端显示跳过原因
4. 新建项目时 `allowed_paths` 预填 `~/Documents/**` 等路径
5. 命中 `allowed_paths` 的路径不触发审批
6. 系统提示与用户手册已更新
