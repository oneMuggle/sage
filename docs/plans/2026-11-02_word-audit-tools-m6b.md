# Word M6b：批量审校与渲染审计工具

> 日期：2026-11-02 · 分支：`feat/word-audit-tools`
> 基线：`origin/main` = `cab0bc457`（M6a 合并后）
> 上游方案：`docs/plans/2026-11-01_word-tools-m6a.md` 非目标段

## 1. 目标

补齐 M6a 留出的两个工具，把批量扫描与渲染级复核也纳入 LLM 工具面：

| 工具 | 风险 | 说明 |
|---|---|---|
| `office_batch_audit` | READ | 批量扫工作区 .docx：file_paths / glob / max_files / 内联或 id 规则包；逐文件失败隔离；汇总 + Markdown 报告 |
| `office_render_audit` | WRITE_LOCAL | 渲染为 PDF 复核页面/边距/字体/页码；无转换器 graceful 降级为 `rendered=false` |

## 2. 反漂移同步点（本 PR 全部覆盖）

- `backend/tools/office_word_intelligence_tools.py`：+2 工具类 + `__all__` 扩展
- `backend/tools/tool_bundles.py`：import + `_install_office_quality` 注册
- `backend/tools/__init__.py`：import + `__all__`
- `backend/domain/tool_names.py`：`OFFICE_TOOLS` +2
- `backend/agents/profiles.py`：writer tools + `_WRITER_CURRENT_DEFAULT_TOOLS`
- `backend/tests/unit/test_tool_bundles_parity.py`：golden 顺序 + 计数（111/110/106/110）
- `backend/tests/unit/test_profiles_office_tools.py`：primary/writer 可见列表按字母序 +2
- `architecture-baseline.json`：profiles.py 1108 → 1111
- `docs/technical/122-word-rule-tools.md`：扩展表格 + 工具数

## 3. 实施步骤

- [x] 2 个工具类 + schema + 上下文/路径/pack 解析
- [x] bundle/导出/名称/profile 同步
- [x] 反漂移测试更新 + 工具单测 2 项（批量扫描、渲染降级）
- [x] 文档：122 + README + 本计划
- [x] 门禁：ruff / py38 / architecture / pytest / CI

## 4. 验收

- `office_batch_audit` 可批量扫工作区 .docx；单文件失败不中断其余；
- `office_render_audit` 无转换器时 graceful 降级（不报错）；
- writer/primary 绑定工作区时可看到 6 个规则包工具；未绑定时隐藏；
- 越界路径、缺上下文 fail-closed。

## 5. 非目标

- 前端批量/渲染审计面板（可后续 M5c）；
- 远程 MCP knowledge 镜像；
- Win7 同步。
