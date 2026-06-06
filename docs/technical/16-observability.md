# 16. 可观测性（Observability）

**最后更新**：2026-06-06
**阶段**：P3 完工
**适用版本**：Sage 全栈质量优化 v0.1

## 16.1 概述

Sage 后端通过三层可观测性基础设施支撑生产环境：

1. **指标（Metrics）**：9 个核心 Prometheus 指标，通过 `GET /metrics` 暴露
2. **事件（Events）**：5 类用户行为审计事件，写入 `backend/data/audit/audit.jsonl`
3. **追踪（Tracing）**：OpenTelemetry stdlib 集成，span 注入到 ChatService / LLMAdapter

## 16.2 Prometheus 9 个核心指标

所有指标在 `backend/adapters/out/metric/prometheus_adapter.py` 的 `__init__` 中**预注册**，即使未触发也以 `# HELP` 行形式立即出现在 `/metrics` 输出。

### Counter（5 个）

| 指标 | 标签 | 含义 |
|------|------|------|
| `sage_http_requests_total` | route, method, status | HTTP 请求总数（按 route/method/status 分桶） |
| `sage_llm_calls_total` | model, provider, outcome | LLM 调用总数（按 model/provider/outcome） |
| `sage_tool_invocations_total` | tool, outcome | 工具调用总数（按 tool/outcome） |
| `sage_tokens_consumed_total` | model, kind | LLM token 消耗（kind: prompt/completion） |
| `sage_errors_total` | layer, error_type | 错误总数（layer: api/llm/tool/skill） |

### Histogram（3 个）

| 指标 | 标签 | 含义 |
|------|------|------|
| `sage_http_request_duration_seconds` | route | HTTP 请求延迟（秒） |
| `sage_llm_call_duration_seconds` | model | LLM 调用延迟（秒） |
| `sage_react_steps_per_request` | (无标签，buckets=[1,2,3,5,10,20]) | ReAct 循环步数分布 |

### Gauge（1 个）

| 指标 | 标签 | 含义 |
|------|------|------|
| `sage_active_sessions` | (无标签) | 当前活跃 session 数 |

### 接入方式

`GET /metrics` 端点（`backend/api/hex_routes.py`）：

```python
@router.get("/metrics")
def metrics(svc: ChatService = Depends(get_chat_service)) -> Response:
    prom = svc.metrics
    if isinstance(prom, PrometheusMetricAdapter):
        return Response(content=prom.render(), media_type=CONTENT_TYPE_LATEST)
    return Response(content=b"", media_type="text/plain")
```

**约束**：`/metrics` 不需要鉴权（仅本机访问，Tauri localhostOnly 保护）。

### 输出示例

```
# HELP sage_http_requests_total HTTP 请求总数（按 route/method/status 分桶）
# TYPE sage_http_requests_total counter
# HELP sage_llm_calls_total LLM 调用总数（按 model/provider/outcome 分桶）
# TYPE sage_llm_calls_total counter
sage_llm_calls_total{model="default",outcome="success",provider="default"} 42.0
# HELP sage_tokens_consumed_total LLM token 消耗总数
# TYPE sage_tokens_consumed_total counter
...
```

## 16.3 5 类审计事件

`backend/adapters/out/event/file_adapter.py` 定义 `AuditEventType`：

| 事件 | 触发点 | Payload 字段 |
|------|--------|--------------|
| `chat_message_sent` | `ChatService.run_turn()` 入口 | session_id, role |
| `chat_response_completed` | `ChatService.run_turn()` 出口 | session_id |
| `tool_invoked` | `ChatService._execute_tool_calls()` | session_id, tool, args |
| `session_created` | `ChatService.create_session()` | session_id, title |
| `settings_changed` | `PUT /api/v1/settings` | changed_fields (列表) |

### 落盘格式

每行一个 JSON 对象，写入 `backend/data/audit/audit.jsonl`：

```json
{"ts": "2026-06-06T14:23:11.456789+00:00", "type": "chat_message_sent", "payload": {"session_id": "mem-1", "role": "user"}}
{"ts": "2026-06-06T14:23:13.789012+00:00", "type": "chat_response_completed", "payload": {"session_id": "mem-1"}}
{"ts": "2026-06-06T14:23:15.123456+00:00", "type": "tool_invoked", "payload": {"session_id": "mem-1", "tool": "calculator", "args": {"expression": "2+2"}}}
```

**注意**：
- 敏感字段（`api_key` 等）**永不**写入 audit payload
- 审计日志由 P2.5 `SqliteStorageAdapter` 之外的 `FileEventAdapter` 独立管理
- 按日轮转可加 cron 任务（PG3.13 收尾时考虑）

## 16.4 OpenTelemetry 追踪

`backend/utils/otel.py`：

```python
def init_tracing(service_name: str = "sage") -> TracerProvider:
    """初始化全局 TracerProvider（stdout 导出；生产可换 OTLP）。"""
    provider = TracerProvider(resource=Resource.create({"service.name": service_name}))
    provider.add_span_processor(BatchSpanProcessor(ConsoleSpanExporter()))
    trace.set_tracer_provider(provider)
    return provider

def get_tracer(name: str = "sage") -> trace.Tracer:
    return trace.get_tracer(name)
```

### 已注入的 Span

| Span 名 | 位置 | 属性 |
|---------|------|------|
| `chat.run_turn` | `ChatService.run_turn` 入口 | session.id, message.role, has_tool_calls, duration, error |
| `session.create` | `ChatService.create_session` | session.id, title |
| `llm.chat` | `HttpxLLMAdapter.chat` | messages.count, tools.count |

Span 嵌套：`chat.run_turn` ⊃ `llm.chat`（通过 `_run_turn_inner` 内部方法解包）。

### 日志关联

`backend/utils/logging.py::TraceIdFilter` 把当前 span 的 `trace_id` 注入 log record：

```
2026-06-06 14:23:11 [INFO] [trace=4bf92f3577b34da6a3ce929d0e0e4736] chat_service: chat.run_turn started
2026-06-06 14:23:13 [INFO] [trace=4bf92f3577b34da6a3ce929d0e0e4736] chat_service: chat.run_turn completed in 2.3s
```

## 16.5 故障排查指南

### 场景 1：/metrics 端点不返回 9 个指标

```bash
# 1. 检查后端是否启动
curl http://localhost:8765/health

# 2. 检查 adapter 注入
# main.py 中 get_chat_service() 必须返回 PrometheusMetricAdapter（不是 Noop）
# 3. 验证预注册
/home/fz/anaconda3/envs/sage-backend/bin/python -c "
from backend.adapters.out.metric.prometheus_adapter import PrometheusMetricAdapter
from prometheus_client import generate_latest
a = PrometheusMetricAdapter()
print(generate_latest(a.registry).decode())
" | head -20
```

### 场景 2：审计日志不写入

```bash
# 1. 检查目录权限
ls -la backend/data/audit/

# 2. 手动触发
curl -X POST http://localhost:8765/chat \
  -H 'Content-Type: application/json' \
  -d '{"session_id":"debug","message":"hi"}'

# 3. 查看
tail -3 backend/data/audit/audit.jsonl
```

### 场景 3：Span 不可见

OTEL 暂导出到 stdout。生产环境切换 OTLP：

```python
# backend/utils/otel.py 替换 ConsoleSpanExporter
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint="...")))
```

## 16.6 已知遗留

- `sage_tokens_consumed_total` 仅在 `LLMResponse.usage` 字段存在时记录；当前 adapters 暂不透传 usage，P3.x 加 message.usage 字段后即生效
- `sage_active_sessions` 预注册但 ChatService 暂无 create_session 路由暴露（hex_routes 删了 POST /sessions 以避免与 legacy 冲突）；P3.x 单独加路由 + 埋点
- audit.jsonl 无自动轮转（P3.13 收尾考虑加 cron）

## 16.7 验收

- [x] `GET /metrics` 返回 9 个核心指标
- [x] audit.jsonl 记录 5 类事件
- [x] ChatService 4 个 span（run_turn / session.create + llm.chat nested）
- [x] 日志带 trace_id 关联
