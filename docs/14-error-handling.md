# 错误处理

## LLM 错误分类

`backend/core/errors.py` 定义 7 种错误类型：

| 类型 | 触发条件 | HTTP 状态 |
|------|----------|-----------|
| `auth_failed` | API Key 无效 | 401 |
| `rate_limited` | 请求频率超限 | 429 |
| `server_error` | LLM 服务端错误 | 5xx |
| `network_error` | 连接失败 | — |
| `timeout` | 请求超时 | — |
| `parsing_error` | 响应格式异常 | — |
| `unknown` | 未分类错误 | — |

## 端到端错误流

```
LLMClient → LLMError → SageAgent.chat → /chat → 前端 → mapLLMErrorToText → 中文化提示
```

## 添加新错误类型

1. 在 `LLMErrorType` 枚举添加
2. 在 `LLMClient.chat()` 的 except 块捕获并转换
3. 在前端 `errorMapping.ts::STATIC_MESSAGES` 添加中文提示
4. 添加测试
