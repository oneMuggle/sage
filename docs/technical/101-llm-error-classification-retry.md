# LLM 错误分类与重试

> 实施于 PR #2574（release/win7）/ PR #2578（main）。

## 背景

Win7 LTS 用户反馈聊天时报错：

```
peer closed connection without sending complete message body (incomplete chunked read)
```

且**重试横幅不触发**，直接失败。

这条信息由 `httpcore` 在读取 chunked transfer 时上游过早关闭 TCP 连接抛出，
对应 `httpx.RemoteProtocolError`。它既不是 SSL 错误（TLS 握手已成功），
也不是 HTTP 状态码错误（响应头已收到），而是**流 body 传输中断**。

## 错误分类模型

`backend/core/legacy/llm_client.py` 的 `LLMClient._raise_classified_error()`
把底层异常统一映射为 `backend.core.errors.LLMError`（带 `LLMErrorType`）：

| 底层异常 | `LLMErrorType` | 可重试 |
| --- | --- | --- |
| `httpx.TimeoutException` | `TIMEOUT` | ✅ |
| `httpx.ConnectError` | `NETWORK` | ✅ |
| `httpx.RemoteProtocolError` / `ReadError` / `WriteError` | `NETWORK` | ✅ |
| `httpx.HTTPStatusError` 401 | `AUTH_FAILED` | ❌ |
| `httpx.HTTPStatusError` 429 | `RATE_LIMITED` | ✅ |
| `httpx.HTTPStatusError` 5xx | `SERVER_ERROR` | ✅ |
| `httpx.HTTPStatusError` 400/413 且响应体命中上下文溢出特征串 | `CONTEXT_OVERFLOW` | ❌ |
| `httpx.HTTPStatusError` 其余 | `UNKNOWN` | ❌ |
| `ValueError` / `KeyError`（含 `json.JSONDecodeError`） | `PARSING` | ❌ |
| 其余异常 | `UNKNOWN` | ❌ |

可重试集合定义在 `backend/core/legacy/llm_client.py`：

```python
_RETRYABLE_ERROR_TYPES = frozenset(
    {
        LLMErrorType.RATE_LIMITED,
        LLMErrorType.SERVER_ERROR,
        LLMErrorType.TIMEOUT,
        LLMErrorType.NETWORK,
    }
)
```

`UNKNOWN` **不在**其中——这是本次修复的关键：分类落到 `UNKNOWN` 的失败，
无论底层是什么网络层异常，都会直接终止而不重试。

## 根因：httpx 异常继承链与 `ConnectError` 不相交

httpx 0.26 的相关 MRO：

```
RemoteProtocolError → ProtocolError → TransportError → RequestError → HTTPError
ReadError           → TransportError → RequestError
WriteError          → TransportError → RequestError
```

三者都是 `TransportError` 子类，但**都不是 `ConnectError` 子类**。修复前的
`_raise_classified_error()` 只单列了 `httpx.ConnectError` 与
`httpx.TimeoutException`，于是 `RemoteProtocolError` 一路落到兜底分支：

```
UNKNOWN ∉ _RETRYABLE_ERROR_TYPES → 重试循环整体跳过 → 直接失败
```

同仓库 `backend/tools/http_factory.py` 的 `RETRYABLE_EXCEPTIONS`（工具层
HTTP 抓取重试）**早已**包含 `RemoteProtocolError` / `ReadError` / `WriteError`
——团队对这三类异常的"可重试"认知是一致的，唯独 `llm_client.py` 漏掉了。

## 修复

在 `_raise_classified_error()` 的 `ConnectError` 分支之后新增一条分支：

```python
# 流传输中断（chunked body 不完整 / 读写出错）→ 归为网络层失败，触发重试。
# 与 backend/tools/http_factory.py 的 RETRYABLE_EXCEPTIONS 口径一致。
if isinstance(exc, (httpx.RemoteProtocolError, httpx.ReadError, httpx.WriteError)):  # noqa: UP038
    logger.error(f"LLM 流传输中断: {exc}")
    raise LLMError(LLMErrorType.NETWORK, f"LLM 连接中断: {exc}")
```

新分支既不会命中前面的 `TimeoutException`（超时是独立分支），也不会命中
`ConnectError`，位置放在其后以保持既有行为的优先级不变。

### 跨分支 lint 注意事项

`# noqa: UP038` **必须保留**：

- `main` 分支 `backend/ruff.toml` 的 `target-version = "py311"` 且选中了 `UP`，
  ruff 会报 `UP038 Use X | Y in isinstance call instead of (X, Y)`；
- 但 `X | Y` 形式只在 Python 3.10+ 运行时可求值，`release/win7`（Python 3.8）
  必须保留元组写法；
- win7 的 `backend/ruff.toml` 已在 `ignore` 中列出 `UP038`，该分支上这条
  `noqa` 冗余但无害——与文件内既有 4 处同款 `noqa` 同性质。

保留冗余 `noqa` 的目的是让 `llm_client.py` 在两个分支保持**字节级一致**，
避免后续 cherry-pick 产生无谓冲突。

## 重试契约

### 首字后不重试

流式路径 `chat_stream_events()` 的重试循环有一条硬约束：**一旦向下游
yield 过任何增量（content 或 reasoning），失败即刻终止，不重试、不降级**。

```python
nothing_yielded = not content_parts and not reasoning_parts
if not nothing_yielded:
    raise
```

原因：增量已实时下发给用户（`agent.run_loop` 的 `_saw_content_delta` 契约），
换模型从零重放会造成内容重复 / 拼接错乱。

因此本次修复只覆盖**首字前**的中断：

| 场景 | 行为 |
| --- | --- |
| 连接被拒（`ConnectError`） | 重试 |
| 超时（`TimeoutException`） | 重试 |
| HTTP 429 / 5xx | 重试 |
| **首字前 chunked 中断（`RemoteProtocolError`）** | **重试**（本次修复） |
| 首字后 chunked 中断 | 直接终止（契约不变） |

### fallback_model 降级

主模型重试耗尽后，若配置了 `fallback_model` 且错误类型可重试，
会换模型再来一轮（每个 client 实例至多一次）。鉴权 / 参数类错误
（`AUTH_FAILED`、`PARSING` 等）换模型无济于事，直接抛出。

## 重试参数

重试次数与退避时长全部**可由用户在设置 UI 调整**（设置 → 基础 → LLM 重试）：

| 设置项 | 键名 | 后端默认值 | UI 默认值 | 有效范围 |
| --- | --- | --- | --- | --- |
| 最大重试次数 | `llmRetryMaxAttempts` | 3 | 3 | UI 0–10；`config_tool` 校验 0–20 的整数 |
| 退避基数（秒） | `llmRetryBaseDelayS` | 1.0 | 1.0 | UI ≥ 0.1；`config_tool` 校验 (0, 600] |
| 最大退避（秒） | `llmRetryMaxDelayS` | 15.0 | 30.0 | UI ≥ 1；`config_tool` 校验 (0, 600] |

几点语义说明：

- `llmRetryMaxAttempts` 是**总尝试次数**（含首次请求），默认 3 = 首次 + 2 次
  重试；设为 `0` 表示禁用自动重试（单次请求即终止）。
- 后端硬编码默认 `llmRetryMaxDelayS = 15.0`，而设置 UI 的默认值是 `30.0`。
  用户一旦在设置页保存过，后端读到的 `app_settings` 里就是 30.0 并优先生效。
- `llmRetryBaseDelayS` 不能大于 `llmRetryMaxDelayS`，否则 `config_tool` 拒绝写入。

配置读取顺序（`backend/core/legacy/llm_client.py` 的 `_retry_settings()`）：

```
app_settings（设置 UI 落库） > 环境变量 > 硬编码默认值
```

环境变量为 `SAGE_LLM_RETRY_MAX_ATTEMPTS`（需 ≥ 1）与
`SAGE_LLM_RETRY_BASE_DELAY_S`（需 ≥ 0），用于调试 / 测试。
读取失败一律回退默认值，**永不抛错**。

退避时长（`_retry_backoff_seconds()`）：

```python
if err.retry_after:                      # 429 的 Retry-After 优先
    return min(float(err.retry_after), max_delay)
return min(base_delay * (2 ** (attempt - 1)), max_delay)
```

即指数退避 `base × 2^(attempt-1)`，单次封顶 `max_delay`。

## 前端可见性

重试发生时，`llm_client` 通过 `retry_callback` / 流式 `"retry"` 事件推送
`RetryEvent`（含 `attempt` / `max_attempts` / `error_type` / `error_message` /
`delay`），由 `agent.run_loop` 转成 `AgentEvent` 经 SSE 下发，前端展示
「重试中」横幅。本章修复的效果正是让 chunked 中断走到这条通道，而不是
静默失败。

## 测试覆盖

| 文件 | 用例 |
| --- | --- |
| `backend/tests/unit/test_llm_client_errors.py` | `test_remote_protocol_error_raises_network_error`、`test_read_error_raises_network_error` |
| `backend/tests/unit/test_llm_client_stream_errors.py` | `test_stream_remote_protocol_error_raises_network_error` |

用例覆盖 `chat()`（非流式）与 `chat_stream_events()`（流式）两条路径，
断言错误类型为 `LLMErrorType.NETWORK` 且 message 保留原始 httpx 文本。

`test_llm_client*.py` 共 8 个文件 93 个用例全部通过；
`backend/tests/unit` 全量 11790 passed / 5 failed（均为既有环境性失败，无回归）。

## 排查提示

再遇到"重试不触发"类问题，先看 `llm_client.py` 的 `_raise_classified_error()`
分类链：任何 `httpx.TransportError` 子类的网络层失败都应归 `NETWORK`，
否则会落进 `UNKNOWN` 而静默跳过重试。分类口径以
`backend/tools/http_factory.py` 的 `RETRYABLE_EXCEPTIONS` 为参照。

## 代理上游超时（2026-10-28）

### 背景

`backend/api/llm_proxy_routes.py` 的 LLM 反向代理在转发上游模型请求时，
把 httpx 的 read timeout **硬编码为 60 秒**。`httpx.Timeout(60)` 的语义是
「两次收到字节之间的最大间隔」，流式响应只要字节持续流动就不会触发
（Win7 实测成功请求最长 238s），但企业网关偶发 >60s 不出字即被切断，
前端报「LLM 连接中断：incomplete chunked read」。

### 可配置化

新增 `app_settings.llmProxyTimeoutS`（UI 位置：设置 → 基础 → LLM 代理超时），
读取优先级：

```
app_settings.llmProxyTimeoutS  >  env SAGE_LLM_PROXY_TIMEOUT_S  >  默认 60s
```

| 属性 | 值 |
| --- | --- |
| 键名 | `llmProxyTimeoutS` |
| 后端默认 | 60 |
| UI 范围 | 5–1800 秒 |
| 生效时机 | 每次上游请求（next-request） |
| 非法值处理 | 一律回退上一级，永不抛错 |

实现函数 `backend/api/llm_proxy_routes.py` 的 `_proxy_timeout_seconds()`，
两处 `httpx.Timeout(PROXY_TIMEOUT_SECONDS)` 已改为函数调用。

### 与流式开关的耦合

关闭「流式输出」后，上游改为走 `LLMClient.chat()`（非流式），
完整响应返回前没有任何字节——`httpx` 的 read timeout 必须大于
**整段生成耗时**。UI 文案已明确提示：关闭流式后建议把代理超时调到 300 秒以上。

## 流式输出开关（2026-10-28 修复）

### 死设置修复

`app_settings.streaming` 此前是「死设置」——前端只做持久化、展示、审计快照，
后端只白名单化并注入给 LLM 的配置摘要，**没有任何代码消费它**。用户关闭
「流式输出」后上游仍收到 `stream: true`。

修复：`backend/core/legacy/agent.py` 新增模块级函数
`_streaming_enabled_from_settings()`，`SageAgent._should_stream()` 在 env 判定后、
`stream_unsupported` 判定前插入设置读取分支。

### 优先级

```
env SAGE_LLM_STREAMING ∈ {0,false,off,no}  → 禁用（调试/测试用，最高优先级）
app_settings.streaming === false           → 禁用（本次新增）
llm_client.stream_unsupported === True     → 禁用（失败后自动回退）
其余                                       → 启用
```

读取失败一律回退为启用，避免配置库异常把整条聊天链路降级成非流式。

## 续写能力现状

「续写」（Resumable Streaming / Continue-After-Disconnect）在协议层**不支持**：

1. OpenAI 兼容 SSE 协议不带事件 ID（`Last-Event-ID`），无法定位断点
2. 上游网关（Ollama / LM Studio / Higress / 企业网关）无 replay buffer
3. LLM 自回归生成无法从中间 token 续采样（需 KV cache 持久化 + 续采样接口）

当前架构下，正确的解法是**延长超时**（本次改动）而非续写。如需续写能力，
需上游模型/网关全链路改造，不在 Sage 单侧可控范围。

## upstream_timeout 504 的可操作分类（2026-10-30）

Sage 自己的 LLM 代理在等待上游超时时返回 504，响应体为
`{"detail":{"type":"upstream_timeout",...}}`。`_raise_classified_error()`
现在会读取错误响应体，命中 `upstream_timeout` 时归类为 `TIMEOUT` 并给出
可操作文案（提示调大「设置 → 基础 → LLM 代理超时」，即
`llmProxyTimeoutS`）。流式路径在 `raise_for_status()` 前先 `aread()`
错误体，否则 `.text` 不可读、分类拿不到该标记。

普通 504（无 `upstream_timeout` 标记）仍归 `SERVER_ERROR`。

## 自动重试总时长预算（2026-10-30）

`chat()` 与 `chat_stream_events()` 的重试循环新增墙钟预算：
从首次尝试起算，退避前的累计耗时超过预算即停止，并用最后一次错误类型
抛出（消息追加「自动重试累计超过 Ns 总时长预算，已停止」）。

| 项 | 值 |
| --- | --- |
| 默认预算 | 180 秒 |
| 环境变量 | `SAGE_LLM_RETRY_TOTAL_BUDGET_S`（0 = 不限，非法值回退默认） |
| 作用范围 | 非流式 + 流式两条重试循环 |

原因：代理超时类 504 每次尝试本身就要等满代理超时（默认 60s），
旧行为下 10 次重试可累计卡住约 10 分钟。

## 非流式重试事件的可见性（2026-10-30）

非流式 `chat()` 的 `retry_callback` 在 `agent.run_loop` 中只能暂存，
旧实现仅在 `chat()` 正常返回后补发——重试耗尽抛异常时补发代码不执行，
前端完全看不到「重试中」。现在失败路径会先补发所有暂存重试事件再抛出。
流式路径仍是实时的。
