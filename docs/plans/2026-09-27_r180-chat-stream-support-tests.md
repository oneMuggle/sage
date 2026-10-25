# R180：chat_stream_support 聊天流支撑函数单测补齐（2026-09-27）

- **上游文档**：parity-loop-sop；C2f 聊天流支撑函数（五份重复收敛）
- **范围**：后端 only，一个测试文件新增，零生产代码改动

## 0. 结论速览

`api/chat_stream_support.py`（166 行，聊天流支撑函数——orch run 闭环、
dispatcher 构造、图片校验、memory_used 事件、工作段清理、NDJSON）
此前零测试。

## 覆盖矩阵（约 22 例）

1. `_finalize_orch_run`：run_id None 跳过、正常调用、异常吞掉；
2. `_build_orchestration_dispatcher`：正常构造、非法 run_id ValueError
   重抛为中文可读文案；
3. `_validate_chat_images`：空列表合法、超4张拒绝、非法前缀拒绝、
   缺base64段拒绝、解码失败拒绝、超5MiB拒绝、合法PNG/JPEG/WebP/GIF
   通过；
4. `_memory_used_event_from_hits`：空命中→None、正常构造（id/memory_type/
   preview）、超5条截断、非dict条目跳过、空preview跳过；
5. `_clear_working_segment`：memory_manager None 跳过、正常委托
   clear_segment；
6. `_ndjson`：ensure_ascii=False + 末尾换行。

## 验证

- pytest 新文件；ruff 0.4.4 从仓库根跑（对齐 CI 口径）。
