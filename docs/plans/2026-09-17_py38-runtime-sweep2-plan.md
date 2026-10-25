# py38 运行期测试适配收尾（Round 22）

日期：2026-09-17 ｜ 分支：`feat/py38-runtime-sweep2` ｜ 基线：#1056 系（analysis/py38-final 实测）

## 背景

#1070 后的 py38 全量重测显示运行期失败从 131 收敛至 72，且可归因为少数几类
py39+ API/语法残留（主要在测试文件——#978 只覆盖了 4 个文件）。

## 本批修复

### 1. `isinstance(x, A | B)`（3.10+ 运行时 union）×8

subprocess_adapter（1）、llm_trace exporter（2）/ redactor（1）、file_summary_tool（2）、
test_legacy_routes_async_safety（1）、test_event_loop_blocking（1）→ 元组形式 `(A, B)`（全版本可用）。

### 2. 括号多上下文 with（py39+ 语法，py38 运行期 `__enter__` AttributeError）×6

AST 定位（py3.11 With.items）→ 嵌套 with + body 整体缩进平移：
test_skill_save_tool（5）、test_entity_refs（1）。

### 3. `Path.write_text(newline=)`（3.10+ 形参）×4

test_skill_md_loader（3，含 helper 重建）、test_file_tool_policy（1）→ `open()`。

### 4. 杂项

- `zip(..., strict=)`（3.10+）×2 → 去掉 strict
- `str.removesuffix`（3.9+）→ endswith 切片（wiki/review.py，解 9 个失败）
- `Path.is_relative_to`（3.9+）→ `os.path.commonpath` 等价（office/test_generators ×3）
- test_memory_storage_adapter 的 to_thread spy 改为 patch 适配器模块绑定
  （from-import 已拷贝引用，patch py_compat 拦不到）

## 验证

- py38（3.8.20）：上述全部受影响文件通过（skill_md_loader 42 passed、
  skill_save+entity_refs 22 passed、file_tool_policy 7 passed、subprocess 24 passed、
  memory_storage 21 passed 等）
- modern：同批文件 199 passed
- 已知遗留（行为类，另行处理）：async_extractor 事件循环 fixture（8 ERROR）、
  browser_events / agent_tool_async 超时序、allowed_paths tilde/symlink 语义 —— 均为
  py38 与 py310+ asyncio 行为差异，需产品级决策
