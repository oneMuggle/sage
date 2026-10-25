# R156：Word 目录刷新工具单测补齐（2026-09-26）

- **上游文档**：parity-loop-sop；Round 39 目录真页码（Word COM 刷新
  TOC 域，可选通道缺失时降级为可读理由）
- **范围**：后端 only，一个测试文件新增，零生产代码改动

## 0. 结论速览

`tools/office_toc_refresh_tool.py`（126 行，office_refresh_toc：参数
校验 → 工作区围栏 → 绝对路径/.docx 白名单/文件存在三道门 → 刷新分派
→ workspace 解析（绑定优先、回退输入父目录））此前零测试。

## 覆盖矩阵（约 14 例）

1. schema：name=office_refresh_toc、required=[file_path]、risk 与
   requires_tool_context；2. 无 ToolExecutionContext →
   missing_tool_context；3. file_path 缺失/非字符串/空白 →
   file_path_required；4. 相对路径 → absolute_required；5. 非 .docx
   （大小写不敏感拒绝验证用 .PDF？—— 大写 .DOCX 放行）；6. 文件不
   存在 → file_not_found；7. 刷新失败 → toc_refresh_failed 前缀 +
   result.error；8. 成功 → content = model_dump()；9. workspace 解析：
   有绑定用绑定工作区，无绑定回退输入父目录（fake refresh 捕获
   workspace 实参）。

## 验证

- pytest 新文件；ruff 0.4.4 从仓库根跑（对齐 CI 口径）。
