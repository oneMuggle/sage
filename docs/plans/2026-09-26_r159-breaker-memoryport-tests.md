# R159：工具熔断器 + MemoryPort 协议单测补齐（2026-09-26）

- **上游文档**：parity-loop-sop；A13 CircuitBreaker（from LLM_Simple）/
  六边形 MemoryPort 协议
- **范围**：后端 only，两个测试文件新增，零生产代码改动

## 0. 结论速览

`application/services/middleware/circuit_breaker.py`（115 行，工具调用
熔断器：以 (tool, 规范化 args) 计数、超过 max_repeats 熔断阻断、
mark_success 清零、reset 全清）与 `ports/memory.py`（101 行，六边形
MemoryPort 协议：retrieve/store/compress 三方法契约）此前零测试。

## 覆盖矩阵（约 18 例）

### `backend/tests/unit/services/middleware/test_circuit_breaker.py`（13 例）

1. max_repeats < 1 → ValueError；2. 前 N 次放行、第 N+1 次熔断消息
（含工具名与次数）；3. 不同参数独立计数；4. mark_success 清零后恢复
放行；5. call_count 查询；6. reset 全清；7. 规范化键：嵌套 dict 键序
不同 → 同键；8. 不可序列化参数 → repr 兜底不抛错；9. 不同工具同参数
独立计数。

### `backend/tests/unit/ports/test_memory_port.py`（5 例）

1. 协议三方法（retrieve/store/compress）在 MemoryPort 上声明；
2. duck-type 实现满足；3. retrieve 带 limit 缺省、store 带
importance/tags 缺省、compress 仅 session_id；4. 异步方法返回协程；
5. 实现类实例方法可正常 await。

## 验证

- pytest 新文件；ruff 0.4.4 从仓库根跑（对齐 CI 口径）。
