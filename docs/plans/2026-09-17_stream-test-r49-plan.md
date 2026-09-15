# 非 openai 流式对话测试（第四十九轮批次 A）

> 日期: 2026-09-17 . 分支: feat-stream-test-r49 . 基于 main @ e0150422
> 来源: R33/#757 + R36/#781 的补充测试批次：为 anthropic/gemini/ollama
> 协议级对话测试增加更完整的边界用例覆盖。
> Win7: 测试增强，不迁。

## 实施
- api.test: anthropic / gemini / ollama 的错误路径（上游 401/500）
- api.test: max_tokens / response 格式断言
- api.test: 空 models 列表降级
## 测试
- 既有 manage-endpoints 套件回归
