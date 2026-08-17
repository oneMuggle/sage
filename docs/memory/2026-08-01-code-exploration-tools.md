---
title: 代码探索工具三件套 (grep/glob/file_summary)
date: 2026-08-01
worktree: /home/fz/project/sage
branch: feat/code-exploration-tools
pr: https://github.com/oneMuggle/sage/pull/265
commit: 4b6f257a
status: merged
---

# 代码探索工具三件套 (grep/glob/file_summary)

## 背景

用户在 Sage 中询问"查看 /home/fz/project/LLM_Simple 中的代码并给出优化建议"时,遇到 `max_iterations_exceeded` 错误。目标项目有 2691 个源文件、515,694 行代码,而 primary agent 只有 15 次 iteration,每次只能读 1 个文件,导致读了约 10 个文件就被截断。

## 根因分析

1. **缺少代码探索工具**: primary agent 只有 list_dir/read_file,无法快速定位关键代码
2. **工具白名单过窄**: grep_search 和 glob_search 已存在于 backend/tools/search_tools.py,但没加入 primary agent 白名单
3. **单文件读取策略**: 每次 iteration 只能读 1 个文件 500 行

## 解决方案

### 新建 FileSummaryTool (287 行)
- 用 ast.parse (Python) / 正则 (JS/TS) 提取文件结构骨架
- 单次调用获取 imports/classes/functions/methods,而非全文
- 复用 file_tool 的二进制嗅探 + BOM 识别
- 5 MiB 硬上限,错误走 ToolResult(success=False)

### 暴露已有工具
- grep_search (正则内容搜索) 加入 primary agent 白名单
- glob_search (glob 文件名搜索) 加入 primary agent 白名单

### Primary Agent 工具扩展
从 5 个扩展到 8 个:
- calculator, memory_search, memory_save, list_dir, read_file
- **grep_search** (已存在,新加入)
- **glob_search** (已存在,新加入)
- **file_summary** (全新实现)

## 实施过程

### TDD 流程
1. **RED**: 写 14 个单元测试 (test_file_summary_tool.py)
2. **GREEN**: 实现 FileSummaryTool, 14/14 测试通过
3. **REFACTOR**: 
   - 修复 ruff UP038: isinstance 改用 `X | Y` 语法
   - 修复 ruff PLR0911: 提取 _validate_file() 减少 return 语句 (10→6)

### 关键文件
- `backend/tools/file_summary_tool.py` (新建, 287 行)
- `backend/tools/__init__.py` (+4 行: import + register + __all__)
- `backend/agents/profiles.py` (+14 行: primary agent 工具白名单)
- `backend/tests/unit/test_file_summary_tool.py` (新建, 258 行, 14 个测试)
- `docs/plans/2026-08-01_code-exploration-tools.md` (计划文档, 253 行)

### CI 结果
- Frontend (TypeScript): ✅
- Backend (Python): ✅ (包含 ruff lint + mypy + pytest)
- Electron build (ubuntu/windows): ✅
- Electron smoke: ✅
- All Checks: ✅

## 效果预期

| 指标 | 改造前 | 改造后 |
|------|--------|--------|
| primary agent 工具数 | 5 | 8 |
| 单次迭代能掌握的文件信息 | 1 个文件 500 行 | ~30 个文件结构 |
| 找关键文件 | list_dir → read_file 多轮 | glob_search 一次到位 |
| 找代码片段 | grep 不在工具集中 | grep_search 直接调用 |
| max_iterations_exceeded 风险 | 高 | 低 |

## 关键技术决策

1. **不新建 grep_search / glob_search**: 已有实现具备生产级质量 (ReDoS 缓解、二进制嗅探、UTF-16 BOM 识别)
2. **FileSummaryTool 用 ast.parse + 正则**: 零依赖,Python 精确提取,JS/TS 近似提取
3. **_validate_file() 提取**: 满足 ruff PLR0911 (最多 6 个 return),同时提高可读性
4. **isinstance 用 `X | Y` 语法**: Python 3.10+ 特性,ruff UP038 要求

## lessons learned

- **Fact-Forcing Gate**: 每次写文件前需要回答 4 个问题(调用者、无重复、数据结构、用户指令)
- **Ruff 严格检查**: PLR0911 (too many returns) 和 UP038 (isinstance syntax) 是常见陷阱
- **TDD 流程**: 先写测试再实现,重构时有测试保护
- **Plan mode**: 复杂功能先规划再实施,避免返工
