# LLM 调用诊断包导出

> 面向开发者的技术 reference。用户操作指南见 `docs/user-manual/15-diagnostic-export.md`。

## 用途

Sage 现场用户(尤其内网 Win7 无法远程调试)遇到 LLM 调用异常时,可一键导出
最近 50 次调用的详细信息为 zip,供支持人员离线分析。

**核心场景**: 用户配错上游 URL 或 API key → 上游返 401/403 → 导出诊断包 → 支持人员从 zip 中 `upstream_url` 字段确认 URL 是否配错。

## 架构概览

```
Electron tray / Settings UI
        │ IPC: diagnostic:export-bundle
        ▼
Backend POST /api/v1/diagnostic/export
        │
        ▼
LlmTraceRecorder (ring buffer, maxlen=50)
        │ TraceRecord list
        ▼
Exporter → zip (manifest + system + config + trace + README)
        │
        ▼
Electron: fs.writeFile → shell.showItemInFolder
```

**数据流**:
- `llm_proxy_routes.py` 旁路 tee → `LlmTraceRecorder.append(TraceRecord)`
- Recorder 进程级内存 ring buffer(`deque(maxlen=50)`),**不**持久化
- Export 时双层脱敏: recorder 第一遍(headers/URL),exporter 第二遍(body)

## 触发入口

| 入口 | 场景 | 特点 |
|---|---|---|
| 托盘菜单 → "导出诊断包…" | 主要入口 | 无 preview,直接 save dialog |
| 设置 → 高级 → 诊断卡片 | 辅助入口 | 带 preview(count / 时间范围 / 样本 URL),可选 prompt / hostname |

## zip 内容

```
diagnostic-<app-version>-<timestamp>.zip
├── manifest.json   schema 版本 / app 版本 / redactor 版本 / trace 数
├── system.json     OS / Python / Electron / app 版本 / (可选)hostname
├── config.yaml     Sage 配置快照(secrets 已脱敏)
├── trace.jsonl     每行一条 TraceRecord(JSON Lines)
└── README.txt      给支持人员的人读说明
```

## TraceRecord 字段

详见 spec §4.2。关键字段:

| 字段 | 用途 |
|---|---|
| `upstream_url` | 实际转发的上游 URL — 诊断 URL 配错的关键信息 |
| `upstream_method` | HTTP 方法(POST / GET) |
| `request_headers` | 发给上游的 headers(已脱敏 Authorization) |
| `request_body` | 请求 body(可能被截断,见容量限制) |
| `response.status` | 上游 HTTP 状态码 |
| `response.headers` | 上游响应 headers |
| `response.body` | 上游响应 body |
| `response.error` | 上游 error.message(若有,从 body 解析) |
| `duration_ms` | 耗时毫秒 |
| `error_class` | 错误分类: `upstream_401` / `upstream_403` / `tls_failed` / `timeout` / 空串(成功) |

## 脱敏规则

10 类 pattern 全覆盖,详见 spec §4.5:

| # | Pattern | 示例 |
|---|---|---|
| 1 | Bearer token | `Authorization: Bearer sk-xxx` → `Bearer ***REDACTED***` |
| 2 | JWT | `ey...` 格式 |
| 3 | API key 通用 | `api_key=xxx` / `apikey=xxx` |
| 4 | password | `password=xxx` |
| 5 | cookie | `Cookie: session=xxx` |
| 6 | Basic auth | `Basic xxx` |
| 7 | OpenAI-style | `sk-xxx` / `sk-proj-xxx` |
| 8 | JSON 敏感字段名 | `{"token": "xxx"}` → `{"token": "***REDACTED***"}` |
| 9 | X-Sage-Local-Authorization | 本地 auth token 强制剥离 |
| 10 | URL 中嵌入的 key | `?api_key=xxx` → `?api_key=***REDACTED***` |

**双层防御**:
- 第一遍: `recorder.append()` 脱敏 headers + URL
- 第二遍: `exporter.export_to_zip_bytes()` 写盘前再脱敏 body
- 兜底: invariant 测试 `test_redactor_invariant_password_never_leaks` 确保 `password=secret123` 输入导出后 `grep -c 'secret123'` 为 0

## 容量与截断

| 限制 | 值 | 行为 |
|---|---|---|
| 单条 body | > 512KB | 截断,尾部追加 `[... truncated N bytes]` |
| 单条 record | > 1MB | 整条 body 丢弃,headers/status 保留 |
| 总 zip | > 5MB | 抛 `ZipTooLargeError` |
| record 数 | 最多 50 | ring buffer `deque(maxlen=50)` 自动丢弃最旧 |

## Electron IPC

```typescript
// preload.ts 暴露
window.electronAPI.diagnostic = {
  preview(): Promise<PreviewResponse>,
  exportBundle(opts?: {
    includePrompts?: boolean,
    includeHostname?: boolean,
  }): Promise<DiagnosticResult>,
}

interface PreviewResponse {
  count: number;
  oldestTs: string | null;
  newestTs: string | null;
  sampleUrls: string[];
  version: string;
}

type DiagnosticResult =
  | { ok: true; path: string }
  | { ok: false; code: string; error: string };
```

错误码:

| code | 含义 |
|---|---|
| `dialog_cancelled` | 用户取消 save dialog |
| `recorder_empty` | 无记录,无导出内容 |
| `backend_unreachable` | 后端服务未启动 |
| `zip_generation_failed` | 后端生成 zip 异常 |
| `write_failed` | 文件系统写入失败 |

## Backend API

```
GET  /api/v1/diagnostic/preview
     → 200 PreviewResponse
     → 401 本地授权无效

POST /api/v1/diagnostic/export?include_prompts=false&include_hostname=false
     → 200 application/zip (zip bytes)
     → 401 本地授权无效
```

## 前端组件

| 文件 | 职责 |
|---|---|
| `src/features/diagnostic/DiagnosticCard.tsx` | 主卡片: preview + checkbox + export button |
| `src/features/diagnostic/ExportButton.tsx` | 导出按钮,管理 busy state + 错误消息 |
| `src/features/diagnostic/useDiagnosticPreview.ts` | Hook: 自动 fetch preview,支持 refresh |

## Win7 兼容性

- **零新依赖**: 仅 stdlib (`deque` / `zipfile` / `re` / `json` / `io` / `datetime` / `platform`)
- **py38 + pydantic v1 双支持**: `scripts/check_py38_compat.py` 强制 0 违规
- **pydantic v1**: 序列化用 `.dict()` 非 `.model_dump()`;类型注解用 `Optional[X]` 非 `X | None`
- **默认文件名**: `sage-diagnostic-<version>-<timestamp>.zip` 不显眼,降低杀软启发式拦截

## 限制

- **不**自动上传;用户决定怎么外发
- **不**实时持久化;应用重启即清空
- **不**替换 `electron/logger.ts`(互补关系)
- 当前代理层仅在 2xx 成功路径记录 trace;4xx/5xx 错误路径尚未接入自动记录(后续任务)

## 文件清单

```
backend/services/llm_trace/
├── __init__.py         # LlmTraceRecorder 导出
├── recorder.py         # TraceRecord dataclass + LlmTraceRecorder (ring buffer)
├── redactor.py         # 10 类 pattern 脱敏
├── exporter.py         # export_to_zip_bytes()
├── tee.py              # tee_stream() helper
└── tests/
    ├── test_recorder.py
    ├── test_redactor.py
    ├── test_exporter.py
    └── test_tee.py

backend/api/
├── diagnostic_preview.py   # GET /api/v1/diagnostic/preview
└── diagnostic_export.py    # POST /api/v1/diagnostic/export

backend/tests/
├── integration/test_llm_proxy_routes.py   # 含 trace 记录集成测试
└── e2e/test_diagnostic_401_journey.py     # 401 场景 E2E

electron/
├── preload.ts            # contextBridge 暴露 window.electronAPI.diagnostic
├── main.ts               # IPC handler: diagnostic:export-bundle
└── __tests__/
    └── diagnosticIpc.test.ts

src/features/diagnostic/
├── DiagnosticCard.tsx
├── ExportButton.tsx
├── useDiagnosticPreview.ts
└── __tests__/
    ├── DiagnosticCard.test.tsx
    ├── ExportButton.test.tsx
    └── useDiagnosticPreview.test.ts
```
