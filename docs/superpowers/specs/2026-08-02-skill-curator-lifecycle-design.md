# Skill Curator 生命周期 — Design Spec

- **Date:** 2026-08-02
- **Branch:** `feat/skill-curator-lifecycle` (基于 `origin/main`)
- **Status:** Draft，待用户 review
- **Author:** Claude (brainstorming with user)

## 1. 背景与目标

### 1.1 问题

Sage 的技能库随使用时间增长：用户导入 / 自建 / builtin 的技能越积越多，但没有任何**生命周期信号**帮助用户判断"哪些技能我在用、哪些已经冷了、哪些该收起来"。PR #269 已落地 `skill_usage` 统计表（`name / use_count / success_count / last_used_at`，`last_used_at DESC` 有索引），其模块 docstring 明确写明"供技能生命周期（curator）与前端使用统计使用"——本功能即兑现该预留。

现状缺口：

| 缺口 | 现状 |
|---|---|
| 无生命周期分类 | `GET /api/v1/skills` 只出 `usage_count`（内存计数），无 active/stale/archived 信号 |
| 无归档能力 | 用户不想要某技能时只能**物理删除**（`POST /skills/{name}/delete`，不可逆 rmtree），无"收起但保留"的中间态 |
| 冷技能仍参与自动激活 | `auto_activate`（A16）与 slash registry 只按 `enabled`/`dispatch` 过滤，从不用或久未用的技能照样占用候选、干扰 system prompt 组装 |

### 1.2 目标

1. 为每个技能计算生命周期三态 **active / stale / archived**，经 `GET /api/v1/skills` 透出，前端 SkillCard 显示 badge。
2. 提供**可逆的软归档**动作（`POST /api/v1/skills/{name}/archive`）：归档技能从 `auto_activate` 与 slash 候选中排除，但文件不动、可 unarchive。
3. 分类是 `last_used_at` 的**纯函数 + 读取时即时计算**，不引入后台 worker，永远与当前时间一致。
4. 归档状态持久化到 DB（重启不丢），内存缓存供热路径（auto_activate 每轮调用）零 DB 开销。

### 1.3 非目标 (YAGNI)

- ❌ **后台周期 curator**（WakeScheduler tick 循环）：分类只是时间比较，读取时即可算；无主动副作用需求（不自动移动文件、不推送通知）。brainstorming 已对比三套方案，A（读时算）完胜——详见 §6.1。
- ❌ **阈值自动归档**：archived 只来自用户显式动作。软标记下"超阈值自动 archived"会导致 unarchive 后弹回，需额外 `manual_unarchived` 标志位，复杂度不值得。stale 即归档的信号，决定权交给用户。
- ❌ **按成功率分类**：探索确认 `success_count` 恒等于 `use_count`——全代码库无任何调用点传 `success=False`，也无 `fail_count` 列。当前无真实失败率数据，分类改以 `last_used_at`（近因）为准。补失败跟踪是独立议题（见 §9 后续）。
- ❌ **移动文件到 `.archived/`**：无生产级 mover / 路径校验先例（`frontmatter.dump` 仅测试用），真实文件移动复杂且有风险。软 DB flag 可逆、零文件风险。
- ❌ **新增 `unused` 第四态**：从未使用（表里无行）归入 `stale`（冷技能、归档候选），保持原定三态，前后端不多一套。
- ❌ **前端 i18n**：Skills 页整体未接 i18n（全硬编码中文，无 `skills.*` 命名空间）。新增文案沿用硬编码中文保持一致，不单独给本功能接 i18n（避免页面半接半不接）。
- ❌ **前端归档筛选 / 分组 / 仪表盘统计**：v1 仅 badge + 归档按钮 + 归档卡片弱化显示。按 lifecycle 筛选、"N 个冷技能"提示等留待后续。
- ❌ **release/win7 同步**：本期只在 main，后续按需 cherry-pick（遵循双分支策略）。

## 2. 用户故事

- **US-1**：作为 Sage 用户，我打开技能页时能一眼看出每个技能是"活跃 / 已冷 / 已归档"，不用靠记忆判断哪些技能我其实早不用了。
- **US-2**：作为 Sage 用户，对于装了但从没用、或久未用的技能，我能"归档"它——它不再自动跳出来干扰对话，但文件还在，哪天想要了一键恢复，不像删除那样不可逆。
- **US-3**：作为 Sage 用户，我归档的技能重启后仍然是归档状态，不会莫名其妙又冒出来。
- **US-4**：作为开发者，生命周期分类不增加任何后台任务 / 常驻协程，不引入 PR #271 那类 worker 生命周期 / drain 竞态 / 测试时序的复杂度。

## 3. 架构

### 3.1 数据模型：新增 `skill_lifecycle` 表

`backend/data/database.py` 的 `init_db()` 内，紧随 `skill_usage` 表之后新增（§3.1 迁移范式沿用现有 `CREATE TABLE IF NOT EXISTS`，无需 PRAGMA 改列——是全新表）：

```sql
CREATE TABLE IF NOT EXISTS skill_lifecycle (
    name TEXT PRIMARY KEY,
    archived INTEGER DEFAULT 0,   -- 0=未归档, 1=已归档
    archived_at INTEGER           -- 归档时刻 ms epoch，未归档为 NULL
);
```

**为什么独立成表而不扩展 `skill_usage`：**

- `skill_usage` 只在技能**首次被 bump 时才 INSERT**（从未使用的技能表里无行）。但**从未使用的技能同样可被归档**——归档状态必须能以 name 独立寻址，不能依赖 usage 行的存在。独立表以 `name` 为主键天然覆盖此情形。
- 职责分离：`skill_usage` = 纯使用统计（docstring 自述"只记聚合统计"）；`skill_lifecycle` = 策展状态。不混用。
- ⚠️ 不复用死表 `skills`（database.py:280-300，带 usage_count/success_count/last_used_at 列但全后端无读写）——历史残留 schema，本功能不碰。

### 3.2 分类纯函数

新增模块 `backend/skills/lifecycle.py`，核心是一个**无副作用纯函数**（可独立单测，无需 DB / 时间冻结）：

```python
DEFAULT_STALE_THRESHOLD_MS = 30 * 24 * 60 * 60 * 1000  # 30 天，命名常量可调

def classify_lifecycle(
    last_used_at_ms: Optional[int],
    archived: bool,
    now_ms: int,
    stale_threshold_ms: int = DEFAULT_STALE_THRESHOLD_MS,
) -> str:
    """返回 'active' / 'stale' / 'archived'。archived 优先级最高。"""
    if archived:
        return "archived"
    if last_used_at_ms is None:        # 从未使用（usage 表无行）→ 冷技能
        return "stale"
    if (now_ms - last_used_at_ms) <= stale_threshold_ms:
        return "active"
    return "stale"
```

- `now_ms` 由调用方注入（不在纯函数内取时间）→ 测试用相对时间戳即可断言三态与边界，**无需 freezegun**（仓库本就不用，沿用 PR #271 / wake_scheduler 的相对时间戳测试范式）。
- 阈值做成常量参数，v1 固定 30 天；settings 可配留待后续。

### 3.3 存储层：`SkillLifecycleStore`

同模块 `backend/skills/lifecycle.py`，**完全仿照 `backend/skills/usage.py` 的 `SkillUsageStore`**（手写薄存储、裸 SQL、全局单例、best-effort）：

```python
class SkillLifecycleStore:
    def __init__(self, db=None) -> None: ...          # 懒绑 get_database()
    def set_archived(self, name: str, archived: bool) -> None:
        """UPSERT：archived + archived_at（归档写 now_ms，取消归档置 NULL）。best-effort。"""
    def get_archived_names(self) -> Set[str]:
        """SELECT name WHERE archived=1 → 批量左连接用（一次查询，非逐技能）。"""
    def is_archived(self, name: str) -> bool: ...

# 全局单例（仿 get_usage_store / reset_usage_store）
def get_lifecycle_store(db=None) -> SkillLifecycleStore: ...
def reset_lifecycle_store() -> None: ...             # 测试钩子
```

- **best-effort 契约**（沿用 usage store）：DB 不可用 / 表不存在时只 `logger.warning`，绝不外抛——策展状态不得影响技能主流程。
- `set_archived` 的 `archived_at` 在 store 内取 `int(time.time()*1000)`（写路径取时间无碍，读路径分类才需注入 now）。

### 3.4 Adapter 集成：内存缓存 + DB 真相

`backend/adapters/out/skill/inproc.py` 的 `InprocSkillAdapter` 已有两个内存态先例：`_enabled: Dict[str,bool]`（toggle，不持久化）与 `_usage_count: Dict[str,int]`（启动 `_hydrate_usage_from_db` 回填）。归档采用**内存缓存 + DB 真相**的混合（取两者之长：持久 + 热路径零 DB）：

```
DB skill_lifecycle 表  = 持久真相（重启不丢）
        ↕ hydrate / write
adapter._archived: Set[str]  = 内存热缓存（auto_activate / slash / list 读它，零 DB）
```

新增成员与方法：

| 成员/方法 | 说明 |
|---|---|
| `self._archived: Set[str]` | `__init__` 末尾 `_hydrate_archived_from_db()` 从 `get_lifecycle_store().get_archived_names()` 灌入（仿 `_hydrate_usage_from_db`，只收 registry 真实存在的技能） |
| `archive(name)` | 校验 `registry.exists(name)`；`get_lifecycle_store().set_archived(name, True)`；`self._archived.add(name)` |
| `unarchive(name)` | 校验存在；`set_archived(name, False)`；`self._archived.discard(name)` |
| `is_archived(name) -> bool` | `name in self._archived`（热路径 O(1) 内存读） |
| `lifecycle_map() -> Dict[str,str]` | 批量算全量 name→lifecycle：`get_usage_store().get_all()` 取 last_used_at + `self._archived` + `now_ms`，逐技能 `classify_lifecycle`。供 `list_skills_extended` 调用 |

**`list_skills_extended`（inproc.py:394）改造**：循环前 `lifecycles = self.lifecycle_map()`（一次），循环内 `item["lifecycle"] = lifecycles.get(schema.name, "stale")`。builtin 与 skillmd 一律计算（builtin 也可归档，见 §4.4）。

### 3.5 API：`POST /api/v1/skills/{name}/archive`

`backend/api/legacy_routes.py` 技能段，**仿 `delete` / `toggle` 端点的异常→状态码映射**：

```
POST /api/v1/skills/{name}/archive
Body: {"archived": true | false}      # 单端点同时承载归档/取消归档（toggle 式，可逆）
→ 200 返回更新后的完整 skill dict（含 lifecycle 字段，仿 toggle 返回）
→ 404 技能不存在（registry 无此 name）
```

- 单端点 + 布尔体而非 `/archive` + `/unarchive` 两个端点：与 toggle 语义一致，前端 `skillsApi.archive(name, archived)` 一个方法覆盖双向。
- 允许归档 builtin（`search/writer/coder/travel`）：归档**非破坏且可逆**（区别于 delete 对 builtin 的硬保护），用户想收起从不用的 `travel` 是合理诉求。可用性由 §4.5 的 `enabled ∧ ¬archived` 统一裁决。

### 3.6 前端

| 改动点 | 内容 |
|---|---|
| `src/shared/api/types.ts`（`Skill`，~296） | 加 `lifecycle?: 'active' \| 'stale' \| 'archived'` |
| `src/shared/api/skillsApi.ts` | 加 `archive(name, archived)` → `invoke('archive_skill', {name, archived})`，模板照 `delete`（`withRetry` + `handleApiError`） |
| Electron bridge | `archive_skill` IPC 命令 → 转 `POST /api/v1/skills/{name}/archive`（照 `delete_skill` bridge 模板，类型在 `src/shared/types/electron-api.ts`） |
| `src/widgets/skills/SkillCard.tsx` | 标题行现有 chip 序列里加**内联 lifecycle badge**（沿用 `px-2 py-0.5 text-xs rounded-full` 内联 span 模式，不抽原语——与 source/version/slash chip 一致）；右侧操作区加**归档/取消归档按钮**（条件渲染，仿 `TwoStepDelete` 位置；归档用 `Button variant="secondary" size="sm"`）；archived 卡片整体弱化（`opacity-60` 类） |
| `src/pages/Skills.tsx` | `handleArchive(name, archived)` — optimistic update + 失败回滚 + `sonner` toast，照 `handleDelete` 模式 |

badge 视觉（语义化 token，沿用现有配色规律）：

| lifecycle | 文案 | 配色（tailwind token） |
|---|---|---|
| active | 活跃 | `bg-primary/20 text-primary`（与 slash chip 同族） |
| stale | 已冷 | `bg-bg-subtle text-muted`（灰底，与 source builtin chip 同族） |
| archived | 已归档 | `bg-accent/20 text-accent` 或灰底删除线，配卡片 `opacity-60` |

文案硬编码中文（页面未接 i18n，保持一致）。

### 3.7 数据流

```
【读路径 — 用户打开技能页】
GET /api/v1/skills
  └─ InprocSkillAdapter.list_skills_extended()
       ├─ lifecycle_map():
       │    ├─ get_usage_store().get_all()          # name → last_used_at（一次索引查询）
       │    ├─ self._archived                        # 内存 Set（O(1)，不查库）
       │    └─ classify_lifecycle(last, archived, now_ms)  # 纯函数
       └─ item["lifecycle"] = ...                    # → 前端 badge

【写路径 — 用户点归档】
POST /api/v1/skills/{name}/archive {archived:true}
  └─ adapter.archive(name)
       ├─ get_lifecycle_store().set_archived(name, True)  # DB 持久真相
       └─ self._archived.add(name)                         # 内存热缓存
  → 返回更新 skill dict → 前端 optimistic 更新 badge + 弱化卡片

【热路径 — 每轮对话】
ChatService._run_turn_inner 步骤 2.6 → adapter.auto_activate()
  └─ 候选过滤：enabled ∧ dispatch ∧ ¬is_archived(name)   # 内存 O(1)，零 DB
```

## 4. 分类规则

### 4.1 三态定义

| 态 | 判定（优先级从上到下） | 语义 |
|---|---|---|
| `archived` | `name ∈ _archived`（用户显式归档） | 已收起，不参与自动激活/slash，可恢复 |
| `active` | 未归档 ∧ `last_used_at` 距今 ≤ 阈值（默认 30 天） | 近期在用 |
| `stale` | 未归档 ∧（`last_used_at` 距今 > 阈值 **或** 从未使用） | 冷技能，归档候选 |

### 4.2 阈值

- `DEFAULT_STALE_THRESHOLD_MS = 30 天`，命名常量，`classify_lifecycle` 参数可覆盖。
- v1 固定；settings 可配为后续项。

### 4.3 从未使用归类

从未使用的技能在 `skill_usage` 表**无行** → `last_used_at = None` → `classify_lifecycle` 返回 `stale`。语义上"装了没用"与"用过已冷"同为冷技能、同为归档候选，统一 stale（brainstorming 已确认，不加 `unused` 第四态）。

### 4.4 archived 与 builtin

builtin 技能（`search/writer/coder/travel`）**允许归档**：归档非破坏、可逆，用户收起从不用的 builtin 是合理策展。区别于 `delete` 对 builtin 的硬保护（delete 不可逆）。

### 4.5 archived 与 enabled 的关系

两者正交：

- `enabled`（toggle）：技能的开/关开关，内存态（**重启丢失**，现有行为）。
- `archived`：策展生命周期标记，DB 持久（重启不丢）。

**可用性裁决**：技能进入 `auto_activate` / slash 候选当且仅当 `enabled ∧ ¬archived`。即：

- archived 技能即使 enabled=true 也不参与自动激活/slash（归档主导可用性）。
- unarchive 不改动 `enabled` 状态（两态独立，互不覆盖）。

## 5. 错误处理

| 层 | 处理 |
|---|---|
| `SkillLifecycleStore` | best-effort：DB 不可用 / 表不存在 → `logger.warning`，不外抛。`get_archived_names` 失败返回空集（降级为"无归档"，不阻断 list）；`set_archived` 失败只 warning（归档动作可能未持久，但不崩） |
| `classify_lifecycle` | 纯函数无异常路径；`last_used_at=None` 是合法输入（→stale）非错误 |
| `adapter.archive/unarchive` | `registry.exists(name)` 为 False → 抛 `KeyError`/`ValueError`，路由映射 404 |
| API 路由 | 仿 delete 端点：技能不存在 → 404；store best-effort 失败不产生 5xx（归档语义降级但响应成功）——与 usage/toggle 的"统计/标记不得影响主流程"契约一致 |
| 前端 | `handleArchive` optimistic + 失败回滚 + toast，照 `handleDelete` |

## 6. 生命周期与一致性

### 6.1 为何无后台 worker（brainstorming 结论）

三套运行模型对比后选 A（读时算）：

| 维度 | A 读时算（选） | B 后台 tick curator | C 混合 |
|---|---|---|---|
| 一致性 | 永远对 `now` 实时一致 | 有 tick 间隔滞后 | 显示实时，归档滞后 |
| 复杂度 | 最低（纯函数 + 1 查询） | 高（worker 生命周期/lifespan/drain） | 中高 |
| 可测性 | 最易（纯函数 + 相对时间戳） | 中（tick + 循环时序） | 中 |
| 风险面 | 几乎无 | worker 崩溃/泄漏/shutdown 顺序/测试污染 | worker 风险（窄） |

**关键洞察**：archived 是软状态、无主动副作用（不移动文件、不通知）时，连"自动归档"都只是读时分类器里一个更长阈值——worker 无可替代价值。且仓库最接近策展的 `EvolutionScheduler` 是 merged 但休眠（`start_scheduler()` 无人调用）的警示先例，不重蹈覆辙。`classify_lifecycle` 纯函数留给未来 worker 复用（若真要主动策展）。

### 6.2 一致性模型

| 状态 | 真相源 | 热缓存 | 刷新时机 |
|---|---|---|---|
| `archived` | DB `skill_lifecycle` | `adapter._archived: Set` | 启动 hydrate；archive/unarchive 双写 |
| `last_used_at`（→active/stale） | DB `skill_usage` | 无（`lifecycle_map` 每次 list 读一次） | 每次 `GET /skills` 实时读 + 对 `now` 分类 |

- active/stale 不落库、不缓存：读取时即时算，天然与当前时间一致，无"上次重算"滞后。
- archived 内存缓存保证热路径（auto_activate 每轮）零 DB；DB 保证重启不丢。
- 唯一可接受的弱一致：archive 写 DB 成功但进程在更新内存前崩溃 → 重启 hydrate 自愈。

### 6.3 无 lifespan 改动

不新增 start/stop/lifespan 接线（无 worker）。唯一启动行为是 adapter `__init__` 的 `_hydrate_archived_from_db()`（adapter 本就在首次 `_get_skill_adapter()` 时构造）。

## 7. 测试

> 全部用 `/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest`（conda `sage-backend`，Py3.11）。不用 freezegun，相对时间戳 + 真实 SQLite。

### 7.1 新增单测

| 文件 | 用例 |
|---|---|
| `backend/tests/unit/test_skill_lifecycle.py` | **classify_lifecycle（纯函数）**：archived 优先；`None`→stale；阈值内→active；超阈值→stale；恰在阈值边界→active；自定义阈值生效 |
| 同上 | **SkillLifecycleStore（真实 SQLite tmp）**：set_archived(True)→get_archived_names 含之 + archived_at 非空；set_archived(False)→移出 + archived_at NULL；is_archived；重启同 db 路径持久；表不存在 best-effort 不抛 |
| `backend/tests/unit/test_inproc_lifecycle.py`（或扩展现有 inproc 测试） | **adapter**：archive→is_archived True + 持久（新 adapter 实例 hydrate 仍在）；unarchive→移除；archive 不存在技能抛错；`lifecycle_map` 对 active/stale/archived/从未用四情形正确；**hydrate** 只收 registry 存在的技能 |
| 同上 | **排除点**：archived 技能不出现在 `auto_activate` 候选；不出现在 slash registry；unarchive 后恢复；`enabled=False ∧ archived` 仍排除 |

### 7.2 API 测试

| 文件 | 用例 |
|---|---|
| `backend/tests/integration/test_skills_archive_api.py`（或扩展 skills API 测试） | `POST /skills/{name}/archive {archived:true}` → 200 + dict.lifecycle=="archived"；再 `{archived:false}` → lifecycle 回到 active/stale；不存在技能 → 404；GET /skills 返回含 lifecycle 字段 |

### 7.3 前端测试（vitest + RTL）

| 文件 | 用例 |
|---|---|
| `src/widgets/skills/__tests__/SkillCard.test.tsx`（扩展） | 渲染 active/stale/archived 三种 badge 文案；archived 卡片弱化；归档按钮点击触发回调；archived 态显示"取消归档" |
| `src/pages/__tests__/Skills.archive.test.tsx`（新增，仿 Skills.delete.test.tsx） | handleArchive optimistic 更新 + 失败回滚 + toast；`skillsApi.archive` 以正确参数被调 |

### 7.4 现有测试适配

`Skill` 类型加字段、`list_skills_extended` 加 lifecycle 字段属**纯增量**，现有断言不受破坏（新增字段不冲突）。若现有 skills API 测试对响应做全等断言，需补 lifecycle 字段预期。

### 7.5 验证命令

```bash
/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest \
  backend/tests/unit/test_skill_lifecycle.py \
  backend/tests/unit/test_inproc_lifecycle.py \
  backend/tests/integration/test_skills_archive_api.py -v
cd /home/fz/project/sage && npm run test -- SkillCard Skills.archive   # vitest
```

## 8. 风险与限制

| 风险 | 应对 |
|---|---|
| `skill_usage` 无失败率数据，分类维度单一（仅近因） | 本期明确以 last_used_at 为准；success_count 留作后续（先补 `success=False` 调用点 + `fail_count` 列，独立议题） |
| auto_activate 热路径读归档集 | 内存 `_archived` Set O(1)，零 DB；启动 hydrate + 写时双写保一致 |
| archive 写库成功、更新内存前崩溃 | 重启 `_hydrate_archived_from_db` 自愈，弱一致可接受 |
| 30 天阈值一刀切 | 命名常量可调；settings 可配留后续 |
| builtin 归档后"消失"令用户困惑 | archived 卡片仍显示（弱化 + badge），可一键 unarchive；非破坏可逆 |
| 前端文案硬编码中文，未来接 i18n 需返工 | 与页面现状一致的有意取舍；整页接 i18n 是独立议题 |
| `frontmatter.dump` 仅测试用，无写回生产路径 | 本功能不写回 SKILL.md（软 DB flag），规避该缺口 |

## 9. 验收

- [ ] `pytest backend/tests/unit/test_skill_lifecycle.py backend/tests/unit/test_inproc_lifecycle.py` 全绿
- [ ] `pytest backend/tests/integration/test_skills_archive_api.py` 全绿
- [ ] 全量 `pytest backend/tests` 无回归
- [ ] `npm run test` 前端新增/扩展用例全绿，`tsc` 0 error
- [ ] ruff 全绿（新增/改动文件）
- [ ] 手动冒烟：技能页显示 active/stale/archived badge；归档后技能从自动激活/slash 消失且卡片弱化；重启后归档状态保持；unarchive 恢复
- [ ] 覆盖率 ≥ 80%（新增后端模块）

## 10. 后续项（非本期）

- 补技能失败跟踪（执行失败传 `success=False` + `fail_count` 列）→ 引入成功率分类维度
- settings 可配 stale 阈值
- 前端按 lifecycle 筛选 / 分组、"N 个冷技能"提示、归档统计仪表盘
- 阈值自动归档（若产品确需主动策展，届时评估 C 方案 + 复用 `classify_lifecycle`）
- Skills 页整体接 i18n（`skills.*` 命名空间）
- release/win7 同步（按需 cherry-pick，Py3.8 + pydantic v1 兼容验证）
