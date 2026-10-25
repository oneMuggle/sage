# r77 批次计划：重接路径补 memory_used —— 重放不丢记忆明细

日期：2026-09-18（分支创建于 main@1fe03456）

## 背景
useChat 的主路径在 R38 已把 memory_used.memories 写入消息
（updateMessage memory_refs/memory_applied），但**重接路径**
（页面刷新后 attach 回进行中的流，事件从头重放）没有同款处理——
重放时 memory_used 被通用降级分支吞掉，当前 run 的记忆明细丢失。

## 交付
- useChat 重接 onEvent 增 memory_used 处理：
  updateMessage(messageId, { memory_refs, memory_applied })，
  与主路径同口径。
- 回归测试：驱动 memory_used 事件 → 断言 assistant 消息携带
  memory_refs 与 memory_applied=1。

## Win7 对齐
新功能不回流。
