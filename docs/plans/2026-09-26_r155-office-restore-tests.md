# R155：office_restore 还原工具单测补齐（2026-09-26）

- **上游文档**：parity-loop-sop；Office CRUD 还原语义（archive 的逆操作）/
  R7 自校验回读 / N4 自检历史
- **范围**：后端 only，一个测试文件新增，零生产代码改动

## 0. 结论速览

`tools/office_restore_tool.py`（114 行，office_restore：按 doc_id 清除
软删时间戳，非破坏、幂等，R7 成功后附工作区存活计数自检，N4 落自检
历史）此前零测试。

## 覆盖矩阵（约 11 例）

1. schema：name=office_restore、required=[doc_id]、risk=WRITE_LOCAL、
   requires_tool_context=True；2. doc_id 缺失/非字符串/空白 →
   doc_id_required；3. 无 ToolExecutionContext → missing_tool_context；
4. get_database 抛异常 → document_not_found；5. service.restore 抛
异常 → restore_failed；6. restore 返回 success=False → 透出错误码；
7. 成功 → content 合并 self_check 且 record() 落历史（断言实参）；
8. self_check 回读失败 → 降级 {ok: False, error} 但主结果仍 success。

patch 点：get_database / current_tool_context / OfficeToolService /
workspace_count_self_check / record。

## 验证

- pytest 新文件；ruff 0.4.4 从仓库根跑（对齐 CI 口径）。
