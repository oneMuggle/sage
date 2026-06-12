# 24 — Skills 系统端到端 (PR-7)

> 收口 [`docs/plans/2026-06-12_finish-designed-features.md`](../plans/2026-06-12_finish-designed-features.md) 的"缺口 C":
> 前端 `pages/Skills.tsx` + `widgets/skills/{SkillCard,SkillList}.tsx` + `api.ts::skillsApi.toggle()` 早已存在,
> 但 Tauri 层无 `list_skills / toggle_skill / execute_skill` 命令,
> 后端 `SkillPort` (`backend/ports/skill.py`) 仅 Protocol,**生产 adapter 标注"未实现,PG3"**。
> 本章记录端到端贯通方案。

## 1. 全景

```
┌──────────┐   GET  /skills              ┌──────────────────┐
│ Frontend │ ──────────────────────────► │ Python FastAPI   │
│  (React) │ ◄────────────────────────── │  legacy_routes   │
│          │   Skill[] (snake_case JSON) │   │              │
└────┬─────┘                              │   ▼              │
     │  invoke('list_skills')             │ InprocSkill      │
     │  invoke('toggle_skill', ...)      │ Adapter          │
     ▼                                    │   │              │
┌──────────────────┐                      │   ▼              │
│ Tauri Rust       │   GET /api/v1/skills │ SkillRegistry    │
│   list_skills    │ ──────────────────►  │   + 4 builtin    │
│   toggle_skill   │                      │   (search/writer │
│   execute_skill  │                      │    /coder/travel)│
└──────────────────┘                      └──────────────────┘
```

## 2. 后端 (`backend/`)

### 2.1 `adapters/out/skill/inproc.py` — `InprocSkillAdapter`

实现 `SkillPort` 协议 (见 `backend/ports/skill.py`) + 路由层辅助方法:

| 方法                                               | 协议 | 说明                                                                                                                |
| -------------------------------------------------- | ---- | ------------------------------------------------------------------------------------------------------------------- |
| `list_skills() -> list[SkillSpec]`                 | ✅   | 把 `SkillSchema` 适配为 `domain.skill.SkillSpec` (字段同构,直接构造)                                                |
| `async execute(name, action, args) -> SkillResult` | ✅   | 内部调 `skill.execute(params, context={})` 同步方法;未注册 / disabled / builtin 缺工具 → `success=False, error=...` |
| `has_skill(name) -> bool`                          | 扩展 | 路由层 execute 前判 404 用                                                                                          |
| `is_enabled(name) -> bool`                         | 扩展 | 路由层 list/toggle 用,默认 True                                                                                     |
| `set_enabled(name, enabled) -> bool`               | 扩展 | 路由层 toggle 用,返回 False 表示 name 不存在                                                                        |
| `usage_count(name) -> int`                         | 扩展 | 路由层 list 序列化用                                                                                                |
| `bump_usage(name)`                                 | 扩展 | execute 成功时调用,累计 usage_count                                                                                 |

设计要点 (来自模块 docstring):

- 接受外部注入的 `SkillRegistry` (测试用 mock);缺省自动 `register_all_skills()` 装载 4 个 builtin
- `enabled` / `usage_count` 进程内 state,重启归零 — 计划文档 §5 列为"未来可拆 PR-7.1"
- execute 失败 (未注册 / disabled / builtin 缺工具) 一律不抛异常,与端口契约"success=False 携带 error"一致

### 2.2 `api/legacy_routes.py` — 3 个 skill 路由

| Method | Path                            | Body                           | 200                                     | 4xx                                                 |
| ------ | ------------------------------- | ------------------------------ | --------------------------------------- | --------------------------------------------------- |
| GET    | `/api/v1/skills`                | —                              | `Skill[]` (含 enabled / usage_count)    | —                                                   |
| POST   | `/api/v1/skills/{name}/toggle`  | `{ "enabled": bool }`          | 完整 skill dict (含新 enabled)          | 404 (name 不存在) / 422 (FastAPI 自动 enabled 校验) |
| POST   | `/api/v1/skills/{name}/execute` | `{ "action": "", "args": {} }` | `{ success, content, metadata, error }` | 404 (name 不存在) / 422 (args 类型错)               |

实现细节:

- `_skill_adapter_singleton` 模块级 cache,避免 toggle 后状态错位 (路由层 → adapter → 内存 state)
- `_skill_to_dict(spec, enabled, usage_count)` 统一序列化器,list / toggle 共用
- execute 路由先 `adapter.has_skill(name)` 判 404,与 disabled (200 + success=False) 区分
- execute 失败 → 200 + success=False,**不抛 4xx/5xx**;前端按 `success` 字段判定

### 2.3 builtin skills

`backend/skills/builtin/` 已有 4 个 (search / writer / coder / travel) + `register_all_skills()` 自动注册。

注意:**builtin 大多依赖 `context.tools['web_search']` 等工具,路由层 execute 传 `context={}` 时多数 builtin 会返回 success=False "工具不可用"** —
端到端跑通需在 ChatService 注入 context.tools,留作未来 PR。本 PR 负责"列表/启用/禁用"的端到端可见,execute 主要用来单测契约 (200 透传 success/error)。

## 3. Tauri (`src-tauri/src/`)

### 3.1 `models.rs` — Skill / SkillExecuteResult

```rust
pub struct Skill {
    pub name, description, triggers, parameters, examples,
    pub enabled: bool, pub usage_count: i32,
}
pub struct SkillExecuteResult {
    pub success: bool, pub content: Option<Value>,
    pub metadata: Value, pub error: Option<String>,
}
```

字段命名与后端 JSON 字段一致 (snake_case),与项目惯例对齐 (参考 `Agent.system_prompt` 等)。

### 3.2 `commands.rs` — 3 个 skill 命令

| 命令                                                                      | 后端映射                                      |
| ------------------------------------------------------------------------- | --------------------------------------------- |
| `list_skills() -> Result<Vec<Skill>, String>`                             | `GET /api/v1/skills`                          |
| `toggle_skill(name, enabled) -> Result<Skill, String>`                    | `POST /skills/{name}/toggle` (返回完整 Skill) |
| `execute_skill(name, action, args) -> Result<SkillExecuteResult, String>` | `POST /skills/{name}/execute`                 |

`main.rs` `invoke_handler!` 注册 3 个新命令。

## 4. 前端 (`src/`)

### 4.1 `lib/api.ts` — `skillsApi`

| 方法                    | 签名                                                           | Tauri 命令      |
| ----------------------- | -------------------------------------------------------------- | --------------- |
| `list()`                | `Promise<Skill[]>`                                             | `list_skills`   |
| `toggle(name, enabled)` | `Promise<Skill>` (返回完整 skill)                              | `toggle_skill`  |
| `execute(name, req?)`   | `Promise<SkillExecuteResult>` (success/content/metadata/error) | `execute_skill` |

`Skill` interface 字段 snake_case (`usage_count`),与 AgentProfile 等保持一致。

### 4.2 `widgets/skills/{SkillCard,SkillList}.tsx`

- `SkillCard` props 用 `usage_count: number` (替换原 `usageCount`)
- `SkillList` 内部 `Skill` 类型从 `lib/api` 导入,去掉本地副本

### 4.3 `pages/Skills.tsx`

已经在用 `skillsApi.list/toggle`,本 PR 仅把字段 `usageCount` → `usage_count`。

## 5. 测试

| 文件                                                      | 覆盖                                                                                                                  |
| --------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------- |
| `backend/tests/integration/test_routes_skills.py` (12 例) | list 4 builtin / toggle (200/404/422) / execute (404/200-disabled/200-enabled-no-tools) / 默认参数 / 失败不累计 usage |
| `backend/tests/conftest.py` (新增)                        | `reset_skill_adapter` fixture — 隔离模块级 adapter 单例                                                               |
| `src/widgets/skills/__tests__/SkillList.test.tsx` (4 例)  | 渲染 name/desc/triggers/usage_count / onToggle 调用 / 空占位 / enabled 状态保留                                       |
| `src/widgets/skills/__tests__/SkillCard.test.tsx` (2 例)  | (已有,本 PR 改 usageCount → usage_count)                                                                              |

`cargo check` 绿,`tsc --noEmit` 绿,`vitest run src/widgets/skills` 6/6 绿,`pytest test_routes_skills.py` 12/12 绿。

## 6. 验收

- [x] `pytest backend/tests/integration/test_routes_skills.py` 12/12 绿
- [x] `cargo check` 全绿
- [x] `tsc --noEmit` 全绿
- [x] `vitest run src/widgets/skills` 6/6 绿
- [x] pre-commit + pre-push hooks 全绿
- [ ] Manual: `npm run tauri dev` → Skills 页面展示 4 个 builtin (search/writer/coder/travel),toggle 持久化
- [ ] Manual: 真实 Chat 场景中触发 skill (需 ChatService 注入 tools, 留作 PR-7.1 范围)

## 7. 风险与限制

| 风险                                                                    | 应对                                                                                  |
| ----------------------------------------------------------------------- | ------------------------------------------------------------------------------------- |
| 路由层 execute 不注入 context.tools,builtin 大多返 success=False        | 端到端 execute 实跑留作 PR-7.1 (ChatService 集成)                                     |
| `enabled` / `usage_count` 进程内 state,重启归零                         | 未来可加 SQL 持久化,与 Agent toggle (PR-5) 对齐                                       |
| SkillExecuteResult.content 可能是 string / object / list,前端需安全渲染 | 已用 `unknown` + `Record<string, unknown>` metadata 类型,前端用 `JSON.stringify` 兜底 |
| `Skill.parameters` JSON Schema 字段,前端未做表单生成                    | 留作未来 PR (UI: "execute skill with custom args")                                    |

## 8. 后续工作 (未在 PR-7 范围)

- PR-7.1: ChatService 集成 SkillPort + context.tools 注入 + 端到端 execute 实跑
- PR-7.2: Skill enabled 状态 SQL 持久化 (与 agents.enabled 同套路)
- PR-7.3: 用户自定义 skill (UI 上传 SkillSpec JSON,存到 `user_skills` 表)
- PR-7.4: Skill parameters 表单动态生成 (基于 JSON Schema) + execute UI

PR-7 完工后,`docs/plans/2026-06-12_finish-designed-features.md` 可删除(按 `feature-development.md` 规则)。
