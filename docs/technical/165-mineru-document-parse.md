# 162. MinerU 文档解析子系统

> 适用范围：Sage 客户端侧的 MinerU 文档解析适配层（可插拔解析引擎、质量路由、后台队列、聊天双阶段附件）。
> 服务端部署（模型搬运、systemd、GPU 多卡）见 [154. MinerU 内网独立部署](./154-mineru-deployment.md)，本文不重复。

---

## 1. 背景与目标

内网已部署 MinerU 4.1.7 离线包（`/home/fz/mineru-offline-bundle-out`，产物 `mineru-offline-bundle-4.1.7-20261115-linux-x86_64.tar`），提供 V1 异步 REST API。Sage 侧需要一个**客户端适配组件**，把 MinerU 变成可插拔的「解析引擎」之一，而不是把 MinerU 调用散落在业务代码里。

目标：

| 目标 | 落地方式 |
| --- | --- |
| 引擎可插拔 | `ParseEngine` Protocol + `DocumentParseService` 路由，新增引擎不改业务层 |
| 本地优先、MinerU 兜底 | 本地文本提取先行，质量不达标才升级 MinerU（省 GPU、保密） |
| 失败不阻断 | MinerU 不可用时自动回退本地，结果带 `warnings` |
| 密钥不外泄 | `apiKey` 静态加密，状态接口只回 `hasApiKey` 布尔 |
| 不重复造轮子 | 复用既有附件提取器（`extract_attachment_text`）、媒体仓（`MediaStore`）、设置 KV |

非目标（本轮不做）：

- 文献调研流水线只留接口，不接自动适配器；
- 不做 MinerU 服务端自身的部署/调优；
- 不做跨引擎结果对比与评测平台。

---

## 2. 架构分层

```text
┌──────────────────────────────────────────────────────────────┐
│ 接入层                                                        │
│  ├─ backend/tools/parse_document_tool.py   （Agent 工具）      │
│  ├─ backend/api/chat_attachment_routes.py  （聊天附件双阶段）   │
│  └─ backend/api/mineru_routes.py           （状态查询）        │
└───────────────┬──────────────────────────────────────────────┘
                │ ParseRequest / ParseResult（纯契约，无适配器依赖）
┌───────────────▼──────────────────────────────────────────────┐
│ 编排层  backend/application/document_parse.py                 │
│  DocumentParseService：引擎路由 / 质量闸门 / 熔断 / 缓存读写     │
│  CircuitBreaker：3 连败开路 60 s，半开重试                      │
└───────┬───────────────────────────────────┬──────────────────┘
        │                                   │
┌───────▼───────────────┐   ┌───────────────▼──────────────────┐
│ 领域契约               │   │ 端口（Protocol）                 │
│ backend/domain/        │   │  ParseCache（get/put）            │
│  document_parse.py     │   │  settings_loader / mineru_factory │
│  MineruSettings        │   └───────────────┬──────────────────┘
│  ParseRequest/Result   │                   │
│  ParseEngine           │   ┌───────────────▼──────────────────┐
└────────────────────────┘   │ 适配器（adapters/out）            │
                             │  ├─ local_engine.py  本地提取     │
                             │  ├─ quality.py       质量打分     │
                             │  ├─ mineru_client.py V1 异步客户端│
                             │  ├─ mineru_models.py 报文编解码    │
                             │  ├─ mineru_errors.py 错误类型     │
                             │  └─ mineru_engine.py 引擎适配     │
                             └───────────────┬──────────────────┘
                                             │
                             ┌───────────────▼──────────────────┐
                             │ 服务层 backend/services/           │
                             │  document_parse/                  │
                             │  ├─ config.py   配置加载（env 覆盖）│
                             │  ├─ cache.py    SQLite 缓存         │
                             │  ├─ queue.py    后台串行队列        │
                             │  └─ factory.py  单例装配           │
                             └──────────────────────────────────┘
```

依赖方向单向向内：`domain` 不依赖任何适配器；`application` 只依赖 `domain` + 端口 Protocol；适配器实现端口；服务层做装配。`import-linter` 契约 `tools→services` 与架构棘轮（`node scripts/architecture-check.mjs`）守护该方向。

---

## 3. 引擎契约与路由

### 3.1 `ParseEngine` 契约

`backend/domain/document_parse.py`：

```python
class ParseEngine(Protocol):
    name: str

    async def parse(self, request: ParseRequest) -> ParseResult: ...
    async def health(self) -> EngineHealth: ...
```

`ParseRequest` 关键字段：`filename`、`content_bytes`、`engine_hint`（`auto|local|mineru`）、`output_format`（`markdown|structured|docx|html`）、`page_range`、`tier`、`timeout_seconds`、`source_path`、`media_id`；派生属性 `.extension`（小写后缀）与 `.content_hash()`（sha256 十六进制）。

`ParseResult` 关键字段：`text`、`engine_used`、`structured`、`tier_used`、`quality_score`、`duration_ms`、`cached`、`warnings`、`media_url`、`assets`；`.with_warning(str)` 返回新对象（不可变）。

### 3.2 路由表

`DocumentParseService.parse()` 的判定顺序（`backend/application/document_parse.py`）：

| 条件 | 行为 | 结果 `engine_used` |
| --- | --- | --- |
| `engine_hint == "mineru"` | 先试 MinerU，失败则回退本地 + `warnings=["mineru_failed"]` | `mineru` 或 `local` |
| `engine_hint == "local"` | 强制本地，**不升级** | `local` |
| `engine_hint == "auto"` | 本地先跑 → 命中质量闸门则升级 MinerU | `local` 或 `mineru` |

`auto` 模式下「是否升级」的闸门 `_block_reason()` 按下列顺序短路返回第一个命中原因：

| 顺序 | 原因码 | 判定 |
| --- | --- | --- |
| 1 | `local_hint` | 用户显式指定本地 |
| 2 | `non_pdf` | 扩展名 ≠ `pdf`（MinerU 只用于 PDF 升级） |
| 3 | `disabled` | `mineru_service.enabled == false` |
| 4 | `not_configured` | `baseUrl` 为空（`MineruSettings.configured == False`） |
| 5 | `too_large` | 文件大小 > `maxUploadMb` MB |
| 6 | `circuit_open` | 熔断器处于开路状态 |
| 7 | `quality_ok` | 本地质量分 ≥ `minQualityThreshold`（默认 0.85）→ **不升级** |

未命中任何原因才升级 MinerU。MinerU 失败一律 `except Exception` 捕获 → `breaker.record_failure()` → 日志 `logger.warning("MinerU 解析失败，回退本地: ...")` → 返回本地结果并追加 `mineru_failed` 警告，**绝不抛出**。

---

## 4. MinerU V1 协议：四步时序、重试与错误映射

### 4.1 四步时序

```text
Sage 客户端                                  MinerU 服务端
     │                                            │
     │ ① POST /v1/tasks                          │
     │   body: {files:[{file_name,bytes,sha256sum}],
     │          output_formats:[...], tier?, ocr_mode?, page_range?}
     │───────────────────────────────────────────▶│  返回 202
     │◀───────────────────────────────────────────│  {id, files:[{file_id, upload:{url,headers}}]}
     │                                            │
     │ ② PUT {upload.url}  (octet-stream)        │
     │───────────────────────────────────────────▶│  文件就绪 → 自动进入执行
     │◀───────────────────────────────────────────│  {task_id, file_id, status}
     │                                            │
     │ ③ GET /v1/tasks/{task_id}   （轮询）        │
     │───────────────────────────────────────────▶│
     │◀───────────────────────────────────────────│  {status: pending|running|done|failed|canceled,
     │                                            │   files:[{status, result_url}]}
     │        …… 直到终态或超时 ……                 │
     │                                            │
     │ ④ GET {result_url}  → /v1/files/{fid}/content
     │───────────────────────────────────────────▶│  ZIP(markdown.md+middle_json.json+images/*)
     │                                            │  或 docx/html 原始字节
     │◀───────────────────────────────────────────│
```

### 4.2 重试规则

`backend/adapters/out/document_parse/mineru_client.py`：

| 步骤 | 是否重试 | 次数 | 退避 |
| --- | --- | --- | --- |
| ① `POST /v1/tasks` | 否 | 1 | — |
| ② 上传 `PUT` | 是 | 3 | `min(2.0, 0.25 * 2**(n-1))` |
| ③ `GET /v1/tasks/{id}` | 是 | 3 | 同上 |
| ④ 下载结果 | 是 | 3 | 同上 |

- 可重试状态码：`{408, 429, 500, 502, 503, 504}`（`_RETRYABLE_STATUSES`）。
- 上传失败后会**重新拉取任务快照**再取新的上传链接（链接可能过期）。
- 下载最多跟随 6 次重定向（`_MAX_REDIRECTS = 6`，状态码 `{301,302,303,307,308}`）。
- `httpx.HTTPError`（连接失败、超时）→ `MineruUnavailableError`。
- **跨域不转发 Authorization**：`_headers_for(url)` 在 URL origin 与 `base_url` 不一致时返回空 header，避免把密钥带到第三方主机。

### 4.3 错误码映射

| 服务端情形 | 客户端异常 | 编排层动作 |
| --- | --- | --- |
| HTTP 401 / 403，或错误体 `code == "invalid_api_key"` | `MineruAuthError` | 记熔断失败，回退本地 |
| 任务终态 `failed` / `canceled` | `MineruRemoteError(code=error_code or status)` | 回退本地 |
| 轮询超时（默认 300 s） | 先 `POST /v1/tasks/{id}/cancel`（5 s 超时，吞掉 `httpx.HTTPError`），再抛 `MineruTimeoutError("timeout", ...)` | 回退本地 |
| 其他 ≥400 | `MineruRemoteError` | 回退本地 |
| 响应不是 JSON 对象 | `MineruRemoteError("invalid_response", ...)` | 回退本地 |
| 网络层异常 | `MineruUnavailableError` | 回退本地 |

错误类型集中在 `backend/adapters/out/document_parse/mineru_errors.py`：`MineruError`（基类，带 `code`/`message`/`param`/`status_code`）+ `MineruConfigError` / `MineruAuthError` / `MineruUnavailableError` / `MineruTimeoutError` / `MineruRemoteError`。

服务端错误体形状为 `{"error": {"code", "message", "param"}}`；4.1.7 内置码到错误类型的映射见 §12。

---

## 5. 质量打分公式

`backend/adapters/out/document_parse/quality.py`：

```text
score = 1.0
        - 0.35  if text_per_page < 120        (LOW_TEXT_PER_PAGE)
        - 0.30  if blank_page_ratio > 0.5     (HIGH_BLANK_RATIO)
        - 0.25  if has_table
        - 0.20  if has_formula
score = round(max(0.0, score), 3)
```

| 信号 | 来源 | 说明 |
| --- | --- | --- |
| `page_count` | PyMuPDF | PDF 页数 |
| `text_per_page` | PyMuPDF | 每页平均字符数 |
| `blank_page_ratio` | PyMuPDF | 空白页占比 |
| `has_table` | 文本启发式 | 检测到表格结构 |
| `has_formula` | 正则 | `[∑∫√≈≠≤≥∂∞±×÷]` 或 `\frac/\sum/\int/\sqrt/\alpha/\beta/\theta` |

- PyMuPDF 通过 `backend.core.lazy.load_module` **惰性导入**，无 PyMuPDF 时不崩，`compute_pdf_signals` 返回 `None`。
- 默认阈值 `minQualityThreshold = 0.85`；`local_score >= 0.85` 即视为「本地够用」，不再升级 MinerU。
- 阈值可配（0–1，越小越激进地升级到 MinerU）。

---

## 6. 缓存：表结构与失效口径

表 `document_parse_cache`（`backend/data/database.py`，建表语句随主库 DDL 一起执行）：

```sql
CREATE TABLE IF NOT EXISTS document_parse_cache (
    content_hash   TEXT NOT NULL,
    engine         TEXT NOT NULL,
    tier           TEXT,
    markdown       TEXT,
    structured_json TEXT,
    images_dir     TEXT,
    meta_json      TEXT,
    created_at     INTEGER NOT NULL,
    PRIMARY KEY (content_hash, engine)
);
```

| 字段 | 含义 |
| --- | --- |
| `content_hash` | 文件内容 sha256 十六进制（`ParseRequest.content_hash()`） |
| `engine` | 引擎名（`local` / `mineru`），与内容哈希组成主键 |
| `tier` | 解析档位（`flash|basic|standard|advanced`），仅 MinerU 有意义 |
| `markdown` | 解析出的 Markdown 文本 |
| `structured_json` | 结构化结果（middle_json / layout） |
| `images_dir` | 抽出的图片目录 |
| `meta_json` | 元信息（质量分、耗时、警告、media_url 等） |

失效口径：

- **主键 = 内容哈希 + 引擎**。同一份文件用不同引擎解析互不覆盖。
- **无自动过期**：缓存不按时间清理，也不做 LRU 淘汰；文件内容不变则永远命中。
- 写入用 `INSERT OR REPLACE`（同主键覆盖）。
- 读写的**任何异常都被吞掉**（`backend/services/document_parse/cache.py`）——缓存故障绝不阻断解析主链路。
- 注意：`tier` **不参与主键**。用 `standard` 解析过一次后，再请求 `flash` 会命中 `standard` 的缓存条目。这是有意的取舍（内容相同则结果近似等价），若需要严格按档位区分，需扩展主键。

---

## 7. 熔断与后台队列

### 7.1 熔断器

`CircuitBreaker(threshold=3, cooldown_seconds=60.0, clock=time.monotonic)`（`backend/application/document_parse.py`）：

| 状态 | 进入条件 | 行为 |
| --- | --- | --- |
| closed（闭合） | 默认 | 正常放行；`record_failure()` 累计失败计数 |
| open（开路） | 连续失败数 ≥ `threshold`（3） | `closed()` 返回 `False` → 路由层跳过 MinerU（`circuit_open`） |
| 冷却结束 → 重新闭合 | `closed()` 被调用且距开路 ≥ `cooldown_seconds`（60 s） | 一次性复位 `_opened_at=None`、`_failures=0` 并返回 `True`；**无独立 half-open 态**，冷却后的第一次失败只把计数置回 1，需再次连续 3 次失败才重新开路 |

熔断器没有「半开试探」状态：冷却期由时间判定，冷却后直接回到闭合并把失败计数清零，因此恢复访问时不会因一次瞬时抖动立刻二次开路。

熔断只作用于 **MinerU 引擎**，本地引擎不受影响 —— 服务端挂掉时文档仍能本地解析。

### 7.2 后台队列

`MineruBackgroundQueue`（`backend/services/document_parse/queue.py`）：

- **单 worker 串行**：一个 `asyncio.Queue` + 一个后台协程，任务逐个执行，避免并发压垮内网 GPU 服务。
- **去重键**：`task_key = f"{sha256(content)}:{tier or 'auto'}"`。重复 `submit()` 同一文件同一档位不会重复上传，返回同一个 `task_key`。
- **状态机**：`pending` → `running` → `completed` / `failed`；查询不到时为 `unknown`。
- **失败不杀 worker**：单个任务异常只把该任务置 `failed` 并记日志，worker 继续处理下一个。

---

## 8. `parse_document` 工具的风险声明

`backend/tools/parse_document_tool.py`：

| 属性 | 值 |
| --- | --- |
| `requires_tool_context` | `True` |
| `risk` | `RiskClass.EXTERNAL` |
| `is_blocking` | `True` |
| `_MAX_SOURCE_BYTES` | 200 MB |

参数：

| 参数 | 类型 | 说明 |
| --- | --- | --- |
| `path` | string | 工作区内文档路径（经 `_resolve_workspace_path` fail-closed 校验，越界返回 `path_outside_workspace`） |
| `media_id` | string | 聊天附件 media id（与 `path` 二选一） |
| `engine` | `auto\|local\|mineru` | 默认 `auto` |
| `output_format` | `markdown\|structured\|docx\|html` | 默认 `markdown` |
| `pages` | string | 页码范围（如 `1-10`） |
| `tier` | `flash\|basic\|standard\|advanced` | 默认取配置里的 `defaultTier` |

输出字段：`engine_used`、`tier_used`、`quality_score`、`cached`、`duration_ms`、`warnings`、`media_url`、`assets`。

**风险披露**（工具描述中显式声明）：

> `engine=auto` 在本地文本质量低且 MinerU 已配置时，会把文档内容上传到内网 MinerU 服务；`engine=mineru`（或 `engine=auto` 且命中升级条件）会把文档内容发送到 MinerU 服务器。`engine=local` 保证文档绝不离机。

对隐私敏感场景，调用方应显式传 `engine=local`。

---

## 9. 聊天附件双阶段时序

`backend/api/chat_attachment_routes.py`：

```text
① 用户拖入 PDF → POST 上传
     └─ store.save(...) 落媒体仓
     └─ 若 ext == "pdf" → _schedule_mineru_enrichment(content, filename)
            ├─ 前置条件：settings.enabled && settings.configured && settings.useInChatAttachment
            └─ get_mineru_queue().submit(content, filename)  ← 后台异步，不阻塞响应

② 立即返回：本地提取的文本（本地引擎提取器，与既有附件链路一致）
     用户可以马上开始对话

③ 后台 worker 跑完 → 解析结果写入 document_parse_cache(engine='mineru')

④ 之后再次调用文本接口（get_chat_attachment_text）
     └─ 先查 SqliteParseCache().get(sha256(content), "mineru")
        ├─ 命中 → {"media_id":..., "text":..., "source":"mineru"}   ← 高保真文本
        └─ 未命中 → 本地提取（source 缺失/非 mineru）
```

要点：

- **首次不等待 MinerU**：上传响应立刻返回，用户体验不受 GPU 时延影响。
- **第二次开始才变好**：MinerU 结果通过缓存生效，文本接口自动切到 `source=mineru`。
- `_schedule_mineru_enrichment` 内所有异常都被吞掉——MinerU 不可用不影响附件上传。
- `useInChatAttachment` 关闭时完全不做后台补跑（仅 `parse_document` 工具路径可用 MinerU）。

---

## 10. 配置项与环境变量覆盖

配置载体：preference KV 键 `mineru_service`（`backend/data/settings_repo.py` 白名单内，`KEYS` 含该键）。

| 字段 | 类型 | 默认 | 约束 | 说明 |
| --- | --- | --- | --- | --- |
| `enabled` | bool | `false` | — | 总开关 |
| `baseUrl` | string | `""` | — | MinerU 服务地址，如 `http://10.0.0.5:8000`；空则 `configured == False` |
| `apiKey` | string | `""` | — | Bearer 密钥；**静态加密存储**（`secret_box.wrap_mineru_service_json`） |
| `defaultTier` | string | `"standard"` | — | 默认档位 |
| `timeoutSeconds` | number | `300` | 5–3600 | 单次解析超时（秒） |
| `maxUploadMb` | number | `25` | 1–200 | 单文件上传上限（MB），超出则不升级 MinerU |
| `useInChatAttachment` | bool | `true` | — | 聊天附件是否做后台 MinerU 补跑 |
| `minQualityThreshold` | number | `0.85` | 0–1 | 本地质量 ≥ 阈值时不升级 MinerU |

键名兼容：读取时接受 camelCase（`baseUrl`）优先，回退 snake_case（`base_url`）。写入统一走 `wrap_mineru_service_json`（加密 `apiKey`）；读取走 `unwrap_mineru_service_json`（解密）。

环境变量覆盖（`backend/services/document_parse/config.py`，**优先级高于 preference**）：

| 环境变量 | 覆盖字段 |
| --- | --- |
| `SAGE_MINERU_BASE_URL` | `baseUrl` |
| `SAGE_MINERU_API_KEY` | `apiKey` |
| `SAGE_MINERU_TIER` | `defaultTier` |
| `SAGE_MINERU_TIMEOUT_SECONDS` | `timeoutSeconds`（clamp 到 5–3600） |

前端入口：设置页 → 「MinerU 文档解析」卡片（`src/entities/setting/settingsRegistry.ts` 中 `mineru_service` 条目，visibility `advanced`）。密钥只经设置页/环境变量写入，**不入日志、不入错误消息、不入聊天**。

---

## 11. 状态接口：`GET /api/v1/mineru/status`

路由 `backend/api/mineru_routes.py`（`backend/main.py` 以 `prefix="/api/v1"` 挂载）。

响应字段：

| 字段 | 类型 | 含义 |
| --- | --- | --- |
| `configured` | bool | `baseUrl` 非空 |
| `enabled` | bool | 用户是否打开开关 |
| `hasApiKey` | bool | **是否**配置了密钥（**永不含明文**） |
| `reachable` | bool | 探测是否成功连上服务 |
| `serverAuthMode` | string | `anonymous`（服务端未开鉴权）/ `bearer`（服务端要求 Bearer 且本次 key 有效）/ `required`（服务端要求鉴权但本次 key 无效或缺失）/ `unknown` |
| `serverTiers` | string[] \| null | 服务端可用档位 |
| `serverVersion` | string \| null | 服务端版本 |
| `reason` | string | 失败原因码，如 `not_configured` / `api_key_required_or_invalid` / `unreachable` |

示例（合成值）：

```json
{
  "configured": true,
  "enabled": true,
  "hasApiKey": false,
  "reachable": true,
  "serverAuthMode": "anonymous",
  "serverTiers": null,
  "serverVersion": null,
  "reason": ""
}
```

探测逻辑（`MineruClient.probe()`，超时 `min(timeoutSeconds, 10)`）：

1. `GET /v1/usage` → 200 ⇒ `reachable=True`；有 key ⇒ `serverAuthMode="bearer"`，无 key ⇒ `"anonymous"`；
2. `GET /v1/usage` → 401/403 ⇒ `reachable=True`、`serverAuthMode="required"`、`reason="api_key_required_or_invalid"`；
3. 其它状态 ⇒ 依次尝试 `GET /v1/tiers`（取 `serverTiers`）与 `GET /v1/health`（取 `version`）；
4. 未配置 `baseUrl` ⇒ `reason="not_configured"`；抛异常 ⇒ `reason="unreachable"`。

> `/v1/health`、`/v1/models`、`/v1/tiers` 是 MinerU 4.1.7 服务端的公开路径（`_PUBLIC_PATHS`），无需鉴权即可访问；`/v1/usage` 不在公开列表内，因此开启鉴权后只有带正确 Bearer 才能读到。

---

## 12. 故障排查

| 现象 | 根因 | 处置 |
| --- | --- | --- |
| 状态接口 `reason="not_configured"` | `baseUrl` 为空 | 设置页填服务地址（注意协议与端口，如 `http://10.0.0.5:8000`） |
| `serverAuthMode="required"`、`reason="api_key_required_or_invalid"` | 服务端开了鉴权（`mineru-kit api-server --api-key ...`），本次请求未带或带错 key | 在设置页填 `apiKey`，或设 `SAGE_MINERU_API_KEY`；服务端未开鉴权时此字段应为 `anonymous` |
| 状态接口 `reachable=false`、`reason="unreachable"` | 网络不通 / 端口不对 / 服务未起 | 先 `curl http://<host>:<port>/v1/health`（公开路径，无需 key）确认服务端活着 |
| 解析报 401 `invalid_api_key` | key 不匹配 | 服务端 key 与 Sage 侧 `apiKey` 必须逐字一致；**不要把 key 贴进日志或聊天** |
| 解析报 403 `feature_requires_api_key` | 请求的是**源文件**而非解析产物（服务端禁止下载 source） | 该错误码名字有误导性：它表示「不允许下载上传的原始文件」，不是「缺 key」。客户端只应下载 `result_url`（`purpose=parse_output`）。若出现此码，说明拿到了源文件的 `result_url`——属于客户端 bug，应改取解析产物地址 |
| 解析报 `quality_tier_unavailable` | 请求的档位服务端未提供（如服务端 `--tier standard`，客户端请求 `advanced`） | 把 `defaultTier` 改成服务端实际支持的档位，或查看状态接口返回的 `serverTiers` |
| 解析报 `parse_failed` / `parse_timeout` | 服务端解析阶段失败或超时 | 看服务端日志；客户端会自动回退本地 |
| 一直本地解析、从不升级 | `minQualityThreshold` 太高 / `enabled=false` / `not_configured` / 文件超 `maxUploadMb` / 非 PDF / 熔断开路 | 逐条对照 §3.2 的闸门表；日志关键字 `MinerU 解析失败，回退本地` 表示熔断计数在涨 |
| 聊天附件解析质量没变好 | 后台补跑未触发或未完成 | 确认 `useInChatAttachment=true` 且服务可达；查 `document_parse_cache` 中 `engine='mineru'` 行是否落库；**第二次**调用文本接口才会读到 `source=mineru` |
| 离线包部署的服务**没有生成 api key** | 离线包 systemd 模板的 `ExecStart` 未传 `--api-key` → 服务端**未开鉴权** | 这是受支持的部署形态：Sage 侧 `apiKey` **留空**即可，状态接口应显示 `serverAuthMode="anonymous"`。注意 `mineru.env` 里的 `MINERU_API_KEY` **不会**被 `mineru-kit api-server` 读取（该命令的 `--api-key` 没有环境变量回退），要真正开启鉴权必须在 `ExecStart` 显式传 `--api-key` |

---

## 13. 附录：模块落点速查

| 关注点 | 文件 |
| --- | --- |
| 领域契约 | `backend/domain/document_parse.py` |
| 编排 / 路由 / 熔断 | `backend/application/document_parse.py` |
| 本地引擎 | `backend/adapters/out/document_parse/local_engine.py` |
| 质量信号与打分 | `backend/adapters/out/document_parse/quality.py` |
| MinerU 客户端 | `backend/adapters/out/document_parse/mineru_client.py` |
| 报文编解码 | `backend/adapters/out/document_parse/mineru_models.py` |
| 错误类型 | `backend/adapters/out/document_parse/mineru_errors.py` |
| MinerU 引擎适配 | `backend/adapters/out/document_parse/mineru_engine.py` |
| 配置加载 | `backend/services/document_parse/config.py` |
| SQLite 缓存 | `backend/services/document_parse/cache.py` |
| 后台队列 | `backend/services/document_parse/queue.py` |
| 单例装配 | `backend/services/document_parse/factory.py` |
| Agent 工具 | `backend/tools/parse_document_tool.py` |
| 聊天附件双阶段 | `backend/api/chat_attachment_routes.py` |
| 状态接口 | `backend/api/mineru_routes.py` |
| 密钥加密 | `backend/data/settings_repo.py`（`wrap/unwrap_mineru_service_json`） |
| 前端设置卡片 | `src/pages/settings/`（MinerU 卡片）+ `src/entities/setting/settingsRegistry.ts` |

服务端部署、模型搬运、systemd 与 GPU 多卡见 [154. MinerU 内网独立部署](./154-mineru-deployment.md)。
