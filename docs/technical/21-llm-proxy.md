# 21 · LLM 代理路由

> 解决浏览器 → 远端 LLM（Ollama / OpenAI / Anthropic 等）的 CORS 拦截问题。

---

## 背景

Sage 前端在「设置 → 端点」页面提供「测试连接」「拉取模型列表」两个调试能力。
这两个能力的早期实现位于
[`src/features/manage-endpoints/api.ts`](../../src/features/manage-endpoints/api.ts)，
是**浏览器直接 `fetch()` 用户的 LLM URL**（`http://<ip>:11434` 之类）。

**问题场景**：当 Ollama 部署在远端服务器，前端跑在本地 `http://localhost:1420` 时，
浏览器因 CORS（同源策略）拒绝跨源请求，前端只看到
`TypeError: Failed to fetch`，与远端 Ollama 真实状态无关。

**已尝试的 CORS 方案**：

| 方案                               | 结果                                                          |
| ---------------------------------- | ------------------------------------------------------------- |
| Ollama `OLLAMA_ORIGINS=*` 环境变量 | 常因 webview / systemd 注入失败 / 监听 127.0.0.1 等原因仍被拦 |
| Python `requests` 直连 Ollama      | 通（因为非浏览器不受 CORS 限制），但浏览器仍卡                |
| Vite dev server 代理               | 只在 dev 生效，prod（Tauri 打包）失效                         |

**根本原因**：CORS 是浏览器的同源策略，不是 LLM 协议本身的硬性要求。
任何「让浏览器直接打远端」的路子都受此约束。

---

## 方案

在已有 FastAPI 后端加一个**通用 LLM 代理路由**。
前端所有浏览器到 LLM 的调用先经本机后端（端口 `8765`），
后端用 `httpx` 透传到 `X-LLM-Provider-Url` 头部指定的上游 —
**非浏览器，无 CORS**。

```
   before                          after
                                       ┌─ Ollama (http://<ip>:11434)
                                       │
浏览器 ──fetch──> Ollama        浏览器 ──fetch──> FastAPI ──httpx──> Ollama
       (CORS ❌)                          (同源 ✅)             (无 CORS,服务端)
```

- `useChat` 主对话流不受影响 — 它走 Tauri IPC → Rust → Python，本来就在后端侧
- 上游 Ollama 完全无需 `OLLAMA_ORIGINS` 配置
- 前端 `EndpointConfig.baseUrl` 仍填 Ollama 真实 URL（如 `http://<ip>:11434`），无需 `/v1` 后缀

---

## 架构

### 后端

新文件 [`backend/api/llm_proxy_routes.py`](../../backend/api/llm_proxy_routes.py)
提供一个 catch-all 路由，挂在 `/api/v1/llm/*` 命名空间下，与现有 `hex_routes` / `legacy_routes` 保持同一前缀约定。

```python
@router.api_route(
    "/llm/{path:path}",
    methods=["GET", "POST", "PUT", "DELETE", "PATCH"],
    include_in_schema=False,  # 透传路由,OpenAPI schema 表达不出语义
)
async def proxy_to_llm(path: str, request: Request) -> Response:
    ...
```

注册于 [`backend/main.py`](../../backend/main.py) 第 162 行，
在 `API_MODE` 判断之前 — **两种 mode（hex / legacy）都注册**，
因为它与 chat pipeline 无关。

### 前端

[`src/features/manage-endpoints/api.ts`](../../src/features/manage-endpoints/api.ts) 顶部：

```typescript
const LLM_PROXY_BASE: string =
  (import.meta.env.VITE_LLM_PROXY_BASE as string | undefined) ?? 'http://localhost:8765/api/v1/llm';

function proxyHeaders(providerUrl: string, apiKey: string): HeadersInit {
  return {
    Authorization: `Bearer ${apiKey}`,
    'Content-Type': 'application/json',
    'X-LLM-Provider-Url': providerUrl,
  };
}
```

`fetchModels` / `testChatCompletion` 内的 `fetch()` 调用改为：

```typescript
// 旧: 直接打上游
fetch(`${baseUrl}/models`, ...)
// 新: 走后端代理
fetch(`${LLM_PROXY_BASE}/v1/models`, {
  headers: proxyHeaders(baseUrl, apiKey),  // 真实上游通过 header 传
})
```

`Settings.tsx` 与 `useChat` 都不动 — 公共签名未变。

---

## 请求流

```
┌─ 浏览器 ────────────────────────────────────────────────┐
│ POST /api/v1/llm/v1/chat/completions                    │
│ Host: localhost:8765                                    │
│ Origin: http://localhost:1420                          │
│ Authorization: Bearer sk-...                            │
│ X-LLM-Provider-Url: http://192.168.1.10:11434          │
│ Content-Type: application/json                          │
│ {"model": "llama3", "messages": [...]}                 │
└────────────────────┬────────────────────────────────────┘
                     │ (同源 1420↔8765 已在 CORS 白名单)
┌─ FastAPI (8765) ─┴─────────────────────────────────────┐
│ proxy_to_llm(path="v1/chat/completions"):             │
│  1. 读 X-LLM-Provider-Url,校验 (http/https 必须)        │
│  2. 重建 upstream URL = base + path + (?qs)            │
│  3. 过滤 hop-by-hop 头 + X-LLM-Provider-Url (避免循环) │
│  4. 取 body (POST/PUT/PATCH)                            │
│  5. httpx.request(method, upstream, headers, body)      │
│  6. Response(content, status_code, filtered_headers)     │
└────────────────────┬────────────────────────────────────┘
                     │
┌─ Ollama (192.168.1.10:11434) ─┴───────────────────────┐
│ 收到: POST /v1/chat/completions                        │
│      Authorization: Bearer sk-...                       │
│      {"model": "llama3", ...}                           │
│ 响应: 200 + application/json + OpenAI chat.completion   │
└────────────────────────────────────────────────────────┘
```

---

## 错误模型

代理返错用 `HTTPException(status_code, detail={...})` — 与 `hex_routes.py` 风格一致。

| HTTP 状态 | `detail.type`              | 触发条件                                                 | 前端表现                                 |
| --------- | -------------------------- | -------------------------------------------------------- | ---------------------------------------- |
| 400       | `missing_provider_url`     | 缺 `X-LLM-Provider-Url` 头                               | `连接失败: 400 ...`                      |
| 400       | `invalid_provider_url`     | 头不是 `http://`/`https://`,或含 userinfo (`user:pass@`) | `连接失败: 400 ...`                      |
| 504       | `upstream_timeout`         | 上游 60s 无响应                                          | `连接失败: 504 ...`                      |
| 502       | `upstream_unreachable`     | TCP 连接失败(`httpx.ConnectError`)                       | `连接失败: 502 ...`                      |
| 502       | `upstream_transport_error` | 其它传输层错误(half-close / 协议错等)                    | `连接失败: 502 ...`                      |
| 4xx       | (上游原始)                 | 上游 401/403/404/429 等                                  | 透传,前端 `fetchModels` 抛 `HTTP <code>` |
| 5xx       | (上游原始)                 | 上游 500/502/503 等                                      | 透传                                     |

---

## 配置

| 名称                  | 默认值                             | 作用                                 | 优先级          |
| --------------------- | ---------------------------------- | ------------------------------------ | --------------- |
| `VITE_LLM_PROXY_BASE` | `http://localhost:8765/api/v1/llm` | 前端代理 base URL                    | vite 构建时常量 |
| `PYTHON_BACKEND_PORT` | `8765`                             | 后端端口(来自已有约定)               | 启动 env        |
| (上游 URL)            | —                                  | **不**进配置,前端按端点动态放 header | —               |

**故意不做的配置**：上游 URL 不进后端 env 变量。
Sage 的设计允许用户在前端同时配多个端点(OpenAI / Ollama / 自建等)并随时切换,
后端单一 env 变量无法支持。

---

## 安全考量

- **API Key 不暴露给浏览器以外**:
  之前 Ollama 默认无鉴权无所谓;以后若前端要接真要 key 的服务(OpenAI 等),
  API key 仍只在浏览器内存(用户在输入框填的),通过 `Authorization` 头传到后端,
  后端再透传给上游 — 全程不出用户主机
- **hop-by-hop 头过滤**:
  严格按 RFC 7230 §6.1 列表过滤请求和响应头(Host / Connection / Content-Length 等)
- **`X-LLM-Provider-Url` 内部头**:
  永不透传给上游,避免「上游把我们的代理头又当 X-LLM-Provider-Url 用」的循环
- **拒绝 URL userinfo**:
  上游 URL 含 `user:pass@` 时返回 400,防止凭据泄露到后端 log
- **path 规范化**:
  用 `posixpath.normpath` 折叠 `.` / `..`,结果永远被约束在 `/` 内(不会逃出上游根)
- **log URL 脱敏**:
  日志中 URL 经 `_safe_url_for_log` 剥 userinfo、限长 80 字符
- **CORS 白名单**:
  `backend/main.py` 已配 `CORSMiddleware(allow_origins=["*"])` —
  本代理的 `Access-Control-Allow-Origin` 头由 FastAPI 中间件统一处理

---

## 测试

| 层级     | 文件                                                  | 覆盖                                                                                  |
| -------- | ----------------------------------------------------- | ------------------------------------------------------------------------------------- |
| 后端集成 | `backend/tests/integration/test_llm_proxy_routes.py`  | 9 用例:GET/POST 透传、缺/错 header、4xx/5xx 透传、查询串、Authorization、循环防护     |
| 前端单元 | `src/features/manage-endpoints/__tests__/api.test.ts` | 6 用例:URL 走代理、X-LLM-Provider-Url header、Authorization、JSON 解析、上游 500 错误 |

后端用 `respx` mock 上游,前端用 `vi.stubGlobal`/`window.fetch` mock。

---

## 端到端验证

```bash
# 1. 启后端
conda activate sage-backend && python backend/main.py

# 2. 启前端
npm run dev

# 3. 浏览器开 http://localhost:1420 → 设置 → 端点
#    名称: Ollama 远程
#    Base URL: http://<server-ip>:11434    (不加 /v1)
#    API Key: 留空
#    → 点 "测试连接" → "连接成功 · 发现 N 个模型"
```

DevTools Network 面板应能看到:

- 实际请求 URL = `http://localhost:1420 → http://localhost:8765/api/v1/llm/v1/models`
- Response 来自 Ollama(`content-type: application/json`)

---

## 为什么不需要 Ollama 配 CORS

`OLLAMA_ORIGINS=*` 是 Ollama 自己的安全配置,只影响**浏览器**
直接打到 Ollama 的请求是否被拒。**本方案让浏览器永远只跟同源后端对话**,
后端用 `httpx` 调 Ollama,Ollama 看到的是普通 HTTP 请求(无 Origin 头,无 CORS 概念),
配不配 `OLLAMA_ORIGINS` 都通。

---

## v2 路线图(本期状态)

- ✅ **SSE 流式透传**(`2026-06-24`)：`_proxy_streaming()` 用 `httpx.AsyncClient.stream()`
  + `StreamingResponse` 把上游 chunked 响应原样回传;触发条件 `Accept: text/event-stream`
  或 query string `stream=true`;`useChat` 主对话现在也走本代理(见下面「LLM 主对话改走代理」)。
- **per-endpoint provider URL 存进 `EndpointConfig`**:目前通过 header 传;
  若日后需 server 重启后恢复多端点,再升级
- **请求体大小限制 / 限流**:60s timeout 已够,先不做

---

## LLM 主对话改走代理(v2, 2026-06-24)

### 动机

v1 时代 `LLMClient`(`backend/core/legacy/llm_client.py`)直接拼
`{base_url}/chat/completions` 直连上游,这条路径与「测试连接」走代理的 baseUrl
解析规则**互斥**：

| baseUrl | 测试连接(proxy 拼 `/v1/models`) | Chat(直连 `/chat/completions`) |
|---|---|---|
| `https://api.minimaxi.com/` | ✅ 拼成 `/v1/models` | ❌ 直连 `/chat/completions` (404) |
| `https://api.minimaxi.com/v1` | ❌ 拼成 `/v1/v1/models` (双 v1, 404) | ✅ 直连 `/v1/chat/completions` |

同一个 baseUrl 配置不可能同时让两边都通;用户必须知道要走哪条规则。

### 方案

让 `LLMClient` 也走本机代理,把真实上游 URL 通过 `X-LLM-Provider-Url` header 注入:

```python
# backend/core/legacy/llm_client.py
def _get_client(self) -> httpx.AsyncClient:
    if self.config.use_proxy:
        backend = (self.config.backend_url or "http://127.0.0.1:8765").rstrip("/")
        client_base_url = f"{backend}/api/v1/llm"
        headers["X-LLM-Provider-Url"] = self.config.base_url
    else:
        client_base_url = self.config.base_url
    ...
```

路径从 `/chat/completions` 改为 `/v1/chat/completions`,因为 base_url 现在指向
proxy(不带 /v1),完整 URL 由 proxy 拼成 `<provider_url>/v1/chat/completions`。

### `LLMConfig` 新增字段

| 字段 | 类型 | 默认 | 说明 |
|---|---|---|---|
| `backend_url` | `str` | `os.environ["BACKEND_URL"]` 或 `http://127.0.0.1:8765` | 本机后端地址,用于拼 proxy URL |
| `use_proxy` | `bool` | `True` | 是否走 proxy。单测可设 `False` 直连上游,简化 respx fixture |

### `backend/main.py` 注入

```python
os.environ.setdefault("BACKEND_URL", f"http://127.0.0.1:{port}")
```

确保 `LLMConfig` 默认值能拿到正确的本机后端地址。

### SSE 流式支持

`_proxy_streaming()` 检测条件:
- `Accept` 头含 `text/event-stream` (SSE 标准)
- 或 query string `stream=true` (OpenAI 流式约定)

错误处理: 上游 4xx/5xx 在 yield 任何 chunk 之前抛 `HTTPException`,调用方拿到正确的
status code + body;yield 之后断开由调用方决定如何处理。

### 兼容性影响(breaking change)

- **现有用户的 baseUrl 配置**(带 `/v1`):改后 chat 调用会请求 `/v1/v1/chat/completions` → 404。
  release notes 必须说明;可考虑加迁移代码去掉末尾 `/v1`。
- **单测**:fixture mock 上游 URL;`_make_config()` 默认 `use_proxy=False` 保持原行为。

### 相关文件

- `backend/core/legacy/llm_client.py` (LLMClient + LLMConfig)
- `backend/api/llm_proxy_routes.py` (proxy + `_proxy_streaming`)
- `backend/main.py` (BACKEND_URL 注入)
- `backend/tests/unit/test_llm_client_remaining.py` (proxy 行为测试)
- `backend/tests/integration/test_llm_proxy_routes.py` (SSE 透传测试)

---

_关联代码_:

- [`backend/api/llm_proxy_routes.py`](../../backend/api/llm_proxy_routes.py)
- [`backend/main.py`](../../backend/main.py)（第 20、162 行）
- [`backend/tests/integration/test_llm_proxy_routes.py`](../../backend/tests/integration/test_llm_proxy_routes.py)
- [`src/features/manage-endpoints/api.ts`](../../src/features/manage-endpoints/api.ts)
- [`src/features/manage-endpoints/__tests__/api.test.ts`](../../src/features/manage-endpoints/__tests__/api.test.ts)
