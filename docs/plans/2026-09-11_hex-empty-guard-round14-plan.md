# hex 路径空响应守卫 Round 14 实施计划（legacy 对齐）

> 日期: 2026-09-11 · 分支: `feat/hex-empty-response-guard` · 基于 main @ 57740a42
> 来源: Round 1 循环守卫的两侧对齐收口
> Win7 对齐: 全部为**新功能**，不 cherry-pick 到 release/win7（31-win7-lts.md §2）。

## 背景

Round 1 给 legacy `run_loop` 加了空响应守卫（注入提示重试，耗尽后兜底
文案），但 hex `ChatService._run_turn_inner` 仍是"空响应直接作为回复
落库"——两侧行为不一致，用户在 hex 模式下会收到空气泡。

## 方案（附加式，不动大 metrics/LLMError 块）

- `chat_service.py` 模块常量 `_EMPTY_RESPONSE_MAX_RETRIES = 1`
- 新方法 `_retry_empty_response(history, llm_tools)`：注入 system 提示
  （"上一次响应内容为空…"）后重试，最多 N 次；返回首个非空响应或
  None（None → 保留原空响应，行为退化为旧版）
- 成功路径（metrics 之后、tool_calls 处理之前）插入检测：无 tool_calls
  且 content 空白 → 重试；span 记 `response.empty_retried`
- 重试调用不重复 metrics 计数（保持既有单次调用口径，简化口径治理）

## 测试

- `backend/tests/unit/test_hex_empty_response.py`：空→重试成功 /
  始终空→保留原响应 / 非空不触发
