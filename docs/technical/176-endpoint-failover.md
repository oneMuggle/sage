# 176 · 端点优先级故障转移

> 2026-11-26 · 设计文档：`docs/superpowers/specs/2026-11-26-endpoint-failover-design.md`

## 一句话

聊天链路的 LLM 端点按优先级组成故障转移链：当前端点重试耗尽或认证失败时，自动切到下一个优先级端点；失败端点进入冷却并由后台轻量探测恢复。默认关闭，开启后单端点用户行为不变。

## 配置

### 端点优先级

`EndpointConfig.priority`（1 = 最高）：

- 设置页「端点配置」每行显示 `P{n}`，用 ↑/↓ 调整并自动重排为 1..N；
- 新端点默认追加到末尾（`length + 1`）；
- 缺省/非法 priority 视为未排序，构链时排在已排序端点之后。

### 故障转移段

`app_settings.failover`（顶层键，默认关闭）：

```json
{
  "enabled": false,
  "probeIntervalMs": 300000,
  "cooldownMs": 60000,
  "consecutiveFailThreshold": 2
}
```

范围：`probeIntervalMs` 30s–24h；`cooldownMs` 5s–1h；`consecutiveFailThreshold` 1–10。
后端 `settings_canonicalizer.validate_settings_shape` 拒收越界值（400）。

## 触发语义

| 场景 | 行为 |
|---|---|
| 429 / 5xx / 超时 / 网络错误 | 当前端点内部按现有重试参数重试；耗尽后切下一端点 |
| 401 认证失败 / 403 | 不重试，直接切下一端点 |
| 流式已输出首字后失败 | **不切换**（防内容重复/截断），记录失败供后续请求规避，本次按错误终止 |
| 400 / 解析错误 / 上下文溢出等 | 不切换（请求本身问题，换端点大概率同样失败） |

每跳内部顺序：主模型重试 → 主跳的 `fallback_model` 降级 → 下一端点。
`fallback_model` 仅主跳生效（目标端点的降级模型语义不明确）。

切换后模型：目标端点 `discoveredModels` 含当前模型 → 沿用；否则 `modelId`；
否则第一个发现的模型；都无则跳过该端点。

全部端点失败时抛最后一个错误，消息附「已尝试 N 个端点：端点A: 原因；端点B: 原因」。

## 端点链构建

`llm_factory.load_llm_config_for_chat()` 在 `failover.enabled=true` 时附加
`LLMConfig.endpoint_chain`：

1. 当前显式选择的端点（会话覆盖/profile/全局）排第一（若可用）；
2. 其余按 priority 升序；
3. 冷却期内的 `failed` 端点整体后移（冷却期满自动回原位）。

候选端点需满足：协议受支持、`baseUrl` 非空、满足协议鉴权契约、能解析出模型。
链长 ≤ 1 时不注入，行为与引入前完全一致。

## 健康状态机

`backend/services/endpoint_health.py`（进程内内存，不持久化）：

- `healthy` → `degraded`（有失败未达阈值）→ `failed`（连续失败 ≥ 阈值）；
- 成功一次立即回 `healthy`；
- `failed` 端点在 `cooldownMs` 内被视为不可用（构链时后移），冷却期满允许被动重试；
- `failoverCount` 仅统计切换次数。

每次 LLM 尝试由 `LLMClient` 被动上报成功/失败；后台探测仅在
`degraded/failed` 端点上运行（健康端点零开销）。

## 后台探测与 failback

`backend/services/endpoint_probe.py`，lifespan 启动 `endpoint-probe` 任务：

- 周期 `probeIntervalMs`，休眠按 ≤30s 分片；
- `GET {baseUrl}/models`（Ollama：`/api/tags`），5s 超时，不消耗 token；
- 2xx → `record_success`；401/5xx/超时/连接失败 → `record_failure("probe")`；
- **403/404/405 → 视为可达**（模型列表权限/路径不支持），不改状态。

**failback 语义**：探测恢复只影响之后的新请求（构链重新按优先级从头排），
不在同一轮流式/多步执行中强制切回，避免上下文不一致。

## API

`GET /api/v1/endpoints/health`（需本地鉴权）：

```json
{
  "endpoints": [
    {
      "endpointId": "ep1",
      "status": "healthy",
      "consecutiveFailures": 0,
      "lastFailureAt": null,
      "lastSuccessAt": 1750000000.0,
      "lastFailureReason": null,
      "failoverCount": 0
    }
  ]
}
```

## 用户可见性

- 设置页（端点配置）：故障转移开关与参数；每行 `P{n}`、上下移按钮、健康状态点
  （开关开启时 15s 轮询，页签卸载即停）。
- 聊天：切换时在重试横幅位置显示「已自动切换到端点「B」（A 失败：超时）」，
  事件载荷为 `retry_info.kind = "failover"`（复用 `state=retry` 通道，无倒计时）。

## 排障

| 现象 | 排查 |
|---|---|
| 没有自动切换 | 检查「设置 → 端点配置」开关是否开启；链内有效端点是否 > 1；失败端点是否仍在冷却期 |
| 一直不切回主端点 | 主端点探测是否成功（`GET {baseUrl}/models` 2xx）；冷却期是否过长 |
| 保存设置 400 | `failover` 只接受 4 个键；数值需在范围内；`priority` 必须正整数 |
| 流式中途失败没有切换 | 设计如此：已输出首字后不可重放，请手动重试 |
| 想临时只用主端点 | 关闭故障转移开关，或把其他端点 priority 调到很后并等待冷却 |

## 测试

- 后端：`test_endpoint_health.py`、`test_endpoint_probe.py`、
  `test_llm_factory_failover.py`、`test_llm_client_failover.py`、
  `test_endpoint_health_routes.py`、`test_agent_failover_event.py`、
  `test_settings_failover_fields.py`、契约测试 `test_settings_schema_parity.py`。
- 前端：`failoverSettings.test.ts`、`endpointPriority.test.ts`、
  `RetryBanner.failover.test.tsx`。

## 双分支说明

main 完成后需 cherry-pick 到 `release/win7`（Python 3.8）：代码未使用
`match` / PEP 604 注解；新增测试文件带 `# ruff: noqa: UP006, UP007, UP035, UP045` 头。
