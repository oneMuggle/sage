# Sage 用量统计与 Prompt Cache 对标 cc-switch (2026-09-09)

## 背景与目标

Sage 现有用量统计体系在「跨 Provider token 归一化」「SQLite 持久化」「花费限额」三方面已做到位，但与社区同类工具 [farion1231/cc-switch](https://github.com/farion1231/cc-switch) 对比，存在 6 类缺口：

1. **缓存维度未拆**：Anthropic 的 `cache_read_input_tokens`（极便宜）与 `cache_creation_input_tokens`（略贵）合并到单列 `cached_tokens`，用户无法判断"命中便宜缓存 vs 反复创建新缓存"。
2. **前端 cache 命中率几乎不可见**：仅 `ContextMeter` tooltip 里隐约显示，全局 `UsagePanel` 完全无 cache 信息。
3. **Prometheus 端点默认关闭**：`/api/v1/metrics` 仅在 `API_MODE=hex` 时挂载（`backend/main.py:652`），默认 legacy 模式无 metrics。
4. **历史时间维度缺失**：只有"今日"和"累计"，无 7d/30d。
5. **请求级明细不可查**：只有聚合，无单次请求详情。
6. **流式首字节延迟（TTFT）未记录**。

**目标**：3 个 PR 系列，把 Sage 用量统计与缓存命中率展示拉至 cc-switch 同等核心水位。

## 涉及的文件与模块

### 后端

| 文件 | 改动内容 |
|---|---|
| `backend/data/database.py:594-621` | `usage_events` 表新增 4 列：`cache_read_tokens` / `cache_creation_tokens` / `first_token_ms` / `latency_ms` |
| `backend/services/usage_tracker.py` | `UsageRecord` dataclass 补字段；`summary()` 返回 cache 命中率派生；新增 `range_filter` 参数 |
| `backend/api/usage_routes.py` | `/api/v1/usage` 加 `?range=today\|7d\|30d`；新增 `/api/v1/usage/requests` 分页；新增 `/api/v1/usage/export.csv` |
| `backend/core/legacy/llm_client.py:511-535, 582-629` | 流式记录 `first_token_ms` |
| `backend/main.py:652` | 移除 `/api/v1/metrics` 的 `API_MODE=hex` 条件 |
| `backend/data/database.py` | 新增 `usage_daily_rollups` 表 + 定期聚合任务 |
| 新增 `backend/services/usage_rollup.py` | rollup 聚合逻辑 |

### 前端

| 文件 | 改动内容 |
|---|---|
| `src/shared/api/usageApi.ts` | 类型补 `cache_read` / `cache_write` / `cache_hit_rate` / `first_token_ms` 字段 |
| `src/widgets/settings/UsagePanel.tsx` | 加 cache 命中率行 + 时间范围 Tab（Today/7d/30d） |
| `src/widgets/settings/UsagePanel.tsx` | 加"导出 CSV"按钮 + "查看明细"按钮 |
| 新增 `src/widgets/settings/UsageRequestsTable.tsx` | 请求明细表（分页 + 过滤） |
| 新增 `src/widgets/settings/UsageTrendChart.tsx` | 趋势折线图（4 色 token + cost 虚线） |
| `src/widgets/chat/SessionUsageBadge.tsx` | 加 cache 命中徽章 |
| `src/shared/i18n/{zh,en}.ts` | 补 i18n 键 |

### 文档

| 文件 | 改动内容 |
|---|---|
| `docs/technical/37-ecosystem-extensions.md:32-67` | 更新 M6 用量面板说明 |
| 新增 `docs/user-manual/usage-and-cache.md` | 用户视角的用量与缓存说明 |

## 技术方案

### PR-A：Cache 拆分 + 前端展示 + Metrics 默认开（P0）

**数据流：**

```
LLM Response
  ├─ usage.input_tokens
  ├─ usage.output_tokens
  ├─ usage.cache_read_input_tokens    →  usage_events.cache_read_tokens
  ├─ usage.cache_creation_input_tokens →  usage_events.cache_creation_tokens
  └─ stream first_token_ms             →  usage_events.first_token_ms
  ↓
usage_tracker.record() 同步落库
  ↓
GET /api/v1/usage
  → { totals, by_model, today,
      cache: { read, write, hit_rate } }
  ↓
UsagePanel 渲染（5 KPI 卡 + 命中率）
```

**API 设计（合成示例）：**

```json
{
  "totals": {
    "requests": 42,
    "input_tokens": 12500,
    "output_tokens": 3200,
    "cache_read_tokens": 8900,
    "cache_creation_tokens": 1200,
    "estimated_cost_usd": 0.045,
    "success_rate": 0.98
  },
  "cache_hit_rate": 0.78,
  "by_model": [
    {
      "model": "claude-opus-4-8",
      "requests": 30,
      "tokens": 12000,
      "cost": 0.035,
      "cache_read": 8500,
      "cache_write": 1000
    }
  ],
  "range": "7d"
}
```

**Schema 迁移（兼容旧库）：**

```sql
ALTER TABLE usage_events ADD COLUMN cache_read_tokens INTEGER NOT NULL DEFAULT 0;
ALTER TABLE usage_events ADD COLUMN cache_creation_tokens INTEGER NOT NULL DEFAULT 0;
ALTER TABLE usage_events ADD COLUMN first_token_ms INTEGER;
ALTER TABLE usage_events ADD COLUMN latency_ms INTEGER;
```

旧库若 4 列已存在则跳过（用 `PRAGMA table_info(usage_events)` 检测）。

### PR-B：时间维度 + 日聚合 rollup + 请求明细（P1）

**双层存储：**

```
usage_events (明细，保留 30 天)
  ↓ 每日 04:00 定时任务
usage_daily_rollups (聚合，永久保留)
  PRIMARY KEY (date, model)
```

**明细 API（合成示例）：**

```json
{
  "total": 187,
  "items": [
    {
      "id": "uuid",
      "session_id": "abc123",
      "model": "claude-opus-4-8",
      "provider": "anthropic",
      "prompt_tokens": 1250,
      "completion_tokens": 320,
      "cache_read_tokens": 890,
      "cache_creation_tokens": 120,
      "estimated_cost_usd": 0.0045,
      "first_token_ms": 850,
      "latency_ms": 2100,
      "status_code": 200,
      "created_at": 1757433600
    }
  ],
  "page": 1,
  "page_size": 20
}
```

**日期格式：** `created_at INTEGER`（unix 秒，毫秒精度需要时改 INTEGER 微秒）；rollup 表 `date TEXT` (`YYYY-MM-DD` 本地时区)。

### PR-C：趋势图 + CSV 导出 + TTFT（P2）

**前端：**
- `UsageTrendChart`：Recharts 折线图，4 色 series（input/output/cache_read/cache_creation）+ cost 虚线
- CSV 导出按钮：`GET /api/v1/usage/export.csv?range=...`

**TTFT：**
- 流式响应收到第一个 SSE chunk 时记录 `time.monotonic() - start`
- 写入 `usage_events.first_token_ms`

## 实施步骤

### PR-A（P0，最小变更）

- [ ] A1. `database.py` schema 迁移（4 列 ALTER TABLE，幂等）
- [ ] A2. `UsageRecord` dataclass + `usage_tracker.record()` 补字段
- [ ] A3. `usage_tracker.summary()` 返回 `cache_hit_rate` 派生
- [ ] A4. `usage_routes.py` 加 `range` 参数
- [ ] A5. `main.py` 移除 `API_MODE=hex` 条件
- [ ] A6. 前端 `usageApi.ts` 类型补齐
- [ ] A7. `UsagePanel.tsx` 加 cache 命中率行
- [ ] A8. `SessionUsageBadge.tsx` 加 cache 徽章
- [ ] A9. i18n 键补全
- [ ] A10. 单元测试（usage_tracker 派生指标）
- [ ] A11. E2E（设置页 → UsagePanel 展示命中率）

### PR-B（P1，时间维度）

- [ ] B1. `database.py` 加 `usage_daily_rollups` 表
- [ ] B2. 新增 `backend/services/usage_rollup.py`
- [ ] B3. 启动时调度每日 rollup 任务
- [ ] B4. `/api/v1/usage?range=` 路由实现
- [ ] B5. 前端 `UsagePanel` 加时间 Tab
- [ ] B6. 新增 `UsageRequestsTable.tsx`
- [ ] B7. `/api/v1/usage/requests` 分页 API
- [ ] B8. 集成测试

### PR-C（P2，可视化）

- [ ] C1. Recharts 安装与封装
- [ ] C2. `UsageTrendChart.tsx`
- [ ] C3. CSV 导出 API
- [ ] C4. 流式 TTFT 记录
- [ ] C5. 文档更新

## 风险评估

| 风险 | 缓解 |
|---|---|
| Schema 迁移失败（用户已有数据） | ALTER TABLE 加 IF NOT EXISTS 兼容；旧库缺列时 fallback 0 |
| TTFT 测量不准（mock provider） | 仅 Anthropic/OpenAI adapter 记录，mock 跳过 |
| 日聚合任务与热写入冲突 | 用 WAL 模式 + 事务 |
| 请求明细表数据量大 | 保留 30 天 + 30 天后自动归档（PR-B 不做，留待 P3） |
| Recharts 体积 | 选用轻量子集，按需 import |
| Metrics 端点默认开的安全 | 仅本机 127.0.0.1 监听，已是默认 |

## 反模式（不做的事）

- ❌ 不引入本地 HTTP 代理接管所有 CLI 流量（cc-switch 反模式，破坏用户原有配置）
- ❌ 不做云同步（API key 泄漏风险）
- ❌ 不引入 50+ provider preset（维护成本不匹配）
- ❌ 不做 CSV 之外的更多导出格式（YAGNI）

## 验证

- 单元测试：cache 字段派生、命中率计算、rollup 聚合
- 集成测试：`/api/v1/usage?range=30d` 返回正确；请求分页正确
- E2E：设置页能切换时间范围，能看到 cache 命中率
- 手动：在 main 上跑一次长会话，确认 cache 字段被正确填充

## 文档归档

完成后：
- `docs/plans/2026-09-09_usage-cache-parity.md` 标 [x] 后**删除**（按 docs 管理规范）
- 增量同步到 `docs/technical/37-ecosystem-extensions.md`（M6 章节扩写）
- 新增 `docs/user-manual/usage-and-cache.md`（用户视角）
