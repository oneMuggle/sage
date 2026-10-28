# 技能智能沉淀与全栈优化 — 设计规格

- **日期**:2026-10-27
- **作者**:Claude (brainstorming with user)
- **状态**:Draft — 待用户 review
- **分支**:`feat/skill-intelligent-consolidation` (base: `release/win7` @ `215a0b61e`)
- **Worktree**:`.worktrees/feat-skill-intelligent-consolidation` (backend `:8777` / frontend `:1432`)

---

## 0. 背景与调研结论

### 0.1 系统现状

Sage 的技能系统分两套并行的执行体系，共用 `SkillRegistry`：

| 体系 | 数量 | 加载 | 执行 | 依赖 |
|---|---|---|---|---|
| **Builtin Python** | 4 (`search`/`writer`/`coder`/`travel`) | `backend/skills/__init__.py::register_all_skills()` | `InprocSkillAdapter.execute()` → `execute_v2(params, context={})` | `context.tools`（路由层传空 dict） |
| **SKILL.md** | 6 shipped + 用户导入 | `loader.py::register_skill_md_skills()` → `SkillMdHotLoader.scan_and_load()` | `SkillMdSkill.execute_v2()` 脚本分发 + body fallback | body 指令 + `allowed-tools` 声明 |

`AcademicSearchSkill`（`backend/skills/builtin/academic_search.py`）类存在但**未注册**，仅测试用。

### 0.2 运行时激活链路（已验证）

```
加载:  discover_skill_md_dirs() (~/.sage/skills, $SAGE_SKILLS_DIR, ./skills)
       + _discover_shipped_dir()  →  loader.py:587 register_skill_md_skills()
门控:  gating.py:82 evaluate_gating()  →  requires.bins / requires.env / requires.config / os / always
       不满足 → 不进 registry（loader.py:382 _record_skip，WARNING 日志）
匹配:  auto_activation.py:203 auto_activate()  →  extract_triggers() + _matches()【子串匹配】
注入:  <system-reminder>Skill 'name' auto-activated: desc...</system-reminder>\n\n<body>
       多块以 \n\n---\n\n 分隔
```

显式调用两条路：
- **`@skill:name`** → `entity_refs.py:175 _resolve_skill()` → **只注入 description**（`/{name}: {desc[:300]}`），不执行
- **`/name`** → `POST /api/v1/skills/command` → `InprocSkillAdapter.execute_command()` → `execute_v2()` → body 作为用户消息发送（`ChatInput.tsx:499-509`）

### 0.3 已有的沉淀机制（完整）

| 触发方式 | 实现 | 状态 |
|---|---|---|
| LLM 显式沉淀 | `skill_save` 工具 (`backend/tools/skill_save_tool.py`) | 完整 |
| 用户主动 `/learn` | `ChatInput.tsx:435` → `POST /api/v1/learn` → `explicit_learn` 事件 | 完整 |
| 重复模式检测 | `repeated_pattern` trigger (`review_queue.py:300`) | 完整（签名简单） |
| 复杂回合检测 | `complex_turn` signal (`chat_service.py:467-490`) | 完整 |
| 周期巡检 | `SkillConsolidationTask` (`evolution.py:1164`)，每周，默认启用 | 完整 |

所有路径最终落 `skill_drafts` 表（status=`pending`），走 `/skills?tab=drafts` 的 approve/reject。

**结论：能力完整，但用户感知不到。** 这是本设计要解决的核心问题。

### 0.4 调研发现的全部缺口

| # | 缺口 | 位置 | 级别 |
|---|---|---|---|
| 1 | 无技能市场 / 发现 UI | — | 架构级 |
| 2 | 无技能创建 UI | — | 架构级 |
| 3 | `allowed-tools` 不强制（仅 UI 显示） | `skill.py:85` | 架构级 |
| 4 | 自动激活是子串匹配（非语义） | `auto_activation.py:123` | 架构级 |
| 5 | `@skill:name` 不执行技能（只注 description） | `entity_refs.py:248` | 架构级 |
| 6 | ChatInput 技能列表不热更新（`useEffect([],)` mount-only） | `ChatInput.tsx` | bug |
| 7 | 门控失败不可见（仅 WARNING 日志） | `gating.py` / `loader.py:382` | 架构级 |
| 8 | 帮助文档过期（`@技能名` / `triggers` / 虚构 builtin 名单） | `src/content/help/skills.md` | bug |
| 9 | `SkillExecuteResult.content` 类型不统一（`ChatInput.tsx:497` 用 `typeof content === 'string'` 兜底） | — | bug |
| 10 | 路由层 `execute` 不注入 `context.tools`（builtin 多返 `success=False`） | `inproc.py:229` | 架构级 |
| 11 | `requires.config` 未实现（代码标注 "v1 暂不支持"） | `gating.py:69` | bug |
| 12 | `SlashCommandRegistry` 不可变快照（reload 后不重建） | `slash_registry.py:10` | bug |
| 13 | 无后台文件监听（热重载需手动 `POST /skills/rescan`） | `loader.py:522` | 架构级 |
| 14 | Prompt injection 风险（body 注入前无净化） | `auto_activation.py:169` | 架构级 |

---

## 1. 目标与非目标

### 1.1 目标

| 维度 | 当前 | 目标 |
|---|---|---|
| 沉淀可感知性 | 0%（后台静默） | 主动提示：对话结束卡片 + 巡检通知 toast |
| 沉淀触发步骤 | 3 步 | 1 步（点击卡片按钮 / 图标） |
| 自动激活准确率 | ~40%（子串） | ~85%（embedding 召回 + LLM 精排） |
| Token 消耗 | 整段 body 注入 | 渐进披露（description 优先，body 按需） |
| 技能创建方式 | 手写 SKILL.md | 应用内编辑器 + AI 辅助生成 |
| 门控可观测性 | 仅 WARNING 日志 | UI 显示具体失败原因 |
| 技能发现 | 手动导入文件 | 市场 Tab（只读聚合） |
| 已知 bug | 5 个 | 全部清零 |

### 1.2 非目标（YAGNI）

- **不做技能市场后端** — 只读聚合外部源，不托管、不审核、不计费
- **不做 `allowed-tools` 运行时强制** — 声明性元数据，UI 可见即可；强制需要 tool policy 沙箱，超出本期
- **不做 `command-dispatch: tool` 路径**（技能直接派发工具不经 LLM）— 现有 `dispatch` 字段已解析但未实现，标注 M11+ 跟进
- **不做技能间依赖管理** — 无版本协商、无依赖解析
- **不引入新的 embedding 服务** — 复用已有 `ModelEmbedder`（`backend/memory/embedder.py`），无 provider 时降级到子串匹配
- **本期不在 main 上实现** — 本 worktree 基于 `release/win7`（py3.8 / pydantic v1）；功能完成后按双分支策略 cherry-pick 回 `main`，需做 py3.10 / pydantic v2 适配验证

---

## 2. 架构总览

```
┌─────────────────────────────────────────────────────────────────────┐
│  Electron Main                                                      │
│  ├── skills:notify          ← 新增：统一沉淀通知出口                 │
│  └── (轮询 GET /skills/notifications，转 webContents.send)          │
└──────────────┬──────────────────────────────────────────────────────┘
               │ IPC
┌──────────────▼──────────────────────────────────────────────────────┐
│  Renderer                                                          │
│  ├── Chat.tsx                                                       │
│  │    ├── ConsolidationCard  ← 新增：对话结束"要不要沉淀？"卡片     │
│  │    └── SkillRefChip       ← 改：@skill: 点击 → 打开技能详情       │
│  ├── ChatInput.tsx                                                 │
│  │    └── dynamicSlashCommands ← 改：订阅 skills_changed 通知        │
│  └── Skills.tsx                                                     │
│       ├── SkillCard          ← 改：门控失败原因 badge                 │
│       ├── SkillEditorModal   ← 新增：frontmatter + body 编辑器      │
│       └── MarketTab          ← 新增：只读市场聚合                    │
└──────────────┬──────────────────────────────────────────────────────┘
               │ HTTP
┌──────────────▼──────────────────────────────────────────────────────┐
│  Backend                                                           │
│  ├── skills/skill_md/auto_activation.py                            │
│  │    ├── 匹配：子串 → embedding 召回 + LLM 精排                    │
│  │    └── 注入：整段 body → 渐进披露（description 优先）            │
│  ├── skills/skill_md/sanitizer.py    ← 新增：body 注入前净化        │
│  ├── skills/skill_md/slash_registry.py ← 改：reload 时重建          │
│  ├── skills/skill_md/gating.py       ← 改：记录失败原因             │
│  ├── skills/skill_md/loader.py       ← 改：暴露 skip 明细           │
│  ├── skills/skill_md/watcher.py      ← 新增：文件监听               │
│  ├── skills/consolidator.py            ← 已有：改 embedding 签名      │
│  │    └── 语义签名：hash → 语义相似度                              │
│  ├── adapters/out/skill/inproc.py    ← 改：execute 注入 context.tools│
│  ├── chat/entity_refs.py             ← 改：@skill: 可选执行          │
│  ├── chat/consolidation_hint.py      ← 新增：回合级沉淀提示检测      │
│  └── api/legacy_skills_routes.py     ← 改：market / editor 端点      │
└─────────────────────────────────────────────────────────────────────┘
```

**设计原则**：
1. **渐进增强** — 任一新能力不可用时降级到现有行为，不报错、不阻断对话
2. **后端为唯一真相源** — 前端不做匹配/门控判断，全部走后端 API
3. **单一通知出口** — 所有沉淀相关通知走 `skills:notify` IPC，前端一个 listener

---

## 3. 第 0 节：基础修复（bug fix）

**范围**：缺口 #6 #8 #9 #11 #12。这些是独立可验证的 bug，应先于所有新功能合入。

### 3.1 ChatInput 技能列表热更新（#6）

**现状**：`ChatInput.tsx` 的 `useEffect(..., [])` 空依赖，mount 时加载一次，注释明说 "re-mount or restart app to pick up new SKILL.md"。

**改法**：由 §9.3 的 watcher 驱动。

- 后端 `InprocSkillAdapter` 在 rescan / import / delete 后广播 `skills:notify{kind:'skills_changed', revision}`
- 前端 `ChatInput.tsx` 订阅 `skills_changed` → 重新拉 `skillsApi.list()` 更新 `dynamicSlashCommands`
- `useEffect` 保留 mount 时的一次性拉取作为初始值，订阅只做增量刷新

> **为什么不用轮询 revision header**：§9.3 已引入 `watchdog` 做后端热重载（新增依赖），前端通知复用同一条链路即可，不引入第二条机制。§9.3 记录 watcher 不可用时的降级路径。

**测试**：后端单测（rescan 后发出 `skills_changed`）；前端单测（收到事件 → 重新 fetch）。

### 3.2 帮助文档同步（#8）

`src/content/help/skills.md` 重写。逐条修正：

| 现有错误 | 修正为 |
|---|---|
| `@技能名` 前缀 | `@skill:name`（仅注 description）+ `/name`（slash 命令，真正执行） |
| `triggers` 字段 | `when_to_use` |
| builtin 名单 `code-review`/`commit`/`office` | 实际 4 个：`search`/`writer`/`coder`/`travel` |
| SKILL.md 位置 `~/.sage/skills/` 唯一 | 实际优先级（`loader.py:84 discover_skill_md_dirs`）：`$SAGE_SKILLS_DIR` → preference `skills_dir` → `$CWD/skills` → `~/.sage/skills` → shipped（只读模板，同名被高优先级覆盖） |
| "5-10% token" | 删除（无依据的虚构统计） |
| 缺失 | 补 `dispatch.user_invocable`、`always`、`license`/`compatibility`/`allowed-tools`、pin/lifecycle/audit-rollback |

**测试**：人工校对；加一条 lint 脚本比对文档提到的 builtin 名单与 `backend/skills/__init__.py` 实际注册表。

### 3.3 `SkillExecuteResult.content` 类型统一（#9）

**现状**：前端类型 `SkillExecuteResult.content?: unknown`（`src/shared/api/types/domainEntityTypes.ts:265`），后端 `InprocSkillAdapter.execute()` 的 `SkillResult.content` 实际类型随 builtin 实现而异（`str` / `dict` / `list`）。唯一消费者 `ChatInput.tsx:497` 用 `typeof result.content === 'string'` 三元判断兜底，非 `str` 时回退到 `"/skillName args"` 拼接。

**改法**：后端统一为**字符串**。`InprocSkillAdapter.execute()` / `execute_command()` 返回前，若 `content` 非 `str` 则 `json.dumps(ensure_ascii=False, indent=2)`。前端 `ChatInput.tsx:497` 的兜底分支保留（防御性），但可加注释说明正常路径不再触发。

**兼容性**：`SkillExecuteResult` 是前端类型，唯一消费者即 `ChatInput.tsx`（slash 命令执行路径，`skillsApi.execute` 调用处）。后端改 `str` 后前端 `content?: unknown` 可考虑收窄为 `content?: string`（不强制，留作后续）。

**测试**：后端单测（dict content → str）；前端单测（`ChatInput` slash 命令执行后 `body` 取自 `result.content` 字符串）。

### 3.4 `requires.config` 实现（#11）

**现状**：`gating.py:69` 标注 "v1 暂不支持"，`evaluate_gating()` 对 `requires.config` 永远返回缺失 → 声明了该字段的技能**永不被加载**。

**改法**：`requires.config` 语义定为"**技能声明自己需要的 settings 键存在**"，查 `SettingsRepository`：

```python
# gating.py
def _check_config_gating(doc, settings_repo) -> GateResult:
    """requires.config 列出 settings 键名；任一键缺失/为空 → 门控失败。"""
```

`SettingsRepository.get(key)` 已存在（`backend/data/settings_repo.py:115`），直接复用。`GatingContext`（`gating.py:30`）增加 `settings_repo` 字段（可注入，测试用 fake）。

> ⚠️ **`SettingsRepository.KEYS` 是白名单**（`settings_repo.py:19`）：`get()` 对不在白名单的 key 一律返回 `None`。因此 `requires.config` 声明的键**必须**在 `SettingsRepository.KEYS` 内，否则该技能将**永久门控失败**且原因不可读。
>
> 处置：检查分两步 ——
> 1. key **不在** `SettingsRepository.KEYS` → 门控失败，reason = `未知配置键：{key}（不在 settings 白名单）`
> 2. key 在白名单但 `get()` 返回 `None` / 空串 → 门控失败，reason = `缺少配置项：{key}`
>
> 两种原因必须可区分，否则用户在 §9.2 的 UI 上无法判断该改 SKILL.md 还是该去设置里填值。

**向后兼容**：`always: true` 仍跳过 `requires.*`，但**仍检查 `os`**（保持 `gating.py:98-106` 现有语义）。

**测试**：单测覆盖 存在/缺失/空值 三态 + `always` 组合。

### 3.5 `SlashCommandRegistry` 重建（#12）

**现状**：`slash_registry.py:10` docstring 明说是不可变快照，"调用方若 reload，需重新构建"。

**改法**：`InprocSkillAdapter` 在 `rescan_skill_mds()` / import / delete 后重建 registry：

```python
# inproc.py
def _rebuild_slash_registry(self) -> None:
    self.slash_registry = SlashCommandRegistry.from_registry(self.registry)
```

`SlashCommandRegistry.from_registry()` 已存在，只需在 adapter 的变更路径上调用。

**测试**：单测——注册新技能后 `slash_registry` 包含新命令。

---

## 4. 第 1 节：主动提示机制

**目标**：把后台静默检测变成用户可见的主动提示（"主动式" UX）。

### 4.1 触发点与提示时机

| 事件源 | 检测位置 | 提示形式 |
|---|---|---|
| 对话结束，检测到可沉淀模式 | `ChatService._run_turn_inner` 回合末尾 | **对话内卡片**（Chat 底部），带"沉淀为技能"按钮 |
| `repeated_pattern` 后台检测命中 | `ReviewQueue._process_event` 起稿成功后 | **全局 toast** + `/skills?tab=drafts` 跳转链接 |
| `SkillConsolidationTask` 巡检产出建议 | `evolution.py` 任务末尾 | **全局 toast**（本周巡检 N 条建议） |
| 用户手动 `/learn` | 已有 | 保持现状（`toast.info` → `toast.success`） |

### 4.2 对话内沉淀卡片

**触发条件**（后端判定，前端不判断）：

```
回合结束时满足：
  (a) 本回合工具调用数 ≥ 5
  或 (b) 本会话已有 ≥ 2 次相似签名（前缀 hash 快速判定，不调 embedding）
  且 (c) 距上次展示同类卡片 ≥ 30 分钟（去抖，避免每轮弹）
```

**数据结构**：

```typescript
// src/features/chat/ConsolidationCard.tsx
interface ConsolidationHint {
  sessionId: string;
  reason: 'tool_heavy' | 'repeated_pattern';
  signature: string;        // 前缀 hash，用于去抖
  toolCallCount: number;
  suggestedName?: string;   // 后端 LLM 预生成的候选名（可选）
}
```

**交互**：

```
┌────────────────────────────────────────────────────┐
│ 这段对话包含 8 个工具调用，疑似可复用流程           │
│                                                     │
│  [沉淀为技能]   [忽略]   [本次会话不再提示]         │
└────────────────────────────────────────────────────┘
```

- 「沉淀为技能」→ `POST /api/v1/learn`（复用现有端点）→ toast + 跳转 `/skills?tab=drafts`
- 「忽略」→ 前端本地记住 `signature`，本会话不再提示
- 「本次会话不再提示」→ 同上，粒度更粗

**后端改动**：`chat_service.py` 回合末尾调用新增的 `backend/chat/consolidation_hint.py::detect_hint()`，通过 IPC `chat:consolidation-hint` 推给前端。

> **通道说明**：卡片刻意**不走** §4.3 的 `skill_notifications` 表。卡片是**同回合同步**产生的事件（回合结束那一刻就要看到），走通知表会引入最多 30s 的轮询延迟，体感上像"反应迟钝"。通知表只承载**异步后台事件**（草稿生成、巡检报告、registry 变更）。

> **为什么不用现成的 `complex_turn` signal**：`complex_turn` 的判据是"同一条件反复触发"（跨回合），而卡片要的是"**本回合**就有沉淀价值"。两者粒度不同，各自保留。

### 4.3 全局通知（IPC 事件总线）

**新增统一出口** `skills:notify`：

```typescript
type SkillNotifyPayload =
  | { kind: 'draft_created'; draftId: string; name: string; source: 'repeated_pattern' | 'explicit_learn' }
  | { kind: 'consolidation_report'; suggestionCount: number; draftCount: number }
  | { kind: 'skills_changed'; revision: number };
```

**后端 → Electron 桥接**：后端是 HTTP 服务，Electron 主进程是通知发出方。方案：

1. 后端新增 `GET /api/v1/skills/notifications?since=<cursor>` — 返回 cursor 之后的通知列表
2. Electron 主进程轮询该端点（30s），有新通知则 `webContents.send('skills:notify', payload)`
3. 前端 `useSkillNotifications()` hook 统一消费

> **为什么后端存通知而不是直接 push**：后端是独立进程（`spawnBackend()`），无反向通道。轮询 + 增量游标是最简可靠方案。通知存 DB 表（重启不丢，可回看）。

**新增表**（只承载异步后台事件，见 §4.2 通道说明）：

```sql
CREATE TABLE IF NOT EXISTS skill_notifications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    kind TEXT NOT NULL,
    payload TEXT NOT NULL,        -- JSON
    created_at INTEGER NOT NULL   -- ms epoch
);
```

**测试**：后端单测（通知入队 + 增量游标）；前端单测（hook 收到事件 → toast）。

---

## 5. 第 2 节：智能检测升级

覆盖缺口 #4（子串匹配）和 #14（prompt injection）。

### 5.1 语义匹配（渐进披露）

**现状**：`auto_activation.py:123 _matches()` 对 `when_to_use` 做大小写不敏感子串匹配，命中即注入**整段 body**。

**改法**：两级召回。

**第一级 — embedding 召回**（可选，provider 不可用时降级）：

```python
# backend/skills/skill_md/auto_activation.py
async def _semantic_candidates(
    message: str,
    docs: Sequence[SkillMdDocument],
    embedder: Optional[ModelEmbedder],
    threshold: float = 0.50,
) -> list[SkillMdDocument]:
    """对每个 skill 的 when_to_use 求 embedding，与消息比对，返回相似度超阈值的候选。"""
```

复用 `ModelEmbedder.from_env()` / `encode_batch()`（`backend/memory/embedder.py:333,402`）。`ModelEmbedder` 有 3 次连续失败熔断（`_CIRCUIT_THRESHOLD = 3`，`_CIRCUIT_COOLDOWN_S = 300.0`，`embedder.py:309-310`），**熔断触发时静默降级到子串匹配**，不报错。

> **召回阈值 = 0.50**（不是 0.62）：召回阈值必须等于 T0 档下界，否则 T0 区间 `[0.50, 0.62)` 的候选永远召不回来，该档位形同虚设。T1 档下界 0.62 是**分档**阈值，不是召回阈值。

**第二级 — LLM 精排**：

对第一级候选（≤ 5 个），拼一段极简 prompt 让 LLM 判定"这条消息是否真的需要该技能"，输出 JSON 数组下标。prompt 模板放 `backend/skills/skill_md/prompts/match.txt`。

> **为什么两级而不是纯 LLM**：纯 LLM 精排每轮多一次模型调用，延迟与成本都高。embedding 召回把候选从 N 压到 ≤5，LLM 只判这几个，成本可控。

**渐进披露 — 三档注入**：

| 档位 | 注入内容 | 何时 | 当前是否存在 |
|---|---|---|---|
| **T0 提及** | 在块头的说明行下方追加一行 `- {name}: {desc}` | embedding ∈ [0.5, 0.62) | 新增（无对应结构） |
| **T1 描述** | 新增 `<available-skills>` 块，每行 `- {name}: {desc}` | embedding ∈ [0.62, 0.75) | 新增（当前无该块） |
| **T2 全文** | 完整 `<system-reminder>` + body 块 | LLM 精排确认需要 | 已有（`build_context_block()`） |

> **核查结论**：当前 `auto_activation.py` **只有** T2 一种形态——`build_context_block()`（`auto_activation.py:133`）为每个命中技能生成 `<system-reminder>` + 裸 body，块头固定中文说明 `以下是根据用户本次消息自动激活的技能指令 (A16 Skill Auto-Activation):`。**不存在** `<available-skills>` 块。因此 T0/T1 是本设计**新增**的结构，不是"往已有块里加一行"。

新增后的块结构（示意）：

```text
以下是根据用户本次消息自动激活的技能指令 (A16 Skill Auto-Activation):

可能相关的技能：
- pdf-tools: 处理 PDF 拆分、合并、提取文本
- office-sheets: Excel 读写与公式计算

<available-skills>
- git-workflow: 分支策略与提交规范
</available-skills>

<system-reminder>
Skill 'pdf-tools' auto-activated: ...
Follow the instructions below.
</system-reminder>

<SKILL.md body>
```

`T2` 的 system-reminder 块格式保持现有实现**不变**（见下），确保已有 E2E / 单测断言不被破坏：

```
<system-reminder>
Skill 'name' auto-activated: description
Follow the instructions below.
</system-reminder>

<body>
```

**尺寸闸门**：现有 `MAX_CONTEXT_BLOCK_CHARS = 32_000`（`auto_activation.py:58`）与"超限整块跳过、不截断"语义（`auto_activation.py:253-262`）沿用。T0/T1 行的长度计入投影，但它们远小于 body，实际不会触发闸门。

**Token 收益**：典型对话从"5 个技能全文注入"降为"5 个技能名 + 描述 + 0-2 个全文"，预估可降 30-50%（需实测确认，见 §14 开放问题 1）。

**阈值可配**：沿用仓库已有的 env 优先级约定（`compaction.py:47` 的 `ENV_THRESHOLD_KEY = "SAGE_COMPACT_THRESHOLD"`）：

| 常量（`auto_activation.py` 顶部） | 默认 | env 覆盖键（优先级最高） |
|---|---|---|
| `SEMANTIC_RECALL_THRESHOLD` | 0.50 | `SAGE_SEMANTIC_RECALL_THRESHOLD` |
| `SEMANTIC_T1_THRESHOLD` | 0.62 | `SAGE_SEMANTIC_T1_THRESHOLD` |
| `SEMANTIC_T2_THRESHOLD` | 0.75 | `SAGE_SEMANTIC_T2_THRESHOLD` |

> **为什么不走 settings 表**：`SettingsRepository.KEYS` 是白名单（见 §3.4），新增一个 settings key 需要改白名单 + 加迁移，成本远高于 env 覆盖；且这几个阈值是调参项，不是用户可见配置。

### 5.2 Body 注入净化（#14）

**现状**：`auto_activation.py:169` 直接把 SKILL.md body 拼进 system prompt，仅靠 `<system-reminder>` 包装，无净化。

**风险**：用户导入的 SKILL.md 可含 `</system-reminder>` 闭合标签、伪造的 role 标记、或 "忽略之前的指令" 类注入文本。

**改法**：新增 `backend/skills/skill_md/sanitizer.py`：

```python
def sanitize_skill_body(body: str) -> SanitizeResult:
    """注入前净化 SKILL.md body。

    - 转义/移除闭合标签 </system-reminder>、</instructions>
    - 移除形如 "ignore previous instructions" 的注入语（多语言关键词表）
    - 统计净化条数，供 UI 显示
    """
```

**净化策略（保守，不破坏正常内容）**：
1. **闭合标签转义**：`</system-reminder>` → `<\/system-reminder>`（保留原意但不可解析）
2. **注入语检测**：匹配 `ignore (all )?previous instructions` / `忽略(以上|之前)(的)?(所有)?指令` / `disregard (the )?(above|prior)` 等模式 → 替换为 `[REDACTED-INJECTION]`
3. **不删除正文**（避免误伤），只做转义 + 标记

**调用点**：`build_context_block()` 内，注入前对每个 body 调用。净化统计写入日志，便于后续调阈值。

**测试**：单测覆盖上述 3 类；含正常 body 的回归测试确保不误伤。

### 5.3 Embedding 签名（替换 hash）

**现状**：`repeated_pattern` 的 signature 是工具调用序列的简单 hash，参数不同即视为不同模式。

**改法**：`backend/skills/consolidator.py` 增加语义签名：

```python
async def semantic_signature(tool_calls: list[dict], embedder) -> str:
    """把工具序列编码为"用户意图 + 工具名 + 关键参数值"的文本，
    求 embedding 后取前 8 维 hash 作为语义签名。
    """
```

**判重升级**：不再只比 signature 完全相等，改为 embedding 余弦相似度 > 0.88 视为同一模式。

**降级**：无 embedder 时用现有 hash 签名（行为不变）。

---

## 6. 第 3 节：技能执行链路统一

覆盖缺口 #3（`allowed-tools` 不强制）、#5（`@skill:` 不执行）、#10（`context.tools` 未注入）。

### 6.1 `context.tools` 注入修复（#10）

**现状**：`inproc.py:229` 调 `skill.execute_v2(params=args, context={})` 传空 dict → builtin 技能访问 `context.tools['web_search']` 报 KeyError → `success=False`。

**改法**：`InprocSkillAdapter` 注入时提供 `ToolRegistry` 的只读视图：

```python
# inproc.py
def _build_context(self, extra: Optional[dict] = None) -> dict:
    """构造 execute_v2 的 context。

    tools 来自注入的 ToolRegistry（只读视图，非全量 schema——
    避免把全部工具描述塞进技能执行上下文）。
    """
```

**关键约束**：只暴露**当前 bundle 已启用**的工具，且只给**名称 + 调用封装**，不给 schema（避免 token 爆炸）。

**影响面**：这会让 builtin 技能从"多数返 `success=False`"变成可执行。需要为 4 个 builtin 各补一条"能成功执行"的测试。

### 6.2 `allowed-tools` 落地（#3）

**分两级**（不强制，但可观测）：

| 级别 | 行为 | 实现 |
|---|---|---|
| **声明**（现有） | UI 显示技能声明的 `allowed-tools` | 保持 `SkillCard` 显示 |
| **引导**（新增） | 若技能声明了 `allowed-tools`，`context.tools` 视图**只暴露**声明内的工具 | `execute_v2` 构造 context 时按声明过滤 |

**为什么不强制**：真正的强制需要 tool policy 沙箱（技能执行时把 `context.tools` 收窄到声明范围）。但 builtin 技能依赖 `context.tools` 动态探测可用性，收窄会导致 builtin 失效。

**折中方案（本期采用）**：技能**声明了** `allowed-tools` → 只暴露声明内的工具；**未声明** → 全量视图（保持 builtin 现有行为）。声明即约束，不声明即不约束。

**UI**：SkillCard 增加 "可用工具" 折叠区，列出声明的工具名 + 执行时实际用到的工具。

### 6.3 `@skill:` 执行（#5）

**现状**：`entity_refs.py:248` 的 `render_references_block` 只输出 `/{name}: {desc[:300]}`，技能不执行。

**改法**：**保持"引用即上下文"的语义不变**（`@` 是"提及/引用"，不是"调用"），但补一条显式执行路径：

- `@skill:name` 仍然注 description（不改语义，避免用户误触发执行）
- **新增**：SkillCard 上的「在对话中使用」按钮 → 展开为一条可编辑的草稿消息（含 body 摘要 + 触发提示），用户确认后发送

**为什么不让 `@` 直接执行**：`@` 的现有语义在项目里是"实体引用"（`@file`、`@memory` 等），改成执行会让用户无法"只提及不执行"。**显式按钮 + 预填草稿**是更安全的中间态。

**`@skill:` 解析增强**：`entity_refs.ts:23 parseEntityRefQuery` 补全列表里，技能项带图标区分类型。

---

## 7. 第 4 节：技能编辑器

覆盖缺口 #2。

### 7.1 入口与形态

**入口**：`/skills` 页右上角「＋ 新建技能」按钮 + SkillCard 上的「编辑」按钮。

**形态**：Modal，全屏编辑器布局：

```
┌─────────────────────────────────────────────────────────┐
│ 技能编辑器                              [保存] [取消]    │
├──────────────────────┬──────────────────────────────────┤
│ Frontmatter (YAML)   │  Body (Markdown)                 │
│ ┌──────────────────┐ │ ┌──────────────────────────────┐ │
│ │ name: my-skill   │ │ │ # 我的技能                    │ │
│ │ description: ... │ │ │                              │ │
│ │ when_to_use: ... │ │ │ ## 步骤                      │ │
│ │ always: false    │ │ │ 1. ...                       │ │
│ │ dispatch:        │ │ │                              │ │
│ │   user_invocable │ │ │                              │ │
│ │   user_invocable_│ │ │                              │ │
│ │   name: /my      │ │ │                              │ │
│ └──────────────────┘ │ └──────────────────────────────┘ │
│ [AI 生成]             │  [AI 改写选中]                    │
├──────────────────────┴──────────────────────────────────┤
│ 状态: frontmatter 合法  ⚠ 未声明 allowed-tools            │
└─────────────────────────────────────────────────────────┘
```

**编辑器组件**：项目已用 `react-markdown@^9.1.0`（`MarkdownPreview.tsx`）。代码编辑器用 **CodeMirror 6**，不用 Monaco（体积过大，Electron 打包负担重）。

> **依赖现状（已核查 `package.json`）**：`@uiw/react-codemirror@^4.25.10` 与 `@codemirror/lang-css@^6.3.1` **已是现有依赖**，CodeMirror 6 基座无需新增。本设计只需补两个语言包：
>
> | 包 | 用途 | 预估体积 |
> |---|---|---|
> | `@codemirror/lang-yaml` | frontmatter 编辑 | ~15KB (gzip ~6KB) |
> | `@codemirror/lang-markdown` | body 编辑 | ~60KB (gzip ~22KB) |
>
> 合计新增约 75KB（gzip ~28KB），远低于原估的 300KB。

### 7.2 后端端点

```
GET    /api/v1/skills/{name}/content     → { frontmatter: str, body: str, path: str }
PUT    /api/v1/skills/{name}/content     → 写入 SKILL.md，触发 rescan
POST   /api/v1/skills                    → 新建（name 冲突校验）
```

**写入安全**：
- 写入根沿用现有优先级解析 `_resolve_skills_dir()`（`importer.py:621` / `delete.py:61` / `loader.py:80`，与 `discover_skill_md_dirs()` 同序），**不重写一套**
- 解析后的路径再过 `validate_base_dir(path, allowed_roots=[skills_root])`（`backend/skills/skill_md/validation.py:31`），越界抛 `SkillMdSecurityError`
- YAML frontmatter 必须能解析且含 `name` / `description`
- `name` 与目录名一致（kebab-case，`^[a-z][a-z0-9-]{2,40}$`）
- 原子写：写临时文件 + `os.replace`

**写后触发**：写入 → `rescan_skill_mds()` → 广播 `skills:notify{kind:'skills_changed'}` → 前端刷新列表。

### 7.3 AI 辅助生成

**入口**：编辑器里的「AI 生成」按钮。

**流程**：
1. 用户可选输入"意图描述"（或直接用当前会话上下文）
2. 调 `POST /api/v1/skills/generate` → 后端调 LLM → 返回 `{ frontmatter, body }`
3. 前端填入编辑器，用户手动调整后保存

**Prompt 模板**：`backend/skills/prompts/generate_skill.txt`。复用 `review_service.py` 的 provider 装配方式（`build_llm_client_from_settings` / `resolve_model_from_settings`），不新建 LLM 通道。

**Context 来源**：`session_id` 可选。传了则用 `MessageRepository.get_by_session()` 拉最近 N 条消息喂给 LLM（与 `review_queue.py:331` 同样的做法）。

**「AI 改写选中」**：前端把编辑器选区文本 + 指令（如"补充错误处理"）发给后端，LLM 返回改写后文本，原地替换。

### 7.4 校验与提示

前端实时校验（YAML 解析 + schema）：

| 规则 | 提示级别 |
|---|---|
| `name` 缺失或不符合 kebab-case | 错误（阻止保存） |
| `description` 缺失 | 错误 |
| `when_to_use` < 30 字符 | 警告 |
| `dispatch.user_invocable_name` 缺 `/` 前缀 | 警告（自动补） |
| 未声明 `allowed-tools` | 提示（info） |
| `always: true` + `os` 约束 | 警告（`always` 仍检查 os） |

---

## 8. 第 5 节：技能市场发现

覆盖缺口 #1。

### 8.1 数据源

**只读聚合**，v1 接两个源：

| 源 | 方式 | 说明 |
|---|---|---|
| **本地已装** | `GET /api/v1/skills` | 已装技能列表（已有） |
| **Shipped starters** | `GET /api/v1/skills/market?source=shipped` | 随包分发的 6 个模板（本地） |
| **GitHub 索引** | `GET /api/v1/skills/market?source=github` | 拉取公开索引 JSON |

**GitHub 源**：
- 固定一个公开索引仓库（具体地址见 §14 开放问题 2）
- 拉取 `index.json`，含 `[{name, description, author, repo_url, tags, stars}]`
- 缓存到 `~/.sage/cache/skills-index.json`，TTL 24h
- 拉取失败（离线/限流）→ 静默降级到 shipped 源，UI 提示"离线模式"

> **不做的事**：不自动安装、不做代码审计、不镜像内容。用户点"查看"跳转到源仓库的 SKILL.md 页面。

### 8.2 UI

`/skills` 页顶部 Tab：

```
[ 我的技能 ] [ 草稿 (3) ] [ 发现 ]
```

「发现」Tab：
- 搜索框（前端过滤）
- 卡片列表：name / description / author / stars / tags
- 每个卡片：「查看」→ 新窗口打开源 URL；「已安装」badge（本地已存在同名）

### 8.3 端点

```
GET /api/v1/skills/market?source=github&refresh=false
→ { items: [{name, description, author, repo_url, tags, stars, installed}], source: 'github'|'shipped', offline: bool }
```

---

## 9. 第 6 节：门控可视化 + 热重载

覆盖缺口 #7、#13。

### 9.1 门控失败原因记录

**现状**：`gating.py` 判定失败 → `loader.py:382 _record_skip(..., reason)` 记 WARNING 日志 → 用户在 UI 完全看不到。

**改法**：`loader.py` 维护一张 skip 明细（持久化到 `skill_gating_status` 表）：

```sql
CREATE TABLE IF NOT EXISTS skill_gating_status (
    name TEXT PRIMARY KEY,
    loaded INTEGER NOT NULL,        -- 0=门控失败, 1=已加载
    reason TEXT,                    -- 人类可读原因
    failed_requirements TEXT,       -- JSON: [{"type":"bins","key":"ffmpeg","actual":null}]
    updated_at INTEGER NOT NULL     -- ms epoch
);
```

**失败原因文案**（后端生成，前端只渲染）：

| 情形 | reason |
|---|---|
| 缺二进制 | `缺少可执行文件：ffmpeg` |
| 缺环境变量 | `缺少环境变量：HIGRESS_TOKEN` |
| settings 键缺失 | `缺少配置项：web_search.endpoint` |
| OS 不匹配 | `仅支持 Linux，当前系统为 Windows` |
| 解析失败 | `SKILL.md 解析失败：第 12 行 YAML 语法错误` |

### 9.2 UI

`SkillCard` 增加 badge：

```
┌────────────────────────────────────────┐
│ ffmpeg-transcode                       │
│ 视频转码流程                            │
│                                        │
│ ⛔ 未加载：缺少可执行文件：ffmpeg        │  ← 红色 badge，点击展开详情
│ 🔧 所需工具：ffmpeg, ffprobe            │  ← 来自 allowed-tools
│ 📌 已固化  │  活跃                     │
└────────────────────────────────────────┘
```

**关键**：未加载的技能**也要出现在列表里**（当前它们完全不显示，用户根本不知道存在）。列表新增「显示未加载的技能」开关，默认开。

`GET /api/v1/skills` 响应扩展：

```json
[{
  "name": "ffmpeg-transcode",
  "loaded": false,
  "gating": { "reason": "缺少可执行文件：ffmpeg", "failed_requirements": [...] },
  "requires": { "bins": ["ffmpeg"], "env": [], "config": [] }
}]
```

### 9.3 热重载（watcher）

**现状**：`check_for_updates()` 按 MD5 对比（`loader.py:522`），触发路径只有手动 `POST /skills/rescan` 或导入完成。

**改法**：新增 `backend/skills/skill_md/watcher.py`，用 `watchdog` 监听 skills 根目录。

> ⚠️ **`watchdog` 是新增依赖，不是已有依赖**。核查确认 `backend/requirements.txt` 与 `backend/requirements-py38.txt` 均**未**包含 `watchdog`，当前 `sage-backend` 环境也未安装。
>
> | 分支 | 文件 | 版本约束 | 理由 |
> |---|---|---|---|
> | `main`（py3.10） | `backend/requirements.txt` | `watchdog>=4.0.0` | 4.x 支持 py3.8+，跨分支统一用 4.x |
> | `release/win7`（py3.8） | `backend/requirements-py38.txt` | `watchdog==4.0.0` | watchdog 5.x 要求 `python>=3.9`，py38 环境不可用 |
>
> 遵守双分支策略：main 侧只改 `requirements.txt`，win7 侧只改 `requirements-py38.txt`，互不污染。

```
skills_dir/
  ├── my-skill/
  │     └── SKILL.md     ← 监听
  └── other/
```

**事件**：
- `SKILL.md` 创建/修改/删除 → 增量重载该技能（不整目录扫）
- 目录创建/删除 → 增量增删该技能

**防抖**：300ms 合并窗口（编辑器保存会触发多次事件）。

**与 §3.1 的关系**：watcher 负责后端状态热更新，触发后广播 `skills:notify{kind:'skills_changed'}` → 前端 slash 菜单刷新。**单一机制，无第二条链路。**

**降级**：`watchdog` 不可用（未安装 / win7 打包问题）→ watcher 不启动，保留手动 rescan 端点，UI 显示"热重载不可用，请手动刷新"。

---

## 10. 数据模型变更汇总

| 表 | 变更 | 用途 |
|---|---|---|
| `skill_notifications` | 新建 | 沉淀通知队列（§4.3） |
| `skill_gating_status` | 新建 | 门控失败明细（§9.1） |
| `skill_drafts` | 无变更 | 现有草稿表 |
| `skill_lifecycle` | 无变更 | 现有归档表 |
| `skill_usage` | 无变更 | 现有使用统计 |

全部走 `CREATE TABLE IF NOT EXISTS`（`backend/data/database.py::init_db` 现有范式），无需迁移脚本。

---

## 11. 里程碑与依赖

| 里程碑 | 内容 | 依赖 | 估时 |
|---|---|---|---|
| **M0** | 基础修复：#6 #8 #9 #11 #12 | — | 2-3 天 |
| **M1** | 主动提示：卡片 + 通知总线 + toast | M0 | 4-5 天 |
| **M2** | 智能检测：embedding 匹配 + 渐进披露 + 净化 + 语义签名 | M0 | 5-7 天 |
| **M3** | 执行链路：`context.tools` + `allowed-tools` + `@skill:` | M0 | 4-5 天 |
| **M4** | 技能编辑器 + AI 生成 | M1（通知总线） | 6-8 天 |
| **M5** | 市场发现 | M0 | 3-4 天 |
| **M6** | 门控可视化 + watcher（**含新增依赖 `watchdog==4.0.0`**） | M0 | 4-5 天 |

**总计**：约 28-37 个工作日。可按 M0→M1→M6→M2→M3→M4→M5 分批交付，每批独立可发布。

**关键路径**：M0 → M1 → M4（编辑器依赖通知总线）；M2 与 M3 相互独立，可并行。

---

## 12. 测试策略

| 层 | 范围 | 数量预估 |
|---|---|---|
| **后端单测** | embedding 匹配、渐进披露分档、sanitizer、gating config、context.tools 注入、allowed-tools 视图、语义签名、通知队列、门控状态持久化 | ~80 |
| **前端单测** | 卡片渲染与交互、hook 订阅、编辑器校验、市场列表过滤、SkillCard badge | ~50 |
| **集成测试** | 完整沉淀链路：对话 → 检测 → 卡片 → learn → draft → approve → SKILL.md 落盘 → rescan → 自动激活 | ~10 |
| **E2E** | Playwright：编辑器创建技能、门控失败展示、市场浏览 | ~6 |

**CI 门禁**：沿用项目现有 pytest + vitest + coverage 阈值（architecture-baseline 阈值按本分支实测，见 memory `sage-win7-sync-per-branch-numbers`）。

---

## 13. 风险与缓解

| 风险 | 影响 | 缓解 |
|---|---|---|
| embedding provider 不可用 | 语义匹配失效 | 三级降级：LLM 精排 → 子串匹配 → 无匹配。永不报错 |
| LLM 精排增加每轮延迟 | 对话变慢 | 仅在 embedding 召回有候选时调用；候选 ≤5；`complete()` 已异步 |
| watcher 在 win7 打包环境失效 | 热重载不工作 | 降级为手动 rescan；UI 明示；CI 有 smoke 覆盖 |
| `watchdog` 为新增依赖，打包体积/兼容性未知 | win7 安装包可能装不上或行为异常 | 钉 `watchdog==4.0.0`（py38 可用）；安装包 smoke 必须覆盖；失败时按上一行降级 |
| CodeMirror 语言包增加打包体积 | 安装包变大 | 仅新增 2 个语言包，约 28KB gzip（基座已有）；不引入 Monaco |
| 主动提示过于频繁 → 用户麻木 | 体验反噬 | 30 分钟去抖 + "本次会话不再提示" + 阈值可配 |
| 渐进披露导致 LLM 漏读 body | 技能不生效 | T2 由 LLM 精排确认；保留 escape hatch（LLM 可显式请求 body） |
| 净化误伤正常内容 | 技能行为异常 | 保守策略（只转义闭合标签 + 标记注入语），不删正文；回归测试覆盖 |
| 市场索引源不稳定 | 市场页空白 | 缓存 + 离线降级到 shipped 源 |

---

## 14. 开放问题

| # | 问题 | 待定 |
|---|---|---|
| 1 | 渐进披露的 T0/T1/T2 阈值具体取值 | 需实测调参（建议 0.5 / 0.62 / 0.75 起步） |
| 2 | 市场索引用哪个公开源 | 需确认是否有稳定的 index.json 约定，否则退到 GitHub 搜索 API |
| 3 | 「本次会话不再提示」的存储粒度 | 内存 vs localStorage |
| 4 | 技能编辑器是否需要支持多文件技能（含 `scripts/`、`references/`） | v1 只支持单文件 SKILL.md |
| 5 | 通知 toast 是否需要免打扰设置 | 待定 |

---

## 附录 A：缺口 → 章节映射

| # | 缺口 | 章节 |
|---|---|---|
| 1 | 无技能市场 | §8 |
| 2 | 无技能创建 UI | §7 |
| 3 | `allowed-tools` 不强制 | §6.2 |
| 4 | 自动激活是子串匹配 | §5.1 |
| 5 | `@skill:name` 不执行 | §6.3 |
| 6 | ChatInput 不热更新 | §3.1 → §9.3 |
| 7 | 门控失败不可见 | §9.1 §9.2 |
| 8 | 帮助文档过期 | §3.2 |
| 9 | content 类型不统一 | §3.3 |
| 10 | `context.tools` 未注入 | §6.1 |
| 11 | `requires.config` 未实现 | §3.4 |
| 12 | SlashCommandRegistry 不可变 | §3.5 |
| 13 | 无后台文件监听 | §9.3 |
| 14 | Prompt injection 风险 | §5.2 |
