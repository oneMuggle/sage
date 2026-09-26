# R138：消息领域模型 + Sage 异常体系单测补齐（2026-09-26）

- **上游文档**：parity-loop-sop；domain 纯净层约定（零外部依赖）
- **范围**：后端 only，两个测试文件新增，零生产代码改动

## 0. 结论速览

`domain/message.py`（57 行，统一消息表示：Role/ToolCall/Message）与
`domain/exceptions.py`（166 行，Sage 异常体系权威定义：SageBaseError
基类 + 七个业务子类的 code/details 合并语义）此前零测试。

## 覆盖矩阵（约 22 例）

### `backend/tests/unit/domain/test_message.py`（9 例）

1. Role 四枚举 str 比较；2. ToolCall 三字段；3. Message 缺省
（tool_calls 空表 / tool_call_id None）；4. ASSISTANT 带 tool_calls
构造；5. TOOL 消息带 tool_call_id；6. dataclass 可变（list 字段非
frozen 约定）；7. role str 枚举直接比较。

### `backend/tests/unit/domain/test_exceptions.py`（13 例）

1. 基类缺省 code=SAGE_ERROR、details 缺省空 dict；2. to_dict 三键；
3. __str__ 有/无 details 两种形态；4. AgentError 固定 code；
5. ToolCallError：message 格式 + details 合并 tool_name（调用方 details
不丢）；6. MaxIterationsError：details 合并 max_iterations + 文案；
7. SageMemoryError：details 合并 operation + 文案；8.
SessionNotFoundError/ValidationError/SecurityError code 断言；
9. except SageBaseError 统一捕获。

## 验证

- pytest 新文件；ruff 0.4.4 从仓库根跑（对齐 CI 口径）。
