# MinerU 文档解析适配子系统（设计文档）

> 文档日期：2026-11-23
> 状态：设计定稿，待用户评审
> 适用分支：main
> 关联既有文档：main 侧 `docs/technical/154-mineru-deployment.md`（待校正）、win7 侧 `docs/technical/157-mineru-deployment.md`（待校正）、`docs/technical/156-pdf-figure-citation.md`

---

## 1. 背景与目标

### 1.1 背景

Sage 现有的文档抽取能力只有两层：

- **本地 PDF**：`backend/services/attachment_pdf.py` → `extract_pdf_pages()` 逐页取文本 → `render_page_marked_text()` 加 `--- page N ---` 标记；图片型页回落到本地 OCR。
- **本地 Office**：`backend/api/chat_attachment_routes.py` → `extract_attachment_text()` 按扩展名分发到 docx/xlsx/pptx 抽取器。

两者都**没有**表格结构还原、公式识别、版面分析与标题分级。对论文 PDF 这类复杂版式文档，输出的是"扁平文本"，下游（文献调研 M1/M2 的 `extract_claims` / `verify_claims`）拿不到结构。

内网已部署 MinerU 4.1.7（离线包 `mineru-offline-bundle-4.1.7-20261115-linux-x86_64.tar`，A6000 48GB，`--tier standard`），提供整份文档 → Markdown + 结构化 JSON 的解析能力。

### 1.2 目标

1. 在 Sage 内建立**统一解析子系统**：可插拔的解析引擎抽象（MinerU 只是一个插件），本地引擎与 MinerU 引擎共用同一入口。
2. **聊天附件 PDF 路由增强**：本地优先秒级返回，质量不足时后台提交 MinerU，结果进内容哈希缓存供后续轮次与其它子系统复用。
3. 提供 `parse_document` 工具，让 agent 可显式要求高精度解析。
4. 提供设置页卡片与后端状态端点，让用户自助配置与自检连通性。
5. 一并修复离线包侧的 3 个已知问题（假 WARN、打包脚本缺失、文档漂移）。

### 1.3 非目标

- 不替换现有 `ocr_image` 工具（单图 → 纯文本，语义不同，并存）。
- 不在 Sage 后端进程内嵌 MinerU（`docvortex` 是 `cp311-abi3 / manylinux_2_28` 二进制轮子，物理上不可能）。
- 不接公有云 MinerU SaaS。
- **本轮不把 `structured_content.json` 接到文献调研 M1/M2 管线**（用户已确认）——解析子系统只负责产出高质量结构化产物并暴露接口，管线侧改造留作后续。
- 不做 PDF 编辑/标注/转换等 MinerU 未提供的功能。

---

## 2. 关键事实核对（设计依据）

本节所有结论来自**离线包内 `mineru-4.1.7-py3-none-any.whl` 的实际源码**，而非既有文档或公开记忆。既有 `docs/technical/154-mineru-deployment.md` 存在 5 处漂移，§11 列出校正项。

| # | 事实 | 源码依据 | 对设计的影响 |
|---|---|---|---|
| F1 | **Sage 不能 `import mineru`** | 离线包同时携带 `docvortex-0.6.22-cp311-abi3-manylinux_2_28_x86_64.whl`（二进制轮子，非 pure-Python） | 必须自写薄 HTTP 客户端；也顺带避开 §154 提到的 `AICapability` 模板方法只支持单请求的问题 |
| F2 | `/v1/health`、`/v1/models`、`/v1/tiers` **免鉴权** | `mineru/parser/api_server.py:2019` `_PUBLIC_PATHS = frozenset({"/v1/health", "/v1/models", "/v1/tiers"})` | 离线包 `verify.sh` 第 6 项"鉴权拦截"探的是免鉴权端点 → **永远只能 WARN，不可能 8 项全 PASS** |
| F3 | 服务端未设 `MINERU_API_KEY` 时**鉴权完全关闭** | `api_server.py` 鉴权中间件：`if not api_key: return await call_next(request)` | 客户端仍总是带 `Authorization: Bearer`（幂等无害）；但需在文档中说明 |
| F4 | `output_formats` 只给 `{docx}` 或 `{html}` 时服务端返回**裸文件**，其余返回 ZIP | `mineru/parser/task_outputs.py:build_task_output()` | 下载分支必须双判（请求格式 + 内容魔数），不能只按 ZIP 解包 |
| F5 | `--tier` **只对 PDF/图片生效**，Office 恒定走 flash 档 | 服务端按输入类型分派 | 路由策略不能对 docx/xlsx/pptx 承诺高保真；需在工具 metadata 里如实标注实际档位 |
| F6 | 响应体用 `.model_dump(exclude_none=True)` | `mineru/tasks/http.py` | 所有字段必须 `.get()` 读取，禁止 `d["x"]` |
| F7 | 实际模型是 `MinerU2.5-Pro-2605-1.2B` | `MANIFEST.env` + 离线包 models 目录 | §154 写的 `MinerU2.5-2509-1.2B` 是漂移，需校正 |
| F8 | `mineru[full]>=4.1,<4.2`（不是 `<5`）；vllm 0.19.1 / torch 2.10.0；Python 3.12.16 便携版 | `MANIFEST.env` | 版本锁定口径需校正 |

---

## 3. 涉及文件与模块

### 3.1 新增（后端）

| 文件 | 职责 |
|---|---|
| `backend/domain/document_parse.py` | `ParseRequest` / `ParseResult` / `ParseEngine` Protocol（零外部依赖） |
| `backend/application/document_parse.py` | `DocumentParseService`：路由决策 + 降级 + 缓存协调 |
| `backend/adapters/out/document_parse/__init__.py` | 包出口 |
| `backend/adapters/out/document_parse/mineru_models.py` | MinerU 请求/响应契约 dataclass（不依赖 `mineru` 包） |
| `backend/adapters/out/document_parse/mineru_errors.py` | 错误分类：`MineruAuthError` / `MineruUnavailableError` / `MineruTaskError` / `MineruTimeoutError` |
| `backend/adapters/out/document_parse/mineru_client.py` | `MineruClient`：4 步 `/v1/tasks` 流程（httpx AsyncClient） |
| `backend/adapters/out/document_parse/local_engine.py` | `LocalEngine`：双路径 —— 内存字节（聊天附件，走 `attachment_pdf.py`）/ 文件路径（工具与 Office 管线，走 `backend/office/pdf.py:read_pdf`，含 `find_tables` 表格抽取） |
| `backend/adapters/out/document_parse/quality.py` | 本地质量评分（纯启发式，零 LLM 成本） |
| `backend/services/document_parse/__init__.py` | 子系统出口 |
| `backend/services/document_parse/config.py` | `MineruConfig` + `load_mineru_config()`（对齐 `backend/services/ocr/config.py`） |
| `backend/services/document_parse/cache.py` | 内容哈希缓存读写（sqlite） |
| `backend/services/document_parse/queue.py` | 后台 MinerU 任务队列（对齐 `backend/memory/async_extractor.py` 的 worker 模式） |
| `backend/tools/parse_document_tool.py` | `ParseDocumentTool(BaseTool)`（对齐 `backend/tools/ocr_image_tool.py`） |

### 3.2 修改（后端）

| 文件 | 改动 |
|---|---|
| `backend/data/settings_repo.py` | `KEYS` 白名单新增 `"mineru_service"` |
| `backend/services/secret_box.py` | 新增 `wrap_mineru_service_json()` / `unwrap_mineru_service_json()`（字段 `apiKey` → account `mineru:api_key`） |
| `backend/data/database.py` | `init_db()` 新增 `document_parse_cache` 表 |
| `backend/tools/__init__.py` | `_LAZY_TOOL_EXPORTS` 新增 `ParseDocumentTool` |
| `backend/tools/tool_bundles.py` | `_install_*` 注册新工具 |
| `backend/api/chat_attachment_routes.py` | PDF 分支接子系统双阶段策略 |
| `backend/api/mineru_routes.py`（新建） | `GET /api/v1/mineru/status` |
| `backend/main.py` | 挂载新路由 |

### 3.3 新增/修改（前端）

| 文件 | 改动 |
|---|---|
| `src/pages/settings/MineruServiceCard.tsx`（新建） | 设置卡片（对齐 `LocalOcrCard.tsx`） |
| `src/shared/api/mineruApi.ts`（新建） | `MineruStatus` / `MineruServiceConfig` 类型 + 请求函数（对齐 `src/shared/api/ocrApi.ts`） |
| `src/pages/settings/ModelsTab.tsx`（改） | 在既有 `<LocalOcrCard />`（第 206 行）旁挂载 `<MineruServiceCard />` |
| `src/pages/settings/__tests__/MineruServiceCard.test.tsx`（新建） | vitest 用例 |

### 3.4 离线包与文档

| 文件 | 改动 |
|---|---|
| `scripts/mineru-offline-bundle/build-bundle.sh`（新建） | 回填打包脚本（可复现） |
| `scripts/mineru-offline-bundle/verify.sh`（改） | 第 6 项改探真需鉴权端点 |
| `docs/technical/154-mineru-deployment.md`（改） | 校正 8 处漂移 |
| `docs/technical/157-mineru-deployment.md`（win7 改） | 同上 |
| `docs/technical/160-mineru-document-parse-subsystem.md`（新建） | 本设计的归档版（实现完成后并入技术手册） |

---

## 4. 技术方案

### 4.1 总体架构

```
┌─────────────────────────────────────────────────────────────┐
│ 消费方                                                        │
│  · parse_document 工具 (agent 主动调用)                      │
│  · 聊天附件路由 (双阶段)                                       │
│  · (后续) 文献调研 M1/M2 管线 —— 本轮只留接口                  │
└───────────────┬─────────────────────────────────────────────┘
                │  统一入口 DocumentParseService.parse(request)
                ▼
┌─────────────────────────────────────────────────────────────┐
│  backend/application/document_parse.py                       │
│  · 引擎可用性判定（配置 + 熔断状态）                            │
│  · 质量门控路由（auto 模式）                                    │
│  · 缓存查/写（sha256 → 产物）                                  │
│  · 降级（MinerU 故障 → 本地）                                   │
└────────┬──────────────────────────────┬────────────────────┘
         │ ParseEngine Protocol          │ ParseEngine Protocol
         ▼                               ▼
┌─────────────────────┐        ┌────────────────────────────┐
│ LocalEngine         │        │ MinerUEngine               │
│ · attachment_pdf    │        │ · MineruClient (httpx)      │
│ · Office 抽取器      │        │ · 4 步 /v1/tasks 协议        │
│ · quality.py 评分    │        │ · py38 兼容                 │
└─────────────────────┘        └────────────┬───────────────┘
                                            │ HTTP
                                            ▼
                                  内网 MinerU api-server
                                  (systemd, --tier standard)
```

**分层约束**：import-linter 契约 `backend.api → backend.adapters → backend.application → backend.ports → backend.domain`。本设计新增代码遵守该方向；`backend/services/` 不在契约内（legacy 自由区），配置与缓存放这里与 `services/ocr/config.py` 对称。

**零新增依赖**：`httpx==0.26.0` 在 `backend/requirements.txt` 与 `backend/requirements-py38.txt` 中均已钉死，无需改依赖清单。

### 4.2 领域契约（`backend/domain/document_parse.py`）

```python
class ParseEngine(Protocol):
    name: str
    async def parse(self, req: ParseRequest) -> ParseResult: ...
    async def health(self) -> EngineHealth: ...
```

- `ParseRequest`：`source_path` / `media_id` / `filename` / `content_bytes` / `engine_hint`（`auto|local|mineru`）/ `output_format`（`markdown|structured|docx|html`）/ `page_range` / `tier` / `timeout_seconds`
- `ParseResult`：`text` / `structured`（dict，可选）/ `engine_used` / `tier_used` / `quality_score` / `duration_ms` / `cached` / `warnings`（list）
- `EngineHealth`：`available` / `detail` / `server_tiers` / `server_version`

纯 dataclass，零外部依赖，不 import httpx / fastapi。

### 4.3 MinerU 客户端契约（已按 F1–F8 核对）

**四步流程**：

| 步 | 请求 | 关键约束 |
|---|---|---|
| 1 | `POST {base}/v1/tasks` | 头 `Authorization: Bearer <key>`；**body 必须 JSON**（服务端拒绝任何 query 参数，返回 400）；`Content-Type: application/json` 否则 415；`files[].bytes` 必填；`file_name` 禁 `/ \ :`、Cc 控制字符、`.` / `..`，长度 1–1024 |
| 2 | `PUT {upload.url}` | 使用响应给出的 `upload.headers`；body 为原始字节 |
| 3 | `GET {base}/v1/tasks/{task_id}` | 轮询；`status` ∈ `waiting-file / pending / running / completed / partial / failed / canceled`；`files[].status` 同集合 |
| 4 | `GET {base}/v1/files/{file_id}/content` | `result_url` 即此路径。`default` → ZIP；`{docx}`/`{html}` → 裸文件 |

**实现约束**：

1. **字段读取**：一律 `.get()`（F6）。`files[].upload` 存在才需 PUT；`files[].result_url` 存在才需下载。
2. **轮询预算**：间隔 1s（对齐官方 client `_POLL_INTERVAL_SECONDS = 1`），最大轮数 = `timeout_seconds`。超时 → 先 `POST /v1/tasks/{task_id}/cancel`（5s 超时），再抛 `MineruTimeoutError`。
3. **重试**：仅连接错误 + HTTP {408, 429, 500, 502, 503, 504}，指数退避 0.25 → 2.0s，最多 3 次。**创建任务不重试**（无幂等保证，重试会产生孤儿任务）。
4. **URL 处理**：`baseUrl` 保留反代路径前缀（`http://host/mineru`）；`task_id` / `file_id` 用 `quote(x, safe='')` 编码。
5. **上传上限**：沿用 Sage 现有 `MAX_ATTACHMENT_SIZE = 25 MB`（`backend/api/chat_attachment_routes.py:85`），配置项 `maxUploadMb` 可下调。
6. **鉴权**：客户端总是带 `Authorization: Bearer`。服务端若未设 key（F3）则忽略之 —— 行为一致，无需分支。
7. **产物解包**：ZIP → 找 `markdown.md` / `middle_json.json` / `structured_content.json`（`middle-json` 候选名兼容 `layout.json`）；裸文件 → 直接按扩展名判定。ZIP 内 `images/` 目录落 MediaStore。
8. **py38 兼容**：不用 `X | Y` 运行时注解、不用 `asyncio.to_thread`、不用泛型下标；`isinstance` 用 tuple 形式（`# noqa: UP038`）。

**错误映射**：

| HTTP / 情况 | 异常 | 降级行为 |
|---|---|---|
| 401 / 403 | `MineruAuthError` | 不重试；标记服务为"鉴权失败"，后续 auto 路由直接走本地 |
| 连接失败 / DNS / 超时（连接层） | `MineruUnavailableError` | 重试 3 次后降级本地 |
| 415 / 400 | `MineruTaskError` | 不重试，降级本地（记录原始错误体） |
| 任务 `status == failed` / `canceled` | `MineruTaskError` | 降级本地，metadata 记 `mineru_failed` |
| 轮询预算耗尽 | `MineruTimeoutError` | 先 cancel 再降级本地 |
| 5xx（任务已创建） | `MineruUnavailableError` | 不重试创建，轮询阶段重试 |

### 4.4 路由策略与质量评分（优化核心）

**本地能力的真实边界**（决定 MinerU 的增量价值）：

| 能力 | 聊天附件路径（内存字节） | Office 管线（文件路径） | MinerU |
|---|---|---|---|
| 逐页文本 | ✅ `attachment_pdf.py` | ✅ `office/pdf.py:read_pdf` | ✅ |
| 扫描页 OCR 兜底 | ✅ | ✅（需 `SAGE_OCR=1`） | ✅ 内建 |
| 表格结构 | ❌ **无** | ⚠️ 仅**文本层有框线**的表格（PyMuPDF `find_tables`）；扫描件无表格 | ✅ 完整结构还原 |
| 公式 | ❌ **无** | ❌ 无 | ✅ LaTeX |
| 版面 / 标题分级 | ❌ 无 | ❌ 无 | ✅ |

→ MinerU 的**增量**正是表格 / 公式 / 版式三项；文本层两者都能出。

**质量评分**（`backend/adapters/out/document_parse/quality.py`，纯启发式、零 LLM 成本、本地计算）：

所有信号都是**扣分项** —— 命中即代表"本地抽取缺少对应能力或不可靠"，分数越低越该交给 MinerU：

```python
score = 1.0
score -= 0.35 if text_per_page < 120        else 0   # 疑似扫描件 / 纯图 PDF
score -= 0.30 if blank_page_ratio > 0.5      else 0   # 近空白页过半
score -= 0.25 if has_table                   else 0   # 本地不还原表格结构
score -= 0.20 if has_formula                 else 0   # 本地不识别公式
score = max(0.0, score)                              # 0.0 ~ 1.0
```

| 信号 | 探测方式 |
|---|---|
| `text_per_page` | 逐页字符数的中位数（`PdfPageText.text` 长度） |
| `blank_page_ratio` | 去空白后字符数 < 20 的页数占比 |
| `has_table` | PyMuPDF `page.find_tables()` 有结果，或正文含连续 `\|` 分隔行 ≥ 2 行（对内存字节同样适用：PyMuPDF 支持 `stream=` 打开） |
| `has_formula` | 正文含 `∑ ∫ √ ≈ ±` 或 `$...$` LaTeX 片段 |

**判定规则**：`quality_score < minQualityThreshold` → 升级 MinerU。默认阈值 **0.85**，对应行为：

| 情形 | score | 是否升级 |
|---|---|---|
| 纯文本 PDF | 1.00 | 否 → 本地 |
| 含公式的 PDF | 0.80 | **是** |
| 含表格的 PDF | 0.75 | **是** |
| 表格 + 公式 | 0.55 | **是** |
| 扫描件 | 0.35 | **是** |

阈值可配置（`minQualityThreshold`），调高 = 更激进走 MinerU。

**auto 模式路由表**：

| 条件 | 引擎 |
|---|---|
| MinerU 未配置 / 不可达 / 熔断 | 本地（静默降级） |
| `engine_hint == "mineru"` | MinerU（失败则降级本地） |
| `engine_hint == "local"` | 本地（绝不调 MinerU） |
| 输入非 PDF（docx/xlsx/pptx） | 本地（F5：Office 恒走 flash，MinerU 对 Office 增益有限） |
| `quality_score < minQualityThreshold` | MinerU |
| 其余 | 本地（秒级、零 GPU 成本） |

**降级矩阵**：

| 场景 | 行为 |
|---|---|
| 未配置 MinerU | 走本地；工具 metadata 标 `engine_used="local"`, `warnings=["mineru_not_configured"]` |
| MinerU 不可达（连接层） | 走本地；`warnings=["mineru_unavailable"]`；连续失败 3 次后进入 10 分钟熔断 |
| MinerU 鉴权失败 | 走本地；`warnings=["mineru_auth_failed"]`；直接进入熔断（配错 key 重试无意义） |
| MinerU 任务失败 / 超时 | 走本地；`warnings=["mineru_failed"]` |
| 本地抽取也失败 | 抛原始异常（此时是真的无法解析） |

**为什么是互补而非替换**：本地能出**文本层**，但出不了**表格结构 / 公式 / 版式层级**（聊天附件路径连文本层表格都没有）。MinerU 补的正是这三项。质量门控保证纯文本 PDF 这类文档仍走秒级本地路径，不占用 GPU。

### 4.5 内容哈希缓存（优化杠杆）

- **键**：`sha256(文件字节)`（不含文件名，避免同名不同内容误命中）。
- **存储**：sqlite 新表 `document_parse_cache`：

```sql
CREATE TABLE IF NOT EXISTS document_parse_cache (
    content_hash   TEXT NOT NULL,
    engine         TEXT NOT NULL,        -- local | mineru
    tier           TEXT,                 -- mineru 实际档位
    markdown       TEXT,                 -- 产物：Markdown 正文
    structured_json TEXT,                -- 产物：结构化 JSON（仅 mineru）
    images_dir     TEXT,                 -- 产物：图片目录（仅 mineru）
    meta_json      TEXT,                 -- 页数 / 耗时 / quality_score / warnings
    created_at     INTEGER NOT NULL,     -- epoch 毫秒
    PRIMARY KEY (content_hash, engine)
);
```

> 复合主键 `(content_hash, engine)`：同一内容可同时有 `local` 与 `mineru` 两条记录，互不顶替。

- **命中规则**：以 `(content_hash, engine)` 直接查表命中。
- **产物字段选择**：`output_format="markdown"` → 取 `markdown` 字段；`output_format="structured"` → 取 `structured_json` 字段。两者同属一条 MinerU 缓存条目（一次解析同时产出），因此 `format` **不参与**命中判断，只决定取哪段。
- **失效**：内容哈希天然失效；`tier` 变更不影响复用（tier 只影响解析质量，不影响产物格式）；`engine` 变更则落到另一条条目。
- **为什么是最强杠杆**：MinerU 是分钟级。同一篇论文被多轮对话、多个会话、文献调研管线反复引用时，**只解析一次**。

### 4.6 后台任务队列（双阶段附件策略）

对齐 `backend/memory/async_extractor.py` 的 `MemoryExtractionQueue` 模式（`asyncio.create_task` worker + 队列）。

- `backend/services/document_parse/queue.py`：
  - `MineruBackgroundQueue`：单 worker `asyncio.create_task` 消费；`submit(content_bytes, filename, tier, page_range) -> task_key`；同 `content_hash` 已在队列/在跑 → 直接返回既有 task_key（去重）。
  - 完成后写缓存；失败写一条失败记录（不缓存失败产物，避免污染）。
  - 提供 `get_status(task_key)` 供前端查询。

### 4.7 工具

```python
class ParseDocumentTool(BaseTool):
    requires_tool_context = True
    risk = RiskClass.READ
    is_blocking = True

    def execute(
        self,
        path: Optional[str] = None,
        media_id: Optional[str] = None,
        engine: str = "auto",              # auto | local | mineru
        output_format: str = "markdown",   # markdown | structured | docx | html
        pages: Optional[str] = None,       # "1-5,8"
        tier: Optional[str] = None,        # flash | basic | standard | advanced
    ) -> ToolResult
```

- **命名为 `parse_document` 而非 `mineru_parse_document`**：MinerU 是实现细节，将来换引擎不改工具名、不改既有 prompt。
- **schema 保持恒定**：未配置 MinerU 时工具依然出现在 schema 里（`engine="auto"` 退本地），避免"工具时有时无"破坏 prompt 稳定性。与 `OcrEngine.available()` 的能力位哲学一致，但降级发生在运行时而非 schema 层，并在 metadata 中如实标注。
- **metadata**：`{engine_used, tier_used, quality_score, cached, duration_ms, pages_parsed, warnings}`。
- **阻塞语义**：`is_blocking = True`（对齐 `ocr_image_tool.py`）。auto 模式命中本地时秒级返回；命中 MinerU 时分钟级（工具层可接受，与附件路径不同）。
- **风险**：`RiskClass.READ` —— 只读外部文件与远程解析，不写用户数据。但 MinerU 会把文档**上传到内网服务器**，这属于数据出本地进程，需在工具 description 中明示，避免用户误用敏感文件。

### 4.8 配置与密钥

**存储位置**：preferences 独立 KV `mineru_service`（**不进 `app_settings.endpoints`** —— MinerU 不是 OpenAI 兼容模型端点，塞进去会造成语义混淆，且会污染 `AICapability.load_config()` 的模型路由）。

**配置形状**：

```json
{
  "enabled": true,
  "baseUrl": "http://10.x.x.x:8000",
  "apiKey": "<64-hex>",
  "defaultTier": "standard",
  "timeoutSeconds": 300,
  "maxUploadMb": 25,
  "useInChatAttachment": true,
  "minQualityThreshold": 0.85
}
```

**读取优先级**（`load_mineru_config()`，对齐 `load_ocr_config()` 的三段式）：

1. 环境变量 `SAGE_MINERU_BASE_URL` / `SAGE_MINERU_API_KEY` / `SAGE_MINERU_TIER` / `SAGE_MINERU_TIMEOUT_SECONDS`（**最高优先级**，便于 CI 与离线环境统一注入）
2. preferences `mineru_service`（读侧自动解密）
3. 兜底默认值（`enabled=False`, `baseUrl=""`, `apiKey=""`）

**任何读取失败都回退默认值，不抛异常，不阻塞主流程。**

**密钥静态加密**：`backend/services/secret_box.py` 新增：

```python
_MINERU_KEY_FIELDS = [("apiKey", "mineru:api_key")]

def wrap_mineru_service_json(raw: str | None) -> str | None: ...
def unwrap_mineru_service_json(raw: str | None) -> str | None: ...
```

完全照抄 `wrap_search_config_json` / `unwrap_search_config_json` 的语义：解析失败 fail-open 原样返回；已是 `enc:` 前缀跳过（幂等）；单字段解密失败置空串（按"未配置"处理，不投毒）。`backend/data/settings_repo.py` 的 `get()` / `set()` 中按 `search_config` 的写法接入。

### 4.9 状态端点与设置 UI

**`GET /api/v1/mineru/status`**：

```json
{
  "configured": true,
  "enabled": true,
  "hasApiKey": true,
  "reachable": true,
  "serverTiers": ["flash", "basic", "standard"],
  "serverVersion": "4.1.7",
  "reason": null
}
```

- `hasApiKey` 只回布尔，**不回明文**（对齐项目既有"设置脱敏"口径）。
- `reachable` 探测打 `/v1/health`（免鉴权，F2）+ `/v1/tiers`；鉴权是否正确由客户端在真实调用时判定（免鉴权端点无法区分）。

**`MineruServiceCard.tsx`**：启用开关 / baseUrl 输入 / apiKey 密码框（带"显示"切换）/ 档位下拉（flash|basic|standard|advanced，默认 standard）/ 超时秒数 / 「测试连接」按钮（打 status 端点并展示 `serverTiers` 与 `reason`）。

### 4.10 聊天附件双阶段策略（用户已确认）

现有契约：`backend/api/chat_attachment_routes.py:87` `MAX_ATTACHMENT_PARSE_SECONDS = 30.0`，硬超时。

**新流程（PDF 分支）**：

```
收到 PDF 附件
  │
  ├─ 阶段 1（同步，≤30s，现有契约不变）
  │    · LocalEngine 抽取 → render_page_marked_text()（保持既有输出格式与页标记）
  │    · 计算 quality_score
  │    · 立即注入对话 → 首轮体验与现在完全一致
  │
  └─ 阶段 2（后台 fire-and-forget，仅当 score < 阈值 且 useInChatAttachment 且 MinerU 可用）
       · 提交 MineruBackgroundQueue（按 content_hash 去重）
       · 完成后写缓存
       · 后续轮次 / parse_document 工具 / 其它子系统命中缓存 → 高保真产物
```

- **降级**：阶段 2 失败不影响阶段 1 的结果，只在附件 metadata 里记 `mineru_pending` / `mineru_failed`。
- **非 PDF**：docx/xlsx/pptx 保持现状（且 F5 明确 Office 恒走 flash，MinerU 对 Office 增益有限）。
- **后台任务不阻塞响应**：`asyncio.create_task` + 队列 worker，异常全部捕获吞掉（记 warnings），**不得冒泡影响聊天链路**。

### 4.11 与后续子系统的接口预留

`ParseResult.structured` 暴露 MinerU 的 `structured_content.json`（标题层级 / 段落 / 表格 / 公式 / 图片）。本轮**不**接到文献调研 M1/M2 管线，但接口就位：后续管线只需在 `DocumentParseService` 处按引擎产出选 `structured` 而非 `markdown` 即可。

---

## 5. 实施步骤（里程碑）

里程碑分**两条轨道**，每条轨道独立成一份实现计划（`superpowers:writing-plans` 各出一个 plan）：

- **轨道 A —— Sage 侧解析子系统**（M0–M7）：本需求的**主要交付物**。
- **轨道 B —— 离线包修复与发布**（M8–M10）：依赖轨道 A 落地，且 M10 依赖 A 已合并到 main。

每个里程碑独立可验证、可单独提交。

### 轨道 A：Sage 侧解析子系统

- [ ] **M0 设计文档落地**（本文件）+ feature 分支创建
- [ ] **M1 领域契约与 MinerU 客户端**
  - `backend/domain/document_parse.py`
  - `backend/adapters/out/document_parse/{mineru_models,mineru_errors,mineru_client}.py`
  - 单测：`httpx.MockTransport` 覆盖 4 步全链路、401、415、任务 failed、轮询超时+取消、`exclude_none` 字段缺失、非法文件名、baseUrl 带路径前缀、连接错误重试退避、创建任务不重试
  - 验收：`pytest backend/tests/unit/test_mineru_client.py` 全绿；py38 兼容检查通过
- [ ] **M2 配置与密钥**
  - `backend/services/document_parse/config.py`（`MineruConfig` + `load_mineru_config()`）
  - `backend/services/secret_box.py` 加 `wrap/unwrap_mineru_service_json`
  - `backend/data/settings_repo.py` KEYS 白名单 + 加解密接入
  - 单测：preferences 读取、env 覆盖优先级、加密往返、单字段解密失败置空、读取异常回退默认值
- [ ] **M3 LocalEngine + 质量评分 + DocumentParseService 路由**
  - `backend/adapters/out/document_parse/{quality,local_engine}.py`
  - `backend/application/document_parse.py`
  - 单测：质量评分四信号扣分与阈值判定、auto 路由各分支、非 PDF 输入走本地、MinerU 不可达降级本地、显式 `engine=local` 绝不调 MinerU
- [ ] **M4 缓存 + 后台队列**
  - `backend/data/database.py` 建 `document_parse_cache` 表
  - `backend/services/document_parse/{cache,queue}.py`
  - 单测：同内容二次命中 / 不同内容不命中 / local 与 mineru 两条独立条目 / 队列同 hash 去重 / 失败产物不入缓存
- [ ] **M5 工具注册**
  - `backend/tools/parse_document_tool.py` + `__init__.py` `_LAZY_TOOL_EXPORTS` + `tool_bundles.py`
  - 单测：schema 生成、execute 各 engine 分支、metadata 字段完整
- [ ] **M6 聊天附件双阶段接入**
  - `backend/api/chat_attachment_routes.py` PDF 分支改造
  - 单测：阶段 1 输出与改造前一致；阶段 2 在低质量时提交；阶段 2 失败不影响阶段 1；阶段 1 仍受 30s 约束
- [ ] **M7 状态端点 + 设置 UI**
  - `backend/api/mineru_routes.py` + `backend/main.py` 挂载
  - `src/shared/api/mineruApi.ts` + `src/pages/settings/MineruServiceCard.tsx` + `ModelsTab.tsx` 挂载
  - 单测（vitest）：卡片渲染、apiKey 掩码、「测试连接」成功/失败态

### 轨道 B：离线包修复、验证与双分支发布

- [ ] **M8 离线包侧修复**
  - `scripts/mineru-offline-bundle/verify.sh` 第 6 项改探需鉴权端点
  - `scripts/mineru-offline-bundle/build-bundle.sh` 回填（按 MANIFEST 反推：wheel 闭包 + portable python + 模型 + 模板渲染 + sha256 落盘）
  - `docs/technical/154-mineru-deployment.md`（main）/ `157`（win7）校正 8 处漂移
- [ ] **M9 真机 E2E 验证**（轨道 A 合并后进行）
  - 用内网真实服务器：baseUrl + API key 走 `.env.local`（**不贴进聊天/日志**）
  - 用一份含公式 + 跨页表格的 PDF：断言 markdown 含表格与公式、`structured_content.json` 可解析、缓存二次命中
  - 断网 / 改错 key：断言降级本地且不阻塞
- [ ] **M10 双分支同步**（轨道 A 合并到 main 后进行）
  - main 合并后 cherry-pick 到 `release/win7`，做 py38 适配（`X | Y` 注解、`asyncio.to_thread`、泛型下标、`isinstance` tuple 形式）
  - win7 侧跑 `scripts/check_py38_compat.py` + py38 单测

---

## 6. 测试策略

| 层 | 内容 | 工具 |
|---|---|---|
| 单元（后端） | MinerU 客户端 4 步协议全分支、路由决策、缓存、配置、加密往返、队列去重 | pytest + `httpx.MockTransport` |
| 单元（前端） | `MineruServiceCard` 渲染 / apiKey 掩码 / 测试连接成功失败 | vitest |
| 集成 | 聊天附件双阶段；工具注册后 schema 可见性 | pytest |
| E2E（真机） | 真实内网 MinerU：含公式+跨页表格 PDF → markdown 含表格与公式；`structured_content.json` 可解析；缓存二次命中；服务端不可达降级 | pytest + 手工 |
| 兼容 | py38 语法/API 兼容 | `scripts/check_py38_compat.py`（win7 分支） |
| 回归 | 既有 PDF / Office 抽取测试不得回归（阶段 1 输出须与改造前逐字一致） | pytest |

覆盖率目标：新代码 ≥ 80%（对齐项目 `testing.md` 规范）。

---

## 7. 风险评估与依赖

| 风险 | 等级 | 缓解 |
|---|---|---|
| MinerU 服务端版本与客户端契约漂移（4.1.x 破坏性协议） | 中 | 客户端与服务端同锁 `>=4.1,<4.2`；响应全字段用 `.get()`（F6）；契约变化表现为"字段缺失"而非崩溃 |
| 内网服务器不可达 / 掉线 | 中 | 质量门控 + 三级降级（§4.4）+ 熔断；聊天首轮永远不依赖 MinerU |
| API key 泄露 | 中 | SecretBox 静态加密（DPAPI/keychain/secret-tool）；`.env.local` gitignore；日志与聊天中不出现明文；status 端点只回 `hasApiKey` |
| MinerU 分钟级延迟拖垮聊天 | 中 | 双阶段：阶段 1 本地秒级；MinerU 只在后台跑 |
| 文档内容上传到内网服务器 | 中 | 工具 description 明示；配置提供 `enabled` 总开关；内网部署本身是既定事实，但需用户知情 |
| GPU 资源争抢（多客户端共享） | 低 | 内容哈希缓存减少重复解析；tier 可下调；熔断避免持续打不通时反复重试 |
| py38 兼容踩坑 | 低 | 里程碑 M1 就跑兼容检查，不留到最后 |
| 既有 PDF/Office 抽取回归 | 低 | M6 单测要求阶段 1 输出与改造前逐字一致 |
| 离线包不可复现 | 中 | M8 回填 `build-bundle.sh` |

**依赖**：
- 内网 MinerU 服务器可达（用户已确认可达，可提供 baseUrl + API key）。
- 用户提供一份含公式 / 跨页表格的测试 PDF（M9）。
- 无新增 Python / Node 依赖。

---

## 8. 错误处理总则

1. **不静默吞错**：每个降级路径都写 `warnings`（进 `ParseResult` / 工具 metadata），前端与日志可见。
2. **不阻塞主流程**：MinerU 相关失败一律降级，绝不让聊天/附件链路失败。
3. **不越权**：本地抽取成功时**不**自动上传文档到内网服务器 —— 只有"质量不足 + 配置开启 + 策略允许"三者同时满足才走 MinerU。
4. **不泄漏**：异常消息与日志中不得出现 apiKey。

---

## 9. 验收标准

- [ ] 配置 baseUrl + API key 后，`parse_document` 工具在 `engine="mineru"` 下能返回含表格与公式的 markdown。
- [ ] 未配置 MinerU 时，`parse_document(engine="auto")` 走本地并正常返回，其余功能不受影响。
- [ ] 质量门控生效：纯文本 PDF 走本地（`engine_used="local"`）；含公式或表格的 PDF 升级 MinerU（`engine_used="mineru"`）。
- [ ] 聊天附件 PDF：首轮输出与改造前一致（本地）；低质量文档后台提交 MinerU 并在缓存中留下产物。
- [ ] 同一文档第二次解析命中缓存（`cached=true`，耗时 < 100ms）。
- [ ] 服务端不可达 / key 错误时，聊天链路不报错，工具返回本地结果 + 明确 warning。
- [ ] `GET /api/v1/mineru/status` 返回配置状态与连通性，**不含明文 key**。
- [ ] `verify.sh` 8 项全部 PASS（修好第 6 项后）。
- [ ] main 与 release/win7 双分支均通过各自 CI。

---

## 10. 后续（本轮不做，留接口）

1. 文献调研 M1/M2 管线改吃 `structured_content.json`。
2. 多 GPU / `mineru-router` 接入（baseUrl 指向 router 即可，客户端零改动）。
3. MinerU 作为 remote-MCP 暴露（若 MinerU 官方后续提供 MCP 实现）。
4. 解析产物的会话级引用（把缓存产物挂到消息上下文）。

---

## 11. §154 / §157 文档校正清单（M8 执行）

| # | 现文档写法 | 校正为 |
|---|---|---|
| 1 | `mineru[full]>=4.1,<5` | `mineru[full]>=4.1,<4.2` |
| 2 | `uv venv --python 3.12` | 便携 CPython（python-build-standalone 3.12.16）→ `/opt/mineru/python` + `python -m venv --copies /opt/mineru/.venv` + `pip install --no-index --find-links wheels` |
| 3 | 模型 `MinerU2.5-2509-1.2B` | `MinerU2.5-Pro-2605-1.2B` |
| 4 | 未提 vllm 版本 | vllm 0.19.1 / torch 2.10.0；驱动 ≥ 535 |
| 5 | 未提 offline env | `MINERU_MODEL_SOURCE=local`、`MINERU_TELEMETRY_DISABLED=1`、`HF_HUB_OFFLINE=1`、`TRANSFORMERS_OFFLINE=1` |
| 6 | 未提 install/verify 脚本 | `install.sh`（建 `mineru` 系统用户、`/etc/mineru/mineru.env` chmod 600、systemd unit、300s 健康轮询）+ `verify.sh` |
| 7 | §5.1 API 契约 | 补 `exclude_none` 语义、`file_name` 校验规则、query 参数被拒、`{docx}`/`{html}` 返回裸文件、`/v1/health`+`/v1/models`+`/v1/tiers` 免鉴权、无 key 时鉴权完全关闭 |
| 8 | 工具名 `mineru_parse_document` | `parse_document`（engine 参数区分） |

---

## 12. 双分支同步计划

| 项 | main | release/win7 |
|---|---|---|
| Python | 3.10 | 3.8 |
| 依赖 | `backend/requirements.txt` | `backend/requirements-py38.txt`（**不互改**） |
| 新增依赖 | 无（httpx 0.26.0 已有） | 无 |
| 代码差异 | 基准 | py38 适配：`X \| Y` → `Optional[X]`/`Union[X, Y]`；不用 `asyncio.to_thread`（用 `run_in_executor`）；不用泛型下标；`isinstance` tuple 形式（`# noqa: UP038`） |
| 文档 | §154 → 校正 + 新增 §160 | §157 → 校正（不改 §160 编号，避免双分支编号冲突） |
| 同步方式 | — | **cherry-pick**（严禁 merge；严禁删分支） |

**顺序**：main 全绿并合并 → cherry-pick 到 win7 → py38 适配 → win7 CI 绿。
