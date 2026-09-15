# 37 · 生态扩展：Hooks + 用量面板 + 项目上下文 + i18n 清扫 + Parity Harness（M6 → L8 三轮）

M6 是里程碑收尾，交付 5 个相互独立的生态扩展能力。设计参考 claw-code
（`rust/crates/runtime/src/{hooks,usage,prompt}.rs` + `mock-anthropic-service`）。

L8 三轮递进（2026-09-09）：PR-A 拆 cache 字段与命中率、PR-B DB 落库 + range
维度 + 请求分页、PR-C 趋势图 + CSV 导出 + TTFT/latency 落库。仅扩 §2 用量面板，
其余 4 节保持 M6 原貌。

---

## 1. Hooks 系统（用户自定义工具钩子）

claw 风格：pre/post tool use，allow / deny / modify 三种决策。配置存
`preferences.hooks` 键（JSON 列表），加载器从 `SettingsRepository` 读，**任何
故障 → 空列表**（fail-open：钩子故障永不断 agent）。

| 项 | 详情 |
| --- | --- |
| 事件 | `PreToolUse` / `PostToolUse` |
| 执行 | `asyncio` 子进程，JSON payload 经 STDIN 传入，env `SAGE_HOOK_EVENT` / `SAGE_TOOL_NAME` 标识 |
| 超时 | `start_new_session` + `killpg`；超时 → fail-open（仅显式 deny 生效） |
| Payload | 事件 + 工具名 + args（pre）/ 结果（post） |
| Modified args | `validate_modified_args` 校验 `PreToolUse` 的 `updated_input` 不破坏原 schema |

接线位于 `agent.run_loop` 工具执行块的前后（`backend/core/legacy/agent.py`），
以 `# ===== M6 HOOKS BEGIN/END =====` 标记块包裹，便于 rebase。

### 测试

| 层 | 文件 | 数量 |
| --- | --- | --- |
| 单元 | `backend/tests/unit/test_hooks.py` | 30 |
| 集成 | `backend/tests/integration/test_hooks_integration.py` | 5 |

## 2. 用量 / 成本面板（cc switch 对标三轮递进）

`backend/services/usage_tracker.py` + `backend/api/usage_routes.py`：

- **M6 初始态**：内存 ring buffer（容量 1000）+ 按日聚合 dict；LLMClient chat / chat_stream
  内部 `tracker.record()` 落桶；**tracker 故障 fail-open，永不影响 chat 返回**
- **L8 PR-A (2026-09-09)**：拆 `cache_read_tokens` / `cache_creation_tokens`，派生
  `cache_hit_rate = cache_read / (prompt + cache_creation)`（取 0..1）
- **L8 PR-B (2026-09-09)**：DB 落库 `usage_events` 表，扩 `created_at_ms / session_id`
  索引 + 幂等 `ALTER TABLE`；range 维度 `today | 7d | 30d | total`，today 走内存
  桶（hour），其余走 SQL `GROUP BY strftime('%Y-%m-%d', created_at_ms, 'unixepoch')`
- **L8 PR-C (2026-09-09)**：`record()` 新增 `first_token_ms` / `latency_ms` 落库，
  `_norm_latency` 校验 None / bool 排除 / int>=0 / str 数字；新增
  `/trend` 时间桶序列 + `/export.csv` 文本导出（UTF-8 BOM）

**重启行为**：M6 内存态已替换为 DB 落库 + 内存 today 桶双轨，重启后历史保留。

### REST 契约

| 端点 | 方法 | 参数 | 返回 |
| --- | --- | --- | --- |
| `/api/v1/usage` | GET | `range=today\|7d\|30d\|total` | `{totals, by_model, today, cache_hit_rate}` |
| `/api/v1/usage/session/{id}` | GET | — | 单会话累计 + `cache_hit_rate` |
| `/api/v1/usage/requests` | GET | `range`, `limit`, `offset`, `session_id?` | `{items, total, limit, offset}` |
| `/api/v1/usage/trend` | GET | `range=today\|7d\|30d\|total` | `{range, bucket: hour\|day, series: [{ts, requests, cost_usd, cache_hit_rate, ...}]}` |
| `/api/v1/usage/export.csv` | GET | `range`, `session_id?` | text/csv + UTF-8 BOM，列：id, session_id, model, prompt, completion, total, cache_read, cache_creation, cost, first_token_ms, latency_ms, created_at_iso |

未知模型成本返回 `None`，前端渲染 `—` 占位。

### 前端

- `electron/commands.ts` — `usage_summary` / `usage_list_requests` / `usage_trend` /
  `usage_export_csv` / `usage_get_session` 共 5 个 IPC 路由
- `src/widgets/settings/UsagePanel.tsx` — 顶部汇总（请求/Token/成本）+ cache 三列
  （读/写/命中率）+ 4 个 range tab + by-model 表格
- `src/widgets/settings/UsageRequestsTable.tsx` — 分页请求明细（6 列 + 翻页）
- `src/widgets/settings/UsageTrendChart.tsx` — **自绘 SVG 双线图**（requests +
  cost_usd，600×180 viewBox，3 Y-grid，day bucket X 中点留空避免拥挤）；不引入
  Recharts（~95KB gzipped 不划算）
- `src/widgets/chat/SessionUsageBadge.tsx` — 单会话徽章，含 🎯 命中率（≥50% 高亮 /
  ≥20% 中性 / 其他灰）
- CSV 导出：浏览器侧 `Blob + UTF-8 BOM + ObjectURL`，文件名
  `sage-usage-{range}-{timestamp}.csv`
- i18n `settings.usage.*` + `settings.section.usage` + `session.cron_badge` 等
  共 14 键 ×2

### 测试

| 层 | 文件 | 数量 |
| --- | --- | --- |
| 单元 | `backend/tests/unit/test_usage_tracker.py` | 36 |
| 前端 | `UsagePanel.test.tsx` + `UsageRequestsTable.test.tsx` + `UsageTrendChart.test.tsx` + `SessionUsageBadge.test.tsx` + commands guard | 21+ |

## 3. 项目上下文发现（SAGE.md / CLAUDE.md）

`backend/chat/project_context.py`（新增）：

| 步骤 | 行为 |
| --- | --- |
| 1 | 从 workspace root 向上遍历至文件系统根 |
| 2 | 每级先查 `SAGE.md`（项目专属），后查 `CLAUDE.md`（业界通用） |
| 3 | 按内容 SHA-256 去重（同一文件被多级引用只取一次） |
| 4 | 单文件 8000 字符上限，总量 16000 字符上限 |
| 5 | 截断标注 `[truncated]` 防止误导 LLM |
| 6 | `realpath` 防符号链接逃逸（避免读 `/etc/passwd` 之类） |
| 7 | 失败 / 不存在静默跳过（不阻塞聊天） |

发现结果注入 `chat_stream_create` 的 system prompt 前缀（**早于 user 消息**）。
设计原则：**用户的 project 上下文 > 框架默认上下文**。

### 测试

| 层 | 文件 | 数量 |
| --- | --- | --- |
| 单元 | `backend/tests/unit/test_project_context.py` | 7 |
| 集成 | `backend/tests/integration/test_project_context_injection.py` | 2 |

## 4. i18n 覆盖清扫

提取 Office 与 Orchestration 两页的硬编码中文字符串为 `zh.ts` / `en.ts` 键：

- **Office 文档**：~50 键（`office.*` / `office.pick.*` / `office.toast.*` / `office.picker.*` / `office.generate.*` / `office.preview.*` / `office.doc.*`）
- **Orchestration 看板**：~22 键（`orchestration.loading` / `error` / `column.*` ×4 / `status.*` ×8 / `heartbeat.*` ×6 / `lane.*` ×2）
- **用量面板**：`settings.section.usage` + `settings.usage.*` 8 键
- **Orchestration 表单/徽标/toast**（M5 独有，M6 补齐）：`orchestration.badge.{subagent,planner}` / `orchestration.toast.*` ×2 / `orchestration.{subtitle,goal_placeholder,create,creating}` 6 键
- **L8 PR-A (2026-09-09) 用量面板**：5 键（`settings.usage.cache.read/creation/cacheHitRate`、`settings.usage.range.today/total`）
- **L8 PR-B (2026-09-09) 用量面板**：11 键（`settings.usage.range.7d/30d` ×2 + `requestsTable.*` ×9）
- **L8 PR-C (2026-09-09) 用量面板**：7 键（`settings.usage.trend.*` ×6 + `settings.usage.exportCsv`）

合计 +106 键（zh + en 同步）。`TranslationKey` 类型自动从 `zh.ts` 派生（`keyof typeof zh`），
新增键时**必须 zh + en 同步**，否则 tsc 报 `[2353]`。

### 验证

`src/pages/Office.tsx`、`src/features/office/**` 与 `src/pages/Orchestration.tsx` 中
所有 `t('...')` 调用都有对应键；vitest 包裹 `I18nProvider` 以便测试时注入键。

## 5. Mock LLM 一致性测试台（parity harness）

`backend/tests/parity/`（新增，**零新依赖**）：

| 文件 | 职责 |
| --- | --- |
| `mock_server.py` | 线程托管的 `http.server.BaseHTTPRequestHandler`；场景检测取自请求消息中的 `PARITY_SCENARIO:<name>` 前缀；响应脚本按请求序号依次消费（耗尽后重复最后一条） |
| `test_llm_client_parity.py` | 把真实 `LLMClient` 指向 mock 服务器（`base_url` 覆盖 + `use_proxy=False`），端到端验证普通 / tool_call round-trip / SSE 流式三种响应的解析 |

### 场景数据

`mock_server.SCENARIOS: Dict[str, List[Dict]]`，每条响应脚本形如：

```python
{"type": "message", "content": "...", "tool_calls": [...], "usage": {...}}
# 或
{"type": "stream", "chunks": [...], "usage": {...}}
```

### 覆盖

- 普通 chat 响应解析
- tool_call 往返（LLM 工具调用 → 用户执行 → 结果回流）
- SSE 流式（含末尾 usage + `data: [DONE]` 终止）

**价值**：客户端的线协议处理在**无网络环境**下被真实执行，而非 mock 掉
`httpx` 客户端。CI 上零网络依赖。

### 测试

| 层 | 文件 | 数量 |
| --- | --- | --- |
| 集成 | `backend/tests/parity/test_llm_client_parity.py` | 4 |

## 6. 风险与缓解

| 风险 | 缓解 |
| --- | --- |
| 钩子命令是用户配置的可信 shell | fail-open（钩子故障不阻断 agent），仅显式 `deny` 生效；`validate_modified_args` 防 `updated_input` 破坏 schema |
| 用量数据已落 DB，命中率公开派生 | L8 PR-B：`usage_events` 表 + `created_at_ms`/`session_id` 索引，幂等 `ALTER TABLE`；tracker 仍 fail-open，写失败仅丢当条记录 |
| 项目上下文注入早于 user 消息 | 注入点位于 `chat_stream_create` 系统 prompt 构造处，保证优先级 |
| i18n 键集不一致（zh/en 漏键） | `TranslationKey = keyof typeof zh` + en 用 `Record<TranslationKey, string>` 标注，tsc 强制同步 |

## 7. 不在范围内

- 远程 hooks webhook 投递（仅本地子进程）
- 项目上下文的 git hook 集成
- i18n 翻译协作流程（`zh` / `en` 当前均由开发者手工维护）
- 用量面板的预算告警 / 月度封顶提醒（仅展示与导出，告警由人工触发）
