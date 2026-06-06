# 02. 指标与审计查询（Metrics & Audit Query）

**最后更新**：2026-06-06
**适用版本**：Sage v0.1（桌面端 / 自部署）

## 2.1 Prometheus 指标查询

Sage 后端通过 `GET /metrics` 端点暴露 Prometheus 兼容的指标文本。

### 2.1.1 基本查询

```bash
# 完整指标输出
curl http://localhost:8765/metrics

# 仅过滤特定指标
curl -s http://localhost:8765/metrics | grep '^sage_'

# 计数
curl -s http://localhost:8765/metrics | grep '^sage_llm_calls_total{' | wc -l
```

### 2.1.2 9 个核心指标

| 指标 | 类型 | 说明 |
|------|------|------|
| `sage_http_requests_total` | Counter | HTTP 请求数（按 route/method/status） |
| `sage_llm_calls_total` | Counter | LLM 调用数（按 model/provider/outcome） |
| `sage_tool_invocations_total` | Counter | 工具调用数（按 tool/outcome） |
| `sage_tokens_consumed_total` | Counter | Token 消耗（按 model/kind=prompt\|completion） |
| `sage_errors_total` | Counter | 错误数（按 layer/error_type） |
| `sage_http_request_duration_seconds` | Histogram | HTTP 延迟分布 |
| `sage_llm_call_duration_seconds` | Histogram | LLM 延迟分布 |
| `sage_react_steps_per_request` | Histogram | ReAct 步数分布 |
| `sage_active_sessions` | Gauge | 当前活跃 session 数 |

### 2.1.3 常用查询示例

**今天 LLM 错误率**：
```promql
rate(sage_errors_total{layer="llm"}[1h])
```

**LLM 平均响应时间（5 分钟）**：
```promql
rate(sage_llm_call_duration_seconds_sum[5m]) / rate(sage_llm_call_duration_seconds_count[5m])
```

**P95 ReAct 步数**：
```promql
histogram_quantile(0.95, rate(sage_react_steps_per_request_bucket[5m]))
```

**Token 消耗速率**：
```promql
sum by (model, kind) (rate(sage_tokens_consumed_total[5m]))
```

## 2.2 Grafana 面板

### 2.2.1 Prometheus 数据源

Grafana → Configuration → Data Sources → Add Prometheus：
- URL：`http://localhost:9090`（如果用 Prometheus 抓取 Sage）
- 抓取配置（`prometheus.yml`）：
  ```yaml
  scrape_configs:
    - job_name: 'sage'
      scrape_interval: 15s
      static_configs:
        - targets: ['localhost:8765']
  ```

### 2.2.2 推荐面板

| 面板 | PromQL |
|------|--------|
| LLM 调用率 | `sum by (model) (rate(sage_llm_calls_total[5m]))` |
| LLM 错误率 | `sum by (model, outcome) (rate(sage_llm_calls_total{outcome!="success"}[5m]))` |
| LLM 延迟 P50/P95/P99 | `histogram_quantile(0.5/0.95/0.99, sum by (le) (rate(sage_llm_call_duration_seconds_bucket[5m])))` |
| Token 消耗 | `sum by (kind) (rate(sage_tokens_consumed_total[1h]))` |
| 工具调用 Top N | `topk(5, sum by (tool) (rate(sage_tool_invocations_total[1h])))` |
| HTTP 状态码 | `sum by (status) (rate(sage_http_requests_total[1m]))` |
| 活跃 session | `sage_active_sessions` |

## 2.3 审计日志查询

Sage 写入用户行为审计到 `backend/data/audit/audit.jsonl`（每行一个 JSON 对象）。

### 2.3.1 5 类事件

| 事件 | 触发时机 | Payload |
|------|----------|---------|
| `chat_message_sent` | 用户发送消息 | session_id, role |
| `chat_response_completed` | LLM 响应完成 | session_id |
| `tool_invoked` | 工具被调用 | session_id, tool, args |
| `session_created` | 新会话 | session_id, title |
| `settings_changed` | 设置被修改 | changed_fields（列表） |

### 2.3.2 常用查询

```bash
# 最近 10 条事件
tail -10 backend/data/audit/audit.jsonl | jq '.'

# 某个 session 的所有事件
grep '"session_id": "mem-1"' backend/data/audit/audit.jsonl | jq '.'

# 今天所有 chat 事件
jq -r 'select(.type | startswith("chat_"))' backend/data/audit/audit.jsonl

# 工具调用 Top 5
jq -r 'select(.type == "tool_invoked") | .payload.tool' backend/data/audit/audit.jsonl | sort | uniq -c | sort -rn | head

# 设置变更历史
jq -r 'select(.type == "settings_changed")' backend/data/audit/audit.jsonl
```

### 2.3.3 隐私保护

- **API Key 永不写入**审计 payload
- 消息内容**不写入**审计（仅 metadata）
- 审计日志存于本地，不上传

### 2.3.4 日志轮转

当前无自动轮转。建议外接 cron：

```cron
# 每天 0 点：压缩前一天 + 启动新文件
0 0 * * * cd /path/to/sage && mv backend/data/audit/audit.jsonl backend/data/audit/audit-$(date +\%Y\%m\%d).jsonl && touch backend/data/audit/audit.jsonl
```

## 2.4 OpenTelemetry trace_id 关联

每条结构化日志带 `trace_id`：

```bash
# 找某个 trace_id 的所有日志
grep 'trace=4bf92f3577b34da6a3ce929d0e0e4736' backend/data/logs/*.log

# 找错误日志及其 trace
grep '\[ERROR\]' backend/data/logs/*.log | grep -oE 'trace=[0-9a-f]+'
```

OTEL 当前导出到 stdout。生产可换 OTLP collector（见 `docs/technical/16-observability.md`）。

## 2.5 端到端排查示例

### 场景：用户报「聊天发不出去」

```bash
# 1. 检查最近错误
jq -r 'select(.type == "chat_message_sent")' backend/data/audit/audit.jsonl | tail -5
jq -r 'select(.type == "settings_changed")' backend/data/audit/audit.jsonl | tail -5

# 2. 检查 LLM 错误指标
curl -s http://localhost:8765/metrics | grep sage_errors_total{layer="llm"

# 3. 检查测试连接状态（设置 → 测试连接）
# 4. 看 trace_id 关联日志
```

### 场景：监控某次会话的完整流程

```bash
# 取 session_id
SID="mem-1"

# 拉该 session 的所有审计事件
grep "\"session_id\": \"$SID\"" backend/data/audit/audit.jsonl | jq -c '{ts, type, payload}'

# 拉相关 LLM 调用指标
curl -s http://localhost:8765/metrics | grep -E "llm_calls_total.*default"
```
