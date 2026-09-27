# R142：AgentEventBus 发布-订阅总线单测补齐（2026-09-26）

- **上游文档**：parity-loop-sop；A23（from pi）Agent 事件流
- **范围**：后端 only，一个测试文件新增，零生产代码改动

## 0. 结论速览

`domain/agent_events.py`（180 行，Agent 事件发布-订阅总线：类型订阅/
取消、publish 等待全部订阅者、steering 打断队列与 follow-up 延迟队列）
此前零测试。

## 覆盖矩阵（约 16 例）

1. AgentEventType 十事件分类齐全（agent/turn/message/tool 生命周期）；
2. AgentEvent 缺省（data 空表、timestamp 自动）与 __str__；
3. subscribe 返回取消函数；4. publish 等待全部订阅者完成（asyncio
gather 语义：两个订阅者都被调用）；5. 未订阅类型 publish 不抛错；
6. unsubscribe 后不再收到事件；7. 重复取消安全（ValueError 吞掉）；
8. steering 队列 FIFO：add → get 逐条弹出、空 → None、clear 清空；
9. follow-up 队列同构；10. 两队列互不干扰。

## 验证

- pytest 新文件；ruff 0.4.4 从仓库根跑（对齐 CI 口径）。
