# 2026-06-12 — 完成有设计但未实现的功能

> 本计划是 `/everything-claude-code:plan` 工作流的产出。
> 当前分支:`feat/agents-mutate`(已合入 PR-4 update_agent)。
> 计划范围:延续 PR-2/3/4 的节奏,把"有设计、文档/注释明确提及、但前后端尚未贯通"的功能闭环。

---

## 1. 背景与目标

### 1.1 现状

项目最近几个 PR 已建立"小步快走、按 PR 编号增量"的节奏:

| PR | 功能 | 范围 | 状态 |
|----|------|------|------|
| PR-2 | `delete_message` | Tauri 命令 + `POST /messages/{id}/delete` | ✅ |
| PR-3 | `list_agents` + `get_agent_by_id` | Tauri 命令 + `GET /api/v1/agents[/{id}]` + agents 表 + seed | ✅ |
| PR-4 | `update_agent` | Tauri 命令 + `PATCH /api/v1/agents/{id}` + 422 校验 | ✅ (刚合入) |

但 PR-4 落地后,**仍有 3 处"端到端未贯通"的设计缺口**(均有相关文档/注释/代码骨架,只差最后几个 PR):

#### 缺口 A:Agents CRUD 前端线缆未对齐 PR-4(BLOCKER)

- 前端 `src/lib/api.ts:574` `agentsApi.update(agent)` 仍按旧契约调用
  `invoke('update_agent', { agent })`,**但 PR-4 的 Tauri 命令签名是
  `update_agent(id, update)`**(`src-tauri/src/commands.rs:242`)
  → 当前编辑界面"保存"按钮一按必报参数错误。
- 前端 `agentsApi.toggle(id, enabled)` 调 `invoke('toggle_agent', ...)`,
  **但 `toggle_agent` Tauri 命令尚未存在**(`commands.rs` 无定义,
  `main.rs:invoke_handler` 未注册)。
- 后端 `legacy_routes.py:251` 注释明确写:**"本节路由不写 (PR-4/5 负责 PATCH /toggle)"**
  → PR-5 是预定的下一个工作单元。

#### 缺口 B:Chat 流式响应前端缺失

- 后端 `POST /api/v1/chat/stream` 已实现 NDJSON 流式协议
  (`legacy_routes.py:410`),并有完整集成测试
  (`tests/integration/test_chat_stream.py`)。
- **但 Tauri 层无 `agent_chat_stream` 命令**,前端 `chatApi` 也无流式调用方法
  → 流式 UX(thinking/acting/observing 实时反馈)无法触达用户。
- `docs/10-api.md:93-99` 明确设计了 `agent_chat_stream` 命令。

#### 缺口 C:Skills 全栈仅 UI 占位

- 前端 `pages/Skills.tsx` + `widgets/skills/{SkillCard,SkillList}.tsx`
  + `api.ts` `skillsApi.toggle()` 已存在。
- 但 Tauri 层无 `list_skills` / `toggle_skill` 命令,后端
  `SkillPort` (`backend/ports/skill.py`) 仅 Protocol,**生产 adapter
  标注 "未实现,PG3"**(`docs/technical/18-hexagonal.md:27`)。
- → 整页是"漂亮的死代码"。

### 1.2 目标

按 PR-2~4 已经建立的"单命令一 PR、后端→Tauri→前端→测试→文档"节奏,**3 个新 PR 收尾**这 3 处缺口:

1. **PR-5**:agents 前端线缆修复 + `toggle_agent` 命令(收口缺口 A,最优先)
2. **PR-6**:`agent_chat_stream` 端到端打通(收口缺口 B)
3. **PR-7**:Skills 后端 `SkillPort` 生产 adapter + 4 个 Tauri 命令(收口缺口 C)

3 个 PR 互不依赖,**可串行也可并行**(建议串行,与现有节奏一致)。

---

## 2. 涉及的文件与模块

### 2.1 PR-5:agents 前端线缆 + toggle

| 层 | 文件 | 改动 |
|----|------|------|
| 后端 | `backend/api/legacy_routes.py` | 新增 `PATCH /api/v1/agents/{id}/toggle` 路由 |
| 后端测试 | `backend/tests/integration/test_routes_agents_toggle.py` (新) | toggle 路由集成测试 (200/404/422) |
| Tauri | `src-tauri/src/commands.rs` | 新增 `toggle_agent` 命令(走 PATCH /toggle) |
| Tauri | `src-tauri/src/main.rs` | `invoke_handler` 注册 `toggle_agent` |
| 前端 | `src/lib/api.ts` | `agentsApi.update()`:`{ agent }` → `{ id, update }`;`agentsApi.toggle()` 签名校对 |
| 前端 | `src/lib/api.ts` | 新增 `AgentUpdate` 类型(对应 Tauri `AgentUpdateRequest`) |
| 前端测试 | `src/features/manage-agents/__tests__/api.test.ts` (新) | mock invoke,断言传参契约 |
| 前端 | `src/pages/Agents.tsx:46` | `handleSave` 改成传 `(id, partial)` 而非整 agent |
| 文档 | `docs/technical/22-agents-crud.md` (新) | agents CRUD 全表 |
| 文档 | `docs/technical/README.md` | 章节目录加第 22 行 |

### 2.2 PR-6:chat 流式

| 层 | 文件 | 改动 |
|----|------|------|
| Tauri | `src-tauri/src/commands.rs` | 新增 `agent_chat_stream` 命令(`StreamingResponse` → Tauri event emit) |
| Tauri | `src-tauri/src/main.rs` | 注册 `agent_chat_stream` |
| Tauri | `src-tauri/src/models.rs` | 新增 `AgentEvent` 结构体(对应后端 `AgentEvent.to_dict()`) |
| 前端 | `src/lib/api.ts` | `chatApi.chatStream(sessionId, message, onEvent)` 方法 |
| 前端 | `src/widgets/chat/MessageList.tsx` 或 `ChatInput.tsx` | 接入流式,渲染 thinking/acting/observing 状态 |
| 前端测试 | `src/features/send-message/__tests__/stream.test.ts` (新) | mock Tauri event emit |
| 文档 | `docs/technical/23-chat-streaming.md` (新) | NDJSON 协议 + Tauri event 桥接 |

### 2.3 PR-7:Skills adapter + Tauri 命令

| 层 | 文件 | 改动 |
|----|------|------|
| 后端 | `backend/adapters/out/skill/__init__.py` (新) | `InprocSkillAdapter` 实现 `SkillPort` |
| 后端 | `backend/skills/` (检查现状) | 4 个默认技能登记 (search/writer/coder/travel) |
| 后端 | `backend/api/legacy_routes.py` 或新增 `api/skill_routes.py` | `GET /skills`、`POST /skills/{name}/toggle`、`POST /skills/{name}/execute` |
| 后端测试 | `backend/tests/integration/test_routes_skills.py` (新) | skills 路由集成测试 |
| Tauri | `src-tauri/src/commands.rs` | `list_skills`、`toggle_skill`、`execute_skill` 命令 |
| Tauri | `src-tauri/src/main.rs` | 注册 3 个 skill 命令 |
| 前端 | `src/lib/api.ts` | `skillsApi.list/toggle/execute` 改 mock → 真接口 |
| 前端 | `src/pages/Skills.tsx` | 替换 mock 数据为真实接口 |
| 文档 | `docs/technical/18-hexagonal.md:27` | SkillPort 行 "未实现,PG3" → "InprocSkillAdapter" |
| 文档 | `docs/technical/24-skills-system.md` (新) | Skills 系统总览 |

---

## 3. 技术方案

### 3.1 PR-5:toggle 路由设计

**为什么 toggle 单开一个路由而不复用 PATCH /agents/{id}?**

技术上,`PATCH /agents/{id}` 已能改 `enabled` 字段(PR-4 已覆盖)。但项目代码里明确写
"PR-4/5 负责 PATCH /toggle",理由有 2:

1. **审计语义清晰**:启用/禁用是高频独立操作,日志里 `POST /agents/primary/toggle`
   比 `PATCH /agents/primary {enabled: false}` 更容易在 events.jsonl 里被单独 grep。
2. **权限边界**:未来如果加权限模型,toggle 可以单独授权(普通用户能 toggle,
   不能改 system_prompt)。

签名:

```python
@router.patch("/agents/{agent_id}/toggle")
async def toggle_agent(agent_id: str, data: ToggleRequest):
    repo = AgentRepository()
    if not repo.set_enabled(agent_id, data.enabled):
        raise HTTPException(404, ...)
    return repo.get(agent_id)
```

Tauri 命令:

```rust
#[tauri::command]
pub async fn toggle_agent(id: String, enabled: bool, state: ...) -> Result<Agent, String> {
    let path = format!("/agents/{}/toggle", id);
    state.python_backend.patch(&path, &serde_json::json!({ "enabled": enabled })).await
}
```

前端 api.ts:

```typescript
async toggle(id: string, enabled: boolean): Promise<AgentProfile> {
  return withRetry(async () => {
    try {
      return await invoke<AgentProfile>('toggle_agent', { id, enabled });
    } catch (error) {
      throw handleApiError(error);
    }
  });
}
```

### 3.2 PR-5:agentsApi.update() 契约修复

**当前签名(broken):**

```typescript
async update(agent: AgentProfile): Promise<void> {
  await invoke('update_agent', { agent });
}
```

**新签名(对齐 Tauri):**

```typescript
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

async update(id: string, update: AgentUpdate): Promise<AgentProfile> {
  return withRetry(async () => {
    try {
      return await invoke<AgentProfile>('update_agent', { id, update });
    } catch (error) {
      throw handleApiError(error);
    }
  });
}
```

**Agents.tsx 调用点改动:**

```typescript
// 旧:整对象传
const updated = { ...selectedAgent, ...editForm } as AgentProfile;
await agentsApi.update(updated);

// 新:仅传 diff(更符合 PATCH 语义)
await agentsApi.update(selectedAgent.id, editForm as AgentUpdate);
```

### 3.3 PR-6:Tauri 流式桥接

Tauri 命令收到流式响应后,通过 `app.emit("chat-stream-{stream_id}", payload)` 推送给前端,
前端用 `listen` 接收。命令本身返回 `Result<String, String>`(一个 stream_id),
方便前端 unlisten。

```rust
#[tauri::command]
pub async fn agent_chat_stream(
    session_id: String, message: String,
    app: tauri::AppHandle, state: ...,
) -> Result<String, String> {
    let stream_id = uuid::Uuid::new_v4().to_string();
    let backend = state.python_backend.clone();
    let app_clone = app.clone();
    let sid = stream_id.clone();

    tokio::spawn(async move {
        // 调后端 /chat/stream,逐行解析 NDJSON,emit 到前端
        let mut stream = backend.post_stream("/chat/stream", &body).await;
        while let Some(line) = stream.next().await {
            let _ = app_clone.emit(&format!("chat-stream-{}", sid), line);
        }
    });
    Ok(stream_id)
}
```

### 3.4 PR-7:SkillPort adapter 边界

按 18-hexagonal 章的依赖约束:`adapters/out/skill/inproc.py` 只能 import
`ports`、`domain`。所以实现进程内 skill 注册表(类似 `InprocToolAdapter`),
不依赖任何 HTTP 客户端。

---

## 4. 实施步骤

### Phase 1 — PR-5:agents 前端线缆 + toggle(最优先,2-3h)

- [ ] **4.1.1** 后端:`backend/api/legacy_routes.py` 加 `PATCH /agents/{id}/toggle`
- [ ] **4.1.2** 后端测试:`tests/integration/test_routes_agents_toggle.py`(200/404/422 + 幂等)
- [ ] **4.1.3** Tauri:`src-tauri/src/commands.rs` 加 `toggle_agent`,`main.rs` 注册
- [ ] **4.1.4** Tauri:`src-tauri/Cargo.toml` 确认 `patch` 方法已在 `python.rs` 客户端中(若无则补)
- [ ] **4.1.5** 前端:`src/lib/api.ts` 新增 `AgentUpdate` 类型,重写 `agentsApi.update / toggle`
- [ ] **4.1.6** 前端:`src/pages/Agents.tsx:46-57` `handleSave` 改用新签名,`handleToggleAgent` 同样校对
- [ ] **4.1.7** 前端测试:`src/features/manage-agents/__tests__/api.test.ts`(mock invoke,断言传参对象形状)
- [ ] **4.1.8** Manual smoke:`npm run tauri dev` → 进 Agent 管理 → 切换/编辑/保存均正常
- [ ] **4.1.9** 文档:`docs/technical/22-agents-crud.md` 新增,总结 list/get/update/toggle 4 个端点
- [ ] **4.1.10** 文档:`docs/technical/README.md` 章节目录加第 22 行
- [ ] **4.1.11** 走 feature-branch-workflow:推荐新开 `feat/agents-toggle`(保持 PR 边界)
- [ ] **4.1.12** code-review agent 自检 → push → PR → CI 绿 → 用户 merge

### Phase 2 — PR-6:chat 流式端到端(3-5h)

- [ ] **4.2.1** Tauri:`src-tauri/src/python.rs` 加 `post_stream` 方法返回 `impl Stream<Item = String>`(若不存在)
- [ ] **4.2.2** Tauri:`src-tauri/src/commands.rs` 加 `agent_chat_stream`,通过 `app.emit` 推送
- [ ] **4.2.3** Tauri:`src-tauri/src/models.rs` 加 `AgentEvent` Rust 结构体
- [ ] **4.2.4** 前端:`src/lib/api.ts` 加 `chatApi.chatStream(sessionId, message, onEvent, onError, onDone)`
- [ ] **4.2.5** 前端:`src/widgets/chat/MessageList.tsx`/`Message.tsx` 渲染 thinking/acting 中间态
- [ ] **4.2.6** 前端:`src/widgets/chat/ChatInput.tsx` 切到流式接口(保留 fallback 到非流式 `agent_chat`)
- [ ] **4.2.7** 前端测试:`src/features/send-message/__tests__/stream.test.ts`(mock `@tauri-apps/api/event`)
- [ ] **4.2.8** Manual smoke:与真实 ollama/openai 端点对话,观察事件流
- [ ] **4.2.9** 文档:`docs/technical/23-chat-streaming.md` 新增
- [ ] **4.2.10** 走 feature-branch-workflow:`feat/chat-stream`

### Phase 3 — PR-7:Skills 全栈(5-8h,最大块)

- [ ] **4.3.1** 检查现状:`backend/skills/` 目录是否已有占位代码
- [ ] **4.3.2** 后端:`backend/adapters/out/skill/inproc.py` 新增 `InprocSkillAdapter`
- [ ] **4.3.3** 后端:`backend/skills/` 落地 4 个默认 SkillSpec(参考 12-plan T3.8-3.11)
- [ ] **4.3.4** 后端:`backend/api/legacy_routes.py` 加 skills 3 路由
- [ ] **4.3.5** 后端测试:`tests/integration/test_routes_skills.py`
- [ ] **4.3.6** Tauri:`src-tauri/src/commands.rs` 加 `list_skills`/`toggle_skill`/`execute_skill`
- [ ] **4.3.7** 前端:`src/lib/api.ts` `skillsApi` 接入真接口(去掉 mock)
- [ ] **4.3.8** 前端:`src/pages/Skills.tsx` 替换 mock 数据
- [ ] **4.3.9** 前端测试:`src/widgets/skills/__tests__/SkillList.test.tsx`(数据流测试)
- [ ] **4.3.10** Manual smoke:技能列表显示真实数据 + toggle 持久化
- [ ] **4.3.11** 文档:更新 `18-hexagonal.md` SkillPort 行;新增 `24-skills-system.md`
- [ ] **4.3.12** 走 feature-branch-workflow:`feat/skills-system`

---

## 5. 风险评估与依赖

| 风险 | 级别 | 应对 |
|------|------|------|
| **PR-5 风险**:`python.rs` 客户端可能尚无 `patch` 方法,需扩 | 低 | 先 grep 确认;若无,扩 patch 即可,~10 行代码 |
| **PR-5 风险**:Agents.tsx 旧调用方式可能其它页面也在用 | 低 | grep `agentsApi.update` 确认仅此一处 |
| **PR-6 风险**:Tauri event 与 React useEffect 的取消语义 | 中 | 严格 `unlisten` + cleanup,加 stream_id 区分多个会话并行流式 |
| **PR-6 风险**:与 LLM 代理路由 (21-llm-proxy) 的协同 | 中 | `/chat/stream` 通过 `LLMPort` 走 httpx,与代理路由独立,无耦合 |
| **PR-7 风险**:SkillPort 设计可能需要返回值 schema | 中 | 先实现最小可用形态(只 list/toggle),`execute` 可分 PR-7.1 拆出 |
| **PR-7 风险**:范围大,可能阻塞 | 高 | Phase 3 可进一步拆为 PR-7a(后端 adapter+路由)、PR-7b(Tauri+前端) |
| **跨 PR 依赖** | 无 | 3 个 PR 互不依赖,可并行 |
| **CI 风险**:Win7 release 矩阵已锁版本(章 20),新 Tauri 命令不影响打包 | 低 | CI 已分 main/release/win7 双轨 |

---

## 6. 验收标准

### Phase 1 (PR-5)
- [ ] 后端 `pytest tests/integration/test_routes_agents_toggle.py` 全绿
- [ ] 前端 `npm test -- src/features/manage-agents` 全绿
- [ ] Manual:Agent 管理页面"启用/禁用"开关 + "编辑 → 保存"均正常,刷新后状态持久
- [ ] import-linter 0 violations
- [ ] CI 全绿

### Phase 2 (PR-6)
- [ ] 后端 `test_chat_stream.py` 仍绿(无回退)
- [ ] 前端流式测试覆盖 `chatStream` 主路径(thinking → done)
- [ ] Manual:对话时能看到 "🤔 思考中" → "🔧 调工具 calculator" → 答案文本逐字到达

### Phase 3 (PR-7)
- [ ] 后端 `test_routes_skills.py` 全绿,覆盖率 ≥ 80%
- [ ] 前端 Skills 页面显示 4 个默认技能,toggle 后刷新仍生效
- [ ] `18-hexagonal.md` SkillPort 状态更新为 "已实现"

---

## 7. 与其它文档的关系

- 本计划是 **`12-plan.md` 的细分实施版**(12-plan 阶段一 T1.7-T1.12 早已完成,本计划补"残缺角落")
- **不修改 `12-plan.md`** — 该文档是宏观计划,本计划是 PR 级 backlog
- 完工后:**3 个新章节归入 `docs/technical/`,本文件直接删除**(按 `feature-development.md` 规则)

---

## 8. 等待用户确认

**当前状态:计划草稿,等待用户回复**。

请确认:

1. **3 个 PR 的优先级是否如上**(PR-5 → PR-6 → PR-7)?或者您希望先做 PR-6 流式(用户体验感知最强)?
2. **是否同时启动 PR-5 + PR-6**(并行 2 个 feature 分支)?默认建议串行。
3. **PR-7 是否拆 7a/7b**(后端先,前端紧跟)?
4. **toggle 路由是单开 `/toggle` 还是复用 PATCH /agents/{id}**?(本计划倾向单开,理由见 §3.1)

回复 "proceed Phase 1" / "modify: ..." / "skip Phase 3" 等指令即可。
