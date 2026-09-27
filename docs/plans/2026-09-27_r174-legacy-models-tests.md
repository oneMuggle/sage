# R174：legacy API 请求/响应模型（13 个 Pydantic DTO）单测补齐（2026-09-27）

- **上游文档**：parity-loop-sop；C1e legacy API 模型拆分（13 个 DTO）
- **范围**：后端 only，一个测试文件新增，零生产代码改动

## 0. 结论速览

`api/legacy_models.py`（281 行，13 个 Pydantic DTO 的唯一归属）此前
零测试。DTO 是 API 契约的权威定义——client_message_id pattern、
AgentToggle StrictBool、AgentCreate id pattern 等边界必须钉死。

## 覆盖矩阵（约 24 例）

1. SessionCreate 缺省 title；2. SessionUpdate 全可选；3. ChatRequest
必填 session_id/message + client_message_id pattern（合法 hex / 非法
→ 422）；4. ChatRequest office_refs/attachment_media_ids/images 缺省
空列表；5. MessageResponse 全字段；6. ChatErrorInfo 含
status_code/retry_after；7. ChatResponse 成功/失败/全空三形态；
8. EvolutionLogResponse 全字段；9. AgentToggle enabled StrictBool
（"yes"/1 拒绝 422）；10. AgentUpdate 全可选字段；11. AgentCreate
缺省 + id pattern（合法 / 非法字符 / 超长）；12. InterruptRequest
stream_id 可选；13. SteerRequest stream_id+content 必填；14.
LearnRequest session_id+prompt 缺省。

## 验证

- pytest 新文件；ruff 0.4.4 从仓库根跑（对齐 CI 口径）。
