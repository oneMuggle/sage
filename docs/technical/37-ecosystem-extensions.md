# 37 · 生态扩展：Hooks + 用量面板 + 项目上下文 + i18n 清扫 + Parity Harness（M6）

M6 是里程碑收尾，交付 5 个相互独立的生态扩展能力。设计参考 claw-code
（`rust/crates/runtime/src/{hooks,usage,prompt}.rs` + `mock-anthropic-service`）。

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

## 2. 用量 / 成本面板

`backend/services/usage_tracker.py`（新增）：

- 内存 **ring buffer（容量 1000）** + 按日聚合 dict
- **不落 SQLite**——重启清零（设计权衡：避免高频写入 + 不持久化用户隐私用量）
- 定价表 USD/1M tokens，未知模型成本返回 `None`
- `LLMClient.chat` 内部记录（**tracker 故障 fail-open，永不影响 chat 返回**）
- `LLMClient.chat_stream` 同样在流末尾记录（基于 `stream_usage` dict 聚合）

### REST 契约

`GET /api/v1/usage`：

```json
{
  "today": [{"date": "2026-07-29", "model": "gpt-4o", "prompt_tokens": 120, "completion_tokens": 80, "est_cost_usd": 0.002}],
  "by_model": {"gpt-4o": {...}},
  "ring_buffer": [...]   // 最近 1000 条
}
```

### 前端

- `electron/commands.ts` — `usage_summary` IPC 路由（`GET /api/v1/usage`）
- `src/pages/settings/GeneralTab.tsx` — `UsagePanel` 挂载
- `src/widgets/settings/UsagePanel.tsx` — 今日 / 按模型 / 刷新按钮
- i18n `settings.section.usage` + `settings.usage.*` 8 键 ×2

### 测试

| 层 | 文件 | 数量 |
| --- | --- | --- |
| 单元 | `backend/tests/unit/test_usage_tracker.py` | 15 |
| API | `backend/tests/api/test_usage_routes.py` | 7 |
| 前端 | `UsagePanel.test.tsx` + commands guard | 3+ |

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

合计 +83 键（zh + en 同步）。`TranslationKey` 类型自动从 `zh.ts` 派生（`keyof typeof zh`），
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
| 用量数据不落 DB → 重启清零 | 设计权衡：避免高频写入 + 不持久化隐私；环形 buffer 1000 容量足以覆盖会话周期 |
| 项目上下文注入早于 user 消息 | 注入点位于 `chat_stream_create` 系统 prompt 构造处，保证优先级 |
| i18n 键集不一致（zh/en 漏键） | `TranslationKey = keyof typeof zh` + en 用 `Record<TranslationKey, string>` 标注，tsc 强制同步 |

## 7. 不在范围内

- 远程 hooks webhook 投递（仅本地子进程）
- 用量数据导出 / 历史报表
- 项目上下文的 git hook 集成
- i18n 翻译协作流程（`zh` / `en` 当前均由开发者手工维护）
