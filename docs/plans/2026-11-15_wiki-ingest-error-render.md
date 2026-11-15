# LLM Wiki 导入失败时 React 崩溃修复

- 日期：2026-11-15
- 分支：`fix/wiki-ingest-error-render`（基于 `origin/main`）
- 关联现象：Wiki「来源文件 → 导入文件」后前端报错
  `Objects are not valid as a React child (found: object with keys {code, message})`

## 1. 背景与根因

复现链路（2026-11-15 19:05，`data/logs/sage_20261115.log:80916`）：

1. 用户配置的 DeepSeek API key 已失效，`analyze_source` 调用
   `https://api.deepseek.com/v1/chat/completions` 返回 401。
2. 后端 `ingest_source_stream` 异常分支发出 failed 事件，但把结构化错误塞进了
   `message` 字段：`{"stage":"failed","percent":0,"message":{"code":"wiki_ingest_failed","message":"Wiki 导入失败"}}`
   （`backend/wiki/ingest.py:750-757`）。
3. 前端 `useWikiIngest` 把 `message` 原样存入 `error`（类型声明为 `string | null`，
   运行时却是对象，`src/features/wiki/useWikiIngest.ts:104-112`）。
4. `WikiIngestProgress` 直接渲染 `导入失败: {error}`（`WikiIngestProgress.tsx:30`）→
   React 抛 "Objects are not valid as a React child"，整个页面崩溃。

衍生问题（同链路）：

- 失败事件只写死「Wiki 导入失败」，真实原因（HTTP 401）被吞掉，用户无从排查。
- `SourcesView.handleIngest` 把聊天端点/聊天模型当 embedding 用
  （`embedModel: modelId`），`WikiChat` 硬编码 `text-embedding-3-small` 打聊天端点。
  DeepSeek 无 embeddings 接口、用户也未配置 `modelSelections.embeddingModel`，
  即使 key 修好，导入也会在「嵌入」步骤失败。
- 渲染层 GET 设置时 apiKey 会被脱敏为空串（`redact_secrets`）；若 localStorage
  缓存丢失，wiki 请求会带空 key 打上游 401，而聊天主链路走后端设置不受影响。

## 2. 目标

1. 导入失败时不再崩溃，进度条正确显示失败原因。
2. 失败事件带上真实上游错误摘要（如 `HTTP 401`），不泄露请求内容/凭据。
3. 前后端事件契约对齐：`message` 恒为字符串，错误码走独立 `code` 字段。
4. Wiki 导入/问答使用 `modelSelections.embeddingModel` 配置的端点与模型；
   未配置时在前端提前给出可操作提示，而不是跑到一半失败。
5. 后端对「请求里 apiKey 为空（被脱敏）」的情况，从 `app_settings` 按 baseUrl
   兜底解析真实 key。

## 3. 涉及文件

| 文件 | 变更 |
| --- | --- |
| `backend/wiki/ingest.py` | `emit` 支持附加字段；failed 事件改为字符串 message + `code`；错误摘要函数 |
| `backend/api/wiki_credentials.py`（新增） | 按 baseUrl 从 app_settings 解析真实 apiKey |
| `backend/api/wiki_routes.py` | ingest/chat/research 路由接入凭据兜底 |
| `src/features/wiki/useWikiIngest.ts` | 进度 payload 归一化（对象 message → 字符串），类型收紧 |
| `src/widgets/wiki/WikiIngestProgress.tsx` | 保持仅渲染字符串（hook 保证） |
| `src/widgets/wiki/SourcesView.tsx` | embedding 端点/模型取自 `embeddingModel`；未配置时提前 toast |
| `src/widgets/wiki/WikiChat.tsx` | embedding 配置同上（未配置时降级为 token 检索） |
| `backend/tests/integration/test_ingest_stream.py` | 更新 failed 事件契约断言，补 HTTP 状态摘要用例 |
| `backend/tests/integration/test_wiki_ingest_stream_route.py` | 契约断言同步 |
| `src/features/wiki/__tests__/useWikiIngest.*.test.ts` | 补对象 message 归一化用例 |
| `src/widgets/wiki/__tests__/SourcesView.test.tsx` | embedding 配置分支用例 |
| `backend/tests/unit/test_wiki_credentials.py`（新增） | 凭据兜底单测 |

## 4. 技术方案

### 4.1 失败事件契约（后端）

`emit` 扩展 `**extra`，failed 路径改为：

```python
yield emit("failed", 0, failure_message(e), code=INGEST_STREAM_ERROR_CODE)
```

`failure_message(e)`：
- `httpx.HTTPStatusError` → `Wiki 导入失败（LLM 请求返回 HTTP {status}）`
- 其它异常 → `Wiki 导入失败`

前端 `IngestProgress` 增加 `code?: string`，`message` 恒为 `string | null`。

### 4.2 前端归一化（防御旧后端）

`useWikiIngest` 新增 `normalizeIngestProgress(payload)`：

- `message` 为字符串 → 保留；
- `message` 为对象且有字符串 `message` 字段 → 取该字段；
- 对象只有 `code` → 用 `code`；
- 其它 → `null`（hook 的既有兜底文案接管）。

监听器与 `broadcast` 统一走归一化，ensureModuleListener 的 catch 分支同样收敛为字符串。

### 4.3 embedding 配置

`SourcesView.handleIngest`：

```ts
const embedSelection = settings.settings.modelSelections.embeddingModel;
const embedEndpoint = resolveEndpoint(embedSelection, settings.settings.endpoints);
if (!endpoint || !modelId) { toast.error('请先在设置中配置聊天模型'); return; }
if (!embedEndpoint || !embedSelection.modelId) {
  toast.error('请先在设置中配置嵌入模型（用于导入后的向量化）');
  return;
}
```

请求改为携带 embedEndpoint.baseUrl / apiKey / embedSelection.modelId。

`WikiChat`：有 embedding 配置时使用之；未配置时传空串（后端 chat 检索对向量
失败已 try/except 降级为 token 搜索，不阻塞问答）。

> 已知限制（非本次修复范围）：wiki 向量维度仍硬约束 1536（`DEFAULT_EMBED_DIM`），
> 需配置 1536 维的 embedding 模型（如 text-embedding-3-small / embo-01）。

### 4.4 后端凭据兜底

新增 `backend/api/wiki_credentials.py::resolve_llm_api_key(base_url, provided)`：

- `provided` 非空直接返回（尊重刚在 UI 输入的新 key）；
- 否则读取 `SettingsRepository().get_json("app_settings")` + `to_camel`，按
  `baseUrl`（去尾部 `/`）匹配 endpoints，返回其 `apiKey`；
- 任何异常返回空串（降级，不阻断请求）。

在 ingest/stream、chat/stream、research 三个路由入口对 llm/embed key 应用。
py38 兼容：仅用 `typing` 注解，不用 PEP 604/585。

## 5. 实施步骤

- [x] M1 后端 failed 事件契约 + 错误摘要（ingest.py + 测试）
- [x] M2 前端 `useWikiIngest` 归一化 + 测试
- [x] M3 SourcesView / WikiChat 使用 embeddingModel + 测试
- [x] M4 后端凭据兜底（wiki_credentials.py + 路由接入 + 单测）
- [x] M5 本地验证：ruff / pytest（相关子集）/ vitest（相关文件）/ tsc
- [ ] M6 提交、push、PR、CI 绿后合并
- [ ] M7 cherry-pick 到 `release/win7` 并验证 py38 兼容

### 本地验证记录

- 后端：`pytest` 相关 4 个测试文件 44 passed；`ruff check` 通过；`check_py38_compat.py` 0 violations。
- 前端：`vitest run src/widgets/wiki src/features/wiki` 23 文件 / 99 tests passed；`tsc --noEmit` 通过；eslint / prettier 通过。
- 架构棘轮：`architecture-baseline.json` 按 ratchet 协议补账
  （wiki_routes.py 1843→1856、ingest.py 859→873），`architecture-check.mjs` 通过。

## 6. 风险与依赖

- 事件契约变更：后端与前端随同一安装包发布，且前端归一化对旧后端兼容，
  风险可控；已有集成测试会同步更新。
- 凭据兜底读取 DB：设置读取失败时降级为空 key，不阻断请求；不引入新的
  凭据外泄面（不记录 key）。
- embedding 维度硬约束 1536 为既有行为，本次不改；未配置 embedding 时导入
  会被前端拦截并提示，属于行为变化（此前会跑到嵌入步骤才失败）。
- 用户侧仍需更新有效的 DeepSeek key（或切换到可用端点），否则导入会以
  「HTTP 401」明确报错而不是崩溃。
