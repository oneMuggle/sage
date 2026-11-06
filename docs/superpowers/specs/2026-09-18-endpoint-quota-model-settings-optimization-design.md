# 端点限额用量统计 + 模型上下文输入优化 — 设计文档

日期: 2026-09-18 · 状态: 已评审待实施(第 1 期) · 范围: Settings 端点/模型配置域

## 1. 背景与现状

| 能力 | 现状 | 位置 |
|---|---|---|
| 用量统计 | 后端 `usage_events` 持久化表(已含 `endpoint_id` 列) + `/api/v1/usage`(totals/today/by_model/cache_hit_rate)/ trend / CSV; 前端 `UsagePanel` 已接入 | `backend/services/usage_tracker.py`, `backend/api/usage_routes.py`, `src/widgets/settings/UsagePanel.tsx` |
| 限额管理 | ❌ 无。仅 429 错误翻译, 无端点配额概念、无预警 | `src/features/manage-endpoints/api.ts:130` |
| 上下文长度 | 全局单值 `maxContext`, number 输入框硬编码 `max=128000`, 512K/1M 无法输入; `autoContext` 已支持 catalog 推断 | `src/pages/settings/ModelsTab.tsx:132-141` |
| 端点配置 | `EndpointConfig`: name/baseUrl/apiKey/protocol/modelId + 连接测试 + 模型发现(4 协议) | `src/entities/setting/types.ts:31-59` |

## 2. 目标

1. **限额用量**: 端点可配置日 token 限额与月预算; 用量按端点聚合展示, 达到 80% 黄色预警、100% 红色超限。
2. **上下文输入**: 支持 512K/1M 等长上下文 — 快捷档位下拉 + 自定义(数值 + K/M 单位), 解除 128000 上限。
3. 对齐主流应用(Claude Desktop / ChatGPT / LobeChat / OpenWebUI / CherryStudio)的可演进方向, 但本期只实施 P0。

## 3. 分期

| 期 | 内容 |
|---|---|
| **P0(本期)** | §4 上下文档位输入 · §5 端点 quota 字段 + by-endpoint 用量聚合 + 预警 |
| P1(后续) | 上游限额响应头采集(`x-ratelimit-*` / anthropic rate-limit 头)入库; RPM/TPM 软限流(前端排队退避); per-model 上下文覆盖(从全局 maxContext 下沉到 DiscoveredModel/catalog) |
| P2(后续) | 服务商预设模板(DeepSeek/Moonshot/百炼等一键填充 baseUrl+协议); "校验 Key"低成本化(只调 /models, 不打真实 chat); API Key 掩码 + 揭示按钮; 模型卡片选择器(上下文/能力/单价/搜索); max output tokens 参数 |

## 4. P0-A: 上下文长度输入(纯前端)

### 4.1 交互

`ModelsTab` "最大上下文长度" 行改为:

- **档位下拉**(默认形态): `4K / 8K / 16K / 32K / 64K / 128K / 200K / 256K / 512K / 1M / 2M / 自定义`。
- 当前 `maxContext` 恰好等于某档位 → 选中该档; 否则自动落到"自定义"。
- **自定义**: 数值框 + 单位下拉(`tokens / K / M`), 输入即 `value × unitMultiplier` 归一化存回 `maxContext: number`。
- 校验区间: **1024 ~ 10,000,000**(超出钳制并提示)。移除 `max=128000`。
- 行尾回显归一化结果, 如 `→ 512000 tokens`, 与 `autoContext` 开关联动说明不变。

### 4.2 数据

存储字段与语义不变(`AppSettings.maxContext: number`), 无迁移。后端 `legacy_routes.resolve_context_window` 仅把它当 int 上限钳制, 无 range 校验, 天然兼容 512K/1M。

新增 `src/entities/setting/contextPresets.ts`: `CONTEXT_PRESETS`(档位数组) + `formatTokens(n)`(4096→'4K', 1000000→'1M', 51234→'51234') + `parseTokenInput(value, unit)`。

## 5. P0-B: 端点限额 + 用量按端点聚合

### 5.1 端点 quota 字段

`EndpointConfig` 增加可选嵌套对象(不进必填, `DEFAULT_ENDPOINT` 给 `{}`):

```ts
export interface EndpointQuota {
  dailyTokens?: number;    // 0/undefined = 不限
  monthlyBudgetUsd?: number; // 0/undefined = 不限
}
// EndpointConfig 上:
quota?: EndpointQuota;
```

同步四处白名单(历史教训: 漏一处即设置保存 400):

1. 前端 `src/entities/setting/storage.ts:ENDPOINT_KEYS` 增 `'quota'`(嵌套对象整树透传, 键名本就 camelCase)。
2. 后端 `settings_canonicalizer.LEGAL_ENDPOINT_KEYS` 增 `"quota"`; `validate_endpoint_payload` 增 `validate_quota`(必须 dict、值必须非负数、未知键报 ValueError)。
3. 后端 `settings_models.EndpointPayload` 增 `quota: Optional[dict] = None`。
4. contract test `test_settings_schema_parity.py` 自动对比项更新(如需)。

### 5.2 编辑 UI

`EndpointsTab` 端点编辑表单底部增"限额(选填)"区: 日 token 限额(档位/单位输入复用 §4 helper)+ 月预算(USD 数值)。留空 = 不限。

### 5.3 后端 by-endpoint 聚合

新路由 `GET /api/v1/usage/by-endpoint`(直查 `usage_events`, 该表已有 `endpoint_id` 列, 无 schema 迁移):

```json
{ "items": [
  { "endpoint_id": "ep-1"|null,
    "today_requests": 12, "today_tokens": 132000,
    "month_requests": 340, "month_tokens": 4100000, "month_cost_usd": 3.21|null }
], "day_start_utc": "...", "month_start_utc": "..." }
```

- 今日窗口: UTC 当日 0 点(`created_at >= ?`); 本月窗口: UTC 当月 1 号 0 点。
- `estimated_cost_usd` 全 null 时透出 null(延续"未知成本不折 0"约定)。
- 异常降级 `{"items": [], "error": ...}`, 不 500(与 /requests 同 pattern)。

### 5.4 用量面板展示 + 预警

`UsagePanel` 底部增"按端点"区块:

- 每端点一行: 名称(按 id 匹配 `settings.endpoints`)、今日 tokens/限额 进度条、本月费用/预算 进度条; 无 quota 的端点只显示用量不显示进度条。
- 进度 ≥ 80% 黄色、≥ 100% 红色, 文案 `已达限额` / `已超出限额`。
- `endpoint_id` 为 null 的聚合行归入"未归属端点"。

数据获取: 面板加载时随 summary 并行拉一次, 手动刷新按钮同时重拉。

## 6. 兼容性与风险

- 旧设置无 `quota` 字段 → 前端 optional / 后端不校验缺失, 零迁移。
- 旧 DB `usage_events.endpoint_id` 为 null 的行 → 聚合进"未归属", 不丢数据。
- 档位换算全部在前端完成, 后端只见归一化 int, 无新增校验面。

## 7. 测试计划

- 前端: `contextPresets` 单测(换算/格式化/边界钳制); `ModelsTab` 档位选择 + 自定义单位写回 `maxContext`; `sanitizeForBackend` quota 透传; `EndpointsTab` quota 编辑保存。
- 后端: `validate_quota` 单测(dict/负数/未知键); `test_settings_schema_parity` 通过; `/api/v1/usage/by-endpoint` 契约测试(空库/多端点/成本 null)。
- 回归: `npx vitest run` 相关用例 + `pytest backend/tests` usage/canonicalizer 相关。

## 8. 实施清单(本期)

1. `src/entities/setting/contextPresets.ts`(新)
2. `ModelsTab.tsx` 上下文输入改造
3. `types.ts` quota 类型 + `storage.ts` 白名单 + `DEFAULT_ENDPOINT`
4. `EndpointsTab.tsx` quota 编辑区
5. 后端 canonicalizer/`settings_models.py` quota 校验
6. 后端 `usage_routes.py` by-endpoint 路由
7. `usageApi.ts` + `UsagePanel` 按端点额度区块
8. 前后端测试
