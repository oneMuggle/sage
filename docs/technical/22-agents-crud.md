# 22 · Agents CRUD 端到端

> Agents 管理(列出/查看/编辑/启停)的全栈链路:后端路由 → Tauri 命令 → 前端 API → UI。
> PR-3/PR-4/PR-5 三个 PR 一起把这条链路打通。

---

## 背景

`docs/05-agent.md` 设计了 4 个默认 agent(coordinator/researcher/coder/memory_manager),
但早期实现只把 dataclass 写在 `backend/agents/profiles.py`,**没有 SQLite 持久化、没有
路由、没有前端入口**。PR-3 起按"单命令一 PR"节奏分阶段补齐:

| PR | 范围 | 状态 |
|----|------|------|
| PR-3 | SQLite `agents` 表 + seed_defaults_if_empty + `GET /agents[/{id}]` + Tauri `list_agents` | ✅ |
| PR-4 | `PATCH /agents/{id}` 部分更新 + Pydantic 白名单校验 + Tauri `update_agent(id, update)` | ✅ |
| PR-5 | `PATCH /agents/{id}/toggle` 启停专用端点 + Tauri `toggle_agent` + 前端契约修复 | ✅ |

---

## 端点全表

| 端点 | 用途 | Pydantic 校验 | Tauri 命令 |
|------|------|---------------|------------|
| `GET /api/v1/agents` | 列出全部(含 disabled), 按 id 排序 | — | `list_agents()` |
| `GET /api/v1/agents/{id}` | 取单个; 404 + `agent_not_found` | — | (走 `list_agents` 客户端过滤) |
| `PATCH /api/v1/agents/{id}` | 部分更新; 422 校验 role 白名单 + max_iterations ∈ [1,50] | `AgentUpdate` | `update_agent(id, update)` |
| `PATCH /api/v1/agents/{id}/toggle` | 启用/禁用; 422 StrictBool | `AgentToggle` | `toggle_agent(id, enabled)` |

**返回**:所有写端点返回**完整最新 profile**(含新 `updated_at`),前端可一次 setState 覆盖。

---

## 双 PATCH 端点的取舍

`PATCH /agents/{id}` 本来已能改 `enabled` 字段,为什么还要单开 `PATCH /agents/{id}/toggle`?

| 维度 | `PATCH /agents/{id}` | `PATCH /agents/{id}/toggle` |
|------|---------------------|----------------------------|
| 字段范围 | 9 个字段任意子集 | 仅 `enabled` 必填 |
| 审计语义 | 杂(可能改 name 也可能切 enable) | 单一(必为启停) |
| 未来权限 | 编辑权限 | 启停权限(可与编辑分离) |
| 高频性 | 低 | 高 |
| 校验严格度 | role 白名单 / max_iterations 范围 | `StrictBool`(拒绝 `"yes"`/`1`) |

events.jsonl 里 `grep "POST.*toggle"` 比 `grep "PATCH /agents.*enabled"` 干净得多。
未来若引入 RBAC,普通用户可仅持 `agent:toggle` 而非 `agent:write`。

---

## 数据流

### 1. 列表加载(`Agents.tsx:loadAgents`)

```
Agents.tsx
  └─ agentsApi.list()
       └─ invoke('list_agents')
            └─ commands.rs::list_agents
                 └─ python_backend.get('/agents')
                      └─ legacy_routes.py::list_agents
                           └─ AgentRepository.list_all()
                                └─ SELECT * FROM agents ORDER BY id
```

### 2. 启用/禁用(`Agents.tsx:handleToggleAgent`)

```
checkbox onChange
  └─ Optimistic update (setAgents 先动 UI)
  └─ agentsApi.toggle(id, enabled): Promise<AgentProfile>
       └─ invoke('toggle_agent', { id, enabled })
            └─ commands.rs::toggle_agent
                 └─ python_backend.patch('/agents/{id}/toggle', { enabled })
                      └─ legacy_routes.py::toggle_agent
                           ├─ if get(id) is None → 404 agent_not_found
                           └─ AgentRepository.set_enabled(id, enabled)
                                └─ UPDATE agents SET enabled=?, updated_at=? WHERE id=?
  └─ setAgents 用返回的完整 profile 覆盖本地(校准 updated_at)
  └─ 出错时回滚 enabled
```

### 3. 编辑保存(`Agents.tsx:handleSave`)

```
EditAgentForm onSave
  └─ agentsApi.update(id, editForm as AgentUpdate)
       └─ invoke('update_agent', { id, update })
            └─ commands.rs::update_agent(id, AgentUpdateRequest)
                 └─ python_backend.patch('/agents/{id}', update)
                      └─ legacy_routes.py::update_agent
                           ├─ Pydantic AgentUpdate 校验 (role / max_iterations)
                           ├─ if get(id) is None → 404
                           └─ AgentRepository.update(id, payload)
  └─ setSelectedAgent + setAgents 用返回的完整 profile 覆盖
```

---

## 前端契约要点

`src/lib/api.ts`:

```ts
export interface AgentUpdate {
  name?: string;
  role?: string;
  system_prompt?: string;
  tools?: string[];
  memory_access?: string[];
  model_config?: AgentProfile['model_config'];
  max_iterations?: number;
  enabled?: boolean;
  description?: string;
}

agentsApi.update(id: string, update: AgentUpdate): Promise<AgentProfile>
agentsApi.toggle(id: string, enabled: boolean): Promise<AgentProfile>
```

**反模式**(PR-5 之前的旧代码):

```ts
// ❌ 不要把整 AgentProfile 当 update 传 —— Tauri 命令拒收
await agentsApi.update({ ...selectedAgent, name: '新名' } as AgentProfile);
```

**正确写法**:

```ts
// ✅ 仅传 diff
await agentsApi.update(selectedAgent.id, { name: '新名' });
```

---

## 校验细节

### `AgentUpdate` (PATCH /agents/{id})

| 字段 | 校验 | 失败 |
|------|------|------|
| `role` | 必须 ∈ `{coordinator, researcher, coder, memory_manager}` | 422 `invalid_role` |
| `max_iterations` | 必须 ∈ `[1, 50]` | 422 `invalid_max_iterations` |
| 其余字段 | Pydantic 自动类型校验 | 422 |
| 空 body | 视为 no-op, 返回当前 profile, `updated_at` **不刷新** | 200 |

### `AgentToggle` (PATCH /agents/{id}/toggle)

| 字段 | 校验 | 失败 |
|------|------|------|
| `enabled` | `StrictBool` — 拒绝 `"yes"`/`1` 等强转 | 422 |
| 缺 `enabled` | Pydantic 必填 | 422 |
| 同值 toggle | 200, `updated_at` **仍刷新**(`set_enabled` 总 UPDATE) | 200 |

---

## 测试覆盖

| 文件 | 用例数 | 关注 |
|------|--------|------|
| `backend/tests/integration/test_routes_agents.py` | 6 | list / get / 404 / 顺序 |
| `backend/tests/integration/test_routes_agents_update.py` | 10 | PATCH 全字段 / 校验 / 隔离 |
| `backend/tests/integration/test_routes_agents_toggle.py` | 10 | toggle / 幂等 / StrictBool / 隔离 |
| `src/features/manage-agents/__tests__/api.test.ts` | 8 | 前端契约(命令名 / 参数形状 / 返回值) |

26 个后端用例 + 8 个前端用例,覆盖三层(repo / 路由 / 前端 API)。

---

## 已知遗留

1. **`get_agent_by_id` 命名**:`legacy_routes.py:266` 的注释说"不能叫 `get_agent`,
   会覆盖 dependency provider"。未来 PR 应把 dependency 改名 `make_sage_agent()`,
   然后 `get_agent_by_id` 重命名 `get_agent`。
2. **agent 创建/删除**:目前 4 个默认 agent 在 lifespan 种子化,无 `POST /agents` /
   `DELETE /agents/{id}`。`agent_repo.py` 注释明确"id 不可改 — 保护默认 agent
   id 不会被前端误改",所以暂不开放(避免破坏 ChatService 引用)。如需自定义 agent,
   未来单开 `custom_agents` 表。
3. **AgentDetails 不显示 `updated_at`**:前端 UI 还没把这个字段渲染出来。低优先,
   未来设计时机加。
