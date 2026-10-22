# LLM 总耗时上限：文案消歧 + 默认值修正 + UI 可配置

> 状态：进行中
> 创建：2026-10-22
> 关联会话：`eff612d7-4848-4fa3-b14d-fbfa4a3032b7`（783.8s 超时事故）
> 叠加于：`feat/agent-limit-error-details`（复用 `parseAgentErrorLimit` / `AGENT_RUNTIME_MESSAGES` / `nonlocal _producer_error` 修复）

---

## 背景与目标

### 事故成因

会话 `eff612d7-...` 失败日志：

```
LLM 调用总耗时 783.8s 超过上限 600s，已强制终止。session_id=..., stream_id=...
```

**这个「超时」是整轮 agent 任务（`agent.run_loop()`）的 wall-clock 预算**——包含 LLM 调用、工具执行、子代理派发、以及重试退避。代码里不存在「端点重连时间」这个概念（所有「重连」字样都指向后端 FastAPI 自恢复、远程 MCP 隧道、SSE resume 或渲染进程重挂载）。

### 四个语义碰撞的「超时」

| 层级 | 位置 | 语义 | 默认 |
| --- | --- | --- | --- |
| ① 整轮 wall-clock | `backend/api/legacy_routes.py:32` `_SAGE_LLM_TOTAL_TIMEOUT_S` | 整个 agent 任务的总耗时上限 | 600s |
| ② 单次 socket 读间隔 | `LLMConfig.timeout`（httpx） | 两次 chunk 之间的读超时 | 60s |
| ③ 代理 → 上游 socket | `PROXY_TIMEOUT_SECONDS` | 连接/读写超时 | 60s |
| ④ 错误标签 | `LLMErrorType.TIMEOUT` | transport 层超时归类 | — |

`httpx.Timeout(60)` 是**按 chunk 间隔**计的，一个持续滴灌的上游永远不触发它——所以 ① 是唯一的兜底护栏，不能删。

### 三个真缺陷

**缺陷 A（歧义）**：用户可见的三条文案都读作「超时」——`请求超时`(②) / `模型端点 {host} 响应超时`(③) / `LLM 调用超时（783s）`(①)。且 `llm_total_timeout` 在前端**零处理**：不映射成中文、不会告知用户这是「任务预算」而非「网络问题」、不会告诉用户去哪调。

**缺陷 B（预算不合理）**：600s < 既有的 `orch.subagentTaskTimeoutS` 默认 900s——**单个合法子代理就可能比整轮预算活得久**。这正是本次事故的成因：16+ 次 LLM 调用（30K–40K prompt tokens）加退避，合法长任务被误杀。

**缺陷 C（不可配置）**：`_SAGE_LLM_TOTAL_TIMEOUT_S` 是模块级常量（import 时求值），UI 改了必须重启后端才生效。

### 已确认的语义（用户决策）

- `0` = **不限上限**
- 前端默认 `llmTotalTimeoutS = 1800`
- 后端优先级：`app_settings.llmTotalTimeoutS`（键存在即用；`0` = 不限）→ 环境变量 `SAGE_LLM_TOTAL_TIMEOUT_S`（> 0）→ 内置默认 1800s
- UI 描述：「0 = 不限；设后优先于环境变量」

---

## 技术方案

### A. 消歧（Fix 1）

**后端两条文案分工**（`legacy_routes.py`）：

- **wire 形式**（进 `sessions.last_error`，供侧栏 tooltip）：`llm_total_timeout (limit=600)`
  与在途计划 `docs/plans/2026-10-22_agent-limit-error-details.md` 定义的 `"<code> (limit=<N>)"` 格式一致，复用现成的 `parseAgentErrorLimit` / `mapAgentErrorToText` 链路。
- **展示文案**（进流式 error envelope 的 `message`，供聊天横幅）：明确写「整轮任务总耗时上限」，并显式排除网络语义 + 指路设置入口。

前端 `src/shared/lib/errorMapping.ts`：

- `AGENT_RUNTIME_MESSAGES` 增 `llm_total_timeout`
- `AGENT_RUNTIME_LIMIT_UNITS` 增 `llm_total_timeout: '秒'`

**明确不改的**：

- 不动 `src/features/send-message/useChat.ts`（architecture-baseline 钉在 824 行 / 实际 823，仅剩 1 行余量）⇒ 不恢复 `chatApi.ts` 丢弃的 `error.type`；后端 prose 仍是聊天横幅最终文案。
- `classifyEndpointError` 对 `llm_total_timeout` 继续返回 `null`（端点健康，不该弹端点横幅）；`EndpointStatusBanner` 的 kind 三元无 default 分支，不新增 kind。
- `STATIC_MESSAGES` 不加码——它的键受 `LLMErrorTypeFE` 字面量联合约束。

### B. 预算策略（Fix 2）

默认 600 → **1800s**（= 2 × `orch.subagentTaskTimeoutS` 默认 900s，保证单个子代理不会比整轮预算活得久）。保留 ① 作为兜底护栏。

### C. UI 可配置（Fix 3）

**常量必须变成函数**——`_SAGE_LLM_TOTAL_TIMEOUT_S` 是模块级 import 时求值，UI 改了必须重启后端才生效。照抄 `_retry_settings()`（`backend/core/legacy/llm_client.py:72-126`）的**函数式读取**范式：每次请求读一次，**app_settings > env > 内置默认**，任何解析失败静默回退、绝不抛错。

新建 `backend/core/legacy/llm_total_timeout.py`：

```python
def llm_total_timeout_s() -> float:
    """整轮任务 wall-clock 上限。app_settings > env > 默认。0 表示不限。"""
```

`asyncio.wait_for(coro, timeout=None)` 在 py3.8 等价于 `await fut`（无超时），所以「不限」直接传 `None` 即可，无需分支。

**两个白名单必须同时改**（漏一个就静默失效）：

| 白名单 | 文件 | 漏了会怎样 |
| --- | --- | --- |
| 前端 `TOP_KEYS` | `src/entities/setting/storage.ts` | `sanitizeForBackend` **静默丢弃**该键 → 后端永远收不到 |
| 后端 `LEGAL_TOP_KEYS` | `backend/data/settings_canonicalizer.py` | PUT 返 400，且**每次 PUT 都会把已存的值剥掉** |

canonicalizer 的 `to_camel` 对未知 camelCase 键原样透传 ⇒ **不需要加 `ALIASES` 条目**。

---

## 涉及文件清单

| 文件 | 改动 |
| --- | --- |
| `backend/core/legacy/llm_total_timeout.py` | **新建**：`llm_total_timeout_s()` |
| `backend/api/legacy_routes.py` | 删模块常量 → 改调函数；重写两条文案 |
| `backend/api/settings_models.py` | `SettingsPayload` + `LegacySettingsPayload` 各加 `llmTotalTimeoutS: Optional[int]` |
| `backend/data/settings_canonicalizer.py` | `LEGAL_TOP_KEYS` 加 `"llmTotalTimeoutS"` |
| `backend/tests/contract/test_settings_schema_parity.py` | `EXPECTED_TOP_KEYS` 加 `"llmTotalTimeoutS"`（硬断言） |
| `backend/tests/unit/test_llm_total_timeout.py` | **新建**：优先级 / 0=不限 / 非法值回退 |
| `src/entities/setting/types.ts` | `AppSettings` + `DEFAULT_SETTINGS` 加 `llmTotalTimeoutS: number` |
| `src/entities/setting/storage.ts` | `TOP_KEYS` 加 `llmTotalTimeoutS` |
| `src/pages/settings/BasicTab.tsx` | 新增「LLM 任务上限」区块 + `SettingRow` + 审计快照/JSON 字段 + 两处调用点 |
| `src/pages/settings/settingsSearchIndex.ts` | 新增索引条目（keywords 须等于自身小写形式） |
| `src/pages/settings/__tests__/BasicTab.test.tsx` | 新增用例 + 回填审计字面量 |
| `src/shared/lib/errorMapping.ts` | `AGENT_RUNTIME_MESSAGES` + `AGENT_RUNTIME_LIMIT_UNITS` 加 `llm_total_timeout` |
| `src/shared/lib/errorMapping.test.ts` | 新增用例 |
| `docs/plans/2026-10-22_agent-limit-error-details.md` | 更新 `llm_total_timeout` 表格行（改为 wire 形式） |
| `docs/user-manual/20-settings.md` | 补「LLM 任务上限」条目 |

**不需要改**：`settingsRegistry.ts`、canonicalizer `ALIASES`、`src/features/send-message/useChat.ts`、`src/shared/api/chatApi.ts`。

---

## 实施步骤

- [x] 步骤 1：仓库内计划文档（本文件）
- [x] 步骤 2：新建 `backend/core/legacy/llm_total_timeout.py`（`llm_total_timeout_s()`）
- [x] 步骤 3：`backend/api/settings_models.py` 两个 payload 加 `llmTotalTimeoutS`
- [x] 步骤 4：`backend/data/settings_canonicalizer.py` `LEGAL_TOP_KEYS` 加键
- [x] 步骤 5：`backend/api/legacy_routes.py` 删常量、接函数、重写两条文案
- [x] 步骤 6：`backend/tests/unit/test_llm_total_timeout.py` + `backend/tests/contract/test_settings_schema_parity.py` 更新
- [x] 步骤 7：`src/entities/setting/types.ts`（类型 + 默认值 1800）
- [x] 步骤 8：`src/entities/setting/storage.ts` `TOP_KEYS` 加键
- [x] 步骤 9：`src/pages/settings/BasicTab.tsx` 新增区块 / 行 / 审计字段 / 两处调用点
- [x] 步骤 10：`src/pages/settings/settingsSearchIndex.ts` 索引条目
- [x] 步骤 11：`src/shared/lib/errorMapping.ts` 加 `llm_total_timeout` 映射
- [x] 步骤 12：前端测试（`BasicTab.test.tsx` 新增 + 回填审计字面量、`errorMapping.test.ts` 新增）
- [x] 步骤 13：后端 pytest + 前端 tsc / vitest / eslint 全绿（vitest 整跑 4742/4746 过，唯一失败 `ArenaAccounts.test.tsx` 与本改动无关；tsc 净、eslint 净、touch-file vitest 36/36 过、后端 pytest 92/92 过）
- [ ] 步骤 14：代码审查（code-reviewer）
- [x] 步骤 15：更新 `docs/plans/2026-10-22_agent-limit-error-details.md` 表格行（`llm_total_timeout` 改为 wire 形式）+ `docs/user-manual/20-settings.md`（补 `## 基础` 段，含 LLM 重试 + LLM 任务上限）+ 顺手修了 `errorMapping.ts` 路径文案从「基础与外观」→「基础」（与 `i18n/locales/zh/chatAndSider.ts:239` 实际 tab 标签对齐）；`legacy_routes.py` 日志空格修（LOW finding）
- [ ] 步骤 16：cherry-pick 同步到 `release/win7`（py38 环境单跑；**不得**改任何 requirements 文件；**不得** merge）

---

## 验证

```bash
# 后端（必须用 sage-backend 环境）
/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest \
  backend/tests/unit/test_llm_total_timeout.py \
  backend/tests/contract/test_settings_schema_parity.py -q

# 前端
npx tsc --noEmit
npx vitest run src/pages/settings/__tests__/BasicTab.test.tsx src/shared/lib/errorMapping.test.ts
npx eslint src/pages/settings/BasicTab.tsx src/shared/lib/errorMapping.ts src/entities/setting/storage.ts
```

**桌面端手工验证（4 步）**：

1. 设置 → 基础 → 找到「LLM 任务上限」，改成 `2`（秒）并保存
2. 重启后端（`npm run electron:dev`），发一条会耗时的消息
3. 期望：几秒后失败，文案明确说「整轮任务总耗时上限」并指向设置入口；侧栏 tooltip 显示中文（含上限值）
4. 把它改回 `1800` → 失败恢复正常；改成 `0` → 不再因总耗时终止

**验收标准**：后端 401/token 契约不受影响；`classifyEndpointError` 对 `llm_total_timeout` 仍返回 `null`（不弹端点横幅）；`useChat.ts` 行数不变（baseline 824）。

---

## 风险评估

| 风险 | 处置 |
| --- | --- |
| 漏改任一白名单 → UI 改了不生效或 PUT 400 | 步骤 3/4/8 各带契约测试；步骤 6 的 parity 测试是硬断言 |
| 改了 app_settings 后环境变量被遮蔽 | 已知代价（用户已确认）：仅首次迁移 / 「恢复默认」会写回 1800；env 仍作为「无 app_settings 键」时的兜底默认 |
| `0`（不限）导致长挂死 | 用户显式选择；UI 描述与搜索关键词都标注「0 = 不限」；默认仍为 1800 |
| `useChat.ts` architecture baseline 超限 | 明确不改该文件；新文案放后端 prose 与 `errorMapping.ts` |
| 双分支漂移 | main 先实现并验证，再 cherry-pick 到 `release/win7`；py38 环境单跑测试；**不改** `backend/requirements-py38.txt` / `backend/requirements.txt` |
| 在途未提交改动被覆盖 | 每步前后 `git status` 核对基线；`docs/plans/` 里的在途计划文档同步更新 |

## 依赖

无新增依赖。
