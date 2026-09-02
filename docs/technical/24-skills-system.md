# 24 — Skills 系统端到端

**最后更新**: 2026-08-30 (Skills remediation 收口与死代码决策记录)
**覆盖范围**: PR-7 (v1 builtin 端到端) + PR-8 (SKILL.md v1) + v2 适配层 (M4-M10)

> **当前实现边界（2026-08-30）**：技能请求经 Electron IPC 转发到 loopback FastAPI；后端所有非健康检查路由受进程级 Bearer capability（`SAGE_LOCAL_AUTH_TOKEN`）保护。浏览器/Vite 无 Electron bridge 时对后端 API fail-closed，返回 desktop-only `BackendNotAvailableError`，不会获得或暴露 capability；因此本地后端 API 的生产路径是 Electron-only。Electron raw relay 与普通 invoke 共用 readiness gate，后端重启时 token 在 main 进程内按 generation 更新，renderer 永不接触 token。 Supervisor readiness additionally uses the protected `/health/proof` endpoint and verifies a token-bound one-way proof; a stale process cannot become ready from public `/health` alone.端点连通性聊天探测经 relay 使用 15 秒有界超时，并要求结构化 `choices` 数组才算成功。SKILL.md 脚本只有在 `SAGE_SKILL_SCRIPT_ALLOWLIST` 精确允许技能名或绝对路径根时才会通过生产确认器，随后由 `ScriptRunner` 进行路径复核；在支持 `O_NOFOLLOW` 的平台上，确认前和确认后都通过 `lstat`、`open(O_NOFOLLOW)`、`fstat` 绑定到实际打开的普通文件对象，并比较 `(st_dev, st_ino)` 与 SHA-256，路径或 inode/content 变化均 fail-closed。确认内容写入随机 0700 临时目录中的 0600 快照后执行，执行 cwd 仍保持原技能目录，finally 清理快照；不支持可靠 `O_NOFOLLOW` 的平台不回退原路径读取，而是拒绝执行。上述脚本源文件保护不等同于操作系统级隔离：执行文件来自受控快照，但为保持现有技能相对资源访问语义，`SandboxRequest.cwd` 仍为原技能目录，该目录及其中其他资源不纳入同一快照/inode 绑定保证。

> 本章合并记录 Skills 系统的全链路实现,涵盖:
> - **PR-7 缺口 C 收口**: InprocSkillAdapter + Skills 管理 API + 4 builtin
> - **PR-8 SKILL.md 适配层 v1**: frontmatter 解析 / hot loader / 路径校验
> - **v2 适配层 (M4-M10)**:
>   - M3 Loader gating (requires/os/always)
- **M4 ResourceIndex**：`backend/skills/skill_md/loader.py` 在构造 `SkillMdDocument` 时调用 `build_resource_index(path.parent)`，并将索引写入 `resources`；`SkillMdSkill` 和自动激活路径在渲染边界使用该索引授权资源，并仅输出安全逻辑相对路径。
>   - M6 确认 port (ConfirmationPort / CLI；生产确认器默认 fail-closed，白名单由 `SAGE_SKILL_SCRIPT_ALLOWLIST` 控制)
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
│ Electron main    │   GET /api/v1/skills │ SkillRegistry    │
│   commands.ts    │ ──────────────────►  │   + builtin /    │
│   IPC mappings   │                      │   SKILL.md       │
└──────────────────┘                      └──────────────────┘
```

## 2. 后端 (`backend/`)

### 2.1 `adapters/out/skill/inproc.py` — `InprocSkillAdapter`

实现 `SkillPort` 协议 (见 `backend/ports/skill.py`) + 路由层辅助方法:

| 方法                                               | 协议 | 说明                                                                                                                |
| -------------------------------------------------- | ---- | ------------------------------------------------------------------------------------------------------------------- |
| `list_skills() -> list[SkillSpec]`                 | ✅   | 把 `SkillSchema` 适配为 `domain.skill.SkillSpec` (字段同构,直接构造)                                                |
| `async execute(name, action, args) -> SkillResult` | ✅   | 优先调 `SkillMdSkill.execute_v2(params, context={})`（脚本技能走确认与沙箱），其他技能回退 `skill.execute(params, context={})`;未注册 / disabled / 执行失败 → `success=False, error=...` |
| `has_skill(name) -> bool`                          | 扩展 | 路由层 execute 前判 404 用                                                                                          |
| `is_enabled(name) -> bool`                         | 扩展 | 路由层 list/toggle 用,默认 True                                                                                     |
| `set_enabled(name, enabled) -> bool`               | 扩展 | 路由层 toggle 用,返回 False 表示 name 不存在                                                                        |
| `usage_count(name) -> int`                         | 扩展 | 路由层 list 序列化用                                                                                                |
| `bump_usage(name)`                                 | 扩展 | execute 成功时调用,累计 usage_count                                                                                 |

设计要点 (来自模块 docstring):

- 接受外部注入的 `SkillRegistry` (测试用 mock);缺省自动 `register_all_skills()` 装载 4 个 builtin
- `enabled` 状态由适配器缓存并由生命周期存储恢复；`usage_count` 由 `skill_usage` 持久化统计。
- execute 失败 (未注册 / disabled / builtin 缺工具) 一律不抛异常,与端口契约"success=False 携带 error"一致

### 2.2 `api/legacy_routes.py` — skill REST routes

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

## 3. Electron (`electron/`)

### 3.1 `commands.ts` — skill IPC mappings

Electron 的主进程命令表将 renderer 的 `invoke()` 请求转发到后端 REST API。技能相关映射包括 `list_skills`、`toggle_skill`、`archive_skill`、`execute_skill`、`delete_skill`、`list_slash_commands`、`approve_skill_draft` 和 `reject_skill_draft`。

### 3.2 `skillsIpc.ts` — rescan and import

需要文件选择或 multipart 上传的操作通过 `window.electronAPI.skills` bridge：

- `rescanSkills()` → `POST /api/v1/skills/rescan`
- `importSkills(paths)` → `POST /api/v1/skills/import`
- `pickSkillFiles()` → 系统文件选择器


## 4. 前端 (`src/`)

`skillsApi` 通过 `desktopInvoke` 提供 `list`、`toggle`、`execute`、`archive`、`delete` 和 `listSlashCommands`；`rescan` 与 `importFiles` 使用 `window.electronAPI.skills` bridge。

### 4.1 `shared/api/skillsApi.ts`

| 方法 | 签名 | Electron IPC |
|---|---|---|
| `list()` | `Promise<Skill[]>` | `list_skills` |
| `toggle(name, enabled)` | `Promise<Skill>` | `toggle_skill` |
| `execute(name, req?)` | `Promise<SkillExecuteResult>` | `execute_skill` |

### 4.2 `widgets/skills/{SkillCard,SkillList}.tsx`

- `SkillCard` 显示来源、版本、生命周期徽章和 `usage_count`。
- `SkillCard` 对 `source === "skillmd"` 的技能提供正文折叠区、归档/删除操作。
- `SkillList` 使用共享 `Skill` 类型，不维护重复的本地技能模型。

### 4.3 `pages/Skills.tsx`

负责加载技能列表、启用/禁用、归档/取消归档、删除、重扫和导入；草稿通过 `?tab=drafts` 进入 Pending Drafts 标签页。

## 5. 测试

| 文件                                                      | 覆盖                                                                                                                  |
| --------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------- |
| `backend/tests/integration/test_routes_skills.py` (12 例) | list 4 builtin / toggle (200/404/422) / execute (404/200-disabled/200-enabled-no-tools) / 默认参数 / 失败不累计 usage |
| `backend/tests/conftest.py` (新增)                        | `reset_skill_adapter` fixture — 隔离模块级 adapter 单例                                                               |
| `src/widgets/skills/__tests__/SkillList.test.tsx` (4 例)  | 渲染 name/desc/triggers/usage_count / onToggle 调用 / 空占位 / enabled 状态保留                                       |
| `src/widgets/skills/__tests__/SkillCard.test.tsx` (2 例)  | (已有,本 PR 改 usageCount → usage_count)                                                                              |

`cargo check` 绿,`tsc --noEmit` 绿,`vitest run src/widgets/skills` 6/6 绿,`pytest test_routes_skills.py` 12/12 绿。

## 6. 当前验收

- `npm run electron:dev` 是桌面端开发入口（已加 `--no-sandbox`，见 package.json）；沙箱环境推荐直接用 `./node_modules/.bin/electron --no-sandbox .`，详见 `.claude/skills/run-desktop/SKILL.md`。本项目不再使用 `npm run tauri dev`。
- 技能列表、管理路由和 Electron IPC 由各自的集成/组件测试覆盖。
- 具体技能执行是否成功取决于运行上下文是否提供所需工具；列表可见不等于每个技能都能独立执行。
- 真实 Chat 场景中的工具注入属于 ChatService 集成范围，不由技能列表页面单独保证。

## 7. 风险与限制

| 风险                                                                    | 应对                                                                                  |
| ----------------------------------------------------------------------- | ------------------------------------------------------------------------------------- |
| 路由层 execute 不注入 context.tools,builtin 大多返 success=False        | 端到端 execute 实跑留作 PR-7.1 (ChatService 集成)                                     |
| `enabled` 状态由适配器缓存并由 `skill_lifecycle` 恢复；`usage_count` 由 `skill_usage` 持久化 | 列表读取时合并持久化状态，执行成功后更新使用统计 |
| SkillExecuteResult.content 可能是 string / object / list,前端需安全渲染 | 已用 `unknown` + `Record<string, unknown>` metadata 类型,前端用 `JSON.stringify` 兜底 |
| `Skill.parameters` JSON Schema 字段,前端未做表单生成                    | 留作未来 PR (UI: "execute skill with custom args")                                    |

## 8. 后续工作 (未在 PR-7 范围)

- PR-7.1: ChatService 集成 SkillPort + context.tools 注入 + 端到端 execute 实跑
- PR-7.2: ~~Skill enabled 状态 SQL 持久化~~（已由生命周期存储覆盖）
- PR-7.3: 用户自定义 skill (UI 上传 SkillSpec JSON,存到 `user_skills` 表)
- PR-7.4: Skill parameters 表单动态生成 (基于 JSON Schema) + execute UI

---

## 9. SKILL.md 适配层 (PR-8)

> PR-8 新增: 让 Sage 兼容 AgentSkills 开放规范 (agentskills.io),与 Hermes Agent / OpenClaw / Claude Skills 生态互通。
> 设计预期见 [spec §"SKILL.md 适配层"](../superpowers/specs/2026-06-29-agentskills-io-spec-conformance-design.md)。原 plan 文档 `docs/plans/2026-06-18_skill-md-adapter.md` 从未在 git 历史中提交,具体实现见本节下文。

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

每个根目录下识别两种形态：`<skill_name>/SKILL.md`（深度 1 子目录）和根目录直接放置的 `SKILL.md` 单文件。两种形态都通过同一套 frontmatter、名称冲突和门控逻辑；同一根目录同时出现时，子目录形态先扫描，单文件形态随后扫描，已注册同名项按 builtin/先注册项优先规则跳过。
### 9.2.1 写入安全边界（2026-08-31）

`backend/skills/safe_writer.py::write_skill_file` 在 POSIX 上继续通过
`O_NOFOLLOW` 目录 fd 链和 `O_EXCL`/`O_TRUNC` 打开叶文件，避免父目录替换造成
TOCTOU。Windows Python 的普通 `os.open(str(path), ...)` 即使配合 `lstat`、
`O_EXCL` 或可选的 `O_NOFOLLOW`，也不能锁定父目录并证明 junction/reparse point
未在检查后替换；项目尚未接入经过验证的原生 Windows handle API。因此 Windows
分支在任何写入前明确 fail-closed，不创建目录、不打开目标文件，也不伪称与
POSIX 等价的保护。

导入器和审批后的 `SkillLoader` 仍复用同一 writer：Windows 上会将该安全失败
转换为既有的导入跳过/写入错误语义，POSIX 上保持原有导入、审批和非覆盖写入
行为。当前测试通过 monkeypatch 模拟 Windows 分支、no-follow 缺失及 symlink
路径拒绝；Windows 实机（包括 junction/reparse point race）尚未验证。

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

**v1 故意不调 LLM / 工具**。`execute()` 在返回 `content` 前会在 prompt 边界调用资源渲染；聊天层拿到已渲染的 `content` 后自行组装到 system prompt。`execute_v2()` 在无 `script` 参数时回退到同一 `execute()` 路径，自动激活路径也在构造 prompt context block 时渲染。这样保持技能层的纯净,也避免双倍 LLM 调用 (写 builtin + 跑 skill)。

### 9.6 `{baseDir}` 占位符语义

body 中可包含 `{baseDir}` 或 `{baseDir}/relative/path`。渲染时 `{baseDir}` 替换为安全逻辑根标识 `.`，资源引用替换为技能根目录下的逻辑相对路径（例如 `references/guide.md`、`scripts/check.py`），绝不输出宿主机绝对路径。带后缀的引用只有在 `ResourceIndex` 中记录且当前仍是 regular resource 时才允许；未索引资源、目录、symlink、路径遍历、绝对路径或 NUL 字符均拒绝并抛 `SkillMdSecurityError`。POSIX 索引继续要求 `O_NOFOLLOW`；Windows/Win7 仅恢复扫描阶段的元数据过滤索引和逻辑路径渲染，扫描时的 reparse/symlink、regular-file、隐藏项、扩展名和 containment 检查失败即跳过。该 metadata-only 索引不消除 pathname TOCTOU，不等于 Windows 实际资源读取、脚本执行或写入安全；渲染仍重新执行 reparse、regular、containment 与 index 检查，且不会在索引阶段读取内容。Windows/Win7 真机（含 junction/reparse race）尚未验证。

### 9.7 路由层 JSON 形状

`GET /api/v1/skills` 返回列表,每项除原有 `name/description/triggers/parameters/examples/enabled/usage_count` 7 字段外:

- builtin 时多一个 `"source": "builtin"`, **不** 输出 `body/base_dir/version`
- SKILL.md 时输出 `"source": "skillmd"` + `"body": "..."` + `"base_dir": "/path/..."` + `"version": "0.1.0"`

`POST /api/v1/skills/{name}/execute` 返回结构同 builtin。当前 adapter 会优先探测 `SkillMdSkill.execute_v2()`：无 `script` 参数时，`execute_v2()` 回退到同步 `execute()` 并返回 markdown body；带 `script` 参数时才进入 `ScriptRunner` 的异步路径。也就是说，v2 是当前执行入口的兼容扩展，不是无条件的脚本执行；脚本路径仍须经过允许根校验、确认器和 subprocess 沙箱。生产确认器默认 fail-closed，并仅在 `SAGE_SKILL_SCRIPT_ALLOWLIST` 中显式允许技能名或绝对路径根时批准脚本。
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
| `references/`、`assets/`、`templates/` | 引用文件 / 模板资源 | ✅ M4: `ResourceIndex` 由 SKILL.md loader 构建并挂载到 `SkillMdDocument.resources`；`execute()`、`execute_v2()` 的 body fallback 与 auto activation 在 prompt 边界渲染 |
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

技能管理与发现相关端点还包括 `POST /api/v1/skills/{name}/archive`、`POST /api/v1/skills/{name}/delete`、`POST /api/v1/skills/rescan` 和 `POST /api/v1/skills/import`；因此本章当前记录的 Skills API 共 9 个端点（含列表、切换、归档、执行、slash command、命令列表、删除、重扫、导入）。
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

## 管理:删除 SKILL.md 技能

PR-A 起,用户可以在 Skills 页面删除一个 SKILL.md 技能。

### 行为

- 操作: Skills 页面 → SkillCard 上 hover → 红色 trash 按钮 → 确认对话框
- 后端: `POST /api/v1/skills/{name}/delete` → `SkillMdDeleter.delete(name)`
- 文件操作: `shutil.rmtree(base_dir / name)` (整目录: SKILL.md + assets/ + examples/)
- Registry: 从 `_SkillRegistry` unregister,影响 `list_skills_extended()` 输出

### 约束

- 仅 `source='skillmd'`(不动 builtin)
- name 必须 `^[a-z0-9-]{1,64}$`
- target 必须在 `SAGE_SKILLS_DIR` 之下(防御 `..` 路径遍历)
- 删除审计: `logger.warning("Deleted SKILL.md skill: %s ...")` 含 base_dir

### 错误响应

| HTTP | 含义 |
|---|---|
| 200 | 成功 |
| 400 | builtin / invalid name / outside skills_dir |
| 404 | skill not found |
| 500 | filesystem error (e.g. 权限) |

### 数据流

参见 [design spec §"流 1"](../superpowers/specs/2026-06-30-skills-management-delete-hotreload-design.md#流-1用户删除-skillmd-技能)。

## 管理:自动刷新(PR-B)

用户可在 Skills 页面启用 "自动刷新 (10s)" 开关，让 UI 反映 SAGE_SKILLS_DIR 下的 SKILL.md 改动。

### 行为

- 默认 OFF
- 启用后:每 10 秒调 `skillsApi.list()`,结果 diff 并更新页面
- 失败:toast 提示,**不**关闭 toggle（下一轮再试）
- 配合 Refresh 按钮和 delete 按钮使用

### 实现位置

- `src/pages/Skills.tsx`:useState `autoRefresh` + useEffect `setInterval`
- toggle UI 在头部 Refresh 按钮左边
- 复用 PR #90 `loadSkills()` 路径

### 关闭 toggle 的清理

useEffect cleanup:`window.clearInterval(id)`,避免组件卸载后内存泄漏。

### 不在 PR-B 范围

- ❌ 实时秒级推送(需 WebSocket,不在 spec)
- ❌ 文件 watcher 后端实现(spec 明确划掉)

参见 [design spec §"流 2"](../superpowers/specs/2026-06-30-skills-management-delete-hotreload-design.md#流-2用户切换-自动刷新-启用)。

## 定时任务 (Phase 8)

> **合并来源**: 原 `docs/technical/24-scheduled-tasks.md`(已删除,56 行设计 sketch)。
> 内容已被 `24-skills-system.md` 的 gating / scripts / dispatch 章节涵盖,作为子系统小节整合。

后端驱动的 scheduler,向目标 chat session 投递一次性或周期性消息。UI 通过 `/scheduled` 页面 + 侧边栏 group 提供 create / edit / delete / run-now 入口。

### 架构

| 层 | 文件 | 职责 |
| --- | --- | --- |
| Backend | `backend/services/scheduler.py` | APScheduler `BackgroundScheduler` 调度核心 |
| Backend | `backend/api/scheduled_router.py` | `/api/v1/scheduled/*` 路由挂载点 |
| Backend | `backend/data/scheduled_tasks.json` | 持久化 (atomic write via `tempfile` + `os.replace`) |
| Frontend | `src/entities/scheduled/taskStore.ts` | Zustand store |
| Frontend | `src/shared/api/scheduledClient.ts` | IPC 客户端 |
| Frontend | `src/pages/ScheduledTasks.tsx` + `src/widgets/sidebar/sections/CronJobSection.tsx` | UI |

### Endpoints

| Method | Path | Purpose |
| --- | --- | --- |
| GET    | `/api/v1/scheduled/health` | Liveness check |
| GET    | `/api/v1/scheduled/tasks` | List all tasks |
| POST   | `/api/v1/scheduled/tasks` | Create |
| PATCH  | `/api/v1/scheduled/tasks/{id}` | Update name/enabled |
| DELETE | `/api/v1/scheduled/tasks/{id}` | Delete |
| POST   | `/api/v1/scheduled/tasks/{id}/run` | Run now |

### Storage

JSON 文件 schema: `{ "version": 1, "tasks": [...] }`。每条 task 字段:`id, name, type, schedule, session_id, content, enabled, created_at, last_run?, next_run?`。写入使用 `tempfile` + `os.replace` 保证 atomic (与 SKILL.md 删除/导入防御同思路)。

### 时区

所有 timestamp 以 UTC epoch 毫秒存储;前端通过 `Intl.DateTimeFormat` 按用户 locale 渲染。

### 错误处理

| 场景 | HTTP |
| --- | --- |
| Bad cron 表达式 | 422 + reason |
| `at` 时间已过去 | 422 |
| 缺失 `session_id` | 422 |
| task 不存在 | 404 |
| 单 job 失败 | 记日志,scheduler 继续运行(不中断其他任务) |

### 与 SKILL.md 体系的衔接

Scheduled tasks 是 chat session 维度的「何时触发」,与 SKILL.md v2 的「做什么」互补:

- **Slash Command** (§9.11) 是用户主动触发的 SKILL.md 入口;scheduled task 是后台定时投递 message 到 `session_id`,由 chat 层继续 dispatch
- 后续 Phase 可能把 schedule 类型 task 包装为 SKILL.md 的 `command-dispatch: scheduler` 形态,复用既有 dispatch registry;当前是独立子系统
- `command-dispatch` (§9.10 M11+) 的 `tool` 模式与 scheduled task 的 `run-now` 都是「不经 LLM 直接派发」的预演,设计上有交集

### 测试覆盖目标

| Module | Coverage |
| --- | --- |
| `backend/services/scheduler.py` | ≥ 95% |
| `backend/api/scheduled_router.py` | ≥ 90% |
| `src/features/scheduled/cronValidator.ts` | ≥ 95% |
| `src/shared/api/scheduledClient.ts` | ≥ 90% |
| Overall | ≥ 85% |

> **后续工作**: scheduled task 的 chat 集成 + 与 SKILL.md dispatch 体系融合(工具路径硬化)详见 in-progress plan `docs/plans/2026-07-04_chat-tool-path-hardening-from-claw-code.md`。

## 10. PR-C: Skills load-new (Rescan + Import)

PR-C 在 PR-7/8/9/10 之上增加"无需重启 backend 即可加载新 SKILL.md"的能力。

### 10.1 背景与目标

启动时 `discover_skill_md_dirs()` 增量加载 `$SAGE_SKILLS_DIR` / `./skills` / `~/.sage/skills` 三个目录。Backend 是常驻进程,之前没有运行时的"重新扫描"入口 — 用户加新 SKILL.md 后必须重启 backend。同时没有"导入"能力。

PR-C 解决:Skills 页面头部新增 2 个图标按钮,**不重启 backend** 即可:
- **重扫磁盘** — 增量加载新 SKILL.md
- **导入 SKILL.md** — 弹 native dialog 多选 `.md` 文件 → multipart 上传 → 落盘 + hot reload

### 10.2 数据流

```
┌──────────────┐                                  ┌──────────────────────────┐
│ Renderer     │  skillsApi.rescan()             │ Backend (FastAPI)        │
│ Skills.tsx   │ ──────────────────────────────► │  POST /skills/rescan     │
│              │                                  │   → SkillMdHotLoader     │
│              │  skillsApi.importFiles(paths)   │     .scan_and_load()     │
│              │ ──────────────────────────────► │  POST /skills/import     │
│              │   (window.electronAPI.skills.*) │   (multipart, files[])   │
│              │                                  │   → SkillMdImporter      │
│              │                                  │     .import_files()      │
└──────┬───────┘                                  └──────────┬───────────────┘
       │ IPC: skills:pick-files / skills:rescan / skills:import
       ▼
┌──────────────┐
│ Electron     │  dialog.showOpenDialog(...)  → 转发到后端 fetch
│ main         │
└──────────────┘
```

### 10.3 API 契约

**`POST /api/v1/skills/rescan`** → 200 `{loaded: [{name, source, path}], skipped: [{name, reason}], total_loaded: int}`
- `total_loaded` 反映本次 rescan **新增**数(非注册表总数)
- Adapter init 时已 auto-load 已有 SKILL.md,首次 rescan 通常返回 0;**加新文件后再 rescan 才能看到非零 total_loaded**
- 幂等:同样状态下重复调用 loaded=[]

**`POST /api/v1/skills/import`** (multipart `files=File[]`) → 200 `{imported: [{name, path: "."}], skipped: [{name, reason}]} `
- `imported[*].path` is always the safe logical label `"."`; the server's absolute storage path is never exposed.
- 400 if `files` empty → `{"detail": {"type": "invalid_request"}}`
- 500 on `NoSkillsDirError` → `{"detail": {"type": "no_skills_dir"}}`
- partial success:即使部分文件失败,HTTP 仍 200,失败明细在 `skipped` 数组中

**IPC channels** (`window.electronAPI.skills.*`):
- `pickSkillFiles()` → `string[] | null` (cancel returns null)
- `rescanSkills()` → `RescanResult`
- `importSkills(paths: string[])` → `ImportResult`

### 10.4 冲突处理(skipped.reason 字典)

| Reason 字符串              | 触发条件                                                  |
| -------------------------- | --------------------------------------------------------- |
| `builtin_conflict`         | name 与 builtin 冲突(builtin 胜)                        |
| `already_exists`           | 磁盘上已有同名 SKILL.md(本期不覆盖)                     |
| `invalid_name`         | name 不符合 `^[a-z0-9-]{1,64}$` slug 规则（包括 parser 抛出的 name-specific 校验错误）               |
| `parse_error`          | 缺 frontmatter、缺 name、非法 UTF-8、YAML 或其他 frontmatter/schema 解析错误（不公开异常 detail） |
| `file_too_large: ...`  | 文件 > 1MB (DoS 防御)                                     |
| `read_failed`          | multipart 读文件失败（不公开异常 detail）                  |
| `hot_reload_failed`    | 写盘成功但注册到 registry 失败（已自动 rollback 文件；不公开异常 detail） |
| `adapter_init_failed`   | (仅 rescan/import 在 init 时 import 失败时)              |

### 10.5 落地目录解析

优先级 + auto-mkdir:
1. 显式 `skills_dir` 参数(测试场景)
2. `$SAGE_SKILLS_DIR` (env 变量,存在则用)
3. `~/.sage/skills` (auto-mkdir,**首次安装用户无需手动创建**)
4. 都失败 → `NoSkillsDirError` → 500 no_skills_dir

### 10.6 实现文件

| 层       | 文件                                                          | 内容                                                    |
| -------- | ------------------------------------------------------------- | ------------------------------------------------------- |
| Backend  | `backend/skills/skill_md/exceptions.py`                       | `NoSkillsDirError`, `WriteFailedError`, `ImportValidationError` |
| Backend  | `backend/skills/skill_md/importer.py`                         | `SkillMdImporter.import_files()` + 镜像 `SkillMdDeleter` 防御性 |
| Backend  | `backend/adapters/out/skill/inproc.py`                       | 新增 `rescan_skill_mds()` + `import_skill_mds(files)` 方法 |
| Backend  | `backend/api/legacy_routes.py`                                | 2 个新 endpoint                                         |
| Electron | `electron/skillsIpc.ts` (新文件)                              | 3 个 IPC handler(pure module, DI 注入 `register`)         |
| Electron | `electron/main.ts`                                            | 调用 `registerSkillsIpc()`                               |
| Electron | `electron/preload.ts`                                         | 暴露 `window.electronAPI.skills.*` (nested, 匹配 `windowControls` 模式) |
| Renderer | `src/shared/types/electron-api.d.ts`                          | `RescanResult` / `ImportResult` / `SkillsElectronApiBridge` |
| Renderer | `src/shared/api/skillsApi.ts`                                  | `rescan()` + `importFiles(paths)` 包装                  |
| Renderer | `src/pages/Skills.tsx`                                        | 2 个新 IconButton (RotateCw / Upload) + handlers + toast |

### 10.7 测试

| 层       | 文件                                                            | 用例 |
| -------- | --------------------------------------------------------------- | ---- |
| Unit     | `backend/tests/unit/test_skill_md_importer.py`                  | 19   |
| Integ.   | `backend/tests/integration/test_skill_import.py`                | 11   |
| Unit     | `electron/__tests__/commands.test.ts` (skills IPC block)         | 8    |
| Comp.    | `src/widgets/skills/__tests__/Skills.test.tsx`                 | 8    |
| **Total**|                                                                 | **46** |

### 10.8 安全防御

- 1MB 文件 size cap (`MAX_FILE_SIZE_BYTES = 1024 * 1024` in `importer.py`)
- `^[a-z0-9-]{1,64}$` slug regex 拒 `../` `/` 空字节
- `yaml.safe_load` 不用 `yaml.load` (无 eval 风险)
- auto-mkdir **只创建目录**,不创建文件
- `hot_reload_failed` 自动 unlink 文件 + rmdir 空目录(回滚)

### 10.9 Known Limitations (计划内,不修)

- `rescan_skill_mds()` 返回 `skipped: [{name, reason}]`，加载器会报告解析、门控、冲突和实例化失败原因。
- `import` 不支持目录导入(只支持 `.md` 文件)。批量导入目录 (`dialog.showOpenDialog({properties: [openDirectory]})`) 留作未来。
- 不支持运行时切换 `SAGE_SKILLS_DIR`(需重启 backend)。
- 不支持 web 模式兼容(项目 Electron-only)。

### 10.10 失败模式 (rescan)

`SkillsElectronApiBridge` 路由结构(nested under `skills.*`):

```typescript
window.electronAPI.skills.pickSkillFiles()  // → string[] | null
window.electronAPI.skills.rescanSkills()    // → RescanResult
window.electronAPI.skills.importSkills(paths: string[])  // → ImportResult
```

不使用 flat top-level(避免与 `windowControls` 模式冲突)。

参见 design spec: `docs/superpowers/specs/2026-07-01-skills-load-new-design.md`

## 10.11 技能使用跟踪 + 技能 Nudge (2026-08-02, PR #269)

### 10.11.1 SkillUsageStore（持久化聚合统计）

`backend/skills/usage.py` — 按技能名聚合 `use_count / success_count / last_used_at`，
持久化到 SQLite `skill_usage` 表（借鉴 hermes-agent `.usage.json` 概念）：

```sql
CREATE TABLE skill_usage (
    name TEXT PRIMARY KEY,
    use_count INTEGER DEFAULT 0,
    success_count INTEGER DEFAULT 0,
    last_used_at INTEGER   -- ms epoch
);
```

- **best-effort**：DB 写入失败只 warning，绝不抛错（使用统计是辅助数据）。
- **UPSERT 幂等**：按 `name` 主键增量累加。
- 全局单例 `get_usage_store()` / `reset_usage_store()`（测试用）。

### 10.11.2 计数接入点（InprocSkillAdapter）

`bump_usage()` 现已在**全部执行路径**的成功分支自动调用：

| 路径 | 调用点 |
|------|--------|
| `execute()`（REST + SkillTool + 任何调用方） | 成功即 bump |
| `execute_command()`（slash command） | 成功即 bump |
| `auto_activate()`（A16 自动激活） | 命中即 bump |

- 移除 `execute_skill` 路由的显式 `bump_usage`（集中到 adapter，避免重复计数）。
- **重启不归零**：`__init__` 从 `skill_usage` 表回填 `_usage_count`（`_hydrate_usage_from_db`）。
- 前端 `list_skills` 已读 `adapter.usage_count()`，自动受益。

### 10.11.3 技能 Nudge（ChatService）

复杂轮次（单轮工具调用 ≥ 4 且未自动激活技能）时，在 assistant 回复末尾追加
"建议保存为技能"提示（`SKILL_NUDGE_SUFFIX`）。best-effort，阈值 4 以下不触发。
nudge 文本在喂给记忆提取器前被剥离（避免被提取为"记忆事实"）。

### 10.11.4 相关文件

- 新增：`backend/skills/usage.py`、`backend/tests/unit/test_skill_usage_tracking.py`
- 修改：`backend/adapters/out/skill/inproc.py`、`backend/api/legacy_routes.py`、`backend/application/services/chat_service.py`
- 新表：`skill_usage`（`database.py` 幂等建表）

## 12. Remediation 收口：保留项与待接线决策（2026-08-30）

本节记录对 Skills 全链路只读审计后的最终决策。本轮**只更新文档，不删除代码、测试或数据库表**；“保留”不等于已经接入生产调用链，具体状态见下表。

### 12.1 `resources.py`：保留实现，已接入 loader

`backend/skills/skill_md/resources.py` 已实现 `ResourceIndex`、`build_resource_index()` 与
`render_body_with_resources()`，并由 `backend/skills/skill_md/__init__.py` 导出；资源目录白名单为
`scripts/`、`references/`、`assets/`、`templates/`，路径替换会经过 `resolve()` 后的 base-dir 校验。

当前 loader 在构造 `SkillMdDocument` 时为每个技能目录建立 `ResourceIndex` 并写入 `resources` 字段。
`SkillMdSkill.execute()` 在 prompt 边界渲染 body；`execute_v2()` 在无 `script` 参数时 fallback 到该路径，
而 `auto_activate()` 也在构造注入 system prompt 的 context block 时渲染。因此资源已经进入这些执行/激活路径的
聊天 prompt 内容，不是“待接线”。渲染只输出安全逻辑根标识 `.` 或技能根目录下的相对路径，绝不输出宿主机
绝对路径；只有索引中的当前 regular resource 才可引用。POSIX 索引要求 `O_NOFOLLOW`；Windows/Win7 仅提供
metadata-only 的 ResourceIndex 枚举和逻辑路径渲染，不能宣称消除 pathname TOCTOU，也不代表 Windows 实际资源
读取、脚本执行或写入安全。渲染仍重新检查 reparse/symlink、regular、containment 和 index，索引阶段不读取内容；
Windows/Win7 真机验证（包括 junction/reparse race）尚未完成。未索引资源、目录、symlink/reparse point、路径遍历、
绝对路径、反斜杠或 NUL 字符均拒绝并抛 `SkillMdSecurityError`。

### 12.2 Slash command：保留后端能力，前端调用待接线

Slash command 不是孤儿能力：`SlashCommandRegistry` 已由 `InprocSkillAdapter` 构建，
`POST /api/v1/skills/command` 与 `GET /api/v1/skills/commands` 已有路由和集成测试，
`backend/tools/skill_tool.py` 也复用 `execute_command()`。命令默认只返回 SKILL.md body 作为 prompt 模板，
不直接执行脚本；脚本仍须走显式 `script` 参数的安全执行路径。这些是保留该能力的理由。

`src/shared/api/skillsApi.ts::listSlashCommands()` 当前没有 renderer 调用方，因此前端自动补全仍是待接线项，
不是已交付的用户流程。后续应在 ChatInput 的命令解析/补全链路中接入 GET 结果，并处理 registry reload 后的
不可变快照重建；在此之前不得把“存在 API”写成“聊天框已支持 slash command”。

### 12.3 只读审计后的死代码决策

| 项目 | 当前事实 | 决策 | 状态标签与后续动作 |
|---|---|---|---|
| `backend/adapters/out/skill/persona_loader.py` 与 `personas/` | 实现完整且有独立测试，但当前后端没有生产调用方，并从该包导出 | **保留** | `待接线候选`：若恢复 Persona/A5 产品范围，另立接线计划；在未确定替代方案前不删实现和测试 |
| `backend/skills/pattern_detector.py` | 有实现和测试；当前没有生产调用方，但被记忆/Background Review 文档作为能力引用 | **保留** | `待接线候选`：明确触发器、调用点和结果持久化后再接入；在此之前不得删除测试以掩盖未接线事实 |
| `backend/tools/skill.py::SkillHotLoader` | 旧 Python `BaseSkill` 文件扫描/热加载器，仍被 `backend.tools` 导出且有完整测试；SKILL.md 使用的是 `skill_md/loader.py` | **保留，标记弃用候选** | `弃用候选`：新代码不得把它当作 SKILL.md loader；待确认 builtin 迁移、外部导入和 release/win7 影响后，再单独制定删除/迁移方案 |
| `backend/data/database.py` 的 `skills` 表 | 旧 schema 含 `code TEXT NOT NULL` 等字段，当前后端没有读写；`skill_usage` 与 `skill_lifecycle` 才是当前 Skills 状态/统计表 | **保留，标记弃用候选** | `弃用候选`：本轮不复用、不新增写入；待数据库迁移策略、旧用户数据兼容和两分支验证完成后再决定弃表 |

上述四项均不属于本轮可安全删除的“已确认死代码”。删除它们会同时改变测试边界、公开导出、历史兼容或数据库迁移语义，
因此本章采用“保留 + 明确标签”，而不是以删除代替架构决策。

### 12.4 剩余风险

- ResourceIndex 已进入 SKILL.md loader，并挂载到每个 `SkillMdDocument.resources`；`execute()`、`execute_v2()` 的 body fallback 与 `auto_activate()` 已在 prompt 边界渲染资源。后续仍可补充资源数量/大小上限及更多聊天层消费集成测试，但不得放宽现有路径校验。
- Slash command 的后端快照在 reload 后必须重建，且 renderer 尚未接入自动补全；当前仅能把它视为已测试的后端能力。
- PersonaLoader、PatternDetector 的保留会维持维护成本和测试成本，但贸然删除可能丢失尚未兑现的产品能力；应以独立接线或弃用迁移任务收口。
- 旧 `SkillHotLoader` 与 `skills` 表并存会造成“两个历史模型仍可见”的认知负担；在没有兼容性审计和 migration 方案前，继续保留比破坏现有安装更安全。
