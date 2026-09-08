# 学术检索 skill 与 skill_save 工具

> **创建日期**: 2026-09-08
> **分支**: `feat/academic-search-skill`
> **状态**: ✅ 已交付(M1 skill_save + O2 SKILL.md 模板形态 + academic_adapters 库 + CNKI adapter)

---

## 1. 总览

本专题交付两件配套能力:

- **`skill_save` 工具**(M1)——让 LLM 在用户授权下,把一次成功的多步工具调用序列
  + 用户给定的描述,沉淀为草稿 skill(进入 `skill_drafts` 表等人工 review)。
- **`academic-search` SKILL.md 模板**(O2)——一个随包分发的**基础版 skill**,
  LLM-driven playbook 形态:把"在文献站点检索 → 抓结果页 → 让用户挑排序偏好
  → 整理摘要"这一流程写进 markdown body,实际执行交给 LLM,站点差异通过
  `academic_adapters` 的 URL 模板适配。**不注册为 builtin**,触发词留空,
  让用户根据使用情况自定义。

两者配合实现了"基础能力 + skill 复用机制 + starter 模板"的三件套:CNKI 只是其中
一个 adapter,后续要加 PubMed / Google Scholar / arXiv 等只需注册新 adapter;
trigger / 触发条件 / 站点偏好由用户在 starter 基础上派生或覆盖。

---

## 2. 架构图

```
┌────────┐  触发词(找文献/检索论文/...)   ┌─────────┐
│  用户  │ ──────────────────────────► │   LLM   │
└────────┘                              └────┬────┘
       ▲                                     │
       │  ① 调用 AcademicSearchSkill.execute │
       │  ② (可选) ask_user_question 排序     │
       │  ③ 返回结构化 prompt,LLM 解析页面     │
       │                                     ▼
       │                          ┌──────────────────────┐
       │                          │  AcademicSearchSkill │
       │                          │  (builtin skill)     │
       │                          └────┬─────────────┬───┘
       │                               │             │
       │              get_site_adapter │             │ 调 web_fetch
       │                               ▼             ▼
       │                  ┌─────────────────────┐  ┌──────────┐
       │                  │ academic_adapters   │  │ web_fetch │
       │                  │  (CNKI / PubMed /..) │  │  工具     │
       │                  └─────────────────────┘  └──────────┘
       │
       │  "把这个流程存为 skill"
       │
       │                          ┌──────────────────┐
       └────── 返回 SkillDraft ───│   skill_save      │
                                  │  (BaseTool)       │
                                  └────┬─────────────┘
                                       │ 走 sync→async bridge
                                       ▼
                            ┌─────────────────────┐
                            │  ReviewService      │
                            │  (LLM 二次校验)     │
                            └────┬────────────────┘
                                 │ SkillDraft
                                 ▼
                        ┌─────────────────────┐
                        │  SkillDraftStore    │
                        │  (SQLite 落盘)      │
                        │  status='pending'   │
                        └────┬────────────────┘
                             │ 人工审核
                             ▼
                        status='approved'
                             │
                             ▼
                        SKILL.md 装载
                        (复用为下次 skill)
```

---

## 3. 核心组件

### 3.1 `skill_save` 工具(M1)

**位置**: `backend/tools/skill_save_tool.py`

**何时用**: 用户明确说"把这个流程存为 skill / 记住这个流程 / 保存为模板"等。

**参数**:

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `name` | str | ✓ | skill 名(3-40 字符,kebab-case,正则 `[a-z](?:[a-z0-9]|-[a-z0-9]){2,39}`) |
| `description` | str | ✓ | ≤80 字符,描述 skill 做什么 |
| `when_to_use` | str | ✓ | ≥30 字符,描述触发条件 |
| `tool_sequence` | list | ✓ | 最近一次成功的工具调用序列(自动 normalizer 过滤) |
| `session_id` | str | ✗ | 当前会话 ID,用于追溯 |

**执行流程**:

1. **校验**: name 走 `SkillSaveTool._validate_skill_name`,content 必须含
   `## 步骤` / `## 触发条件` / `## 示例`,tool_sequence 元素必须是
   `{"tool": str, "args": dict}` 形态。
2. **走 sync→async bridge**(`_run_async`):从 LLM 异步生成草稿 → 在同步上下文
   中拿结果(三种分支:无 loop / 在 loop / 跨线程)。
3. **ReviewService 校验**: `generate_draft(trigger_type="user_explicit_save",
   context={...})` 内部再次调用 LLM 做 schema + 内容校验,产出 `SkillDraft`。
4. **持久化**: `SkillDraftStore.insert(draft)` → SQLite `skill_drafts` 表,
   `status="pending"`,`reviewed_at` / `reviewed_by_user_id` 为 NULL。
5. **返回**: `ToolResult(success=True, content={"draft_id", "name", "status"})`。

**风险**:

- ⚠️ 用户填的 `name` / `description` / `when_to_use` 必须是**用户原话或经用户
  同意**,不要让 LLM 自由发挥去编造触发条件。
- ⚠️ `tool_sequence` 会被 normalizer 过滤,只保留 `{"tool", "args"}` 形态;不要
  把包含敏感参数的调用(如 API token)塞进去。

### 3.2 `academic-search` SKILL.md 模板(O2,已改为模板形态)

**位置**:
- 随包分发: `backend/skills/skill_md/shipped/academic-search/SKILL.md`
- 文档镜像: `docs/templates/academic-search/SKILL.md`

**装载机制**:`backend/skills/skill_md/loader.py` 的两个 API 协作:

- `discover_skill_md_dirs()` 返回**用户层**(env / `$CWD/skills` / `~/.sage/skills`),**不含 shipped** —— 因为 `InprocSkillAdapter` 用它算 `ScriptRunner.allowed_roots`,把 shipped 加进去会放宽脚本沙箱边界。
- `register_skill_md_skills(registry, dirs=None)` 默认 (`dirs=None`) 走 `discover_skill_md_dirs() + shipped` 拼起来的 effective_dirs,shipped 作为最低优先级 fallback;显式传 `dirs` 时调用方完全掌控,不自动追加 shipped。

用户在前 3 个目录放同名 skill 自动覆盖 shipped 版本。

**关键设计决策:triggers 留空**

模板 frontmatter:
```yaml
---
name: academic-search
description: 在文献站点(默认 CNKI)检索学术论文并整理成 Markdown 摘要列表。
license: Apache-2.0
compatibility: Requires Python 3.10+,需要 backend.skills.builtin.academic_adapters 模块
when_to_use: 当用户想查找学术文献、综述、期刊文章,或用"找文献""检索论文""find papers""literature search"等表达时使用
allowed-tools: web_fetch ask_user_question
triggers: []
---
```

**为什么 triggers 留空而不是预设**:
- ❌ 预设 `"找文献"` / `"检索论文"` 会**全局占用**这些关键中文短语,后续用户基于
  同意图做差异化 skill(综述专用 / pubmed 专用 / 按引用排序专用)会被 builtin
  抢在前面,没法自然沉淀出定制版本
- ✅ 留空 + `when_to_use` 描述触发语义,让 LLM 在 chat 层根据 description 自己
  判断是否激活 —— 用户派生 skill 时可自由加 `triggers: [找综述, pubmed 检索]`,
  与 starter 互不冲突

**模板 body 概要**:

1. **解析查询** —— 从用户消息提取 `query` / `limit` / `site`
2. **构造检索 URL** —— `get_site_adapter(site).build_search_url(query, limit)`
3. **抓取结果页** —— 调 `web_fetch` 工具
4. **(可选)询问排序** —— 调 `ask_user_question`(按相关度/时间/引用数)
5. **解析并输出** —— LLM 自己解析页面,按偏好输出 Markdown 文献列表

**不做的事**(YAGNI):

- ❌ 不内嵌 HTML 解析——LLM 解析更稳,站点改版也不破
- ❌ 不实现 PubMed / Scholar / arXiv adapter——扩展点留好
- ❌ 不管理登录态——adapter 只构造公开检索页
- ❌ 不预设 triggers——让用户基于此模板自定义

### 3.3 `academic_adapters` 注册表

**位置**: `backend/skills/builtin/academic_adapters.py`

**Protocol**:

```python
@runtime_checkable
class AcademicSiteAdapter(Protocol):
    name: str
    def build_search_url(self, query: str, **kwargs: Any) -> str: ...
```

**当前注册**:

- `cnki` → `CNKIAdapter()`,URL 模板 `https://www.cnki.net/old/kns/brief/
  default_result.aspx`,query string 传 `Txt=...`、`t=<limit>`。

**新增站点**(3 步):

```python
# 1. 实现 adapter
class PubMedAdapter:
    name = "pubmed"
    def build_search_url(self, query: str, **kwargs: Any) -> str:
        return f"https://pubmed.ncbi.nlm.nih.gov/?term={quote(query)}"

# 2. 注册
from backend.skills.builtin.academic_adapters import register_site_adapter
register_site_adapter(PubMedAdapter())

# 3. 使用
AcademicSearchSkill(site="pubmed")  # 或 params={"site": "pubmed"}
```

注册表是简单的 `dict[str, AcademicSiteAdapter]`,**没有 plugin 系统**(真有 N
个站点再升级)。

### 3.4 模板怎么变成用户专属版本

starter SKILL.md 是**只读模板**,4 条路径可派生自定义版本:

| 路径 | 操作 | 适用场景 |
| --- | --- | --- |
| **A. 编辑同名覆盖** | 把 starter 复制到 `~/.sage/skills/academic-search/SKILL.md`,改 triggers / when_to_use / 步骤 | 想调整 starter 的默认行为(如换默认 site = pubmed) |
| **B. 派生新 skill** | 复制整个目录为 `~/.sage/skills/my-cnki-survey/SKILL.md`,改 `name` + 自定 triggers | 想基于学术检索做差异化变体(综述专用 / 期刊专用 / pubmed 专用) |
| **C. skill_save 沉淀** | 跑通一次后调 `skill_save` 工具,LLM 把工具序列沉淀为草稿,经人工 review | 想把"我这次怎么用的"复刻为可复用 skill |
| **D. 写 Python skill** | 继承 `AcademicSearchSkill` 类(库代码保留),自定义 `triggers` / `execute()`,然后 `registry.register()` | 高级用户想加 builtin 行为(例:加缓存、加并发抓取) |

路径 A/B 的优先级由 `register_skill_md_skills()` 决定:`$SAGE_SKILLS_DIR` > `$CWD/skills` >
`~/.sage/skills` > shipped,前 3 个任何同名 skill 自动覆盖 shipped。

> **安全注意**:`ScriptRunner.allowed_roots` **不**包含 shipped 目录 —— 只用
> `discover_skill_md_dirs()` 算根,避免把 shipped SKILL.md 模板路径纳入脚本沙箱
> 允许根。这点由 `discover_skill_md_dirs()` 的契约保证(明确不含 shipped)。

> **设计意图**:shipped 只装"装包即用"的 starter,**不预设触发词**,把
> "找文献 / 检索论文"等关键中文短语留给用户基于真实使用情况派生定制版。

---

## 4. 完整示例对话

> **用户**: 帮我找 5 篇大语言模型综述
>
> **LLM**: (读到 shipped `academic-search/SKILL.md`,看 `when_to_use` 命中
> 用户意图,按 body 步骤执行)
>
> **Skill 流程**:
> 1. 解析 → `query="大语言模型综述"`, `limit=5`
> 2. URL → `get_site_adapter("cnki").build_search_url("大语言模型综述", limit=5)`
>    = `https://www.cnki.net/old/kns/brief/default_result.aspx?QueryID=0&
>    Txt=...&t=5`
> 3. `web_fetch(url=...)` → 拿到结果页 HTML
> 4. `ask_user_question("已从 cnki 检索到「大语言模型综述」的结果,如何排序?",
>    ["按相关度", "按时间", "按引用数"])` → 用户答"按相关度"
> 5. LLM 自己解析页面,按用户偏好输出 5 篇综述的 Markdown 列表
>    (标题 / 作者 / 期刊 / 年份 / 摘要)
>
> **用户**: 这个流程挺好的,以后我每次想找文献都能用。帮我把这个流程存为 skill
> 吧,叫 `academic-search-cnki`,触发词加"LLM 综述"和"大模型 survey"。
>
> **LLM**: (检测到"存为 skill"触发词,先确认 when_to_use,然后调用
> `skill_save.execute(name="academic-search-cnki", description="在 CNKI 上检索
> 学术文献并整理摘要", when_to_use="当用户需要检索 CNKI 上的学术论文并按主题
> 整理摘要时使用,特别是 LLM 综述/大模型 survey 时", tool_sequence=[{"tool":
> "web_fetch", ...}, {"tool": "ask_user_question", ...}], session_id="sess-...")`)
>
> **Skill**: 走 review pipeline → SQLite 落盘 → 返回
> `draft_id="draft-abc123"`。
>
> **LLM**: ✅ 草稿已保存到 review 队列,`draft_id=draft-abc123`,等待人工审核。
> 审核通过后下次就能直接复用这个 skill,而且**不会**和 shipped
> `academic-search` 冲突(triggers 不同,`when_to_use` 描述更精确)。

---

## 5. 风险与边界

### 5.1 合规

- ⚠️ **学术检索场景**:CNKI 检索结果页本身受版权保护,本 skill **不抓全文**,
  只抓检索结果列表(标题/作者/期刊/摘要)。LLM 解析时也不应全文复制。
- ⚠️ `skill_save` 落盘的内容里**不应**包含用户敏感数据(API token、cookie、
  密码等);`tool_sequence` 的 normalizer 不会自动剔除这些字段。

### 5.2 登录态 / 反爬

- ❌ 当前 **不管理登录态**。如果站点需要登录(如 Web of Science),adapter
  构造的 URL 只能拿到公开检索页,登录后才能看到的全文不在 skill 范围内。
- ⚠️ `web_fetch` 走的是后端 HTTP 请求,如果站点有反爬(JS 渲染、Cookie 校验、
  验证码)可能拿不到结果。NetworkPolicy 三档门禁见
  [`46-intranet-web-access.md`](./46-intranet-web-access.md)。

### 5.3 Skill 沉淀副作用

- ⚠️ `skill_save` 调用后,草稿**必须经人工 review**(目前是异步队列 + SQLite
  pending 状态,前端 review UI 后续接入)。
- ⚠️ skill 名必须全局唯一;如果用户起的名字和已有 skill 冲突,review 阶段
  会拒收。

---

## 6. 不做的事(YAGNI)

| 想法 | 不做的理由 |
| --- | --- |
| 内嵌 CNKI HTML 解析(BeautifulSoup 解析结果页) | 站点改版即失效;交给 LLM 解析更稳 |
| 实现 N 个站点的 adapter(PubMed / Scholar / arXiv) | YAGNI;扩展点已留好,按需加 |
| 自动 `ToolExecutionContext.tool_calls` 字段 | 当前 tool 调用上下文是隐式的;显式字段属于下一次重构 |
| skill 自动审核(LLM self-review 后直接 approved) | 必须人工 review;trust LLM to review itself 是 anti-pattern |
| **`academic-search` 注册为 builtin 自动加载** | **占"找文献 / 检索论文"等关键触发词,后续用户派生定制版会被抢占。改为 shipped SKILL.md starter,triggers 留空,留出空间给用户自定义** |
| Adapter 的 schema 校验(`Pydantic` 模型) | dict 注册足够;真有 N 个站点再升级 |
| 给 starter 预设触发词 | 同上;让用户基于真实使用情况派生 |

---

## 7. 测试覆盖

| 范围 | 文件 | 测试数 |
| --- | --- | --- |
| `CNKIAdapter` URL 构造 / `get_site_adapter` 注册 | `backend/tests/unit/test_academic_adapters.py` | 9 |
| `AcademicSearchSkill` schema / happy path / 失败模式 / 自定义 site(库代码,未注册) | `backend/tests/unit/test_academic_search.py` | 8 |
| **shipped SKILL.md 模板 + discover/register 分离 + register fallback** | `backend/tests/unit/test_skill_md_loader.py` | **3 新增** |
| `skill_save` 端到端 pipeline(真 review + 真 SQLite + fake LLM) | `backend/tests/integration/test_skill_save_pipeline.py` | 1 |
