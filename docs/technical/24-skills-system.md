# 24 — Skills 系统端到端

**最后更新**: 2026-06-19 (M11 收口)
**覆盖范围**: PR-7 (v1 builtin 端到端) + PR-8 (SKILL.md v1) + v2 适配层 (M4-M10)

> 本章合并记录 Skills 系统的全链路实现,涵盖:
> - **PR-7 缺口 C 收口**: InprocSkillAdapter + 3 路由 (list/toggle/execute) + 4 builtin
> - **PR-8 SKILL.md 适配层 v1**: frontmatter 解析 / hot loader / 路径校验
> - **v2 适配层 (M4-M10)**:
>   - M3 Loader gating (requires/os/always)
>   - M4 ResourceIndex (references/ 渲染)
>   - M5 沙箱 port (SandboxPort / subprocess 实现 / denylist)
>   - M6 确认 port (ConfirmationPort / CLI / auto-confirm)
>   - M7 ScriptRunner 编排 (路径校验 → 确认 → 沙箱 → 异常收敛)
>   - M8 execute_v2 路径 (SkillMdSkill.execute_v2 异步方法,回退 v1)
>   - M9 DispatchMode 元数据序列化 (前端 SkillDispatch interface + SkillCard UI)
>   - M10 SlashCommandRegistry (POST `/skills/command` + GET `/skills/commands`)
>
> 用户视角文档见 [`../user-manual/04-skill-md-authoring.md`](../user-manual/04-skill-md-authoring.md)
> 与 [`../user-manual/05-skill-md-migration.md`](../user-manual/05-skill-md-migration.md)。

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

---

## 9. SKILL.md 适配层 (PR-8)

> PR-8 新增: 让 Sage 兼容 AgentSkills 开放规范 (agentskills.io),与 Hermes Agent / OpenClaw / Claude Skills 生态互通。
> 完整设计文档见 `docs/plans/2026-06-18_skill-md-adapter.md` (按 `feature-development.md` 规则完工后并入本节并删除 plan 文档)。

### 9.1 双 loader 并存

Sage 现在有两套技能加载机制,**共享同一个 `SkillRegistry`**:

| Loader | 路径 | 职责 |
|---|---|---|
| builtin (Python `BaseSkill` 子类) | `backend/skills/builtin/*.py` | 4 个内置: search / writer / coder / travel |
| **SKILL.md (AgentSkills 规范)** | `backend/skills/skill_md/` (新增) | 解析 SKILL.md (YAML frontmatter + markdown body),包装为 `SkillMdSkill` |

**冲突优先级**: builtin 永远胜。SKILL.md 命名若与 builtin 冲突 (例如 `name: search`),SKILL.md 被 skip 并记 WARNING 日志。

### 9.2 发现根优先级

`backend/skills/skill_md/loader.py::discover_skill_md_dirs()` 按以下顺序返回搜索根 (不存在的目录被过滤):

1. `$SAGE_SKILLS_DIR` 环境变量指向的目录 (若存在) — 优先级最高
2. `$CWD/skills` (若存在) — 项目级
3. `~/.sage/skills` (若存在) — 用户级

每个根目录下识别 `<skill_name>/SKILL.md` 形态 (深度 1 子目录, 内含 SKILL.md 文件)。

### 9.3 支持的 frontmatter 字段 (v1)

| 字段 | 必填 | 说明 |
|---|---|---|
| `name` | ✅ | 合法 slug (小写字母/数字/连字符), 也是技能的注册名 |
| `description` | ✅ | 一句话描述 |
| `triggers` | ❌ | 触发关键词列表, 缺省时默认 `[name.lower()]` |
| `version` | ❌ | 版本号字符串, 透传到 `metadata.version` |
| `metadata` | ❌ | 任意嵌套 dict, 透传到 `metadata.frontmatter` |
| 其他任意字段 | ❌ | 原样保留在 `metadata.frontmatter`, 供聊天层高级处理 |

### 9.4 SKILL.md 形态示例

`~/.sage/skills/code-review/SKILL.md`:

```markdown
---
name: code-review
description: Review a code diff for correctness and reuse opportunities.
triggers: [review, code review]
version: 0.1.0
---

You are a careful code reviewer. For each diff, look for:
- correctness bugs
- reuse opportunities
- simplification cleanups
```

### 9.5 `execute()` 语义 (v1)

`SkillMdSkill.execute(params, context)` 是**无副作用**的纯函数:

```python
return SkillResult(
    success=True,
    content=doc.body,            # markdown body 字符串, 供聊天层拼到 system prompt
    metadata={
        "source": "skillmd",
        "name": doc.name,
        "version": doc.version,
        "frontmatter": dict(doc.raw_frontmatter),
    },
)
```

**v1 故意不调 LLM / 工具**。聊天层拿到 `content` 后自行组装到 system prompt。这样保持技能层的纯净,也避免双倍 LLM 调用 (写 builtin + 跑 skill)。

### 9.6 `{baseDir}` 占位符语义

body 中可包含 `{baseDir}`, 由聊天层替换为 `metadata.base_dir` 的绝对路径。**路径遍历防御**通过 `backend/skills/skill_md/validation.py::validate_base_dir()` 强制 base_dir 必须落在允许根 (`~/.sage/skills`、`cwd/skills`、`$SAGE_SKILLS_DIR`) 之一。

### 9.7 路由层 JSON 形状

`GET /api/v1/skills` 返回列表,每项除原有 `name/description/triggers/parameters/examples/enabled/usage_count` 7 字段外:

- builtin 时多一个 `"source": "builtin"`, **不** 输出 `body/base_dir/version`
- SKILL.md 时输出 `"source": "skillmd"` + `"body": "..."` + `"base_dir": "/path/..."` + `"version": "0.1.0"`

`POST /api/v1/skills/{name}/execute` 返回结构同 builtin, SKILL.md 技能的 `content` 是 markdown body, `metadata.source == "skillmd"`。

### 9.8 前端展示

`Skill` interface (`src/shared/api/api.ts`) 新增 5 个可选字段:

```typescript
source?: 'builtin' | 'skillmd';
body?: string;
scripts?: string[];
base_dir?: string;
version?: string;
```

`SkillCard` 在 `source === 'skillmd'` 时:

- 渲染 `skillmd` badge (accent 颜色, 与 builtin 的灰色 badge 区分)
- 渲染 `v{version}` badge (若有)
- 在卡片底部渲染 `<details>` 折叠区,点击展开 body + 显示 `base_dir` 路径

### 9.9 v1 不支持的特性 (v2 路线)

| 特性 | 说明 | v2 计划 / 状态 |
|---|---|---|
| `scripts/*.py` 执行 | AgentSkills spec 支持, 但 `exec` 用户代码风险高 | ✅ M5-M8: subprocess 沙箱 + 用户确认 + ScriptRunner 编排 + `execute_v2` 路径 |
| `references/`、`assets/`、`templates/` | 引用文件 / 模板资源 | ⏳ M4: ResourceIndex 构建（已实现）,渲染到聊天上下文待 M10+ |
| `requires.bins/env/config` 门控 | 仅在依赖满足时加载 | ✅ M3: `gating.evaluate_gating` |
| `os` 平台过滤 | 仅在指定 OS 加载 | ✅ M3: 同上 |
| `always` 跳过门控 | 始终加载 | ✅ M3: 同上 |
| `disable-model-invocation` | 不进 system prompt, 仅手动触发 | ✅ M9: DispatchMode 元数据序列化 |
| `user-invocable` | 暴露为 slash command | ✅ M9: SkillCard 渲染 slash command badge;✅ M10: POST `/skills/command` + SlashCommandRegistry |
| `command-dispatch: tool` | 直接派发到工具, 不经 LLM | ⏳ M11+: 路由层额外 endpoint |

### 9.10 DispatchMode 元数据序列化 (M9)

SKILL.md v2 frontmatter 中的 4 个 dispatch 字段（`disable-model-invocation` / `user-invocable` / `user-invocable-name` / `command-dispatch`）经 `InprocSkillAdapter.list_skills_extended()` 序列化为前端 JSON 的 `dispatch` 嵌套对象:

```json
{
  "name": "code-review",
  "source": "skillmd",
  "dispatch": {
    "disable_model_invocation": false,
    "user_invocable": true,
    "user_invocable_name": "/review",
    "command_dispatch": "auto"
  }
}
```

**契约要点**：

- builtin 技能无 `dispatch` key（TS strict optional 兼容）
- `user_invocable_name` 为 `null` 时,前端不渲染 slash command badge（不自动回退到 `name`,避免语义混淆）
- `command_dispatch='auto'` 时前端不显示 chip（默认模式,渲染会增加 UI 噪音）
- 前端 `SkillCard` 消费方式：`dispatch?.user_invocable && dispatch.user_invocable_name` 渲染等宽字体 badge；`dispatch?.command_dispatch !== 'auto'` 渲染灰色 mode chip

**消费者**：

- `src/shared/api/api.ts::SkillDispatch` 类型定义
- `src/widgets/skills/SkillCard.tsx` 渲染（slash command badge + mode chip）
- chat 层（M10+）消费 `disable_model_invocation` / `command_dispatch` 决定派发策略

### 9.11 Slash Command 暴露 (M10)

SKILL.md v2 的 `user-invocable` / `user-invocable-name` 字段通过 `SlashCommandRegistry` 暴露为运行时 slash command,提供两个新路由:

| 路由 | 方法 | 说明 |
|---|---|---|
| `/api/v1/skills/command` | POST | 执行 slash command,返回 SKILL.md body |
| `/api/v1/skills/commands` | GET | 列出所有已注册命令(供前端自动补全) |

**SlashCommandRegistry** (`backend/skills/skill_md/slash_registry.py`):

- `from_registry(registry)` 一次性构建索引:遍历 `SkillRegistry`,仅索引 `SkillMdSkill` 且 `dispatch.user_invocable=true` 的技能
- `resolve(command_name) -> SkillMdSkill | None`:接受 `/foo` / `foo` / `//foo` 等变体,内部规范化
- `execute_command(command, args)` 委托 `SkillMdSkill.execute_v2`(M8) 走 v1 body fallback 路径,返回 `SkillResult(content=body, ...)` 供聊天层注入 system prompt 模板

**契约要点**:

- **不直接执行脚本**:slash command 触发后默认返回 body 作为 prompt 模板。脚本执行仍走 POST `/skills/{name}/execute` with 显式 `script` 参数 — slash command 不直接 dispatch 脚本
- **builtin 永不索引**:`isinstance(skill, SkillMdSkill)` 检查过滤 builtin
- **404 语义**:`LookupError` 在路由层映射为 404 + `command_not_found` detail
- **reload 时需重建**:`SlashCommandRegistry` 是不可变快照,registry reload 后需重新 `from_registry()` 重建

**集成点**:

- `InprocSkillAdapter.__init__` 末尾构建 `self._slash_registry = SlashCommandRegistry.from_registry(self._registry)`
- `InprocSkillAdapter.execute_command(command, args)` 公共方法供路由层调用
- `InprocSkillAdapter.list_slash_commands()` 返回命令名列表

**消费者(M11+)**:

- 聊天层解析用户输入 `/review arg1 arg2` → 剥离 `/` 前缀 → POST `/skills/command`
- 前端自动补全通过 GET `/skills/commands` 拿命令列表

### 9.12 端到端验证

手测冒烟流程:

```bash
mkdir -p ~/.sage/skills/code-review

cat > ~/.sage/skills/code-review/SKILL.md << 'EOF'
---
name: code-review
description: Review a code diff for correctness and reuse opportunities.
triggers: [review, code review]
version: 0.1.0
---

You are a careful code reviewer. For each diff, look for:
- correctness bugs
- reuse opportunities
- simplification cleanups
EOF

# 重启后端
cd /home/fz/project/sage/backend && python -m uvicorn main:app --reload

# 列技能 (应见 4 builtin + code-review)
curl http://127.0.0.1:8765/api/v1/skills | jq '.[] | {name, source}'

# 执行 SKILL.md 技能
curl -X POST http://127.0.0.1:8765/api/v1/skills/code-review/execute \
  -H 'Content-Type: application/json' \
  -d '{"action": "run", "args": {}}'

# M10: slash command 端点 (user-invocable=true 的 SKILL.md)
curl http://127.0.0.1:8765/api/v1/skills/commands
curl -X POST http://127.0.0.1:8765/api/v1/skills/command \
  -H 'Content-Type: application/json' \
  -d '{"command": "/review", "args": []}'
```

### 9.13 风险

- **Prompt injection**: SKILL.md body 含恶意指令。聊天层应把 body 视为不可信用户内容, 包装成 system message 而非塞进开发者模板。
- **路径遍历**: `{baseDir}` 占位符可能被恶意替换到允许根之外。`validate_base_dir` 强制 base_dir 必须在允许根内。
- **LLM 行为差异**: 同一 SKILL.md 在不同 LLM 下表现可能差异大。建议作者跨模型测试。
- **Slash command 索引陈旧**: `SlashCommandRegistry` 是不可变快照,registry reload 后需重建 — `InprocSkillAdapter.hot_reload()` 路径会同步重建(M11+ 跟进)。

## 10. SKILL.md Spec Conformance (agentskills.io)

The SKILL.md adapter layer (`backend/skills/skill_md/`) conforms to the [agentskills.io open specification](https://agentskills.io/specification) since 2026-06-29. See `docs/technical/28-skill-md-spec-conformance.md` for full details, including:

- 3 new spec-optional fields (`license`, `compatibility`, `allowed-tools`)
- Strengthened `name` (≤64 chars) and `description` (≤1024 chars) validation
- Single-file `<dir>/SKILL.md` form support
- `name`-vs-parent-dir warning (soft constraint, not blocking)

All changes are forward-compatible: existing SKILL.md files continue to load without modification.
