# LLM 客户端 `RemoteProtocolError` 重试盲区修复

> 状态：PR 已开 (https://github.com/oneMuggle/sage/pull/2574)
> 分支：`fix/llm-protocol-error-retry`
> 范围：`release/win7`（主战场） + `main`（同步）
> 创建日期：2026-10-27

---

## 1. 背景与目标

### 1.1 现象

最新 Win7 LTS 安装包用户反馈：

> 使用 Sage 聊天时报错 `"peer closed connection without sending complete message body（incomplete chunked read）"`，**没有触发重试横幅**，直接失败。

该错误信息是 `httpcore` 在读取 chunked transfer 时上游过早关闭 TCP 连接抛出的
`httpx.RemoteProtocolError`。它**不是** SSL 错误（TLS 握手已成功），也**不是**
HTTP 状态码错误（响应头已收到），而是流 body 中断。

### 1.2 根因

`backend/core/legacy/llm_client.py` 的 `_raise_classified_error()` 只把两类 httpx 异常
映射为可重试类型：

| httpx 异常 | LLMErrorType | 可重试？ |
|---|---|---|
| `TimeoutException` | `TIMEOUT` | ✅ |
| `ConnectError` | `NETWORK` | ✅ |
| `HTTPStatusError` | AUTH/RATE_LIMITED/SERVER/.../UNKNOWN | 视状态 |
| `ValueError/KeyError` | `PARSING` | ❌ |
| **其它**（含 `RemoteProtocolError`/`ReadError`/`WriteError`） | `UNKNOWN` | ❌ |

`httpx.RemoteProtocolError` 的 MRO 是
`RemoteProtocolError → ProtocolError → TransportError → RequestError → HTTPError`，
**不是** `ConnectError` 子类，因此落到兜底 `UNKNOWN`。

`_RETRYABLE_ERROR_TYPES = {RATE_LIMITED, SERVER_ERROR, TIMEOUT, NETWORK}` 不含 `UNKNOWN`，
所以整个重试循环跳过。

### 1.3 同仓库内自相矛盾

`backend/tools/http_factory.py:183` 的 `RETRYABLE_EXCEPTIONS`（工具层 HTTP 抓取重试）
**明确**包含 `httpx.RemoteProtocolError`、`ReadError`、`WriteError`。团队对该异常的
"可重试"认知一致，唯独 `llm_client.py` 漏掉了。

### 1.4 目标

1. 把 `RemoteProtocolError` / `ReadError` / `WriteError` 纳入 `NETWORK` 分类
2. 让首字前的 chunked 中断能触发指数退避重试（默认 3 次，用户可在设置 UI 调整，上限 20；尊重 `_LLM_RETRY_MAX_ATTEMPTS` 配置）
3. 补测试覆盖：`chat()` 与 `chat_stream_events()` 两条路径
4. 同步 `main` 分支（main 同样有该盲点，代码完全一致）

### 1.5 不在范围

- **首字后的中断仍按契约终止**——这是设计（避免重试导致内容重复）。本次不修改。
- 不新增 UI 提示；原 `LLMError.to_dict()` 透传 message 已经够用。
- 不改动 `http_factory.RETRYABLE_EXCEPTIONS` 或 `download_tool` 已有重试。

---

## 2. 涉及的文件与模块

| 文件 | 改动 | 说明 |
|---|---|---|
| `backend/core/legacy/llm_client.py` | 修改 | `_raise_classified_error` 增加 `RemoteProtocolError`/`ReadError`/`WriteError` → `NETWORK` 映射；同步 docstring |
| `backend/tests/unit/test_llm_client_errors.py` | 新增测试 | `test_remote_protocol_error_raises_network_error`、`test_read_error_raises_network_error` |
| `backend/tests/unit/test_llm_client_stream_errors.py` | 新增测试 | `test_stream_remote_protocol_error_raises_network_error` |

---

## 3. 技术方案

### 3.1 代码改动

`backend/core/legacy/llm_client.py` 的 `_raise_classified_error` 在 `ConnectError` 分支后追加：

```python
if isinstance(exc, httpx.ConnectError):
    logger.error(f"LLM 连接失败: {exc}")
    raise LLMError(LLMErrorType.NETWORK, f"无法连接 LLM: {exc}")
# 新增：流 body 中断（chunked 中途关闭 / 读写出错）→ 归为网络层失败
if isinstance(exc, (httpx.RemoteProtocolError, httpx.ReadError, httpx.WriteError)):
    logger.error(f"LLM 流传输中断: {exc}")
    raise LLMError(LLMErrorType.NETWORK, f"LLM 连接中断: {exc}")
```

异常类 MRO 校验（实测 httpx 0.26.0 / py38 env）：

```
RemoteProtocolError → ProtocolError → TransportError → RequestError
ReadError           → TransportError → RequestError
WriteError          → TransportError → RequestError
```

三者都不是 `ConnectError` 子类，不会与现有分支冲突；也都不是 `TimeoutException` 子类
（超时走前一个分支）。

docstring 同步更新列出新映射：

```python
"""
...
- ``httpx.TimeoutException``              → TIMEOUT
- ``httpx.ConnectError``                  → NETWORK
- ``httpx.RemoteProtocolError/ReadError/WriteError`` → NETWORK（流传输中断）
- ``httpx.HTTPStatusError``               → AUTH_FAILED (401) / RATE_LIMITED (429)
                                            / SERVER_ERROR (5xx)
                                            / CONTEXT_OVERFLOW (400/413 且命中溢出特征串)
                                            / UNKNOWN (其余)
- ``ValueError`` / ``KeyError``           → PARSING
- 其余异常                                → UNKNOWN
"""
```

### 3.2 测试覆盖

**`test_llm_client_errors.py`**：
- `test_remote_protocol_error_raises_network_error`：mock `client.post` side_effect =
  `httpx.RemoteProtocolError("peer closed connection... (incomplete chunked read)")`，
  断言 `exc.type == LLMErrorType.NETWORK`，且 message 含原异常文本
- `test_read_error_raises_network_error`：`httpx.ReadError("read aborted")` 同理

**`test_llm_client_stream_errors.py`**：
- `test_stream_remote_protocol_error_raises_network_error`：用 `_patch_stream` 把
  `enter_error=httpx.RemoteProtocolError(...)` 注入到流入口，断言 NETWORK

### 3.3 契约保持不变

| 场景 | 现有行为 | 本次修复后 |
|---|---|---|
| 连接被拒（ConnectError） | 重试 | 重试（不变） |
| 首字前 chunked 中断（RemoteProtocolError） | ❌ 直接 UNKNOWN 失败 | ✅ NETWORK → 重试 |
| 首字后 chunked 中断 | ❌ `_saw_content_delta` → raise | ❌ 不变（契约） |
| 超时 | 重试 | 重试（不变） |
| HTTP 429 | 重试 | 重试（不变） |
| HTTP 5xx | 重试 | 重试（不变） |

---

## 4. 实施步骤

- [x] 步骤 1：在 `test_llm_client_errors.py` 新增 2 个测试（TDD RED → GREEN）
- [x] 步骤 2：在 `test_llm_client_stream_errors.py` 新增 1 个测试（TDD RED → GREEN）
- [x] 步骤 3：跑新测试确认失败（RED 验证）
- [x] 步骤 4：修改 `_raise_classified_error` + docstring
- [x] 步骤 5：跑新测试确认通过（GREEN 验证）
- [x] 步骤 6：跑整个 `test_llm_client*.py` 测试文件集合（93/93 通过，无回归）
- [x] 步骤 7：跑 `pytest backend/tests/unit` 全量，按 6 个环境性失败基线判断 → 5/5 都是 baseline，无新增回归
- [x] 步骤 8：commit + push + 开 PR → release/win7（#2574）
- [ ] 步骤 9：CI 绿后 cherry-pick 到 main

---

## 5. 风险评估与依赖

| 风险 | 等级 | 缓解 |
|---|---|---|
| 改动可能让真正不可重试的协议错误（如 provider 协议不兼容）进入重试循环 | 低 | 默认 3 次（用户可调，上限 20）+ 指数退避默认封顶 15s（用户可调，下限 1s）；失败后仍按原错误面终止 |
| 用户上游 endpoint 配置问题（非代码层）| 信息 | 修复仅让重试触发；若 endpoint 持续中断，最终仍失败，用户会看到按自己设置次数重试的横幅而非直接报错——信息量反而更大 |
| main 分支同步冲突 | 低 | 两分支 `_raise_classified_error` 当前代码一致；cherry-pick 即可 |
| 影响流式首字后契约 | 无 | 本次完全不动 `if not nothing_yielded` / `_saw_content_delta` 判断 |

### 依赖

- 无新依赖
- httpx 0.26.0（已 pin，主/Win7 一致）
- 测试依赖 pytest-asyncio、pytest-mock（已存在）

---

## 6. 不在本次范围

- **首字后的流中断重试**：涉及内容去重，需要 SSE 协议层配合回滚，是单独方案
- **UI 侧错误文案优化**：把原始 httpx 信息换成对用户更友好的文案，是另一个 PR
- **`LLMErrorType.UNKNOWN` 的细分**：把兜底拆出更多子类（如 `PROTOCOL_ERROR`），
  属于重构，本次只把已明确属于网络层的异常归位
